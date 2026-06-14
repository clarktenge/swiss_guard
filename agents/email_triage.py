"""
email_triage — pulls the last 24h of mail, asks Claude to categorize it, and
returns clean markdown ready to post to Discord.

This is the simple version: no Pydantic schema, no eval checks, no governance.
Claude reads the batch and writes the briefing markdown directly; we just wrap
the email content as untrusted data and post the result.

Run it directly to triage your live inbox and print the briefing:

    python agents/email_triage.py

That path calls execute() only — it hits Gmail and Claude but deliberately
skips run()'s side effects (Supabase logging, Discord post, Voyage embedding).
"""

import os
import sys
import json

# Allow running this file directly (python agents/email_triage.py) — the script
# dir is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult            # noqa: E402
from integrations.gmail import list_recent_emails          # noqa: E402


SYSTEM_PROMPT = """\
You are an email triage assistant. You are given a batch of emails from the
last 24 hours (sender, subject, and a short snippet for each). Your job is to
produce a concise, scannable briefing for the reader to skim on Discord.

Sort the emails into these four sections, in this order:

  🔴 Urgent / time-sensitive
      Genuinely needs attention soon: deadlines, account/security issues,
      bills due, anything time-bound. Do NOT mark something urgent just
      because the subject shouts "URGENT" — judge the actual content.

  💼 Jobs & research opportunities
      Job postings, internships, interviews, referrals, intros, scholarships,
      research positions, grants, calls for collaboration.

  🏷️ Sales, drops & discounts
      Promotions, price drops, coupon codes, product launches, and marketing
      offers from brands and stores.

  📚 ISW & research papers (flag only)
      Emails from the Institute for the Study of War (ISW) and research-paper
      / academic-digest emails (e.g. arXiv, journal alerts, paper newsletters).
      Just flag that they arrived — list the sender and subject. Do NOT
      summarize them; a separate email-digest agent handles summaries.

Rules:
  - Only include a section if it has at least one email. Omit empty sections
    entirely (no "None" placeholders).
  - Under each section, use a markdown bullet per email: the subject in bold,
    then the sender, then a brief (≤ 12 word) note on why it matters. For the
    ISW & research section, skip the "why it matters" note — sender + subject
    is enough.
  - Routine noise (newsletters that aren't research, receipts, social
    notifications, automated no-reply chatter) does not need to be listed.
    Don't force every email into a section.
  - Keep it tight and skimmable. No preamble, no sign-off, no "here is your
    briefing" — start directly with the first section heading.
  - Output GitHub-flavored markdown only. Do not wrap it in code fences.
"""


class EmailTriageAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "email-triage"

    def execute(self) -> AgentResult:
        emails = list_recent_emails(hours_back=24)

        if not emails:
            return AgentResult(
                content="📭 **Email triage** — no new emails in the last 24h.",
                metadata={"input_count": 0},
            )

        # Compact, data-only view for the model. from/subject/snippet are
        # attacker-controlled, so this whole blob goes in as untrusted_data
        # (see the prompt-injection note in BaseAgent.call_claude).
        batch = [
            {
                "from": e["from"],
                "subject": e["subject"],
                "snippet": e.get("snippet", ""),
            }
            for e in emails
        ]

        body = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                f"Triage these {len(emails)} emails and write the briefing "
                "markdown described in your instructions, and nothing else."
            ),
            untrusted_data=json.dumps(batch, ensure_ascii=False, indent=2),
            max_tokens=4096,
        )

        header = f"📬 **Email triage** — {len(emails)} emails in the last 24h\n\n"
        return AgentResult(
            content=header + body.strip(),
            metadata={"input_count": len(emails)},
        )


# ── Direct-run harness (no Supabase/Discord/embedding side effects) ──────────

if __name__ == "__main__":
    # The output is emoji-heavy; the default Windows console is cp1252 and would
    # crash on it. Force UTF-8 where the runtime supports it.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    agent = EmailTriageAgent()
    result = agent.execute()
    print(result.content)
