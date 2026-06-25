"""
schemas — Pydantic models defining the structured-output contracts for the
agents. These are the typed shapes Claude is asked to return and that everything
downstream (eval checks, governance, rendering) validates against.

This module is pure data definitions: no I/O, no Claude calls, no Supabase. That
keeps it cheap to import from the eval layer without pulling in network clients.

Phase 1 wires these into email-triage's eval checks only. The digest / market
models are defined here now so the contract lives in one place as those agents
get structured later. See docs/governance.md and docs/evals/email-triage.md.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Email triage ─────────────────────────────────────────────────────────────

class EmailItem(BaseModel):
    # 'from' is a Python keyword, so the attribute is from_ with a "from" alias.
    # populate_by_name lets us build items in code with from_ while still
    # accepting Claude's JSON, which uses the "from" key.
    model_config = ConfigDict(populate_by_name=True)

    email_id: str               # must match a real ID from the input batch
    from_: str = Field(alias="from")
    subject: str
    reason: str                 # one sentence: why it's in this bucket
    confidence: float = Field(ge=0.0, le=1.0)   # 0.0–1.0


class SaleItem(EmailItem):
    brand: str
    expires_at: Optional[str] = None


class TriageOutput(BaseModel):
    urgent: List[EmailItem] = Field(default_factory=list)
    opportunities: List[EmailItem] = Field(default_factory=list)
    sales: List[SaleItem] = Field(default_factory=list)
    # Emails the agent chose not to surface. Forcing it to account for *every*
    # input — surface it or explicitly set it aside — is what lets the
    # conservation check catch silently-dropped emails.
    uncategorized: List[EmailItem] = Field(default_factory=list)


# ── Email digest ─────────────────────────────────────────────────────────────

class DigestItem(BaseModel):
    email_id: str
    title: str
    summary: str
    is_delta: bool                       # is this new vs. what we already knew?
    delta_basis: Optional[str] = None    # what prior context the delta is against


class DigestOutput(BaseModel):
    isw: List[DigestItem] = Field(default_factory=list)
    research: List[DigestItem] = Field(default_factory=list)


# ── Market report ────────────────────────────────────────────────────────────

class HoldingLine(BaseModel):
    ticker: str
    shares: float
    price: float
    day_change_pct: float
    day_pnl: float
    total_pnl: float


class MarketReportOutput(BaseModel):
    date: str
    portfolio_value: float
    day_pnl: float
    day_pnl_pct: float
    holdings: List[HoldingLine] = Field(default_factory=list)
    narrative: str


# ── Health sync ──────────────────────────────────────────────────────────────

class Activity(BaseModel):
    name: str
    sport_type: str
    date: str
    distance_miles: float
    duration_minutes: float
    elevation_feet: float
    avg_heart_rate: Optional[float] = None
    calories: Optional[float] = None


class HealthOutput(BaseModel):
    # Every numeric field below is computed in Python from the activity list
    # (the "numbers in Python, narrative from Claude" pattern, docs/architecture.md):
    # Claude contributes only `narrative`. The eval checks assert week_* against
    # `activities`, so these must be derived from the same list.
    activities: List[Activity] = Field(default_factory=list)
    week_distance_miles: float       # sum of activity distances (Python)
    week_duration_minutes: float     # sum of activity durations (Python)
    week_activity_count: int         # len(activities) (Python)
    vs_last_week_distance: Optional[float] = None  # % change vs prior week (Python)
    narrative: str                   # Claude writes this only
