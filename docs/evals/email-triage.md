# Evaluating email-triage

This document defines what a correct `email-triage` output looks like and how
I check for it automatically. The point is to stop trusting the agent by vibes.
When I change a prompt or swap a model, I want a way to know whether the output
got better or worse without manually reading 70 emails.

## What the agent does

`email-triage` pulls the last 24 hours of mail across my accounts (via
`integrations/gmail.py`), sends the batch to Claude, and gets back a
categorization of what matters. Five buckets: urgent, opportunities, sales,
updates, and uncategorized. It runs at 7 AM and posts to Discord.

The problem with the first version: the output was free-text markdown. There's
no way to programmatically check free text. "Did it catch the urgent email?" is
not a question I can answer with code if the answer is buried in prose. So the
first real change is making the output structured.

## Structured output contract

The agent returns JSON matching this shape (validated with Pydantic before
anything else happens to it). Crucially, **Claude returns decisions only** —
`email_id`, `reason`, `confidence` (plus `brand`/`expires_at` for sales). It does
*not* echo `from_`/`subject` back; those human-facing fields are reconstructed in
Python from the original fetch (`emails_by_id` in `_build_triage_output`), so the
only free text the model contributes is its own `reason`. This is a
prompt-injection mitigation: attacker-controlled sender/subject text never makes
a round-trip through the model. The validated `EmailItem` therefore carries the
full shape below, but only the marked fields come from Claude:

```
TriageOutput
  urgent:        list[EmailItem]
  opportunities: list[EmailItem]
  sales:         list[SaleItem]
  updates:       list[EmailItem]   # newsletters / digests — no action needed
  uncategorized: list[EmailItem]   # emails the agent chose not to surface

EmailItem
  email_id:   str        # from Claude; must match a real ID from the input batch
  reason:     str        # from Claude; one sentence: why it's in this bucket
  confidence: float      # from Claude; 0.0–1.0
  from_:      str        # reconstructed in Python ("from" alias); not emitted by Claude
  subject:    str        # reconstructed in Python; not emitted by Claude

SaleItem  (extends EmailItem)
  brand:      str        # from Claude
  expires_at: str | None # from Claude
```

The `uncategorized` bucket matters more than it looks. Forcing the agent to
account for *every* input email — either surface it or explicitly set it aside —
is what lets me check for dropped emails. An agent that silently ignores input
is the failure mode I most want to catch.

## Tier 1 — deterministic checks

These run on every output via `run_all_checks()` in `evals/checks.py`. They're
cheap, fast, and don't need a model. The results are stashed on
`self._eval_results` during `execute()` and persisted by `run()`.

1. **Schema validity** (`check_schema_valid`). Output parses as valid
   `TriageOutput`. Pydantic already enforces this upstream — if we hold a
   `TriageOutput` at all, it parsed — so this check always returns pass; it
   exists so a schema-validity result is recorded for every run rather than being
   silently implicit.

2. **Conservation** (`check_conservation`). Every `email_id` in the input appears
   exactly once across all five buckets. No email invented (ID not in input),
   none dropped (ID in input, missing from output), none duplicated. This is the
   check that proves the agent processed the whole batch.

3. **Confidence sanity** (`check_confidence_sanity`). Anything in `urgent` with
   confidence below 0.5 is suspect — if the agent isn't sure it's urgent, it
   probably shouldn't be in the bucket that pings me. Advisory: it reports
   `passed=False` when it flags something (so the signal is queryable) but is not
   meant to fail a run on its own.

4. **No empty reasons.** *Designed, not yet implemented.* The idea: every
   surfaced item has a non-empty `reason`; an item with no justification is the
   agent padding output. There is no corresponding check function in
   `evals/checks.py` today.

## Tier 2 — LLM-as-judge

**Designed, not yet implemented.** No judge code exists in `evals/` today; the
three judges below describe the intended Tier 2 layer, not current behavior.

Some things can't be checked with assertions. "Is this email actually urgent, or
did the agent overreact to the word 'URGENT' in a marketing subject line?" is a
judgment call. For these I'd run a second, separate Claude call with a narrow job:
score one specific quality, return a number and a reason.

The plan keeps the judge calls small and single-purpose rather than asking one
prompt to grade everything. Three judges:

- **Urgency precision.** Given the urgent bucket and the original emails, what
  fraction are genuinely time-sensitive vs. promotional language? Returns a
  score and lists any false positives.

- **Missed-urgent recall.** Given the `uncategorized` and `sales` buckets, did
  anything time-sensitive get set aside? This is the expensive question (it has
  to look at everything the agent *didn't* flag) so I sample rather than run it
  every day.

- **Summary faithfulness.** For opportunity items, does the
  `reason` accurately reflect the source email? Catches hallucinated details.

The judge is a different model instance with no memory of the original run, so
it isn't grading its own homework.

## What I record

Every eval result writes to a row keyed to the `agent_runs` id: tier-1 pass/fail
per check, tier-2 scores, and any flagged items. Over time this gives me a trend
line — if urgency precision drifts down after a prompt change, I see it. That
trend is the actual asset. The agent's individual outputs are disposable; the
record of how well it's been doing is what I'd protect.

## Known gaps

- The judge is itself an LLM and can be wrong. I treat its scores as signal, not
  truth. When a judge flags something I disagree with, that disagreement is its
  own data point about prompt clarity.
- Recall (missed-urgent) is fundamentally hard to measure without ground truth.
  Sampling + my own thumbs-down feedback in Discord is the pragmatic substitute
  until I have enough labeled history to do better.
- Confidence scores from the model aren't calibrated. A 0.8 doesn't mean 80%
  correct. I use them for relative ranking within a run, not as absolute truth.
