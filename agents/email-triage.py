"""
email-triage — pulls the last 24h of mail, asks Claude to categorize it, and
returns a *structured* (Pydantic-validated) result instead of free-text markdown.

Why structured: free text can't be checked programmatically. With a typed
contract we can run cheap, model-free Tier 1 checks on every run (schema
validity, conservation, GPA math, confidence, empty reasons) — see
docs/evals/email-triage.md.

Run it directly to triage your live inbox and print the result + Tier 1 report:

    python agents/email-triage.py

That path calls execute() only — it hits Gmail and Claude but deliberately
skips run()'s side effects (Supabase logging, Discord post, Voyage embedding).
"""

import os
import re
import sys
import json
from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel, Field, ConfigDict, ValidationError

# Allow running this file directly (python agents/email-triage.py) — the script
# dir is agents/, so put the project root on the path for the package imports.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base import BaseAgent, AgentResult            # noqa: E402
from integrations.gmail import list_recent_emails          # noqa: E402


# ── Structured output contract (docs/evals/email-triage.md) ──────────────────

class EmailItem(BaseModel):
    # 'from' is a Python keyword, so the attribute is from_ with a "from" alias.
    # populate_by_name lets us build items in code with from_ while still
    # accepting Claude's JSON which uses the "from" key.
    model_config = ConfigDict(populate_by_name=True)

    email_id: str
    from_: str = Field(alias="from")
    subject: str
    reason: str = ""
    confidence: float = 0.0


class GradeChangeItem(EmailItem):
    course: str
    old_grade: Optional[float] = None
    new_grade: float
    gpa_delta: str  # human-readable, e.g. "3.71 → 3.74"


class SaleItem(EmailItem):
    brand: str
    expires_at: Optional[str] = None


class TriageOutput(BaseModel):
    urgent: List[EmailItem] = Field(default_factory=list)
    grade_changes: List[GradeChangeItem] = Field(default_factory=list)
    opportunities: List[EmailItem] = Field(default_factory=list)
    sales: List[SaleItem] = Field(default_factory=list)
    # Emails the agent chose not to surface. Forcing it to account for *every*
    # input — surface it or explicitly set it aside — is what lets conservation
    # catch silently-dropped emails.
    uncategorized: List[EmailItem] = Field(default_factory=list)

    def all_items(self) -> List[EmailItem]:
        return (
            self.urgent
            + self.grade_changes
            + self.opportunities
            + self.sales
            + self.uncategorized
        )

    def surfaced_items(self) -> List[EmailItem]:
        """Everything except uncategorized — the buckets that actually ping me."""
        return self.urgent + self.grade_changes + self.opportunities + self.sales


# ── Tier 1: deterministic checks (no model needed) ───────────────────────────

@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str   # "fail" (hard) or "warn" (logged for review)
    detail: str


def _floats_in(text: str) -> List[float]:
    """Pull the numbers out of a string like '3.71 → 3.74'."""
    return [float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", text)]


def run_tier1_checks(output: TriageOutput, input_ids: List[str]) -> List[CheckResult]:
    """
    The model-free checks from docs/evals/email-triage.md, item-for-item.
    (Schema validity — check 1 — is enforced upstream by the Pydantic parse;
    if we got a TriageOutput at all, that check already passed.)
    """
    results: List[CheckResult] = []
    input_set = set(input_ids)

    # 2. Conservation — every input id appears exactly once across all buckets.
    out_ids = [item.email_id for item in output.all_items()]
    counts = {}
    for i in out_ids:
        counts[i] = counts.get(i, 0) + 1
    invented = sorted(set(out_ids) - input_set)
    dropped = sorted(input_set - set(out_ids))
    duplicated = sorted(i for i, c in counts.items() if c > 1)
    conserved = not (invented or dropped or duplicated)
    detail = "every input email accounted for exactly once"
    if not conserved:
        parts = []
        if dropped:
            parts.append(f"{len(dropped)} dropped")
        if invented:
            parts.append(f"{len(invented)} invented")
        if duplicated:
            parts.append(f"{len(duplicated)} duplicated")
        detail = "; ".join(parts) + (
            f" (dropped={dropped[:3]}, invented={invented[:3]}, "
            f"dup={duplicated[:3]})"
        )
    results.append(CheckResult("conservation", conserved, "fail", detail))

    # 3. GPA math consistency — claimed gpa_delta direction matches old→new.
    gpa_problems = []
    for g in output.grade_changes:
        if g.old_grade is None:
            continue  # nothing to compare a direction against
        grade_dir = (g.new_grade > g.old_grade) - (g.new_grade < g.old_grade)
        nums = _floats_in(g.gpa_delta)
        if len(nums) < 2:
            gpa_problems.append(f"{g.course}: can't parse gpa_delta '{g.gpa_delta}'")
            continue
        gpa_dir = (nums[-1] > nums[0]) - (nums[-1] < nums[0])
        # A grade going up must not be paired with GPA going down (or vice versa).
        if grade_dir != 0 and gpa_dir != 0 and grade_dir != gpa_dir:
            gpa_problems.append(
                f"{g.course}: grade {g.old_grade}->{g.new_grade} but "
                f"gpa_delta '{g.gpa_delta}' moves the other way"
            )
    results.append(CheckResult(
        "gpa_math",
        not gpa_problems,
        "fail",
        "consistent" if not gpa_problems else "; ".join(gpa_problems),
    ))

    # 4. Confidence sanity — urgent items under 0.5 are suspect (warn, not fail).
    low_conf = [
        f"{u.subject[:40]!r} ({u.confidence})"
        for u in output.urgent if u.confidence < 0.5
    ]
    results.append(CheckResult(
        "confidence_sanity",
        not low_conf,
        "warn",
        "all urgent items confident" if not low_conf
        else f"{len(low_conf)} urgent under 0.5: " + "; ".join(low_conf),
    ))

    # 5. No empty reasons — every *surfaced* item must justify itself.
    no_reason = [
        f"{item.email_id} ({item.subject[:40]!r})"
        for item in output.surfaced_items()
        if not item.reason.strip()
    ]
    results.append(CheckResult(
        "no_empty_reasons",
        not no_reason,
        "fail",
        "all surfaced items have a reason" if not no_reason
        else f"{len(no_reason)} missing: " + "; ".join(no_reason[:5]),
    ))

    return results


# ── The agent ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an email triage assistant. You are given a batch of emails from the
last 24 hours and must sort EVERY one of them into exactly one bucket.

Buckets:
  - urgent:        genuinely time-sensitive / needs action soon. Do not put an
                   email here just because the subject shouts "URGENT" — judge
                   the actual content.
  - grade_changes: a posted grade or grade update for a course.
  - opportunities: jobs, internships, scholarships, referrals, intros.
  - sales:         promotions, discounts, price drops, marketing offers.
  - uncategorized: everything else — newsletters, receipts, noise. Put an email
                   here if it doesn't clearly belong in another bucket. This is
                   not a dumping ground for emails you skipped; it is an explicit
                   "I saw this and chose not to surface it" decision.

Rules:
  - Every input email MUST appear in exactly one bucket. Never drop an email,
    never invent an email_id that wasn't in the input, never list one twice.
  - Echo the email_id and from/subject exactly as given.
  - Output ONLY a single JSON object, no prose, no markdown fences.

JSON shape:
{
  "urgent":        [ EmailItem, ... ],
  "grade_changes": [ GradeChangeItem, ... ],
  "opportunities": [ EmailItem, ... ],
  "sales":         [ SaleItem, ... ],
  "uncategorized": [ EmailItem, ... ]
}

EmailItem        = {"email_id","from","subject","reason","confidence"}
                   reason: one sentence on why it's in this bucket.
                   confidence: 0.0-1.0.
GradeChangeItem  = EmailItem + {"course","old_grade"(number|null),
                                "new_grade"(number),"gpa_delta"(e.g. "3.71 -> 3.74")}
SaleItem         = EmailItem + {"brand","expires_at"(string|null)}
"""


def _strip_json(text: str) -> str:
    """Claude is told not to fence the JSON, but strip fences/prose defensively."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # Otherwise grab the outermost {...}.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


@dataclass
class TriageRun:
    """What execute() produces: the parsed output plus its Tier 1 verdict."""
    output: TriageOutput
    checks: List[CheckResult]
    input_count: int

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "fail")


class EmailTriageAgent(BaseAgent):

    @property
    def agent_id(self) -> str:
        return "email-triage"

    def triage(self) -> TriageRun:
        """
        The core: fetch -> Claude -> Pydantic parse -> Tier 1 checks.
        Returns the structured run; raises on schema-invalid output (Tier 1
        check #1 is a hard failure — malformed JSON means the agent is broken).
        """
        emails = list_recent_emails(hours_back=24)
        input_ids = [e["id"] for e in emails]

        # Compact, data-only view for the model. from/subject/snippet are
        # attacker-controlled, so this whole blob goes in as untrusted_data.
        batch = [
            {
                "email_id": e["id"],
                "from": e["from"],
                "subject": e["subject"],
                "snippet": e.get("snippet", ""),
            }
            for e in emails
        ]

        if not emails:
            return TriageRun(TriageOutput(), run_tier1_checks(TriageOutput(), []), 0)

        raw = self.call_claude(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=(
                f"Triage these {len(emails)} emails. Return the JSON object "
                "described in your instructions and nothing else."
            ),
            untrusted_data=json.dumps(batch, ensure_ascii=False, indent=2),
            max_tokens=8192,
        )

        # Tier 1, check 1 — schema validity. A parse failure is a hard failure.
        try:
            output = TriageOutput.model_validate_json(_strip_json(raw))
        except (ValidationError, json.JSONDecodeError) as e:
            raise RuntimeError(
                f"email-triage produced schema-invalid output (Tier 1 check 1 "
                f"failed): {e}\n--- raw ---\n{raw[:1000]}"
            )

        checks = run_tier1_checks(output, input_ids)
        return TriageRun(output, checks, len(emails))

    def execute(self) -> AgentResult:
        run = self.triage()
        return AgentResult(
            content=render_markdown(run),
            metadata={
                "triage": run.output.model_dump(by_alias=True),
                "tier1": [c.__dict__ for c in run.checks],
                "tier1_passed": run.passed,
                "input_count": run.input_count,
            },
        )


# ── Rendering ────────────────────────────────────────────────────────────────

def render_markdown(run: TriageRun) -> str:
    o = run.output
    lines = [f"📬 **Email triage** — {run.input_count} emails in the last 24h", ""]

    def section(title, items, fmt):
        if not items:
            return
        lines.append(f"**{title}** ({len(items)})")
        for it in items:
            lines.append(f"- {fmt(it)}")
        lines.append("")

    section("🔴 Urgent", o.urgent,
             lambda i: f"{i.subject} — {i.from_}  _({i.reason}, conf {i.confidence:.2f})_")
    section("📊 Grade changes", o.grade_changes,
            lambda i: f"{i.course}: {i.gpa_delta} — {i.subject}  _({i.reason})_")
    section("💼 Opportunities", o.opportunities,
            lambda i: f"{i.subject} — {i.from_}  _({i.reason})_")
    section("🏷️ Sales", o.sales,
            lambda i: f"{i.brand}: {i.subject}"
                      + (f" (expires {i.expires_at})" if i.expires_at else ""))

    lines.append(f"_{len(o.uncategorized)} other emails set aside._")
    lines.append("")
    lines.append("**Tier 1 checks**")
    for c in run.checks:
        mark = "✅" if c.passed else ("⚠️" if c.severity == "warn" else "❌")
        lines.append(f"- {mark} {c.name}: {c.detail}")
    return "\n".join(lines)


# ── Direct-run harness (no Supabase/Discord/embedding side effects) ──────────

if __name__ == "__main__":
    # The output is emoji-heavy; the default Windows console is cp1252 and would
    # crash on it. Force UTF-8 where the runtime supports it.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    agent = EmailTriageAgent()
    run = agent.triage()

    print(render_markdown(run))
    print()
    verdict = "PASS" if run.passed else "FAIL"
    print(f"=== Tier 1 verdict: {verdict} "
          f"({sum(c.passed for c in run.checks)}/{len(run.checks)} checks ok) ===")
