"""
cost_report — a quick Claude-cost summary for Swiss Guard agents.

Reads the last 7 days of rows from the Supabase `agent_runs` table (populated by
BaseAgent.run(), which records input_tokens / output_tokens / estimated_cost_usd
per run) and prints:

  - total estimated cost per agent
  - total estimated cost for the week
  - average cost per run, per agent

Run from the project root (so .env is picked up):

    python scripts/cost_report.py
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

DAYS = 7


def main() -> None:
    supabase: Client = create_client(
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )

    since = datetime.now(timezone.utc) - timedelta(days=DAYS)
    rows = (
        supabase.table("agent_runs")
        .select("agent_id, estimated_cost_usd, input_tokens, output_tokens, started_at")
        .gte("started_at", since.isoformat())
        .execute()
        .data
    ) or []

    if not rows:
        print(f"No agent runs found in the last {DAYS} days.")
        return

    # Aggregate per agent. estimated_cost_usd can be NULL for runs logged before
    # cost tracking existed (or runs that made no Claude call); treat those as $0
    # but still count them toward the run total so the average isn't inflated.
    cost_by_agent: dict[str, float] = defaultdict(float)
    runs_by_agent: dict[str, int] = defaultdict(int)
    in_tokens_by_agent: dict[str, int] = defaultdict(int)
    out_tokens_by_agent: dict[str, int] = defaultdict(int)

    for r in rows:
        agent = r.get("agent_id") or "unknown"
        cost_by_agent[agent] += float(r.get("estimated_cost_usd") or 0)
        runs_by_agent[agent] += 1
        in_tokens_by_agent[agent] += int(r.get("input_tokens") or 0)
        out_tokens_by_agent[agent] += int(r.get("output_tokens") or 0)

    total_cost = sum(cost_by_agent.values())
    total_runs = sum(runs_by_agent.values())

    print(f"\nClaude cost report — last {DAYS} days "
          f"(since {since.date()} UTC)")
    print("=" * 64)
    header = f"{'agent':<20}{'runs':>6}{'in tok':>10}{'out tok':>10}{'cost':>9}{'avg/run':>9}"
    print(header)
    print("-" * 64)

    for agent in sorted(cost_by_agent, key=lambda a: cost_by_agent[a], reverse=True):
        runs = runs_by_agent[agent]
        cost = cost_by_agent[agent]
        avg = cost / runs if runs else 0.0
        print(
            f"{agent:<20}{runs:>6}{in_tokens_by_agent[agent]:>10}"
            f"{out_tokens_by_agent[agent]:>10}{cost:>9.4f}{avg:>9.4f}"
        )

    print("-" * 64)
    print(f"{'TOTAL':<20}{total_runs:>6}{'':>10}{'':>10}{total_cost:>9.4f}")
    print(f"\nTotal estimated cost for the week: ${total_cost:.4f}")


if __name__ == "__main__":
    main()
