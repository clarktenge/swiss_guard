"""
email_digest — pulls the last 24h of mail, keeps only the two kinds worth a
deep read (ISW situation reports and research-paper / article emails), fetches
their full bodies, and asks Claude to summarize them into clean Discord markdown.

This is the simple version, like email_triage: no Pydantic schema, no eval
checks, no governance. The differences from triage are that this agent reads
*full bodies* (not just snippets) and pulls prior ISW context out of memory so
the summary can call out what's genuinely new since the last report.

Run it directly to digest your live inbox and print the markdown:

    python agents/email_digest.py

That path calls execute() only — it hits Gmail and Claude but deliberately
skips run()'s side effects (Supabase logging, Discord post, Voyage embedding).
"""

import os
import sys
import json

# Allow running this file directly (python agents/email_digest.py) — the script
# dir is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult                      # noqa: E402
from integrations.gmail import list_recent_emails, get_email_body   # noqa: E402


# Senders matching any of these (case-insensitive substring of the From header)
# are treated as ISW situation reports.
ISW_SENDER_TERMS = (
    "isw",
    "understandingwar",
    "institute for the study of war",
)

# Emails whose sender OR subject contains any of these are treated as research
# papers / article digests.
RESEARCH_TERMS = (
    "arxiv",
    "journal",
    "research",
    "digest",
    "newsletter",
    "weekly",
)


def _classify(email: dict) -> str:
    """
    Return 'isw', 'research', or '' for an email. ISW wins when an email could
    match both (an ISW newsletter is still an ISW report, not generic research).
    """
    sender = email.get("from", "").lower()
    subject = email.get("subject", "").lower()

    if any(term in sender for term in ISW_SENDER_TERMS):
        return "isw"
    if any(term in sender or term in subject for term in RESEARCH_TERMS):
        return "research"
    return ""


SYSTEM_PROMPT = """\
You are a research-digest assistant. You are given the full bodies of emails
from the last 24 hours that have already been filtered down to two kinds:

  • ISW — situation reports from the Institute for the Study of War.
  • RESEARCH — research papers, journal alerts, and article/newsletter digests.

You may also be given PRIOR CONTEXT: summaries you wrote in earlier runs. Use it
only to judge what is genuinely new — never repeat it as if it just happened.

Produce GitHub-flavored markdown with up to two sections, in this order. Omit a
section entirely if it has no emails (no "None" placeholders).

## 🗺️ ISW — Institute for the Study of War
Write a single flowing 3–5 paragraph summary of the key developments across all
ISW emails (synthesize them; do not summarize each email separately). Lead with
the most significant developments. Where the prior context shows something was
already reported, explicitly frame the new material as an update ("newly", "now",
"since the last report") rather than re-describing settled facts. If nothing is
materially new versus the prior context, say so plainly in a sentence.

## 📄 Research & Articles
One bullet per email. Each bullet: the title/subject in bold, then 2–3 sentences
covering the key finding, the method or approach, and why it's relevant. Be
concrete — name the result, not just the topic.

Rules:
  - Start directly with the first section heading. No preamble, no sign-off.
  - Base every claim on the email bodies provided. Do not invent findings.
  - Output markdown only. Do not wrap it in code fences.
"""


class EmailDigestAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "email-digest"

    def execute(self) -> AgentResult:
        emails = list_recent_emails(hours_back=24)

        isw, research = [], []
        for e in emails:
            kind = _classify(e)
            if kind == "isw":
                isw.append(e)
            elif kind == "research":
                research.append(e)

        matched = isw + research
        if not matched:
            return AgentResult(
                content="📭 **Email digest** — no ISW or research emails in the last 24h.",
                metadata={"input_count": len(emails), "isw": 0, "research": 0},
            )

        # Fetch full bodies for the matched emails. The body is attacker-
        # controlled, so it flows to Claude as untrusted_data (see the prompt-
        # injection note in BaseAgent.call_claude), never as trusted text.
        def _payload(email: dict, kind: str) -> dict:
            return {
                "kind": kind,
                "from": email["from"],
                "subject": email["subject"],
                "body": get_email_body(email["id"]),
            }

        batch = (
            [_payload(e, "ISW") for e in isw]
            + [_payload(e, "RESEARCH") for e in research]
        )

        # Pull prior ISW context so the summary can flag what's actually new.
        # This is our own past output (trusted), so it goes in the user prompt,
        # not the untrusted_data block. Skip the lookup when there's no ISW mail.
        prior_context = ""
        if isw:
            query = "ISW situation report developments: " + "; ".join(
                e["subject"] for e in isw
            )
            prior_context = self.recall_memory(query, limit=3)

        user_prompt = (
            f"Summarize these {len(batch)} emails ({len(isw)} ISW, "
            f"{len(research)} research/article) into the markdown described in "
            "your instructions, and nothing else."
        )
        if prior_context:
            user_prompt += (
                "\n\nPRIOR CONTEXT (your earlier ISW summaries — for judging "
                f"what is new, do not repeat verbatim):\n{prior_context}"
            )

        body = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            untrusted_data=json.dumps(batch, ensure_ascii=False, indent=2),
            max_tokens=4096,
        )

        header = (
            f"📰 **Email digest** — {len(isw)} ISW, {len(research)} research "
            "in the last 24h\n\n"
        )
        return AgentResult(
            content=header + body.strip(),
            metadata={
                "input_count": len(emails),
                "isw": len(isw),
                "research": len(research),
            },
        )


# ── Direct-run harness (no Supabase/Discord/embedding side effects) ──────────

if __name__ == "__main__":
    # The output is emoji-heavy; the default Windows console is cp1252 and would
    # crash on it. Force UTF-8 where the runtime supports it.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    agent = EmailDigestAgent()
    result = agent.execute()
    print(result.content)
