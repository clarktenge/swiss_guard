# Evaluating email-triage

This document defines what a correct `email-triage` output looks like and how
I check for it automatically. The point is to stop trusting the agent by vibes.
When I change a prompt or swap a model, I want a way to know whether the output
got better or worse without manually reading 70 emails.

## What the agent does

`email-triage` pulls the last 24 hours of mail across my accounts (via
`integrations/gmail.py`), sends the batch to Claude, and gets back a
categorization of what matters. Four buckets: urgent/time-sensitive, grade
changes, opportunities, and sales/drops. It runs at 7 AM and
posts to Discord.

The problem with the first version: the output was free-text markdown. There's
no way to programmatically check free text. "Did it catch the urgent email?" is
not a question I can answer with code if the answer is buried in prose. So the
first real change is making the output structured.

## Structured output contract

The agent returns JSON matching this shape (validated with Pydantic before
anything else happens to it):

```
TriageOutput
  urgent:        list[EmailItem]
  opportunities: list[EmailItem]
  sales:         list[SaleItem]
  uncategorized: list[EmailItem]   # emails the agent chose not to surface

EmailItem
  email_id:   str        # must match a real ID from the input batch
  from:       str
  subject:    str
  reason:     str        # one sentence: why it's in this bucket
  confidence: float      # 0.0–1.0

SaleItem  (extends EmailItem)
  brand:      str
  expires_at: str | None
```

The `uncategorized` bucket matters more than it looks. Forcing the agent to
account for *every* input email — either surface it or explicitly set it aside —
is what lets me check for dropped emails. An agent that silently ignores input
is the failure mode I most want to catch.

## Tier 1 — deterministic checks

These run on every output. They're cheap, fast, and don't need a model. If any
fail, the run is flagged in `agent_runs` and the eval logger records which check
broke.

1. **Schema validity.** Output parses as valid `TriageOutput`. A model that
   returns malformed JSON is a hard failure — this is the single most common
   real-world agent breakage and the cheapest to catch.

2. **Conservation.** Every `email_id` in the input appears exactly once across
   all five buckets. No email invented (ID not in input), none dropped (ID in
   input, missing from output), none duplicated. This is the check that proves
   the agent processed the whole batch.

3. **Confidence sanity.** Anything in `urgent` with confidence below 0.5 is
   suspect — if the agent isn't sure it's urgent, it probably shouldn't be in
   the bucket that pings me. These get logged for review rather than hard-failed.

4. **No empty reasons.** Every surfaced item has a non-empty `reason`. An item
   with no justification is the agent padding output.

## Tier 2 — LLM-as-judge

Some things can't be checked with assertions. "Is this email actually urgent, or
did the agent overreact to the word 'URGENT' in a marketing subject line?" is a
judgment call. For these I run a second, separate Claude call with a narrow job:
score one specific quality, return a number and a reason.

I keep the judge calls small and single-purpose rather than asking one prompt to
grade everything. Three judges:

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
