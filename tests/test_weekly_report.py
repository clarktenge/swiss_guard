# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  LIVE smoke test — NOT a free/offline unit test. Run manually only.
# Running this hits real services and has side effects:
#   • reads the agent_outputs table from Supabase (the other agents' results)
#   • calls Claude (billed)
#   • posts the wrap-up to your weekly-report Discord webhook
#   • generates a Voyage AI embedding + inserts Supabase rows (via run())
#
# It does NOT call any external content APIs (Gmail, Strava, job boards) — the
# weekly report only reads what the other agents already stored.
#
# Run it once with:  python test_weekly_report.py
# ─────────────────────────────────────────────────────────────────────────────
import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.weekly_report import WeeklyReportAgent

agent = WeeklyReportAgent()

# run() does the full pipeline: execute() -> Supabase logging -> Discord post.
# Swap for `agent.execute()` if you want to preview the markdown without any
# side effects (no Discord post, no DB rows, no embedding).
result = agent.run()

print(result.content)
