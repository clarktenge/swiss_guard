"""
governance — classifies every agent output into a capability class.

WHY THIS FILE EXISTS (read docs/governance.md for the full reasoning):

The governance model in docs/governance.md describes three capability classes —
READ_ONLY, DRAFT, ACTION — and a future enforcement gate that blocks ACTION-class
output from running without an approval row. None of that gate is built yet,
*on purpose*: today all six agents only fetch data and post reports, so there is
nothing ACTION-class to block. Building the gate before there is anything to gate
would be untestable scaffolding.

But there is one piece worth building now: the *classifier*. Until this file
existed, the `agent_outputs.governance_class` column (added in
`db/migration_001.sql`) was populated purely by its SQL default ('READ_ONLY') —
nothing in the code ever decided the value. That is a lie of omission: the column
*looked* governed but no logic stood behind it. This module replaces that silent
default with a real function so that:

  1. The value in the column is the result of a deliberate decision, not a
     schema default that happens to be right.
  2. The day someone adds an agent that proposes an external action, the decision
     logic lives in exactly one place (here), and base.py never has to change to
     support it — base.py just calls classify_output() and stores what it returns.

In other words: the classifier is made load-bearing *before* there is a load, so
the safe-by-default machinery is already in place when the load arrives.
"""

from agents.base import AgentResult


# Each agent's maximum capability class — the ceiling it is *allowed* to ever
# emit, declared centrally here rather than decided by the agent itself.
#
# WHY a floor table instead of asking the agent what it is: an agent that could
# declare its own class could, through a bug or a prompt injection, claim a more
# powerful class than it should have. By keeping the ceiling here — outside the
# agent's own code path — even a buggy agent cannot escalate its privileges past
# what this table permits. This is rule 1 ("capability floor") from
# docs/governance.md: a static ceiling enforced in code, not a suggestion to the
# model. Today every agent reads and reports only, so every ceiling is READ_ONLY.
AGENT_CAPABILITY_FLOOR = {
    "email-triage": "READ_ONLY",
    "email-digest": "READ_ONLY",
    "market-report": "READ_ONLY",
    "health-sync": "READ_ONLY",
    "weekly-report": "READ_ONLY",
    "job-scout": "READ_ONLY",
}


def classify_output(agent_id: str, result: AgentResult) -> str:
    """
    Classify an agent's output into one of 'READ_ONLY', 'DRAFT', 'ACTION'.

    Today every agent in this system only reads data and reports it — none of
    them send emails, spend money, or take any action outside this codebase. So
    this function correctly returns 'READ_ONLY' for all six agents right now.

    It exists as a real function (not a hardcoded constant in base.py) so that
    the day an agent IS added that proposes an external action, this is the one
    place that decision logic lives. base.py calls this and stores the result;
    it never needs to know *how* the class was decided.

    The `result` parameter is unused today — the decision is made purely from the
    capability floor (see AGENT_CAPABILITY_FLOOR). It is part of the signature on
    purpose: the future DRAFT/ACTION logic (rule 2, "action category override",
    in docs/governance.md) will need to inspect what the agent actually proposed,
    and that data rides on the AgentResult. Keeping it in the signature now means
    that future logic slots in here without changing how base.py calls this.

    --- TIER 2 / FUTURE EXTENSION POINT ---------------------------------------
    This is where the richer governance logic from docs/governance.md will plug
    in, in restrictiveness order (most restrictive applicable rule wins):

      1. Capability floor  — implemented below (the AGENT_CAPABILITY_FLOOR cap).
      2. Action-category override — inspect `result` for a proposed external
         action; force ACTION for sensitive categories (money, anything
         irreversible, anything that contacts a person), capped by the floor.
      3. Confidence downgrade — hold a DRAFT whose underlying confidence is below
         threshold rather than surfacing low-confidence noise.

    None of 2–3 is built yet because no agent emits DRAFT/ACTION today, so there
    is no code path to exercise them against. When the first such agent lands,
    add those rules between here and the return below — and that is the *only*
    file that changes.
    ---------------------------------------------------------------------------
    """
    # Capability floor: look up this agent's declared ceiling. An agent_id that
    # is NOT in the table defaults to 'ACTION' — the most restrictive class — so
    # the system fails CLOSED, not open. An agent nobody deliberately added to
    # the floor table is treated as maximally dangerous until someone does, which
    # is rule 4 ("default deny") from docs/governance.md: unknown is the most
    # dangerous shape, so it gets the most restrictive handling.
    return AGENT_CAPABILITY_FLOOR.get(agent_id, "ACTION")
