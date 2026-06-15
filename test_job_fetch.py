"""
test_job_fetch.py — standalone, READ-ONLY job-fetch verification.

Loops every company in config/companies.py, calls the appropriate fetcher via
integrations.job_boards.fetch_company_jobs (which routes by `ats`), and prints
what came back — then applies the SAME relevance filter the agent uses and
reports how much survives it.

NO side effects: no Supabase, no Discord, no Claude. Just GETs/POSTs to the job
boards and prints to the terminal.

    python test_job_fetch.py

NB on the relevance filter: the matching RULE (target_roles → those terms, else
the global RELEVANCE_KEYWORDS; case-insensitive substring) lives in
agents/job_scout.py as filter_relevant_jobs/is_relevant. The DATA it matches
against (each company's target_roles and the global RELEVANCE_KEYWORDS) lives in
config/companies.py. We import the real filter so this verifies the actual code
path, not a re-implementation.
"""

import sys
import time

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from config.companies import COMPANIES, RELEVANCE_KEYWORDS, SEARCH_QUERY
from integrations.job_boards import fetch_company_jobs
# The real filter the agent applies (read-only import — nothing is modified).
from agents.job_scout import filter_relevant_jobs


def _titles(jobs, n=3):
    """First n job titles, joined for a compact one-line sample."""
    return [j.get("title", "<no title>") for j in jobs[:n]]


def main():
    rows = []          # collected per-company results for the summary
    zero_pass_flags = []  # companies that returned jobs but 0 passed the filter

    for company in COMPANIES:
        name = company["name"]
        ats = company.get("ats", "?")
        target_roles = company.get("target_roles") or []
        filter_basis = "target_roles" if target_roles else "RELEVANCE_KEYWORDS"

        print("=" * 78)
        print(f"{name}  [{ats}]")

        # ── Placeholder: nothing to fetch ──────────────────────────────────
        if ats == "placeholder":
            print("  SKIPPED (placeholder)"
                  + (f" — {company['note']}" if company.get("note") else ""))
            rows.append((name, ats, "SKIPPED", 0, 0))
            continue

        # ── Fetch ──────────────────────────────────────────────────────────
        try:
            jobs = fetch_company_jobs(company, SEARCH_QUERY)
        except Exception as e:
            print(f"  FAILED — {type(e).__name__}: {e}")
            rows.append((name, ats, "FAILED", 0, 0))
            continue

        n = len(jobs)
        print(f"  jobs returned: {n}")
        for t in _titles(jobs):
            print(f"     • {t}")

        # ── Relevance filter (same logic the agent uses) ───────────────────
        relevant = filter_relevant_jobs(jobs, target_roles, RELEVANCE_KEYWORDS)
        r = len(relevant)
        print(f"  relevant ({filter_basis}): {r}")
        for t in _titles(relevant):
            print(f"     ✓ {t}")

        # Flag: returned jobs but none passed the filter — likely the filter is
        # too strict for this company, or its titles don't match the keywords.
        if n > 0 and r == 0:
            print("  ⚠️  0 relevant despite returning jobs — filter may be too "
                  "strict / keywords don't match this company's titles")
            zero_pass_flags.append((name, ats, n, filter_basis))

        status = "OK" if n > 0 else "EMPTY"
        rows.append((name, ats, status, n, r))

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "#" * 78)
    print("SUMMARY")
    print("#" * 78)
    print(f"{'STATUS':<8} {'COMPANY':<24} {'ATS':<11} {'JOBS':>5} {'RELEVANT':>9}")
    print("-" * 78)
    for name, ats, status, n, r in rows:
        print(f"{status:<8} {name:<24} {ats:<11} {n:>5} {r:>9}")

    counts = {}
    for _, _, status, _, _ in rows:
        counts[status] = counts.get(status, 0) + 1
    total_jobs = sum(n for *_, n, _ in rows)
    total_rel = sum(r for *_, r in rows)
    print("-" * 78)
    print("  ".join(f"{k}={v}" for k, v in sorted(counts.items()))
          + f"  | total jobs={total_jobs}  total relevant={total_rel}")

    if zero_pass_flags:
        print("\n⚠️  Returned jobs but 0 passed the relevance filter:")
        for name, ats, n, basis in zero_pass_flags:
            print(f"     - {name} [{ats}] — {n} jobs, filtered on {basis}")
    else:
        print("\nNo company returned jobs with 0 passing the relevance filter.")


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\nDone in {time.time() - t0:.1f}s")
