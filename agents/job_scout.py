"""
job_scout — scans target companies for open roles, keeps a permanent record of
every job it has ever seen, and surfaces the NEW postings so Clark can review
them personally. This is a notification system, not a filter: two cheap Python
filters (US-based + an entry-level keyword on the title) keep the noise down,
and everything that survives is posted as-is.

Flow:
  1. Fetch each company's current listings via integrations.job_boards.
  2. Two Python filters only — no Claude:
     - US-only: keep jobs whose location looks US-based, OR has no location
       (don't discard on missing data).
     - Entry-level: keep jobs whose TITLE contains an entry-level/role keyword.
  3. seen_jobs (Supabase): keep only postings not already recorded for that
     company, and record every new one immediately.
  4. Multi-location dedup: collapse the same role posted across cities into one
     entry (location → "📍 Multiple locations").
  5. Discord: one message per new posting to #💼-job-scout. If nothing is new,
     a single "no new postings today" line. Errors go to the agent-logs webhook.

Every non-placeholder company in config/companies.py is scanned on every run.

Run directly to preview against the live boards WITHOUT posting:
    python agents/job_scout.py
(execute() with post=False prints messages instead of sending to Discord; it
still reads/writes seen_jobs.)
"""

import os
import sys
import re
from typing import List, Dict, Optional

# Allow running this file directly (python agents/job_scout.py): the script dir
# is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult                    # noqa: E402
from config.companies import COMPANIES, SEARCH_QUERY              # noqa: E402
from integrations.job_boards import fetch_company_jobs            # noqa: E402
from integrations.discord_notify import notify_raw, notify_error  # noqa: E402


# Max job_ids per seen_jobs request. A single .in_() with thousands of ids makes
# a GET URL long enough for PostgREST to 400; batching keeps each request small.
_SEEN_BATCH = 100


# ── Filter 1: US-only ────────────────────────────────────────────────────────
# Full US state/territory names and postal abbreviations.
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
    missing data). A location may be a string ("Reston, VA") or a dict
    ({"city","state","country"}); both are flattened to text. We match on
    "United States"/"USA"/"Remote", a US state name, or a US state postal
    abbreviation (case-sensitive, so we don't flag "in"/"or"/"me" inside words).
    """
    loc = job.get("location")
    if isinstance(loc, dict):
        loc = " ".join(str(v) for v in loc.values() if v)
    if not loc or not isinstance(loc, str) or not loc.strip():
        return True  # no location → keep

    text = loc.lower()
    if "united states" in text or "usa" in text or "u.s." in text or "remote" in text:
        return True
    if any(state in text for state in _US_STATE_NAMES):
        return True
    if _US_ABBR_RE.search(loc):  # case-sensitive on the original string
        return True
    return False


# ── Filter 2: entry-level keyword on the title ───────────────────────────────
_ENTRY_LEVEL_KEYWORDS = (
    "new grad", "new graduate", "entry", "associate", "junior", "early career",
    "university", "campus", "software engineer", "data scientist",
    "machine learning", "ml engineer", "ai engineer", "forward deployed",
    "applied scientist", "outcome engineer",
)


def _passes_entry_level_filter(job: Dict) -> bool:
    """True if the job title contains any entry-level / target-role keyword."""
    title = (job.get("title") or "").lower()
    return any(kw in title for kw in _ENTRY_LEVEL_KEYWORDS)


# ── Multi-location dedup ─────────────────────────────────────────────────────
# The same role is frequently posted once per city ("ML Engineer - Austin",
# "ML Engineer - San Diego", …). We collapse those into one entry so Clark sees
# the role once with a "📍 Multiple locations" tag instead of five near-
# identical cards.

# Words that, standing alone after a trailing " - ", mark a location suffix.
_LOCATION_WORDS = {
    "remote", "hybrid", "onsite", "on-site", "on site", "anywhere",
    "us", "u.s.", "usa", "united states", "multiple locations",
}
# Trailing " - <X>" segments that are role/function qualifiers, NOT locations —
# these must NOT be stripped, or unrelated roles would wrongly collapse.
_NON_LOCATION_QUALIFIERS = {
    "computer vision", "machine learning", "deep learning", "nlp", "llm",
    "genai", "backend", "back end", "frontend", "front end", "full stack",
    "platform", "infrastructure", "infra", "data", "research", "security",
    "embedded", "robotics", "perception", "ml", "ai", "applied", "core",
    "growth", "new grad", "university grad",
}


def _looks_like_location_suffix(segment: str) -> bool:
    """
    True if `segment` (the text after a trailing " - " in a job title) looks
    like a location rather than a role qualifier. Locations are: known
    remote/hybrid words, anything carrying a US state name or postal abbr
    (e.g. "Austin, TX"), or a short Title-Case proper-noun phrase like "Austin"
    or "San Diego". A small denylist protects function qualifiers like
    "Computer Vision" / "NLP" from being mistaken for a place.
    """
    s = segment.strip()
    if not s:
        return False
    low = s.lower()
    if low in _NON_LOCATION_QUALIFIERS:
        return False
    if low in _LOCATION_WORDS:
        return True
    if any(state in low for state in _US_STATE_NAMES):
        return True
    if _US_ABBR_RE.search(s):  # case-sensitive postal abbr ("CA", "VA")
        return True
    # Bare city: 1–3 capitalized alphabetic words ("Austin", "San Diego").
    words = s.split()
    if 1 <= len(words) <= 3 and all(w[:1].isupper() and w.isalpha() for w in words):
        return True
    return False


# Matches the LAST " - <segment>" (segment itself dash-free) so we can peel
# location suffixes off one at a time, innermost last.
_TITLE_SUFFIX_RE = re.compile(r"^(.*\S)\s+[-–—]\s+([^-–—]+?)\s*$")


def _normalize_title(title: str) -> str:
    """
    Lowercase a title and strip any trailing " - <location>" suffix(es) so the
    same role across cities maps to one key. "ML Engineer - Remote - Austin"
    → "ml engineer"; "ML Engineer - Computer Vision" stays
    "ml engineer - computer vision" (qualifier, not a location).
    """
    base = (title or "").strip()
    while True:
        m = _TITLE_SUFFIX_RE.match(base)
        if not m or not _looks_like_location_suffix(m.group(2)):
            break
        base = m.group(1).strip()
    return base.lower()


def dedup_multi_location(jobs: List[Dict]) -> List[Dict]:
    """
    Collapse jobs that share a (company, normalized-title) key. The first
    posting in each group is kept; if the group has more than one member its
    location is stamped "📍 Multiple locations". Single-posting groups keep
    their own location (or "Not specified"). Input dicts are not mutated —
    each kept entry is a shallow copy.
    """
    groups: Dict[tuple, List[Dict]] = {}
    for j in jobs:
        key = (j.get("company", "").strip().lower(), _normalize_title(j.get("title", "")))
        groups.setdefault(key, []).append(j)

    out: List[Dict] = []
    for members in groups.values():
        kept = dict(members[0])
        if len(members) > 1:
            kept["location"] = "📍 Multiple locations"
        else:
            kept["location"] = kept.get("location") or "Not specified"
        out.append(kept)
    return out


# ── Discord message presentation ─────────────────────────────────────────────
# Priority is matched on company name against config/companies.py and shown as a
# coloured tag on the company line.
_COMPANY_PRIORITY = {c["name"]: c.get("priority") for c in COMPANIES}
_PRIORITY_TAG = {"high": "🔴", "medium": "🟡"}


def format_job_message(company: str, title: str, url: str, location: str) -> str:
    """
    Render the Discord message for one new posting:

        🏢 {🔴/🟡} **{company}** — {title}
        📍 {location}
        🔗 {url}

    The company name leads with a priority tag (🔴 high / 🟡 medium, looked up
    from config/companies.py by name; 🔹 if the company has no priority).
    """
    tag = _PRIORITY_TAG.get(_COMPANY_PRIORITY.get(company) or "", "🔹")
    return (
        f"🏢 {tag} **{company}** — {title}\n"
        f"📍 {location or 'Not specified'}\n"
        f"🔗 {url}\n"
    )


class JobScoutAgent(BaseAgent):

    def __init__(self, companies: Optional[List[Dict]] = None, post: bool = True):
        """
        companies: company configs to scan. Defaults to EVERY non-placeholder
            company in COMPANIES (placeholders self-skip in fetch_company_jobs,
            but excluding them here keeps companies_checked an honest count of
            boards actually scanned).
        post: when True, new postings are sent to #💼-job-scout. When False
            (direct-run preview / tests) messages are printed instead.
        """
        super().__init__()
        if companies is None:
            companies = [c for c in COMPANIES if c.get("ats") != "placeholder"]
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
        notification once than to double-post a flood. The job_ids are looked up
        in batches so a company with thousands of roles doesn't build a GET URL
        long enough for PostgREST to reject with a 400.
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
        Persist new jobs to seen_jobs immediately, so a role is never surfaced
        twice. Upsert with ignore-on-conflict makes a re-run idempotent if two
        runs race.
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
            for i in range(0, len(rows), _SEEN_BATCH):
                self.supabase.table("seen_jobs").upsert(
                    rows[i:i + _SEEN_BATCH],
                    on_conflict="job_id,company", ignore_duplicates=True,
                ).execute()
        except Exception as e:
            print(f"[{self.agent_id}] seen_jobs write failed: {e}")
            notify_error(self.agent_id, f"seen_jobs write failed: {e}")

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

            # STEP 2 — two Python filters: US-based, then entry-level title.
            candidates = [
                j for j in jobs
                if _passes_us_filter(j) and _passes_entry_level_filter(j)
            ]

            # STEP 3 — new vs. seen; record every new posting immediately.
            company_new = self._find_new_jobs(name, candidates)
            self._record_seen(company_new)
            new_jobs.extend(company_new)

        # STEP 4 — collapse the same role posted across multiple cities into one
        # entry (seen_jobs already recorded every individual posting above).
        deduped = dedup_multi_location(new_jobs)

        # STEP 5 — Discord. One message per new posting, or a single line when
        # there's nothing new today.
        if deduped:
            for j in deduped:
                self._emit(format_job_message(
                    j["company"], j["title"], j["url"],
                    j.get("location") or "Not specified",
                ))
            content = (
                f"✅ Job scout complete — {companies_checked} companies checked, "
                f"{len(deduped)} new posting(s) surfaced"
            )
        else:
            self._emit(f"✅ {companies_checked} companies checked — no new postings today")
            content = (
                f"✅ Job scout complete — {companies_checked} companies checked, "
                f"no new postings today"
            )

        return AgentResult(
            content=content,
            metadata={
                "companies_checked": companies_checked,
                "jobs_scanned": jobs_scanned,
                "new_jobs": len(new_jobs),
                "deduped": len(deduped),
            },
        )


# ── Direct-run harness (no Discord posting / no Supabase logging via run()) ──

if __name__ == "__main__":
    # Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    # post=False → prints postings instead of sending to Discord. Still reads/
    # writes seen_jobs. execute() directly, so run()'s Supabase logging + summary
    # post + embedding are all skipped.
    agent = JobScoutAgent(post=False)
    result = agent.execute()
    print("\n" + "=" * 60)
    print(result.content)
    import json
    print(f"\nmetadata: {json.dumps(result.metadata, indent=2)}")
