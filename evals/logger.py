"""
logger — persists eval check results to Supabase.

Each check result becomes one row in the eval_results table (db/migration_001).
Over time those rows are the trend line that tells you whether a prompt or model
change made an agent better or worse — see docs/evals/email-triage.md.

base.py calls log_eval_results() automatically after _save_output() when an
agent has populated self._eval_results during execute().
"""

import os
from typing import List

from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


def log_eval_results(run_id: str, agent_id: str, results: List[dict]) -> None:
    """
    Write each check result to the eval_results table.

    results is the list produced by evals.checks.run_all_checks():
        [{"check": str, "passed": bool, "message": str}, ...]

    The eval_results.tier column is NOT NULL; these are all deterministic Tier 1
    checks, so we default tier to 1 unless a result explicitly carries its own
    "tier" (forward-compat for when Tier 2 LLM-judge results flow through here).
    """
    if not results:
        return

    supabase: Client = create_client(
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )

    rows = [
        {
            "run_id": run_id,
            "agent_id": agent_id,
            "check_name": r["check"],
            "tier": r.get("tier", 1),
            "passed": r["passed"],
            "reason": r["message"],
        }
        for r in results
    ]

    supabase.table("eval_results").insert(rows).execute()
