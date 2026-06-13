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

**Structured output.**
```
DigestOutput
  isw:      list[DigestItem]
  research: list[DigestItem]

DigestItem
  email_id:    str
  title:       str
  summary:     str
  is_delta:    bool          # true if this builds on a prior summary
  delta_basis: str | None    # which prior output this references, if any
```

**Tier 1 — deterministic.**
- Schema validity.
- Every `email_id` traces to a real input email.
- Summary length within bounds — not one sentence (under-summarizing a long ISW
  report), not longer than the source (padding).
- If `is_delta` is true, `delta_basis` is non-null and points to a real prior
  output id in `agent_outputs`. A claimed delta with no basis is a hallucinated
  continuity — exactly the failure I most want to catch in a memory-using agent.

**Tier 2 — judge.**
- **Faithfulness.** Does the summary represent the source, or did it invent
  developments? This is the headline risk for a summarization agent.
- **Delta validity.** When `is_delta` is true, is the claimed change real?
  Compare today's summary, the referenced prior summary, and the source. Catches
  the agent saying "since yesterday X advanced" when nothing changed.

The delta check is the one that proves memory is doing real work rather than
decorating the output. If I can't validate deltas, I can't claim the memory layer
changes behavior — I can only claim it retrieves.

---

## market-report

**What it does.** End-of-day portfolio summary. Pulls holdings from Supabase,
quotes and news from Alpha Vantage, synthesizes a report. The defining risk here
is different from the email agents: the numbers have to be *right*, and an LLM is
bad at arithmetic.

**Structured output.**
```
MarketReportOutput
  date:              str
  portfolio_value:   float
  day_pnl:           float
  day_pnl_pct:       float
  holdings:          list[HoldingLine]
  narrative:         str       # the LLM's qualitative read
  watch:             list[str] # upcoming events to track

HoldingLine
  ticker:        str
  shares:        float
  price:         float
  day_change_pct: float
```

**Tier 1 — deterministic, and this is the important part.**
The numbers are computed in Python, not by the model. The agent fetches prices,
Python does the P&L math, and the *computed* numbers are what populate the
structured fields. The LLM only writes the `narrative`. So the tier-1 checks are:
- Portfolio value equals the sum of (price × shares) across holdings, to the cent.
- `day_pnl_pct` is consistent with `day_pnl` and prior value.
- Every ticker in the output exists in the holdings table.
- No holding line references a price the API didn't return.

This is a deliberate architecture decision worth being able to defend: **the
model never touches the math.** It synthesizes context around numbers that were
computed deterministically. An LLM writing "your portfolio is up $340" by reading
prices is a liability; Python computing $340 and the LLM explaining *why* is not.

**Tier 2 — judge.**
- **Narrative grounding.** Does the qualitative narrative contradict the computed
  numbers? Catches the model saying "a rough day" when the portfolio was up. The
  judge gets the computed numbers as ground truth and checks the prose against them.

---

## health-sync

**What it does.** Daily activity summary from Strava (Garmin later). Lowest-risk
agent — it's reporting on data, not taking action, and the stakes of being wrong
are low. Eval is correspondingly lighter.

**Structured output.**
```
HealthOutput
  activities:    list[Activity]
  week_volume:   float          # computed in Python
  vs_last_week:  float          # computed in Python
  note:          str            # LLM's observation
```

**Tier 1.**
- Schema validity.
- `week_volume` and `vs_last_week` computed in Python from the Strava data, then
  checked for internal consistency. Same principle as market-report: numbers are
  deterministic, the model only writes `note`.
- Activity count matches what the integration returned.

**Tier 2.** Minimal — one grounding check that `note` doesn't contradict the
volume numbers. Not worth more given the stakes.

---

## weekly-report

**What it does.** Sunday recap aggregating the week. Reads other agents' outputs
from `agent_outputs` rather than raw data — it's a summary of summaries. Its
correctness depends on the agents it reads from, which makes its eval partly an
integration check.

**Structured output.**
```
WeeklyOutput
  workouts_done:   int
  emails_processed: int
  opportunities:   list[str]
  week_score:      int        # 1–10
  next_week:       list[str]  # at most 3
  narrative:       str
```

**Tier 1.**
- Counts (`workouts_done`, `emails_processed`) reconcile against the underlying
  agent_outputs they're aggregated from. This is the key check — it verifies the
  aggregation is faithful to source, not invented.
- `week_score` in range, `next_week` has at most 3 items.

**Tier 2.**
- **Aggregation faithfulness.** Does the narrative reflect what actually happened
  per the source outputs, or did the model confabulate a week? Given a summary of
  summaries, drift is easy and worth checking.

---

## Cross-cutting note

The pattern across all five: **anything quantitative is computed in Python and
checked deterministically; the model is confined to qualitative synthesis, which
is checked by a judge.** That single principle is what makes the system
verifiable. It also draws a clean line for where errors can come from — a wrong
number is a code bug I can fix, a wrong narrative is a prompt problem. Keeping
those failure domains separate is most of what makes the thing debuggable.