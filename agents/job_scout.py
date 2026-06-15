"""
job_scout — scans target companies for open roles, keeps a permanent record of
every job it has ever seen, and surfaces only the NEW roles that Claude judges to
be both (a) entry-level / new-grad appropriate and (b) genuinely relevant to
Clark's ML/AI/defense background — each with a one-line "why this fits" rationale.

Flow (implemented exactly as specified):
  1. Fetch each company's current listings via integrations.job_boards.
  2. US-only filter (Python): keep jobs whose location looks US-based; keep jobs
     with no location field (don't discard on missing data).
  3. seen_jobs (Supabase): keep only jobs not already recorded for that company,
     and record ALL new jobs immediately — regardless of relevance — so a role
     is never shown twice even if Claude later filters it out.
  4. Claude judgment (replaces the old keyword filter): hand the new jobs to
     Claude, which returns only the entry-level + relevant ones with a reason.
  5. Discord: one message per matching job to #💼-job-scout; if nothing matched,
     a single completion summary. Errors go to the agent-logs webhook.

Division of labor: Python owns the facts (US filter, what's new, the counts) and
all side effects (Supabase, Discord); Claude owns the judgment + rationale.

TEST_MODE limits the scan to a short company list for safe live testing.

Run directly to preview against the live boards + Claude WITHOUT posting/writing:
    python agents/job_scout.py
(that calls execute() with post=False; it still reads/writes seen_jobs and calls
Claude, but skips run()'s Supabase logging, Discord summary, and embedding.)
"""

import os
import sys
import re
import json
from typing import List, Dict, Optional

# Allow running this file directly (python agents/job_scout.py): the script dir
# is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult                    # noqa: E402
from config.companies import COMPANIES, SEARCH_QUERY              # noqa: E402
from integrations.job_boards import fetch_company_jobs            # noqa: E402
from integrations.discord_notify import notify_raw, notify_error  # noqa: E402


# ── Live-test scoping ────────────────────────────────────────────────────────
# With TEST_MODE on, only TEST_COMPANIES are scanned — a small, safe set for the
# first end-to-end live run. Flip to False to scan all of COMPANIES.
TEST_MODE = True
TEST_COMPANIES = ["Onebrief", "Anduril", "Palantir", "Shield AI", "Vannevar Labs"]

# Max job_ids per seen_jobs request. A single .in_() with thousands of ids makes
# a GET URL long enough for PostgREST to 400; batching keeps each request small.
_SEEN_BATCH = 100


# ── Claude prompts (verbatim from the spec) ──────────────────────────────────

CLAUDE_SYSTEM = (
    "You are a job matching assistant. The candidate is Clark Enge — "
    "UCSB Statistics & Data Science student, ML Researcher at AFRL studying "
    "synthetic-to-real data gap for satellite imagery, active Secret clearance, "
    "background in agentic AI systems, computer vision, and deep learning. "
    "Target roles: Outcome Engineer, Forward Deployed Engineer, Applied Scientist, "
    "ML Engineer, AI Engineer."
)

CLAUDE_USER = (
    "Here are today's new job postings. Return ONLY the ones that are:\n"
    "1. Entry-level or new-grad appropriate (0-3 years experience, associate level,\n"
    "   early career, new graduate, or senior roles clearly open to new grads like\n"
    "   Forward Deployed Engineer at Palantir or Outcome Engineer at Onebrief)\n"
    "2. Genuinely relevant to the candidate's ML/AI/defense background\n\n"
    "For each matching job return JSON:\n"
    "{\n"
    '  "company": str,\n'
    '  "title": str, \n'
    '  "url": str,\n'
    '  "reason": str  // one sentence why this fits Clark specifically\n'
    "}\n\n"
    "Return an empty list if nothing matches. Return JSON only, no other text."
)


# ── Pure helpers (no I/O — unit-testable offline) ───────────────────────────

# Full US state/territory names and postal abbreviations, for the US-only filter.
_US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
}
_US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
_US_ABBR_RE = re.compile(r"\b(" + "|".join(sorted(_US_STATE_ABBR)) + r")\b")


def _passes_us_filter(job: Dict) -> bool:
    """
    True if the job looks US-based, OR has no usable location (don't discard on
    missing data — that's the spec's rule).

    A location may be a string ("Reston, VA") or a dict ({"city","state",
    "country"}); both are flattened to text. We match on "United States"/"USA",
    a US state name, or a US state postal abbreviation (case-sensitive, so we
    don't flag "in"/"or"/"me" inside ordinary words).

    NB: integrations.job_boards does not currently populate a `location` field,
    so in practice every job passes today. This is written to work the moment a
    fetcher starts returning location.
    """
    loc = job.get("location")
    if isinstance(loc, dict):
        loc = " ".join(str(v) for v in loc.values() if v)
    if not loc or not isinstance(loc, str) or not loc.strip():
        return True  # no location → keep

    text = loc.lower()
    if "united states" in text or "usa" in text or "u.s." in text:
        return True
    if any(state in text for state in _US_STATE_NAMES):
        return True
    if _US_ABBR_RE.search(loc):  # case-sensitive on the original string
        return True
    return False


def _parse_matches(raw: str) -> List[Dict]:
    """
    Parse Claude's JSON array of matching jobs. Defensive: strips an accidental
    ```json fence and returns [] (rather than raising) on anything unparseable,
    so a malformed reply degrades to "nothing matched" instead of crashing.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    try:
        items = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


# Per-job message presentation. Priority is matched on company name against
# config/companies.py and shown as a coloured tag on the company line.
_COMPANY_PRIORITY = {c["name"]: c.get("priority") for c in COMPANIES}
_PRIORITY_TAG = {"high": "🔴", "medium": "🟡"}
_JOB_DIVIDER = "─────────────────────────────"


def format_job_message(company: str, title: str, url: str, reason: str) -> str:
    """
    Render the Discord message for one matching job:

        ─────────────────────────────
        🏢  **{company}**  {priority tag}
        📋  {title}
        🔗  {url}
        💡  {reason}

    A divider tops each message for clear separation between jobs; the company
    line carries a priority tag (🔴 high / 🟡 medium, looked up from
    config/companies.py by name); a trailing blank line gives breathing room
    before the next job's divider.
    """
    tag = _PRIORITY_TAG.get(_COMPANY_PRIORITY.get(company) or "", "")
    header = f"🏢  **{company}**" + (f"  {tag}" if tag else "")
    return (
        f"{_JOB_DIVIDER}\n"
        f"{header}\n"
        f"📋  {title}\n"
        f"🔗  {url}\n"
        f"💡  {reason}\n"
    )


class JobScoutAgent(BaseAgent):

    def __init__(self, companies: Optional[List[Dict]] = None, post: bool = True):
        """
        companies: company configs to scan. Defaults to COMPANIES, narrowed to
            TEST_COMPANIES when TEST_MODE is on.
        post: when True, matching jobs are posted to #💼-job-scout. When False
            (direct-run preview / tests) messages are printed instead, so
            execute() has no Discord side effects.
        """
        super().__init__()
        if companies is None:
            companies = COMPANIES
            if TEST_MODE:
                companies = [c for c in companies if c["name"] in TEST_COMPANIES]
        self.companies = companies
        self.post = post

    @property
    def agent_id(self) -> str:
        return "job-scout"

    # ── Supabase: seen_jobs bookkeeping ─────────────────────────────────────

    def _find_new_jobs(self, company_name: str, jobs: List[Dict]) -> List[Dict]:
        """
        Return the subset of `jobs` not already in seen_jobs for this company.
        On a lookup failure we treat nothing as new — better to miss a
        notification once than to double-post a flood.

        The job_ids are looked up in batches: a single `.in_(...)` with thousands
        of ids (e.g. Anduril lists ~2k roles) builds a GET URL long enough for
        PostgREST to reject with a 400, which previously skipped that company
        entirely.
        """
        if not jobs:
            return []

        job_ids = [j["job_id"] for j in jobs]
        seen_ids: set = set()
        try:
            for i in range(0, len(job_ids), _SEEN_BATCH):
                chunk = job_ids[i:i + _SEEN_BATCH]
                existing = (
                    self.supabase.table("seen_jobs")
                    .select("job_id")
                    .eq("company", company_name)
                    .in_("job_id", chunk)
                    .execute()
                    .data
                )
                seen_ids.update(row["job_id"] for row in existing)
        except Exception as e:
            print(f"[{self.agent_id}] seen_jobs lookup failed for {company_name}: {e}")
            notify_error(self.agent_id, f"seen_jobs lookup failed for {company_name}: {e}")
            return []

        return [j for j in jobs if j["job_id"] not in seen_ids]

    def _record_seen(self, jobs: List[Dict]) -> None:
        """
        Persist new jobs to seen_jobs. Called BEFORE Claude judgment so a role is
        never surfaced twice even if Claude rejects it this run. Upsert with
        ignore-on-conflict makes a re-run idempotent if two runs race.
        """
        if not jobs:
            return
        rows = [
            {
                "job_id": j["job_id"],
                "company": j["company"],
                "title": j["title"],
                "url": j["url"],
                "source": j.get("source", "unknown"),
            }
            for j in jobs
        ]
        try:
            # Batch the writes too, so a company with thousands of new roles
            # doesn't push one oversized request.
            for i in range(0, len(rows), _SEEN_BATCH):
                self.supabase.table("seen_jobs").upsert(
                    rows[i:i + _SEEN_BATCH],
                    on_conflict="job_id,company", ignore_duplicates=True,
                ).execute()
        except Exception as e:
            print(f"[{self.agent_id}] seen_jobs write failed: {e}")
            notify_error(self.agent_id, f"seen_jobs write failed: {e}")

    # ── Claude: entry-level + relevance judgment ────────────────────────────

    def _evaluate_with_claude(self, jobs: List[Dict]) -> List[Dict]:
        """
        Ask Claude which new jobs are entry-level-appropriate AND relevant, in
        one call. Returns a list of {company, title, url, reason}. The job list
        is untrusted external text, so it's passed via call_claude's
        untrusted_data guard. Never raises — on failure logs to agent-logs and
        returns [].
        """
        if not jobs:
            return []

        payload = [
            {"company": j["company"], "title": j["title"], "url": j["url"]}
            for j in jobs
        ]
        try:
            raw = self.call_claude(
                system_prompt=CLAUDE_SYSTEM,
                user_prompt=CLAUDE_USER,
                untrusted_data=json.dumps(payload, ensure_ascii=False, indent=2),
                max_tokens=4096,
            )
        except Exception as e:
            print(f"[{self.agent_id}] Claude evaluation failed: {e}")
            notify_error(self.agent_id, f"Claude evaluation failed: {e}")
            return []

        matches = _parse_matches(raw)

        # Guard the links: only trust URLs that were actually in our input. If
        # Claude tweaked a URL, repair it from the original by (company, title);
        # drop the match if we can't verify it points at a real posting.
        valid_urls = {j["url"] for j in jobs}
        by_key = {(j["company"].lower(), j["title"].lower()): j["url"] for j in jobs}
        cleaned: List[Dict] = []
        for m in matches:
            if not all(k in m and isinstance(m[k], str) and m[k].strip()
                       for k in ("company", "title", "url", "reason")):
                continue
            if m["url"] not in valid_urls:
                fixed = by_key.get((m["company"].lower(), m["title"].lower()))
                if not fixed:
                    continue
                m["url"] = fixed
            cleaned.append(m)
        return cleaned

    # ── Discord ──────────────────────────────────────────────────────────────

    def _emit(self, message: str) -> None:
        """Post one message to #💼-job-scout, or print it in preview mode."""
        if self.post:
            notify_raw(self.agent_id, message)
        else:
            print(message + "\n")

    # ── Orchestration ──────────────────────────────────────────────────────

    def execute(self) -> AgentResult:
        companies_checked = 0
        jobs_scanned = 0
        new_jobs: List[Dict] = []

        for company in self.companies:
            companies_checked += 1
            name = company["name"]

            # STEP 1 — fetch. One board failing must not sink the run.
            try:
                jobs = fetch_company_jobs(company, SEARCH_QUERY)
            except Exception as e:
                print(f"[{self.agent_id}] fetch failed for {name}: {e}")
                notify_error(self.agent_id, f"fetch failed for {name}: {e}")
                continue
            jobs_scanned += len(jobs)

            # STEP 2 — US-only filter (before anything else touches the jobs).
            us_jobs = [j for j in jobs if _passes_us_filter(j)]

            # STEP 3 — new vs. seen; record ALL new immediately (pre-judgment).
            company_new = self._find_new_jobs(name, us_jobs)
            self._record_seen(company_new)
            new_jobs.extend(company_new)

        # STEP 4 — Claude judges the new jobs (entry-level + relevant).
        matches = self._evaluate_with_claude(new_jobs) if new_jobs else []

        # STEP 5 — Discord. One message per match (posted here); the returned
        # `content` is what run() posts as the single completion/summary message.
        for m in matches:
            self._emit(format_job_message(
                m["company"], m["title"], m["url"], m["reason"]
            ))

        if matches:
            content = (
                f"✅ Job scout complete — {companies_checked} companies checked, "
                f"{len(new_jobs)} new jobs found, {len(matches)} matched today"
            )
        else:
            content = (
                f"✅ Job scout complete — {companies_checked} companies checked, "
                f"{len(new_jobs)} new jobs found, none matched today's criteria"
            )

        return AgentResult(
            content=content,
            metadata={
                "companies_checked": companies_checked,
                "jobs_scanned": jobs_scanned,
                "new_jobs": len(new_jobs),
                "matched": len(matches),
                "matches": matches,
                "test_mode": TEST_MODE,
            },
        )


# ── Direct-run harness (no Discord posting / no Supabase logging via run()) ──

if __name__ == "__main__":
    # Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    # post=False → prints matches instead of sending to Discord. Still reads/
    # writes seen_jobs and calls Claude. execute() directly, so run()'s Supabase
    # logging + summary post + embedding are all skipped.
    agent = JobScoutAgent(post=False)
    result = agent.execute()
    print("\n" + "=" * 60)
    print(result.content)
    print(f"\nmetadata: {json.dumps(result.metadata, indent=2)}")
