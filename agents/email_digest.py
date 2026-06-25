"""
email_digest — pulls the last 24h of mail, keeps only the two kinds worth a
deep read (ISW situation reports and research-paper / article emails), fetches
their full bodies, and asks Claude to summarize them.

Governance Phase 2: Claude now returns a structured DigestOutput (Pydantic)
rather than free-form markdown. We validate that JSON, run the Tier 1 eval
checks against it (evals/checks.py), then render it to readable Discord
markdown. The structured object is saved separately
(AgentResult.structured_output) so the eval layer has typed data to assert on.

The field that matters most here is is_delta: it proves memory is changing
behavior (the agent recognizes a summary builds on a prior one), not just being
retrieved. The delta_validity check guards it — a claimed delta must name the
prior summary it builds on.

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
from agents.schemas import DigestOutput                             # noqa: E402
from evals.checks import run_digest_checks                          # noqa: E402
from integrations.gmail import list_recent_emails, get_email_body   # noqa: E402
from integrations.discord_notify import notify_error                # noqa: E402


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

You may also be given PRIOR CONTEXT: summaries you wrote in earlier runs, each
tagged with the date you wrote it. Use it only to judge what is genuinely new —
never repeat it as if it just happened.

Write one entry per email. For each entry produce a tight, concrete summary:
for ISW, the key developments; for research, the key finding, the method, and
why it's relevant. Base every claim on the email body provided. Do not invent
findings.

Respond with valid JSON only. No prose before or after.
Your response must match this exact structure:
{
  "isw": [
    {
      "email_id": "...",
      "title": "...",
      "summary": "...",
      "is_delta": true,
      "delta_basis": "..."
    }
  ],
  "research": [...]
}

For is_delta: set true if this builds on a prior summary provided in context.
If true, delta_basis must be the exact date of the prior summary you referenced
(e.g. '2026-06-20'). If false, set delta_basis to null.
email_id must be the exact id given for that email in the input.
summary must be plain text only — no quotes, no special characters.
title must be the email subject line, plain text only.
"""


# ── Rendering / parsing helpers ──────────────────────────────────────────────

def _strip_code_fences(text: str) -> str:
    """
    Defensively unwrap a ```json … ``` (or bare ``` … ```) fence if Claude adds
    one despite being asked for raw JSON. Leaves clean JSON untouched.
    """
    s = text.strip()
    if s.startswith("```"):
        # Drop the opening fence line (``` or ```json) and the trailing fence.
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -len("```")]
    return s.strip()


def _clean_json_response(text: str) -> str:
    """
    Trim anything Claude tucked outside the JSON object — a stray sentence
    before the opening brace or a sign-off after the closing one — so
    model_validate_json sees only the object. Run after _strip_code_fences.
    """
    return text[text.index("{"): text.rindex("}") + 1]


# Sections in display order, with the emoji headings the digest has always used.
# Each entry is (heading, attribute name on DigestOutput).
_SECTIONS = (
    ("🗺️ ISW — Institute for the Study of War", "isw"),
    ("📄 Research & Articles", "research"),
)


def _format_digest_for_discord(output: DigestOutput) -> str:
    """
    Render a validated DigestOutput into the readable markdown digest posted to
    Discord. Preserves the ISW and research section headers; one bullet per
    item (title in bold, then the summary). A 🔄 marks items where is_delta is
    True, so it's clear at a glance which summaries build on prior context.
    Empty sections are omitted.
    """
    total = len(output.isw) + len(output.research)
    lines = [
        f"📰 **Email digest** — {len(output.isw)} ISW, "
        f"{len(output.research)} research in the last 24h",
        "",
    ]

    for heading, attr in _SECTIONS:
        items = getattr(output, attr)
        if not items:
            continue
        lines.append(f"**{heading}**")
        for item in items:
            delta = " 🔄" if item.is_delta else ""
            lines.append(f"- **{item.title}**{delta} — {item.summary}")
        lines.append("")

    if total == 0:
        return "📭 **Email digest** — nothing to surface in the last 24h."
    return "\n".join(lines).strip()


class EmailDigestAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "email-digest"

    def execute(self) -> AgentResult:
        # Step 1: filter into ISW and research, then fetch full bodies for the
        # matched emails. We keep the input ids around so each item Claude
        # returns can be tied back to a real email.
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

        # The body is attacker-controlled, so it flows to Claude as
        # untrusted_data (see the prompt-injection note in BaseAgent.call_claude),
        # never as trusted text. email_id is included so Claude can echo each id
        # back into the right list.
        def _payload(email: dict, kind: str) -> dict:
            return {
                "kind": kind,
                "email_id": email["id"],
                "from": email["from"],
                "subject": email["subject"],
                "body": get_email_body(email["id"]),
            }

        batch = (
            [_payload(e, "ISW") for e in isw]
            + [_payload(e, "RESEARCH") for e in research]
        )

        # Step 2: pull prior ISW context so Claude can flag what's actually new
        # (and ground any is_delta against a dated prior summary). This is our
        # own past output (trusted), so it goes in the user prompt, not the
        # untrusted_data block. Skip the lookup when there's no ISW mail.
        prior_context = ""
        if isw:
            query = "ISW situation report developments: " + "; ".join(
                e["subject"] for e in isw
            )
            prior_context = self.recall_memory(query, limit=3)

        # Step 3: ask for JSON (the structure is spelled out in SYSTEM_PROMPT).
        user_prompt = (
            f"Summarize these {len(batch)} emails ({len(isw)} ISW, "
            f"{len(research)} research/article) into the JSON object described "
            "in your instructions, and nothing else."
        )
        if prior_context:
            user_prompt += (
                "\n\nPRIOR CONTEXT (your earlier ISW summaries, each tagged with "
                "the date you wrote it — for judging what is new and as the "
                f"delta_basis for any is_delta item):\n{prior_context}"
            )

        response_text = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            untrusted_data=json.dumps(batch, ensure_ascii=False, indent=2),
            max_tokens=8192,
        )

        # Step 4: parse into the typed contract. A failure here means Claude
        # returned something off-shape; raise so base.py run() marks the run as
        # error rather than silently posting garbage.
        try:
            digest_output = DigestOutput.model_validate_json(
                _clean_json_response(_strip_code_fences(response_text))
            )
        except Exception as e:
            notify_error(
                "email-digest",
                f"DigestOutput validation failed: {e}\n"
                f"Raw response:\n{response_text[:1800]}",
            )
            raise ValueError(
                f"email-digest: Claude response failed DigestOutput validation: {e}\n"
                f"Raw response (first 500 chars): {response_text[:500]}"
            ) from e

        # Step 5: run the Tier 1 deterministic checks and stash the results so
        # base.py run() persists them via log_eval_results() after _save_output.
        eval_results = run_digest_checks(digest_output)
        self._eval_results = eval_results

        # Step 6: render the typed object to readable Discord markdown.
        content = _format_digest_for_discord(digest_output)

        # Step 7: hand back both the markdown (for Discord) and the structured
        # object (for the eval layer / agent_outputs.structured_output).
        delta_count = sum(
            1 for i in digest_output.isw + digest_output.research if i.is_delta
        )
        return AgentResult(
            content=content,
            structured_output=digest_output.model_dump(),
            metadata={
                "isw_count": len(digest_output.isw),
                "research_count": len(digest_output.research),
                "delta_count": delta_count,
                "eval_passed": all(r["passed"] for r in eval_results),
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
