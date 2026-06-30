# Evaluating the other agents

Each agent needs its own notion of "correct" because they fail differently. The
two-tier pattern from `email-triage` (deterministic checks + a narrow LLM judge)
carries over, but the specific checks change. This file covers the rest.

---

## email-digest

**What it does.** Deep summaries of ISW reports, research papers, and articles.
Depends on `email-triage` finishing first. The interesting property of this
agent is that it's supposed to use memory — yesterday's ISW summary should change
how today's is written (see `docs/memory-behavior.md`).

**Structured output** (`DigestOutput` / `DigestItem` in `agents/schemas.py`).
```
DigestOutput
  isw:      list[DigestItem]
  research: list[DigestItem]

DigestItem
  email_id:    str
  title:       str
  summary:     str
  is_delta:    bool          # true if this builds on a prior summary
  delta_basis: str | None    # what prior context the delta is against
```

**Tier 1 — deterministic** (`run_digest_checks()` in `evals/checks.py`). Two
checks are implemented:
- **Delta validity** (`check_digest_delta_validity`). If `is_delta` is true,
  `delta_basis` must be non-null. A claimed delta with no basis is a hallucinated
  continuity — exactly the failure I most want to catch in a memory-using agent.
  (Note: the check verifies the basis is *present*; it does not yet verify it
  points to a real prior output id in `agent_outputs`.)
- **Summaries not empty** (`check_digest_summaries_not_empty`). Every surfaced
  item's `summary` is non-empty and at least 20 characters — guards against the
  agent listing an item without saying anything about it.

*Designed, not yet implemented:* a standalone schema-validity check, `email_id`
traceability to a real input email, and an upper summary-length bound (not longer
than the source). No functions for these exist in `evals/checks.py` today.

**Tier 2 — judge.** *Designed, not yet implemented* (no judge code exists):
- **Faithfulness.** Does the summary represent the source, or did it invent
  developments? This is the headline risk for a summarization agent.
- **Delta validity.** When `is_delta` is true, is the claimed change real?
  Compare today's summary, the referenced prior summary, and the source. Catches
  the agent saying "since yesterday X advanced" when nothing changed.

The delta check is the one that would prove memory is doing real work rather than
decorating the output. Until it's built, the Tier 1 check only confirms a delta
*claims* a basis — it can't confirm the change is real.

---

## market-report

**What it does.** End-of-day portfolio summary. Pulls holdings from Supabase,
quotes and news from yfinance, synthesizes a report. The defining risk here
is different from the email agents: the numbers have to be *right*, and an LLM is
bad at arithmetic.

**Structured output** (`MarketReportOutput` / `HoldingLine` in
`agents/schemas.py`).
```
MarketReportOutput
  date:            str
  portfolio_value: float
  day_pnl:         float
  day_pnl_pct:     float
  holdings:        list[HoldingLine]
  narrative:       str        # the LLM's qualitative read

HoldingLine
  ticker:         str
  shares:         float
  price:          float
  day_change_pct: float
  day_pnl:        float
  total_pnl:      float
```
(There is no `watch` field on the schema.)

**Tier 1 — deterministic, and this is the important part**
(`run_market_checks()` in `evals/checks.py`). The numbers are computed in Python,
not by the model. The agent fetches prices, Python does the P&L math, and the
*computed* numbers populate the structured fields. The LLM only writes the
`narrative`. Two checks are implemented:
- **Numeric consistency** (`check_market_numeric_consistency`). `portfolio_value`
  equals the sum of (`price × shares`) across holdings, to the cent (0.01
  tolerance).
- **Narrative not empty** (`check_market_narrative_not_empty`). `narrative` is
  present and at least 50 characters — a report that went out with numbers but no
  commentary is a failure.

*Designed, not yet implemented:* a `day_pnl_pct`-vs-`day_pnl` consistency check,
verifying every ticker exists in the holdings table, and verifying no holding
line references a price the API didn't return.

This is a deliberate architecture decision worth being able to defend: **the
model never touches the math.** It synthesizes context around numbers that were
computed deterministically. An LLM writing "your portfolio is up $340" by reading
prices is a liability; Python computing $340 and the LLM explaining *why* is not.

**Tier 2 — judge.** *Designed, not yet implemented* (no judge code exists):
- **Narrative grounding.** Does the qualitative narrative contradict the computed
  numbers? Catches the model saying "a rough day" when the portfolio was up. The
  judge gets the computed numbers as ground truth and checks the prose against them.

---

## health-sync

**What it does.** Daily activity summary from Strava (Garmin later). Lowest-risk
agent — it's reporting on data, not taking action, and the stakes of being wrong
are low. Eval is correspondingly lighter.

**Structured output** (`HealthOutput` / `Activity` in `agents/schemas.py`).
```
HealthOutput
  activities:           list[Activity]
  week_distance_miles:  float          # computed in Python (sum of activity distances)
  week_duration_minutes: float         # computed in Python
  week_activity_count:  int            # computed in Python (len(activities))
  vs_last_week_distance: float | None  # computed in Python (% change vs prior week)
  narrative:            str            # LLM's observation (the only model-written field)
```
(The field is `narrative`, not `note`; volume is split into
`week_distance_miles` / `week_duration_minutes` / `week_activity_count`.)

**Tier 1** (`run_health_checks()` in `evals/checks.py`). One check is implemented:
- **Numeric consistency** (`check_health_numeric_consistency`). Verifies
  `week_distance_miles` equals the sum of activity distances (0.1 tolerance) and
  `week_activity_count` equals `len(activities)`. Same principle as
  market-report: the numbers are deterministic, the model only writes
  `narrative`.

*Designed, not yet implemented:* a standalone schema-validity check and a check
on `vs_last_week_distance`.

**Tier 2.** *Designed, not yet implemented* — one grounding check that
`narrative` doesn't contradict the volume numbers. Not worth more given the stakes.

---

## weekly-report

**What it does.** Sunday recap aggregating the week. Reads other agents' outputs
from `agent_outputs` rather than raw data — it's a summary of summaries. Its
correctness depends on the agents it reads from, which makes its eval partly an
integration check.

**Structured output** (`WeeklyOutput` in `agents/schemas.py`).
```
WeeklyOutput
  week_of:             str        # ISO date for Monday of the week
  workouts_completed:  int        # computed in Python from health-sync outputs
  total_distance_miles: float     # computed in Python from health-sync outputs
  emails_processed:    int        # computed in Python from email-triage outputs
  opportunities_found: int        # computed in Python from email-triage outputs
  new_jobs_found:      int        # computed in Python from job-scout outputs
  portfolio_day_pnl:   float      # computed in Python from market-report outputs
  week_score:          int        # Claude assigns 1–10
  narrative:           str        # Claude writes this
  next_week_priorities: list[str] # Claude writes these, max 3
```
(Field names differ from the earlier draft: `workouts_completed` not
`workouts_done`; the counts are scalar ints, not an `opportunities` list;
`next_week_priorities` not `next_week`.)

**Tier 1** (`run_weekly_checks()` in `evals/checks.py`). Three checks are
implemented:
- **Score in range** (`check_weekly_score_in_range`). `week_score` is within
  1–10.
- **Priorities count** (`check_weekly_priorities_count`). `next_week_priorities`
  has 1–3 items (fails on empty or more than 3).
- **Narrative not empty** (`check_weekly_narrative_not_empty`). `narrative` is
  present and at least 50 characters.

*Designed, not yet implemented:* reconciling the counts (`workouts_completed`,
`emails_processed`, etc.) against the underlying `agent_outputs` they're
aggregated from. That's the check that would verify the aggregation is faithful
to source rather than invented; no function for it exists today. (The counts
*are* computed in Python from those outputs in `agents/weekly_report.py` — what's
missing is an eval that re-derives and compares them.)

**Tier 2.** *Designed, not yet implemented* (no judge code exists):
- **Aggregation faithfulness.** Does the narrative reflect what actually happened
  per the source outputs, or did the model confabulate a week? Given a summary of
  summaries, drift is easy and worth checking.

---

## Cross-cutting note

The pattern across all five: **anything quantitative is computed in Python and
checked deterministically; the model is confined to qualitative synthesis, which
is *intended* to be checked by a judge.** The Tier 1 deterministic half of that
is built today; the Tier 2 judge half is designed but not yet implemented. That
single principle is what makes the system verifiable. It also draws a clean line for where errors can come from — a wrong
number is a code bug I can fix, a wrong narrative is a prompt problem. Keeping
those failure domains separate is most of what makes the thing debuggable.