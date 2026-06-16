"""
weekly_report — the Sunday wrap-up. Unlike every other agent, this one calls NO
external APIs. It only reads from the agent_outputs table where the other agents
have already stored their results, then asks Claude to synthesize the week across
all domains into one clean personal briefing.

Flow:
  1. For each source agent (email-triage, email-digest, market-report,
     health-sync, job-scout), pull its outputs from the last 7 days, newest
     first, out of the agent_outputs table.
  2. Hand the whole collection to Claude with the wrap-up system prompt.
  3. Return the report as an AgentResult; run() posts it to #weekly-report and
     saves it to memory like any other agent.

Run it directly to preview this week's report WITHOUT posting or logging:
    python agents/weekly_report.py
(that calls execute() only — it reads Supabase and calls Claude, but skips
run()'s agent_runs logging, Discord post, and Voyage embedding.)
"""

import os
import sys
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List

# Allow running this file directly (python agents/weekly_report.py): the script
# dir is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult  # noqa: E402


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
You are writing a personal weekly wrap-up for Clark Enge.
Synthesize the week across all domains into one clean report.
Write it like a smart personal assistant briefing someone
on their own week — direct, useful, no filler.

Structure the report as:

📧 EMAIL & INTEL
Key themes from the week's emails. Any important ISW developments.
Any research worth remembering.

📊 MARKETS
How the portfolio moved this week. Any notable positions.
One forward-looking note.

🏃 FITNESS
What got done this week. Training load and consistency.
One honest observation about the week's effort.

💼 JOB PIPELINE
New roles found this week. Any perfect fits to follow up on.
Companies showing activity.

📋 WEEK SCORE
Rate the week 1-10 with one sentence of honest reasoning.

🎯 NEXT WEEK
Three specific priorities based on what happened this week.

Keep the whole report under 1500 words.
Be specific — reference actual data from the outputs.
Do not make things up if an agent had no output that week.
"""


class WeeklyReportAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "weekly-report"

    # ── Supabase: read other agents' outputs ────────────────────────────────

    def _fetch_recent_outputs(self, source_agent_id: str, cutoff: str) -> List[Dict]:
        """
        Return this source agent's outputs from the last DAYS_BACK days, newest
        first. On a lookup failure we log and return [] so one agent's missing
        history degrades to "no output this week" instead of sinking the report.
        """
        try:
            return (
                self.supabase.table("agent_outputs")
                .select("content, created_at")
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

    # ── Format the collected outputs for Claude ─────────────────────────────

    @staticmethod
    def _build_payload(week: Dict[str, List[Dict]]) -> str:
        """
        Render the week's outputs into a single readable block, grouped by agent.
        Agents with no outputs this week are explicitly labelled so Claude knows
        the silence is real (and per the prompt, doesn't invent anything).
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

    # ── Orchestration ───────────────────────────────────────────────────────

    def execute(self) -> AgentResult:
        week = self._collect_week()
        counts = {agent_id: len(week.get(agent_id) or []) for agent_id in SOURCE_AGENTS}
        total_outputs = sum(counts.values())

        if total_outputs == 0:
            return AgentResult(
                content=(
                    "📋 **Weekly wrap-up** — no agent outputs in the last "
                    f"{DAYS_BACK} days, so there's nothing to summarize this week."
                ),
                metadata={"total_outputs": 0, "counts": counts},
            )

        payload = self._build_payload(week)

        # The outputs ultimately derive from external content (emails, job
        # postings, etc.), so pass them through call_claude's untrusted_data
        # guard rather than as trusted instructions — consistent with the rest
        # of the system, and it's exactly the framing we want anyway (treat the
        # week's data as material to synthesize, not commands to follow).
        body = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                "Below are this past week's outputs from Clark's agents, grouped "
                "by agent and newest first. Write the weekly wrap-up exactly as "
                "described in your instructions, and nothing else."
            ),
            untrusted_data=payload,
            max_tokens=4096,
        )

        header = "📋 **Weekly Wrap-Up**\n\n"
        return AgentResult(
            content=header + body.strip(),
            metadata={"total_outputs": total_outputs, "counts": counts},
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
