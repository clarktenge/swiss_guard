# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  LIVE smoke test — NOT a free/offline unit test. Run manually only.
# Calls the real Gmail API with your OAuth token and reads your actual inbox.
# (Gmail reads don't cost money, but this is a live call against your account
# and consumes API quota — it is not a mocked test.)
# ─────────────────────────────────────────────────────────────────────────────
from integrations.gmail import list_recent_emails

emails = list_recent_emails(hours_back=24)
print(f"Found {len(emails)} emails")
for e in emails[:3]:
    print(f"  - {e['from'][:40]} | {e['subject'][:50]}")