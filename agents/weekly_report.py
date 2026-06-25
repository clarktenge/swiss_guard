"""
weekly_report — the Sunday wrap-up. Unlike every other agent, this one calls NO
external APIs. It only reads from the agent_outputs table where the other agents
have already stored their results, then synthesizes the week across all domains
into one clean personal briefing.

Governance Phase 2: the numbers come from Python, the words come from Claude —
the same division of labor as health-sync / market-report, adapted to an agent
whose "raw data" is the prior week's governed agent outputs rather than an
external API.

Flow:
  1. Pull each source agent's last-7-days outputs from agent_outputs (newest
     first), reading the structured_output / metadata columns the governed
     agents now populate.
  2. Compute the week's headline stats in Python from those outputs — workouts,
     distance, emails, opportunities, new jobs, day P&L. No LLM arithmetic.
  3. Ask Claude ONLY for the qualitative bits: a 1-10 week_score, a short
     narrative, and three next-week priorities — returned as JSON.
  4. Assemble a typed WeeklyOutput (numbers from step 2, words from step 3),
     run the Tier 1 eval checks against it, and render it to Discord markdown.

Run it directly to preview this week's report WITHOUT posting or logging:
    python agents/weekly_report.py
(that calls execute() only — it reads Supabase and calls Claude, but skips
run()'s agent_runs logging, Discord post, and Voyage embedding.)
"""

import os
import sys
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List

# Allow running this file directly (python agents/weekly_report.py): the script
# dir is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult        # noqa: E402
from agents.schemas import WeeklyOutput               # noqa: E402
from evals.checks import run_weekly_checks            # noqa: E402


# Source agents whose week we're summarizing, in the order they appear in the
# report. (weekly-report is deliberately NOT in here — it never summarizes
# itself.)
SOURCE_AGENTS = [
    "email-triage",
    "email-digest",
    "market-report",
    "health-sync",
    "job-scout",
]

DAYS_BACK = 7


SYSTEM_PROMPT = """\
You are writing a personal weekly wrap-up.
You will be given computed stats from the week.
Respond with valid JSON only matching this exact structure:
{
  "week_score": <integer 1-10>,
  "narrative": "<3-5 sentences, plain text, no special chars>",
  "next_week_priorities": ["<priority 1>", "<priority 2>", "<priority 3>"]
}

Scoring criteria — use the actual data provided:
- 8 or higher: strong fitness consistency, positive portfolio,
  new opportunities found
- 5-7: mixed week, some domains strong some weak
- Below 5: missed workouts, no opportunities, portfolio down

next_week_priorities must be exactly 3 specific actionable items
based on what happened this week. Plain text only.
"""


# ── JSON parsing helpers (match email_triage's pattern) ──────────────────────

def _strip_code_fences(text: str) -> str:
    """
    Defensively unwrap a ```json … ``` (or bare ``` … ```) fence if Claude adds
    one despite being asked for raw JSON. Leaves clean JSON untouched.
    """
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the trailing fence.
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -len("```")]
    return s.strip()


def _clean_json_response(text: str) -> str:
    """
    Trim anything Claude tucked outside the JSON object — a stray sentence
    before the opening brace or a sign-off after the closing one — so json.loads
    sees only the object. Run after _strip_code_fences. Leaves the text
    untouched if it can't find a brace pair to slice on.
    """
    if "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text.strip()


# ── Numeric extraction helpers (pure — unit-testable offline) ────────────────

def _so(output: Dict) -> Dict:
    """The output row's structured_output, or {} when null (ungoverned run)."""
    return output.get("structured_output") or {}


def _md(output: Dict) -> Dict:
    """The output row's metadata, or {} when null."""
    return output.get("metadata") or {}


def _pick_num(*values, default: float = 0.0) -> float:
    """
    First value that coerces to a real number, else default. Lets each fact try
    structured_output first and fall back to metadata (a far more reliable
    fallback than re-parsing the prose `content`, and one the governed agents
    already populate) without crashing on a null or non-numeric field.
    """
    for v in values:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return default


class WeeklyReportAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "weekly-report"

    # ── Supabase: read other agents' outputs ────────────────────────────────

    def _fetch_recent_outputs(self, source_agent_id: str, cutoff: str) -> List[Dict]:
        """
        Return this source agent's outputs from the last DAYS_BACK days, newest
        first. Pulls structured_output + metadata alongside the content/date so
        the stat extraction can read the governed agents' typed numbers. On a
        lookup failure we log and return [] so one agent's missing history
        degrades to "no output this week" instead of sinking the report.
        """
        try:
            return (
                self.supabase.table("agent_outputs")
                .select("content, created_at, structured_output, metadata")
                .eq("agent_id", source_agent_id)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .execute()
                .data
            ) or []
        except Exception as e:
            print(f"[{self.agent_id}] fetch failed for {source_agent_id}: {e}")
            return []

    def _collect_week(self) -> Dict[str, List[Dict]]:
        """Map each source agent_id -> its last-7-days outputs (newest first)."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
        ).isoformat()
        return {
            agent_id: self._fetch_recent_outputs(agent_id, cutoff)
            for agent_id in SOURCE_AGENTS
        }

    # ── Step 1: compute the week's numbers in Python ─────────────────────────

    @staticmethod
    def _compute_stats(week: Dict[str, List[Dict]]) -> Dict:
        """
        Derive the headline numbers from the governed agents' outputs. Each fact
        reads structured_output first and falls back to metadata; nothing here is
        asked of Claude. Outputs are newest-first, so [0] is the latest run.
        """
        health = week.get("health-sync") or []
        email = week.get("email-triage") or []
        jobs = week.get("job-scout") or []
        market = week.get("market-report") or []

        # health-sync: workouts summed across the week's runs; distance is the
        # latest run's rolling weekly figure (per spec).
        workouts_completed = int(sum(
            _pick_num(_so(o).get("week_activity_count"), _md(o).get("activity_count"))
            for o in health
        ))
        total_distance_miles = round(_pick_num(
            _so(health[0]).get("week_distance_miles") if health else None,
            _md(health[0]).get("week_distance_miles") if health else None,
        ), 2)

        # email-triage: emails processed summed from metadata; opportunities
        # counted from each run's structured opportunities bucket.
        emails_processed = int(sum(
            _pick_num(_md(o).get("email_count")) for o in email
        ))
        opportunities_found = sum(
            len(_so(o).get("opportunities") or []) for o in email
        )

        # job-scout: new postings summed from metadata (it stores no structured
        # output, so metadata.new_jobs is the source).
        new_jobs_found = int(sum(
            _pick_num(_md(o).get("new_jobs")) for o in jobs
        ))

        # market-report: latest run's day P&L.
        portfolio_day_pnl = round(_pick_num(
            _so(market[0]).get("day_pnl") if market else None,
            _md(market[0]).get("day_pnl") if market else None,
        ), 2)

        return {
            "workouts_completed": workouts_completed,
            "total_distance_miles": total_distance_miles,
            "emails_processed": emails_processed,
            "opportunities_found": opportunities_found,
            "new_jobs_found": new_jobs_found,
            "portfolio_day_pnl": portfolio_day_pnl,
        }

    # ── Supabase: read this week's run costs ────────────────────────────────

    def _fetch_cost_summary(self) -> List[Dict]:
        """
        Pull the last DAYS_BACK days of agent_runs (every agent, including the
        ones not in SOURCE_AGENTS) with their stored Claude-cost estimate. On any
        failure — including the estimated_cost_usd column not existing yet
        (migration_005 not applied) — log and return [] so the wrap-up still
        posts, just without a spend section.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
        ).isoformat()
        try:
            return (
                self.supabase.table("agent_runs")
                .select("agent_id, estimated_cost_usd")
                .gte("started_at", cutoff)
                .execute()
                .data
            ) or []
        except Exception as e:
            print(f"[{self.agent_id}] cost fetch failed: {e}")
            return []

    @staticmethod
    def _format_cost_section(rows: List[Dict]) -> str:
        """
        Build the deterministic 💰 spend block from agent_runs rows. Costs are
        summed straight from the per-run estimated_cost_usd the agents already
        recorded — Claude is never asked to do this math — so the numbers are
        exact. Returns "" when there's nothing to report (no runs, or all costs
        NULL summing to $0), so the caller can skip the section entirely.
        """
        if not rows:
            return ""

        cost_by_agent: Dict[str, float] = defaultdict(float)
        runs_by_agent: Dict[str, int] = defaultdict(int)
        for r in rows:
            agent = r.get("agent_id") or "unknown"
            cost_by_agent[agent] += float(r.get("estimated_cost_usd") or 0)
            runs_by_agent[agent] += 1

        total = sum(cost_by_agent.values())
        total_runs = sum(runs_by_agent.values())
        if total <= 0:
            return ""

        lines = ["💰 AGENT SPEND (LAST 7 DAYS)"]
        for agent in sorted(cost_by_agent, key=lambda a: cost_by_agent[a], reverse=True):
            runs = runs_by_agent[agent]
            lines.append(
                f"• {agent} — ${cost_by_agent[agent]:.4f} "
                f"({runs} run{'s' if runs != 1 else ''})"
            )
        lines.append(f"Total: ${total:.4f} across {total_runs} runs")
        return "\n".join(lines)

    # ── Format the collected outputs as grounding for Claude ─────────────────

    @staticmethod
    def _build_payload(week: Dict[str, List[Dict]]) -> str:
        """
        Render the week's outputs into a single readable block, grouped by agent.
        Claude gets this as untrusted supporting context so the narrative and
        priorities can reference what actually happened — the numbers it scores
        against still come from the Python-computed stats, never from here.
        Agents with no outputs this week are explicitly labelled so Claude knows
        the silence is real (and doesn't invent anything).
        """
        sections = []
        for agent_id in SOURCE_AGENTS:
            outputs = week.get(agent_id) or []
            header = f"===== {agent_id} ({len(outputs)} output(s) this week) ====="
            if not outputs:
                sections.append(f"{header}\n(no output this week)")
                continue

            entries = [
                f"[{o.get('created_at', '')[:10]}]\n{o.get('content', '').strip()}"
                for o in outputs
            ]
            sections.append(header + "\n" + "\n\n".join(entries))

        return "\n\n\n".join(sections)

    @staticmethod
    def _format_stats_for_claude(stats: Dict) -> str:
        """Plain-text rendering of the computed stats handed to Claude as context."""
        return (
            "Computed stats for the week (authoritative — do not recompute):\n"
            f"- Workouts completed: {stats['workouts_completed']}\n"
            f"- Total distance: {stats['total_distance_miles']} miles\n"
            f"- Emails processed: {stats['emails_processed']}\n"
            f"- Opportunities found: {stats['opportunities_found']}\n"
            f"- New jobs found: {stats['new_jobs_found']}\n"
            f"- Portfolio day P&L: ${stats['portfolio_day_pnl']:,.2f}"
        )

    # ── Step 3 parse: Claude's qualitative JSON ──────────────────────────────

    def _ask_claude(self, stats: Dict, payload: str) -> Dict:
        """
        Ask Claude for the week_score / narrative / next_week_priorities JSON,
        grounded in the computed stats (trusted context) and the week's outputs
        (untrusted supporting material). Raises on a malformed response so run()
        marks the run as an error rather than posting garbage.
        """
        body = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                f"{self._format_stats_for_claude(stats)}\n\n"
                "Below are this past week's agent outputs as supporting context. "
                "Use them to ground your narrative and priorities, but score the "
                "week against the computed stats above. Return only the JSON "
                "object described in your instructions, and nothing else."
            ),
            untrusted_data=payload,
            max_tokens=1024,
        )

        try:
            data = json.loads(_clean_json_response(_strip_code_fences(body)))
            # Validate the shape up front so a missing key surfaces here rather
            # than as a confusing KeyError deeper in WeeklyOutput construction.
            return {
                "week_score": int(data["week_score"]),
                "narrative": str(data["narrative"]),
                "next_week_priorities": list(data["next_week_priorities"]),
            }
        except Exception as e:
            raise ValueError(
                f"weekly-report: Claude response failed JSON parsing: {e}\n"
                f"Raw response (first 500 chars): {body[:500]}"
            ) from e

    # ── Render the typed output for Discord ──────────────────────────────────

    @staticmethod
    def _format_weekly_for_discord(output: WeeklyOutput) -> str:
        """
        Render the validated WeeklyOutput into the scannable briefing posted to
        Discord, preserving the emoji-headed section structure. Every number is
        Python-computed; Claude contributes only the score reasoning, narrative,
        and priorities.
        """
        lines = [f"📋 **Weekly Wrap-Up** — week of {output.week_of}", ""]

        lines.append("📧 EMAIL & INTEL")
        lines.append(
            f"{output.emails_processed} emails processed · "
            f"{output.opportunities_found} opportunities flagged"
        )
        lines.append("")

        lines.append("📊 MARKETS")
        lines.append(f"Portfolio day P&L: ${output.portfolio_day_pnl:,.2f}")
        lines.append("")

        lines.append("🏃 FITNESS")
        lines.append(
            f"{output.workouts_completed} workouts · "
            f"{output.total_distance_miles:g} miles"
        )
        lines.append("")

        lines.append("💼 JOB PIPELINE")
        lines.append(f"{output.new_jobs_found} new role(s) found this week")
        lines.append("")

        lines.append("📋 WEEK SCORE")
        lines.append(f"{output.week_score}/10 — {output.narrative}")
        lines.append("")

        lines.append("🎯 NEXT WEEK")
        for priority in output.next_week_priorities:
            lines.append(f"• {priority}")

        return "\n".join(lines)

    # ── Orchestration ───────────────────────────────────────────────────────

    def execute(self) -> AgentResult:
        week = self._collect_week()
        counts = {agent_id: len(week.get(agent_id) or []) for agent_id in SOURCE_AGENTS}
        total_outputs = sum(counts.values())

        # Spend is derived from agent_runs independently of agent_outputs, so
        # build it once and append it whether or not there were outputs to
        # summarize (a week of all-errored runs still cost money).
        cost_section = self._format_cost_section(self._fetch_cost_summary())

        if total_outputs == 0:
            # Nothing to summarize and nothing to score — say so plainly rather
            # than asking Claude to narrate an empty week. No structured output /
            # eval row here, matching the other agents' empty-input early returns.
            content = (
                "📋 **Weekly wrap-up** — no agent outputs in the last "
                f"{DAYS_BACK} days, so there's nothing to summarize this week."
            )
            if cost_section:
                content += "\n\n" + cost_section
            return AgentResult(
                content=content,
                metadata={"total_outputs": 0, "counts": counts},
            )

        # Step 1: compute the week's numbers in Python from the governed outputs.
        stats = self._compute_stats(week)

        # Step 2/3: ask Claude for the score, narrative and priorities (JSON).
        payload = self._build_payload(week)
        claude_data = self._ask_claude(stats, payload)

        # Step 4: assemble the typed WeeklyOutput — numbers from Python, words
        # from Claude. Monday-of-this-week anchors the report to a week.
        monday = date.today() - timedelta(days=date.today().weekday())
        output = WeeklyOutput(
            week_of=monday.isoformat(),
            workouts_completed=stats["workouts_completed"],
            total_distance_miles=stats["total_distance_miles"],
            emails_processed=stats["emails_processed"],
            opportunities_found=stats["opportunities_found"],
            new_jobs_found=stats["new_jobs_found"],
            portfolio_day_pnl=stats["portfolio_day_pnl"],
            week_score=claude_data["week_score"],
            narrative=claude_data["narrative"],
            next_week_priorities=claude_data["next_week_priorities"][:3],
        )

        # Step 5: run the Tier 1 deterministic checks; base.py run() persists
        # self._eval_results via log_eval_results() after _save_output.
        self._eval_results = run_weekly_checks(output)

        # Step 6: render to Discord markdown, then append the deterministic spend
        # block (built from agent_runs, not the LLM).
        content = self._format_weekly_for_discord(output)
        if cost_section:
            content += "\n\n" + cost_section

        return AgentResult(
            content=content,
            structured_output=output.model_dump(),
            metadata={
                "total_outputs": total_outputs,
                "counts": counts,
                "week_score": output.week_score,
                "eval_passed": all(r["passed"] for r in self._eval_results),
            },
        )


# ── Direct-run harness (no Supabase logging / Discord post / embedding) ──────

if __name__ == "__main__":
    # Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    agent = WeeklyReportAgent()
    result = agent.execute()
    print(result.content)
    print(f"\nmetadata: {json.dumps(result.metadata, indent=2)}")
