"""
Tests for the market-report agent.

Two modes:

  python test_market_report.py
      Offline, free, deterministic. Verifies the P&L math computed in Python
      (_compute_holding) and the markdown rendering. This is the important one:
      the whole design rests on the numbers being correct in Python, never from
      Claude. No network, no API keys needed.

  python test_market_report.py --live
      ⚠️  LIVE smoke test — NOT free. Runs the full agent.run():
        • reads holdings from Supabase
        • hits Alpha Vantage for quotes + news (consumes daily quota)
        • calls Claude (billed)
        • posts the report to the market-report Discord webhook
        • inserts Supabase rows + a Voyage embedding
"""

import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.market_report import _compute_holding, MarketReportAgent


def test_compute_holding_gain():
    """100 sh bought at $100, now $110 (prev close $108)."""
    holding = {"ticker": "AAPL", "shares": 100, "avg_cost": 100.0}
    quote = {"price": 110.0, "prev_close": 108.0, "change": 2.0, "change_percent": 1.85}

    r = _compute_holding(holding, quote)

    assert r["market_value"] == 11000.0, r["market_value"]
    assert r["cost_basis"] == 10000.0, r["cost_basis"]
    assert r["day_pnl"] == 200.0, r["day_pnl"]          # 100 * (110 - 108)
    assert r["total_pnl"] == 1000.0, r["total_pnl"]      # 100 * (110 - 100)
    assert round(r["total_pnl_pct"], 2) == 10.0, r["total_pnl_pct"]
    print("✓ test_compute_holding_gain")


def test_compute_holding_loss():
    """10 sh bought at $250, now $200 (prev close $210) — a down day and a loss."""
    holding = {"ticker": "NVDA", "shares": 10, "avg_cost": 250.0}
    quote = {"price": 200.0, "prev_close": 210.0, "change": -10.0, "change_percent": -4.76}

    r = _compute_holding(holding, quote)

    assert r["market_value"] == 2000.0, r["market_value"]
    assert r["day_pnl"] == -100.0, r["day_pnl"]          # 10 * (200 - 210)
    assert r["total_pnl"] == -500.0, r["total_pnl"]       # 10 * (200 - 250)
    assert round(r["total_pnl_pct"], 2) == -20.0, r["total_pnl_pct"]
    print("✓ test_compute_holding_loss")


def test_render_contains_numbers():
    """The rendered markdown should carry the Python-computed figures verbatim."""
    rows = [
        _compute_holding(
            {"ticker": "AAPL", "shares": 100, "avg_cost": 100.0},
            {"price": 110.0, "prev_close": 108.0, "change": 2.0, "change_percent": 1.85},
        )
    ]
    agent = MarketReportAgent.__new__(MarketReportAgent)  # skip __init__ (no API clients)
    md = agent._render(
        rows=rows,
        total_value=11000.0,
        total_cost=10000.0,
        total_day_pnl=200.0,
        day_pnl_pct=1.85,
        total_pnl=1000.0,
        total_pnl_pct=10.0,
        market_context="Apple drifted higher with no single catalyst.",
    )

    assert "Portfolio summary" in md
    assert "$11,000.00" in md          # total value
    assert "+$1,000.00" in md          # total P&L, signed
    assert "AAPL" in md
    assert "Market context" in md
    print("✓ test_render_contains_numbers")


def test_build_embed_colors_and_fields():
    """Embed is green on an up day, red on a down day, with one field per holding."""
    rows = [
        _compute_holding(
            {"ticker": "AAPL", "shares": 100, "avg_cost": 100.0},
            {"price": 110.0, "prev_close": 108.0, "change": 2.0, "change_percent": 1.85},
        ),
        _compute_holding(
            {"ticker": "NVDA", "shares": 10, "avg_cost": 250.0},
            {"price": 200.0, "prev_close": 210.0, "change": -10.0, "change_percent": -4.76},
        ),
    ]
    agent = MarketReportAgent.__new__(MarketReportAgent)  # skip __init__ (no API clients)

    up = agent._build_embed(rows, 13000.0, 100.0, 0.78, 500.0, 4.0, "ctx")
    assert up["color"] == 0x2ECC71, up["color"]            # positive day → green
    assert up["title"].startswith("Market Report — "), up["title"]
    assert "Total value:" in up["description"]
    # One inline field per holding, plus the market-context field.
    holding_fields = [f for f in up["fields"] if f["inline"]]
    assert len(holding_fields) == 2, holding_fields
    assert {f["name"] for f in holding_fields} == {"AAPL", "NVDA"}
    assert up["fields"][-1]["name"] == "Market context"

    down = agent._build_embed(rows, 13000.0, -300.0, -2.0, 500.0, 4.0, "ctx")
    assert down["color"] == 0xE74C3C, down["color"]        # negative day → red
    print("✓ test_build_embed_colors_and_fields")


def run_offline():
    test_compute_holding_gain()
    test_compute_holding_loss()
    test_render_contains_numbers()
    test_build_embed_colors_and_fields()
    print("\nAll offline tests passed ✅")


def run_live():
    print("⚠️  Running LIVE market-report (Supabase + yFinance + Claude + Discord)\n")
    agent = MarketReportAgent()
    result = agent.run()
    print(result.content)


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live()
    else:
        run_offline()
