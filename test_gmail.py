from integrations.gmail import list_recent_emails

emails = list_recent_emails(hours_back=24)
print(f"Found {len(emails)} emails")
for e in emails[:3]:
    print(f"  - {e['from'][:40]} | {e['subject'][:50]}")