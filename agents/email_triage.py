"""
email_triage — pulls the last 24h of mail, asks Claude to categorize it, and
returns clean markdown ready to post to Discord.

Governance Phase 2: Claude now returns a structured TriageOutput (Pydantic)
rather than free-form markdown. We validate that JSON, run the Tier 1 eval
checks against it (evals/checks.py), then render it to the same human-readable
markdown for Discord. The structured object is saved separately
(AgentResult.structured_output) so the eval layer has typed data to assert on.

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
from agents.schemas import TriageOutput, EmailItem, SaleItem  # noqa: E402
from evals.checks import run_all_checks                    # noqa: E402
from integrations.gmail import list_recent_emails          # noqa: E402
from integrations.discord_notify import notify_error       # noqa: E402


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
  - For each item, the "reason" is one brief (≤ 12 word) note on why it's in
    that bucket. For the opportunities bucket, ISW / research-paper items can
    use a short sender/subject-based reason — they're flagged, not summarized.
  - "confidence" is your 0.0–1.0 certainty that the item belongs in its bucket.

Respond with valid JSON only. No prose before or after.
Your response must match this exact structure:
{
  "urgent":       [{"email_id": "...", "reason": "...", "confidence": 0.0}],
  "opportunities":[{"email_id": "...", "reason": "...", "confidence": 0.0}],
  "sales":        [{"email_id": "...", "brand": "...", "reason": "...",
                    "confidence": 0.0, "expires_at": null}],
  "uncategorized":[{"email_id": "..."}]
}
Every input email_id must appear in exactly one bucket.
reason must be one short sentence with no quotes or special characters.
brand (sales only) must be the sender brand name only, no other text."""


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
    Leaves the text untouched if it can't find a brace pair to slice on.
    """
    if "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text.strip()


def _sanitize_email(email: dict) -> dict:
    """
    Scrub the attacker-controlled string fields (from/subject/snippet) of
    characters that corrupt a JSON string before they reach Claude. Real
    inbox subjects carry stray double quotes, backslashes, newlines, and
    control characters that break the prompt's JSON blob — and, downstream,
    the model's echo of it. Returns a new dict; the original is left intact.
    """
    def clean(value: str) -> str:
        value = value.replace('"', "'").replace("\\", "/")
        value = value.replace("\n", " ").replace("\r", " ").replace("\t", " ")
        # Drop any remaining control characters (ord < 32).
        return "".join(ch for ch in value if ord(ch) >= 32)

    cleaned = dict(email)
    # Handle both "from" (raw Gmail key) and "from_" defensively.
    for key in ("from", "from_", "subject", "snippet"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = clean(cleaned[key])
    if isinstance(cleaned.get("subject"), str):
        cleaned["subject"] = cleaned["subject"][:200]
    if isinstance(cleaned.get("snippet"), str):
        cleaned["snippet"] = cleaned["snippet"][:300]
    return cleaned


def _build_triage_output(claude_response: str, emails_by_id: dict) -> TriageOutput:
    """
    Merge Claude's slim classification decisions back into full typed items.

    Claude now returns only the decision per email (email_id, reason,
    confidence, plus brand/expires_at for sales) — never the from_/subject,
    which it used to copy verbatim and corrupt with stray quotes and unicode.
    We reconstruct the human-facing fields from the original fetch
    (emails_by_id), so the only free text Claude contributes is its own reason.

    Raises (json.JSONDecodeError / ValidationError / KeyError) on a bad
    response so execute() can mark the run as an error rather than post garbage.
    """
    data = json.loads(_clean_json_response(_strip_code_fences(claude_response)))

    def base_fields(item: dict) -> dict:
        original = emails_by_id.get(item["email_id"], {})
        return {
            "email_id": item["email_id"],
            "from_": original.get("from", ""),
            "subject": original.get("subject", ""),
            # uncategorized items carry no reason/confidence in the new schema.
            "reason": item.get("reason", ""),
            "confidence": item.get("confidence", 0.0),
        }

    return TriageOutput(
        urgent=[EmailItem(**base_fields(i)) for i in data.get("urgent", [])],
        opportunities=[
            EmailItem(**base_fields(i)) for i in data.get("opportunities", [])
        ],
        sales=[
            SaleItem(
                **base_fields(i),
                brand=i.get("brand", ""),
                expires_at=i.get("expires_at"),
            )
            for i in data.get("sales", [])
        ],
        uncategorized=[
            EmailItem(**base_fields(i)) for i in data.get("uncategorized", [])
        ],
    )


# Sections in display order, with the emoji headings the briefing has always
# used. Each entry is (heading, attribute name on TriageOutput).
_SECTIONS = (
    ("🔴 Urgent", "urgent"),
    ("💼 Opportunities", "opportunities"),
    ("🏷️ Sales", "sales"),
    ("📦 Uncategorized", "uncategorized"),
)


def _format_for_discord(output: TriageOutput) -> str:
    """
    Render a validated TriageOutput into the scannable markdown briefing posted
    to Discord. Preserves the existing emoji/section structure: a bold heading
    per non-empty bucket, then one bullet per email (subject in bold, sender,
    and the short reason). Empty buckets are omitted.
    """
    total = sum(len(getattr(output, attr)) for _, attr in _SECTIONS)
    lines = [f"📬 **Email triage** — {total} emails in the last 24h", ""]

    for heading, attr in _SECTIONS:
        items = getattr(output, attr)
        if not items:
            continue
        lines.append(f"**{heading}**")
        for item in items:
            # Sales items carry a brand (and maybe an expiry) worth surfacing.
            brand = getattr(item, "brand", None)
            expires_at = getattr(item, "expires_at", None)
            sender = f"{brand} · {item.from_}" if brand else item.from_
            note = item.reason
            if expires_at:
                note = f"{note} (expires {expires_at})"
            lines.append(f"- **{item.subject}** — {sender} · {note}")
        lines.append("")

    return "\n".join(lines).strip()


class EmailTriageAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "email-triage"

    def execute(self) -> AgentResult:
        # Step 1: fetch the batch and remember every input id up front. The
        # conservation check (evals/checks.py) compares these against the ids
        # Claude returns, so we capture them before the model sees anything.
        emails = list_recent_emails(hours_back=24)

        if not emails:
            return AgentResult(
                content="📭 **Email triage** — no new emails in the last 24h.",
                metadata={"input_count": 0},
            )

        # Cap the batch so the JSON response can't outgrow Claude's output
        # budget. With the slim decision-only schema each item is ~4 fields
        # (~40 tokens), so 50 emails is ~2000 output tokens — well inside the
        # 8192 budget. Cap before computing input_email_ids so the conservation
        # check only expects ids Claude saw.
        if len(emails) > 50:
            print(f"[email-triage] Capped batch from {len(emails)} to 50 emails")
            emails = emails[:50]

        input_email_ids = [e["id"] for e in emails]

        # Index the original fetch by id so _build_triage_output can restore the
        # from_/subject Claude no longer echoes back (it only returns decisions).
        emails_by_id = {e["id"]: e for e in emails}

        # Compact, data-only view for the model. from/subject/snippet are
        # attacker-controlled, so this whole blob goes in as untrusted_data
        # (see the prompt-injection note in BaseAgent.call_claude). email_id is
        # included so Claude can echo each id back into the right bucket.
        batch = [
            _sanitize_email(
                {
                    "email_id": e["id"],
                    "from": e["from"],
                    "subject": e["subject"],
                    "snippet": e.get("snippet", ""),
                }
            )
            for e in emails
        ]

        # Step 2: ask for JSON (the structure is spelled out in SYSTEM_PROMPT).
        response_text = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                f"Triage these {len(emails)} emails and return the JSON object "
                "described in your instructions, and nothing else."
            ),
            untrusted_data=json.dumps(batch, ensure_ascii=False, indent=2),
            # Override the base default (4096): a batch of JSON triage items
            # needs a larger output budget or the response truncates mid-string.
            max_tokens=8192,
        )

        # Step 3: parse into the typed contract. A failure here means Claude
        # returned something off-shape; raise so base.py run() marks the run as
        # error rather than silently posting garbage.
        try:
            triage_output = _build_triage_output(response_text, emails_by_id)
        except Exception as e:
            # A response cut off by max_tokens won't end in the closing brace;
            # point at the budget rather than the schema so the fix is obvious.
            cleaned = _clean_json_response(_strip_code_fences(response_text))
            truncated = len(cleaned) > 100 and not cleaned.rstrip().endswith("}")
            hint = (
                " (response appears truncated — increase max_tokens or reduce batch)"
                if truncated else ""
            )
            # Surface the full raw response (not just a 500-char head) to the
            # agent-logs channel so we can see exactly which character broke the
            # JSON. notify_error caps at Discord's limit; cap here too to match.
            notify_error(
                "email-triage",
                f"TriageOutput validation failed{hint}: {e}\n"
                f"Raw response:\n{response_text[:1800]}",
            )
            raise ValueError(
                f"email-triage: Claude response failed TriageOutput validation{hint}: {e}\n"
                f"Raw response (first 500 chars): {cleaned[:500]}"
            ) from e

        # Step 4: run the Tier 1 deterministic checks and stash the results so
        # base.py run() persists them via log_eval_results() after _save_output.
        eval_results = run_all_checks(triage_output, input_email_ids)
        self._eval_results = eval_results

        # Step 5: render the typed object to the same human-readable markdown.
        content = _format_for_discord(triage_output)

        # Step 6: hand back both the markdown (for Discord) and the structured
        # object (for the eval layer / agent_outputs.structured_output).
        return AgentResult(
            content=content,
            structured_output=triage_output.model_dump(),
            metadata={
                "email_count": len(emails),
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

    agent = EmailTriageAgent()
    result = agent.execute()
    print(result.content)
