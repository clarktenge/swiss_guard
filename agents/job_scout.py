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
  4. Multi-location dedup: collapse the same role posted across cities into one
     entry (location → "📍 Multiple locations") before Claude sees it.
  5. Claude judgment (replaces the old keyword filter): hard-rejects (degree/
     experience/seniority/clearance/intern/2026/non-US) plus relevance, returning
     the survivors with a reason, location, and a perfect_fit flag.
  6. Watch list: perfect_fit roles are persisted to watched_jobs (deduped by
     job_id+company) and flagged ⭐ today; every run also re-posts the full
     watch list as 📌 daily reminders.
  7. Discord: one message per matching job to #💼-job-scout, then the reminders;
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
TEST_COMPANIES = ["Onebrief", "Palantir", "Anduril"]

# Max job_ids per seen_jobs request. A single .in_() with thousands of ids makes
# a GET URL long enough for PostgREST to 400; batching keeps each request small.
_SEEN_BATCH = 100

# Jobs per Claude evaluation call. Sending the whole (potentially thousands-long)
# candidate list in one shot overruns the model's output budget and truncates the
# JSON reply to nothing; chunking keeps each call's input + output bounded.
_CLAUDE_CHUNK = 75


# ── Claude prompts (verbatim from the spec) ──────────────────────────────────

CLAUDE_SYSTEM = (
    "You are a job matching assistant for Clark Enge — UCSB Statistics & Data \n"
    "Science student, ML Researcher at AFRL (synthetic-to-real data gap for \n"
    "satellite imagery), active Secret clearance, background in agentic AI \n"
    "systems, computer vision, and deep learning. Targeting June 2027 start.\n"
    "Target roles: Outcome Engineer, Forward Deployed Engineer, Applied \n"
    "Scientist, ML Engineer, AI Engineer.\n\n"
    "HARD REJECTS — return nothing for a job if ANY of these are true:\n"
    "- Requires a Masters degree, PhD, or 2+ years of experience\n"
    "- Has senior/staff/principal/lead in the title\n"
    "- Requires ACTIVE TS, TS/SCI, or any clearance above Secret as a \n"
    '  hard requirement ("must have active TS/SCI" = reject; \n'
    '  "able to obtain TS/SCI" = keep)\n'
    "- Is an internship or co-op\n"
    "- Has a 2026 start date\n"
    "- Is not US-based or requires visa sponsorship\n\n"
    "For jobs that pass all hard rejects, return JSON:\n"
    "[\n"
    "  {\n"
    '    "company": str,\n'
    '    "title": str,\n'
    '    "url": str,\n'
    '    "location": str or "Not specified",\n'
    '    "reason": str,  // one sentence why this fits Clark specifically\n'
    '    "perfect_fit": bool  // true only if this is an exceptional match\n'
    "  }\n"
    "]\n\n"
    'A "perfect_fit" is a role where Clark\'s specific background \n'
    "(AFRL satellite imagery research, agentic AI systems, Secret clearance) \n"
    "maps directly onto what the job is asking for. Use sparingly — \n"
    "maybe 1 in 20 roles qualifies.\n\n"
    "Return empty list [] if nothing passes. Return JSON only, no other text."
)

CLAUDE_USER = (
    "Here are today's new job postings as a JSON array. Evaluate each one "
    "against the criteria and hard rejects in your instructions, and return "
    "the JSON array described there."
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


# ── Multi-location dedup ─────────────────────────────────────────────────────
# The same role is frequently posted once per city ("ML Engineer - Austin",
# "ML Engineer - San Diego", …). We collapse those into one entry before they
# reach Claude, so Clark sees the role once with a "📍 Multiple locations" tag
# instead of five near-identical cards.

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


# ── Cheap Python pre-filter (before any Claude call) ─────────────────────────
# Obvious hard rejects we can spot from the title alone, so Claude never has to
# spend a token (or a chunk slot) on them. Matched on word boundaries — a plain
# substring test would wrongly drop "Internal"/"International" on "intern" — and
# Claude still applies the same hard rejects, so anything that slips past here is
# caught downstream; the only failure mode worth avoiding is a false reject that
# hides a real role from Clark, which the word boundary guards against.
_TITLE_HARD_REJECT_TERMS = (
    "senior", "staff", "principal", "lead", "director", "manager",
    "vp", "vice president", "intern", "co-op", "internship",
    "phd", "ph.d", "doctorate", "head of",
)
_TITLE_HARD_REJECT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _TITLE_HARD_REJECT_TERMS) + r")\b",
    re.IGNORECASE,
)


def _title_hard_reject(title: str) -> bool:
    """True if the title carries an obvious hard-reject term (seniority, intern/
    co-op, doctorate, management)."""
    return bool(_TITLE_HARD_REJECT_RE.search(title or ""))


# Per-job message presentation. Priority is matched on company name against
# config/companies.py and shown as a coloured tag on the company line.
_COMPANY_PRIORITY = {c["name"]: c.get("priority") for c in COMPANIES}
_PRIORITY_TAG = {"high": "🔴", "medium": "🟡"}
_JOB_DIVIDER = "─────────────────────────────"


def format_job_message(
    company: str, title: str, url: str, location: str, reason: str,
    perfect_fit: bool = False,
) -> str:
    """
    Render the Discord message for one matching job:

        ─────────────────────────────
        ⭐ PERFECT FIT          (only when perfect_fit)
        {🔴/🟡} **{company}**
        📋 {title}
        📍 {location}
        🔗 {url}
        💡 {reason}

    The company line leads with a priority tag (🔴 high / 🟡 medium, looked up
    from config/companies.py by name; 🔹 if the company has no priority).
    Perfect-fit roles get a ⭐ PERFECT FIT banner under the divider.
    """
    tag = _PRIORITY_TAG.get(_COMPANY_PRIORITY.get(company) or "", "🔹")
    lines = [_JOB_DIVIDER]
    if perfect_fit:
        lines.append("⭐ PERFECT FIT")
    lines.extend([
        f"{tag} **{company}**",
        f"📋 {title}",
        f"📍 {location}",
        f"🔗 {url}",
        f"💡 {reason}",
    ])
    return "\n".join(lines) + "\n"


def format_watch_reminder(
    company: str, title: str, url: str, location: str, reason: str,
) -> str:
    """
    Render a daily watch-list reminder for a previously-flagged perfect fit:

        ─────────────────────────────
        📌 **WATCH LIST REMINDER**
        🏢 {company} — {title}
        📍 {location}
        🔗 {url}
        💡 {reason}
    """
    return (
        f"{_JOB_DIVIDER}\n"
        f"📌 **WATCH LIST REMINDER**\n"
        f"🏢 {company} — {title}\n"
        f"📍 {location}\n"
        f"🔗 {url}\n"
        f"💡 {reason}\n"
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
            {"company": j["company"], "title": j["title"], "url": j["url"],
             "location": j.get("location") or "Not specified"}
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
        # drop the match if we can't verify it points at a real posting. We also
        # recover job_id + location from OUR input rather than trusting Claude,
        # so the watch-list key is real and the dedup "📍 Multiple locations"
        # marker survives.
        valid_urls = {j["url"] for j in jobs}
        by_key = {(j["company"].lower(), j["title"].lower()): j for j in jobs}
        cleaned: List[Dict] = []
        for m in matches:
            if not all(k in m and isinstance(m[k], str) and m[k].strip()
                       for k in ("company", "title", "url", "reason")):
                continue
            src = by_key.get((m["company"].lower(), m["title"].lower()))
            if m["url"] not in valid_urls:
                if not src:
                    continue
                m["url"] = src["url"]
            if src:
                m["job_id"] = src.get("job_id")
                m["location"] = src.get("location") or m.get("location") or "Not specified"
            else:
                m["location"] = m.get("location") or "Not specified"
            m["perfect_fit"] = bool(m.get("perfect_fit"))
            cleaned.append(m)
        return cleaned

    def _evaluate_chunked(self, jobs: List[Dict]) -> List[Dict]:
        """
        Evaluate jobs in batches of _CLAUDE_CHUNK, one Claude call per chunk, and
        union the results. Chunks are disjoint, so the union is just a
        concatenation. Returns [] for an empty input.
        """
        if not jobs:
            return []

        total_chunks = (len(jobs) + _CLAUDE_CHUNK - 1) // _CLAUDE_CHUNK
        all_matches: List[Dict] = []
        for n, i in enumerate(range(0, len(jobs), _CLAUDE_CHUNK), start=1):
            chunk = jobs[i:i + _CLAUDE_CHUNK]
            print(f"[{self.agent_id}] Evaluating chunk {n} of {total_chunks} "
                  f"({len(chunk)} jobs)")
            all_matches.extend(self._evaluate_with_claude(chunk))
        return all_matches

    # ── Supabase: watched_jobs (perfect-fit daily reminders) ────────────────

    def _watch_if_new(self, match: Dict) -> bool:
        """
        Persist a perfect-fit match to watched_jobs if it isn't already there
        (keyed by job_id + company). Returns True if it was newly added. Never
        raises — a watch-list hiccup must not sink the run.
        """
        job_id = match.get("job_id")
        company = match.get("company")
        if not job_id or not company:
            return False
        try:
            existing = (
                self.supabase.table("watched_jobs")
                .select("id")
                .eq("job_id", job_id)
                .eq("company", company)
                .execute()
                .data
            )
            if existing:
                return False
            self.supabase.table("watched_jobs").insert({
                "job_id": job_id,
                "company": company,
                "title": match.get("title", ""),
                "url": match.get("url", ""),
                "location": match.get("location") or "Not specified",
                "reason": match.get("reason", ""),
            }).execute()
            return True
        except Exception as e:
            print(f"[{self.agent_id}] watched_jobs write failed for {company}: {e}")
            notify_error(self.agent_id, f"watched_jobs write failed for {company}: {e}")
            return False

    def _fetch_watched_jobs(self) -> List[Dict]:
        """
        Every row in watched_jobs, oldest first, for the daily reminder re-post.
        Never raises — on failure logs to agent-logs and returns [].
        """
        try:
            return (
                self.supabase.table("watched_jobs")
                .select("job_id, company, title, url, location, reason")
                .order("added_at")
                .execute()
                .data
            ) or []
        except Exception as e:
            print(f"[{self.agent_id}] watched_jobs fetch failed: {e}")
            notify_error(self.agent_id, f"watched_jobs fetch failed: {e}")
            return []

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

        # STEP 4 — collapse the same role posted across multiple cities into one
        # entry (seen_jobs already recorded every individual posting above).
        deduped = dedup_multi_location(new_jobs)

        # STEP 4b — cheap Python pre-filter: drop obvious title hard-rejects
        # (seniority, intern/co-op, doctorate, management) before spending any
        # Claude tokens on them.
        candidates = [j for j in deduped if not _title_hard_reject(j["title"])]
        prefiltered = len(deduped) - len(candidates)
        print(f"[{self.agent_id}] pre-filtered {prefiltered} job(s) on title "
              f"hard-rejects ({len(candidates)} to evaluate)")

        # STEP 4c — Claude judges the survivors in chunks (entry-level + relevant).
        matches = self._evaluate_chunked(candidates)

        # STEP 5 — watch list: flag perfect fits and persist any new ones so they
        # come back as daily reminders.
        perfect = 0
        for m in matches:
            if m.get("perfect_fit"):
                perfect += 1
                self._watch_if_new(m)

        # STEP 6 — Discord. One message per match (posted here); the returned
        # `content` is what run() posts as the single completion/summary message.
        for m in matches:
            self._emit(format_job_message(
                m["company"], m["title"], m["url"],
                m.get("location") or "Not specified", m["reason"],
                perfect_fit=bool(m.get("perfect_fit")),
            ))

        # STEP 7 — daily watch-list reminder: re-post everything we're watching,
        # whether or not it surfaced today.
        watched = self._fetch_watched_jobs()
        for w in watched:
            self._emit(format_watch_reminder(
                w.get("company", ""), w.get("title", ""), w.get("url", ""),
                w.get("location") or "Not specified", w.get("reason", ""),
            ))

        matched_note = f"{len(matches)} matched today" if matches else "none matched today's criteria"
        perfect_note = f", {perfect} ⭐ perfect fit" if perfect else ""
        content = (
            f"✅ Job scout complete — {companies_checked} companies checked, "
            f"{len(new_jobs)} new jobs found, {matched_note}{perfect_note} "
            f"({len(watched)} on watch list)"
        )

        return AgentResult(
            content=content,
            metadata={
                "companies_checked": companies_checked,
                "jobs_scanned": jobs_scanned,
                "new_jobs": len(new_jobs),
                "deduped": len(deduped),
                "prefiltered": prefiltered,
                "candidates": len(candidates),
                "matched": len(matches),
                "perfect_fits": perfect,
                "watched": len(watched),
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
