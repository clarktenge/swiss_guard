"""
Offline unit tests for the governance-wired market-report agent.

These exercise the Tier 1 checks (run_market_checks / check_market_*) on typed
MarketReportOutput objects, plus execute()'s structured-output path with every
external dependency mocked. No Supabase, yfinance, Claude, Voyage, or Discord
calls happen here, so this file is safe for CI.

Same pattern as test_health_sync_governance: build the agent with __new__ (skips
BaseAgent.__init__, which would construct the API clients), stub the attributes
execute() touches, and patch the module-level fetch_quotes / fetch_news and
call_claude on the class.
"""

from datetime import datetime as real_datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from agents.schemas import MarketReportOutput, HoldingLine
from evals.checks import (
    check_market_numeric_consistency,
    check_market_narrative_not_empty,
    run_market_checks,
)
from agents.market_report import MarketReportAgent


# ── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_NARRATIVE = (
    "The portfolio finished the day modestly higher, led by a strong move in "
    "AAPL while NVDA gave back some ground. Headlines were light, so the moves "
    "look more like positioning than reaction. Watch tomorrow's open for "
    "follow-through."
)


def _holdings() -> list[HoldingLine]:
    return [
        HoldingLine(ticker="AAPL", shares=100.0, price=110.0,
                    day_change_pct=1.85, day_pnl=200.0, total_pnl=1000.0),
        HoldingLine(ticker="NVDA", shares=10.0, price=200.0,
                    day_change_pct=-4.76, day_pnl=-100.0, total_pnl=-500.0),
    ]


def _valid_output(**overrides) -> MarketReportOutput:
    # portfolio_value = 100*110 + 10*200 = 13000.0
    kwargs = dict(
        date="2026-06-25",
        portfolio_value=13000.0,
        day_pnl=100.0,
        day_pnl_pct=0.78,
        holdings=_holdings(),
        narrative=FAKE_NARRATIVE,
    )
    kwargs.update(overrides)
    return MarketReportOutput(**kwargs)


# ── Tier 1 check tests ───────────────────────────────────────────────────────

def test_numeric_consistency_passes_on_valid_output():
    passed, msg = check_market_numeric_consistency(_valid_output())
    assert passed is True, msg

    # And it's surfaced through the roll-up the eval logger consumes.
    results = run_market_checks(_valid_output())
    consistency = [r for r in results if r["check"] == "numeric_consistency"]
    assert consistency and consistency[0]["passed"] is True
    assert all(r["tier"] == 1 for r in results)


def test_numeric_consistency_fails_on_mismatched_portfolio_value():
    # holdings sum to 13000.0; claim a different total.
    output = _valid_output(portfolio_value=12000.0)
    passed, msg = check_market_numeric_consistency(output)
    assert passed is False
    assert "does not match" in msg


def test_narrative_not_empty_fails_on_empty_narrative():
    passed, msg = check_market_narrative_not_empty(_valid_output(narrative=""))
    assert passed is False

    # A too-short narrative (< 50 chars) also fails.
    passed, _ = check_market_narrative_not_empty(_valid_output(narrative="Up a bit."))
    assert passed is False

    # The valid, full narrative passes.
    passed, _ = check_market_narrative_not_empty(_valid_output())
    assert passed is True


# ── execute() integration (all external calls mocked) ────────────────────────

FAKE_HOLDINGS = [
    {"ticker": "AAPL", "shares": 100, "avg_cost": 100.0},
    {"ticker": "NVDA", "shares": 10, "avg_cost": 250.0},
]
FAKE_QUOTES = {
    "AAPL": {"price": 110.0, "prev_close": 108.0, "change": 2.0, "change_percent": 1.85},
    "NVDA": {"price": 200.0, "prev_close": 210.0, "change": -10.0, "change_percent": -4.76},
}
FAKE_NEWS = [{"ticker": "AAPL", "title": "Apple drifts higher", "summary": "No catalyst."}]


def _make_agent() -> MarketReportAgent:
    """
    Build a MarketReportAgent without BaseAgent.__init__ (which would spin up the
    Anthropic/Supabase/Voyage clients). Stub the attributes execute() and run()'s
    eval hook read; the Supabase holdings query is wired to return FAKE_HOLDINGS.
    """
    agent = MarketReportAgent.__new__(MarketReportAgent)
    agent._eval_results = []
    agent.voyage = MagicMock()
    agent.anthropic = MagicMock()

    supabase = MagicMock()
    (supabase.table.return_value
     .select.return_value
     .execute.return_value).data = FAKE_HOLDINGS
    agent.supabase = supabase
    return agent


def test_execute_builds_structured_output_and_passes_checks():
    # Force the market-open guard open so this test isn't flaky on the wall clock
    # (it would otherwise early-exit when CI runs on a weekend / before close).
    with patch("agents.market_report._is_market_day_and_closed", return_value=(True, "open")), \
         patch("agents.market_report.fetch_quotes", return_value=FAKE_QUOTES), \
         patch("agents.market_report.fetch_news", return_value=FAKE_NEWS), \
         patch.object(MarketReportAgent, "call_claude", return_value=FAKE_NARRATIVE):
        agent = _make_agent()
        result = agent.execute()

        assert result.structured_output is not None
        so = result.structured_output
        # portfolio_value = 100*110 + 10*200 = 13000.0, computed in Python.
        assert abs(so["portfolio_value"] - 13000.0) < 0.01
        assert len(so["holdings"]) == 2
        assert so["narrative"] == FAKE_NARRATIVE

        assert result.metadata["holding_count"] == 2
        assert result.metadata["eval_passed"] is True

        # Tier 1 checks ran and all passed.
        assert agent._eval_results
        assert all(r["passed"] for r in agent._eval_results)


# ── Market-open guard (timing bug fix) ───────────────────────────────────────

def _fixed_et(year, month, day, hour) -> real_datetime:
    """A fixed, tz-aware US Eastern datetime for the _is_market_day_and_closed guard."""
    return real_datetime(year, month, day, hour, 0, tzinfo=ZoneInfo("America/New_York"))


def test_skips_on_weekend():
    # 2026-06-27 is a Saturday in ET → guard should skip.
    saturday = _fixed_et(2026, 6, 27, 12)
    with patch("agents.market_report.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        agent = _make_agent()
        result = agent.execute()

    assert result.metadata.get("skipped") is True
    assert result.structured_output is None
    assert "Saturday" in result.metadata["reason"]


def test_skips_before_market_close():
    # Monday 2:00pm ET — market still open (< 4pm) → guard should skip.
    monday_2pm = _fixed_et(2026, 6, 29, 14)
    with patch("agents.market_report.datetime") as mock_dt:
        mock_dt.now.return_value = monday_2pm
        agent = _make_agent()
        result = agent.execute()

    assert result.metadata.get("skipped") is True
    assert result.structured_output is None
    assert "not yet closed" in result.metadata["reason"]


def test_runs_after_close():
    # Monday 5:00pm ET — weekday, after close → guard passes, full flow runs.
    monday_5pm = _fixed_et(2026, 6, 29, 17)
    with patch("agents.market_report.datetime") as mock_dt, \
         patch("agents.market_report.fetch_quotes", return_value=FAKE_QUOTES), \
         patch("agents.market_report.fetch_news", return_value=FAKE_NEWS), \
         patch.object(MarketReportAgent, "call_claude", return_value=FAKE_NARRATIVE):
        mock_dt.now.return_value = monday_5pm
        agent = _make_agent()
        result = agent.execute()

    # Did NOT early-exit: structured output was built and checks ran.
    assert result.metadata.get("skipped") is None
    assert result.structured_output is not None
    assert result.structured_output["narrative"] == FAKE_NARRATIVE
    assert result.metadata["eval_passed"] is True
    assert all(r["passed"] for r in agent._eval_results)
    # BUG 3: date label comes from the ET market session, not the UTC clock.
    assert result.structured_output["date"] == "Monday, June 29, 2026"
