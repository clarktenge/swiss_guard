# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  LIVE smoke test — NOT a free/offline unit test. Run manually only.
# Running this hits real services and has side effects:
#   • reads your actual inbox via the Gmail API (consumes quota)
#   • calls Claude (billed)
#   • posts the briefing to your email-triage Discord webhook
#   • generates a Voyage AI embedding + inserts Supabase rows (via run())
#
# Run it once with:  python test_email_triage.py
# ─────────────────────────────────────────────────────────────────────────────
import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.email_triage import EmailTriageAgent

agent = EmailTriageAgent()

# run() does the full pipeline: execute() -> Supabase logging -> Discord post.
# Swap for `agent.execute()` if you want to preview the markdown without any
# side effects (no Discord post, no DB rows, no embedding).
result = agent.run()

print(result.content)
