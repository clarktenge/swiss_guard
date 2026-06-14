# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  LIVE smoke test — NOT a free/offline unit test. Run manually only.
# Running this hits real services and has side effects:
#   • reads your actual inbox via the Gmail API (consumes quota)
#   • fetches full bodies for every matched email (more quota)
#   • calls Claude (billed) and Voyage AI for memory recall (billed)
#   • posts the digest to your email-digest Discord webhook
#   • generates a Voyage AI embedding + inserts Supabase rows (via run())
#
# Run it once with:  python test_email_digest.py
# ─────────────────────────────────────────────────────────────────────────────
import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.email_digest import EmailDigestAgent

agent = EmailDigestAgent()

# run() does the full pipeline: execute() -> memory recall -> Supabase logging
# -> Discord post. Swap for `agent.execute()` to preview the markdown without
# any side effects (no Discord post, no DB rows, no output embedding).
result = agent.run()

print(result.content)
