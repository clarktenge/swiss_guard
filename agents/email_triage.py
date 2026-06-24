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

Sort EVERY email into exactly one of these four buckets, in this order:

  🔴 urgent
      Time-sensitive emails requiring action today. Genuinely needs attention
      soon AND requires action from a real person or institution: academic /
      application deadlines, account or security alerts (login attempts,
      password resets, fraud warnings), bills or payments due, and
      time-sensitive personal or professional matters (a message from a
      person, employer, school, bank, or government body that expects a
      response).

      Marketing time-pressure language is NOT urgency. Any promotional or
      marketing email goes in the sales bucket, never here, even when it
      uses phrases like "today only", "expires today", "last chance",
      "ends soon", "final hours", or "act now". A countdown in marketing
      copy does not make an email urgent.

      If the sender is a retail brand, e-commerce store, or marketing /
      mailing list, the email belongs in sales regardless of any urgency
      language in the subject line. Judge by who is actually asking and
      what real action is required — not by how loud the wording is.

  💼 opportunities
      Job postings, research opportunities, internships, interviews,
      referrals, intros, scholarships, research positions, grants, and calls
      for collaboration. This also includes emails from the Institute for the
      Study of War (ISW) and research-paper / academic-digest emails (e.g.
      arXiv, journal alerts, paper newsletters). Flag only — list the sender
      and subject; do NOT summarize them, as a separate email-digest agent
      handles summaries.

  🏷️ sales
      Discounts, drops, and promotional emails from brands: price drops,
      coupon codes, product launches, and marketing offers from brands and
      stores. This includes promotions that use deadline / scarcity wording
      ("today only", "expires today", "last chance", "ends soon") — they go
      here, not in urgent.

  📦 uncategorized
      Everything else — emails that don't fit any bucket above. Routine noise
      (newsletters that aren't research, receipts, social notifications,
      automated no-reply chatter) goes here.

Rules:
  - Account for EVERY input email. Each email goes into exactly one bucket —
    either a named bucket (urgent, opportunities, sales) or uncategorized.
    Never silently drop an email; if it doesn't fit a named bucket, it belongs
    in uncategorized.
  - Only include a section if it has at least one email. Omit empty sections
    entirely (no "None" placeholders).
  - Under each section, use a markdown bullet per email: the subject in bold,
    then the sender, then a brief (≤ 12 word) note on why it matters. For the
    opportunities bucket, ISW / research-paper items only need sender +
    subject — skip the "why it matters" note for those.
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
