"""
scripts/clean_watchlist.py — one-time watch-list cleanup.

Re-evaluates every job currently in watched_jobs against the corrected HARD
REJECTS — specifically the degree / years-of-experience requirements that live
in the job DESCRIPTION — and removes any that violate them.

Why this exists: job_scout used to judge roles on their TITLE alone (the posting
description was never sent to Claude), so appealing-sounding titles whose
qualifications section actually demands a Master's/PhD or N+ years of experience
slipped onto the watch list. Now that the agent reads descriptions, this script
back-fills that judgment for the rows already persisted:

  1. Read every row in watched_jobs.
  2. Re-fetch each role's company board to recover its live description
     (watched_jobs stores no description, so we must re-fetch).
  3. Ask Claude ONLY the hard-reject question (not relevance — we only remove
     roles that genuinely violate a hard reject, never ones that are merely a
     weaker match).
  4. Delete the violators from watched_jobs and report exactly what was removed.

Roles whose description can't be recovered (posting closed / board changed / a
source that carries no body) are reported as "unresolved" and KEPT — we never
delete on missing data.

Usage:
    python scripts/clean_watchlist.py            # apply removals
    python scripts/clean_watchlist.py --dry-run  # preview only, delete nothing
"""

import os
import sys
import json
from typing import Dict, List

# scripts/ is one level below the project root; put the root on the path so the
# package imports below resolve when run directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.job_scout import JobScoutAgent                  # noqa: E402
from config.companies import COMPANIES, SEARCH_QUERY        # noqa: E402
from integrations.job_boards import fetch_company_jobs      # noqa: E402


# Jobs per Claude hard-reject call. Each job carries a full description, so keep
# the batch small (mirrors job_scout._CLAUDE_CHUNK).
_CHUNK = 10


# Hard-reject-only judge. Deliberately NARROWER than job_scout's CLAUDE_SYSTEM:
# that prompt also drops roles for weak relevance, but here we must remove ONLY
# genuine hard-reject violations, so this prompt judges nothing else.
CLEANUP_SYSTEM = (
    "You audit job postings already on Clark Enge's watch list. Clark is an "
    "entry-level candidate (UCSB undergrad, June 2027 start, active Secret "
    "clearance). For EACH job object, read the `description` field IN FULL and "
    "decide ONLY whether it trips a HARD REJECT. Judge nothing about relevance "
    "or fit — a perfectly relevant role still fails if it trips a hard reject.\n\n"
    "HARD REJECTS (any one makes the job a violation):\n"
    "- The description states a minimum professional/industry experience "
    'requirement of 2+ years (e.g. "3+ years," "5+ years industry experience," '
    '"minimum 4 years," "4+ years professional C++"). An entry-level range like '
    '"0-2 years" is NOT a violation.\n'
    "- The description REQUIRES a Master's, MS, PhD, or doctorate (e.g. "
    '"Master\'s degree required," "MS required," "PhD in..."). A degree listed '
    'only as "preferred"/"a plus"/"or equivalent experience", or a plain '
    "Bachelor's requirement, is NOT a violation.\n"
    "- senior/staff/principal/lead in the title.\n"
    "- Requires ACTIVE TS / TS/SCI / a clearance above Secret as a hard "
    '("must have") requirement. "Able to obtain TS/SCI" is NOT a violation.\n'
    "- Internship or co-op; a 2026 start date; not US-based / requires visa "
    "sponsorship.\n\n"
    "Return a JSON array with one object per input job, echoing its `id`:\n"
    "[\n"
    '  {"id": str, "violates": bool, "rule": str, "evidence": str}\n'
    "]\n"
    '`rule` is a short label (e.g. "experience", "degree", "seniority", '
    '"clearance", "intern", "2026", "non-US") or "" when violates is false. '
    '`evidence` quotes the exact phrase from the description that triggers the '
    "reject, or \"\" when none. Return JSON only, no other text."
)

CLEANUP_USER = (
    "Audit these watch-list jobs. For each, read the `description` and decide "
    "whether it trips a hard reject, echoing the `id`. Return the JSON array "
    "described in your instructions."
)


def _company_config(name: str) -> Dict:
    """The COMPANIES entry whose name matches `name`, or {} if none."""
    for c in COMPANIES:
        if c["name"] == name:
            return c
    return {}


def _descriptions_for(company: str, agent: JobScoutAgent,
                      cache: Dict[str, Dict[str, str]]) -> Dict[str, str]:
    """
    {job_id -> description} for a company's live board, fetched once and cached.
    Returns {} (and logs) if the company isn't in COMPANIES or the fetch fails.
    """
    if company in cache:
        return cache[company]

    cfg = _company_config(company)
    descriptions: Dict[str, str] = {}
    if not cfg:
        print(f"  ! '{company}' not found in config/companies.py — cannot re-fetch")
    else:
        try:
            for job in fetch_company_jobs(cfg, SEARCH_QUERY):
                descriptions[job["job_id"]] = job.get("description") or ""
        except Exception as e:
            print(f"  ! re-fetch failed for '{company}': {e}")
    cache[company] = descriptions
    return descriptions


def _judge(agent: JobScoutAgent, batch: List[Dict]) -> Dict[str, Dict]:
    """
    Ask Claude the hard-reject question for a batch of {id, title, description}.
    Returns {id -> {"violates": bool, "rule": str, "evidence": str}}. On a
    malformed/failed reply, returns {} for the batch (→ those jobs are treated
    as unresolved and kept).
    """
    payload = [
        {"id": b["id"], "title": b["title"], "description": b["description"]}
        for b in batch
    ]
    try:
        raw = agent.call_claude(
            system_prompt=CLEANUP_SYSTEM,
            user_prompt=CLEANUP_USER,
            untrusted_data=json.dumps(payload, ensure_ascii=False, indent=2),
            max_tokens=2048,
        )
    except Exception as e:
        print(f"  ! Claude call failed for a batch: {e}")
        return {}

    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        items = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        print("  ! Claude reply was not parseable JSON; keeping this batch")
        return {}
    if not isinstance(items, list):
        return {}

    out: Dict[str, Dict] = {}
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("id"), str):
            out[it["id"]] = {
                "violates": bool(it.get("violates")),
                "rule": str(it.get("rule") or ""),
                "evidence": str(it.get("evidence") or ""),
            }
    return out


def main(dry_run: bool) -> None:
    agent = JobScoutAgent(post=False)

    watched = agent._fetch_watched_jobs()
    print(f"Watch list: {len(watched)} job(s)\n")
    if not watched:
        return

    # Recover each watched job's live description, then batch them to Claude.
    desc_cache: Dict[str, Dict[str, str]] = {}
    judgeable: List[Dict] = []      # {id, company, title, url, description}
    unresolved: List[Dict] = []     # description couldn't be recovered

    for w in watched:
        company, job_id = w.get("company", ""), w.get("job_id", "")
        description = _descriptions_for(company, agent, desc_cache).get(job_id, "")
        record = {"id": job_id, "company": company, "title": w.get("title", ""),
                  "url": w.get("url", ""), "description": description}
        (judgeable if description else unresolved).append(record)

    verdicts: Dict[str, Dict] = {}
    for i in range(0, len(judgeable), _CHUNK):
        chunk = judgeable[i:i + _CHUNK]
        print(f"Evaluating {len(chunk)} job(s) "
              f"({i + 1}-{i + len(chunk)} of {len(judgeable)})…")
        verdicts.update(_judge(agent, chunk))

    # Partition into remove / keep. A job with no verdict (Claude dropped it or
    # the batch failed) is treated as unresolved → kept.
    to_remove: List[Dict] = []
    for j in judgeable:
        v = verdicts.get(j["id"])
        if v and v["violates"]:
            j["rule"], j["evidence"] = v["rule"], v["evidence"]
            to_remove.append(j)
        elif not v:
            unresolved.append(j)

    # ── Report ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    if to_remove:
        verb = "WOULD REMOVE" if dry_run else "REMOVING"
        print(f"{verb} {len(to_remove)} hard-reject violation(s):\n")
        for j in to_remove:
            print(f"  ✗ {j['company']} — {j['title']}")
            print(f"      rule: {j['rule']}")
            if j["evidence"]:
                print(f"      evidence: \"{j['evidence']}\"")
            print(f"      {j['url']}\n")
    else:
        print("No hard-reject violations found on the watch list.\n")

    if unresolved:
        print(f"Kept {len(unresolved)} job(s) that could not be re-evaluated "
              f"(no live description — posting closed or no body available):")
        for j in unresolved:
            print(f"  • {j['company']} — {j['title']}")
        print()

    # ── Apply ─────────────────────────────────────────────────────────────────
    if dry_run:
        print("Dry run — no rows deleted. Re-run without --dry-run to apply.")
        return

    deleted = 0
    for j in to_remove:
        try:
            agent.supabase.table("watched_jobs").delete().eq(
                "job_id", j["id"]).eq("company", j["company"]).execute()
            deleted += 1
        except Exception as e:
            print(f"  ! delete failed for {j['company']} — {j['title']}: {e}")
    print(f"Deleted {deleted} of {len(to_remove)} violating row(s) from watched_jobs.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    main(dry_run="--dry-run" in sys.argv[1:])
