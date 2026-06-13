# Governance

The first version of governance was a label. Each output got tagged READ_ONLY,
DRAFT, or ACTION in `governance/classifier.py`. That's honest about intent but it
doesn't actually *do* anything — a label is a comment with extra steps. This
document describes turning the label into a policy that gates what the system is
allowed to do.

## The distinction that matters

A label describes an output. A policy controls it. The difference is enforcement:

- **Label:** "this output is ACTION class" → then nothing stops it from running.
- **Policy:** "this output is ACTION class" → therefore it is blocked from
  executing until an approval row exists, and the code that would execute it
  checks for that row first.

Right now none of my agents take external action — they all report. So why build
this before I need it? Because the moment I add an agent that *can* act (a draft
reply, a calendar event, eventually a job application), the safe-by-default
machinery needs to already exist. Building the gate after you've built the thing
that needs gating is how accidents happen. The classifier should be load-bearing
before there's a load.

## The three classes, defined by capability not content

- **READ_ONLY** — produces information, takes no external action. All five
  current agents. Posts to Discord, writes to memory, nothing leaves the system
  that affects the outside world. No approval needed.
- **DRAFT** — produces something intended to become an external action but not
  yet executed. A drafted email reply, a proposed calendar event. Surfaced for
  me to approve, edit, or discard. Nothing happens automatically.
- **ACTION** — would change something outside the system: send a message, book
  an event, submit a form. Hard-gated. Cannot execute without an explicit
  approval record tied to that specific output.

The classes are about *capability*, not how the content reads. An email that
merely discusses sending money is READ_ONLY. An agent step that would actually
move money is ACTION even if it looks trivial. Classifying by capability rather
than by content keywords is what keeps the gate from being fooled by phrasing.

## Policy rules

The classifier applies rules in order; the most restrictive applicable rule wins.
This is the actual logic, not just a mapping:

1. **Capability floor.** Each agent declares the maximum class it's allowed to
   produce. `email-triage` is declared READ_ONLY and *cannot* emit a DRAFT or
   ACTION even if something goes wrong in the prompt. This is a static ceiling
   enforced in code, not a suggestion to the model. An agent can't escalate its
   own privileges.

2. **Action category override.** Any output whose proposed action falls in a
   sensitive category — financial transactions, anything irreversible, anything
   that contacts a person — is forced to ACTION regardless of what the model
   thought. The model doesn't get to talk its way down to DRAFT.

3. **Confidence downgrade.** If an agent emits a DRAFT but its own confidence on
   the underlying item is below threshold, the draft is held rather than
   surfaced. Low-confidence drafts are noise that trains me to rubber-stamp, which
   defeats the point of approval.

4. **Default deny.** If an output doesn't match a known shape, it's treated as
   ACTION and blocked. Unknown is the most dangerous class, so it gets the most
   restrictive handling. The system fails closed.

## Enforcement mechanics

The gate lives in `base.py`, in the path between an agent producing output and
anything happening to that output. Concretely:

- After `execute()` returns, the output is classified.
- READ_ONLY flows straight through to memory + Discord as it does now.
- DRAFT writes an `approvals` row with status `pending` and posts a preview to
  Discord, but the action payload is *not* executed. It sits.
- ACTION does the same but additionally refuses to execute even if asked, until
  the approval row flips to `approved`. The executing code (whenever I build it)
  takes an output id and checks the approvals table first. No approval row, no
  execution. This is the actual safety property.

The `approvals` table already exists in the schema. What's new is that it becomes
a *precondition* checked in code, not a record written after the fact.

## Why this is the right amount

I'm deliberately not building a policy engine, a rules DSL, or role-based access
control. There's one user — me. The governance that matters at this scale is:
agents can't exceed their declared capability, sensitive actions are always gated,
and the system fails closed on anything it doesn't recognize. That's three rules
and a precondition check. More than that would be governance theater — complexity
that looks rigorous but guards against threats a single-user personal system
doesn't have.

The honest version of "what breaks first": this model assumes the agent correctly
identifies its own proposed action's category. A mislabeled action category would
slip the override. The mitigation is the capability floor (rule 1) — even a
mislabeled action can't exceed its agent's static ceiling, so the blast radius is
bounded by which agent is running, not by the model's self-classification.