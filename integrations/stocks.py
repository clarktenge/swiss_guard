"""
stocks.py — stock quotes + news for the market-report agent, via yfinance.

Two jobs:
  - fetch_quotes(tickers)  → live price + day change for each ticker
  - fetch_news(tickers)    → recent headlines/summaries across the tickers

yfinance notes:
  - It's a pure Python library scraping Yahoo Finance — no API key, no signups,
    and no hard daily/per-second quota (unlike the old Alpha Vantage path). It
    can still be throttled by Yahoo under heavy use, so we fail soft per ticker
    rather than letting one bad symbol sink the whole report.
  - Quotes come from Ticker.fast_info (lastPrice / previousClose). News comes
    from Ticker.news, whose payload is nested under each item's "content" key in
    current yfinance versions.
  - fast_info["previousClose"] is unreliable for day P&L: once a session ends it
    can roll forward to *today's* close, which would zero out the day's move. So
    prev_close is sourced from the daily history (the unambiguous close of the
    most recent trading day before today) and only falls back to fast_info's
    value when history is unavailable. See _reliable_prev_close.

SECURITY: news titles/summaries are third-party content. The agent treats them
as untrusted data when handing them to Claude (see BaseAgent.call_claude).
"""

from datetime import date, datetime
from typing import List, Dict
from zoneinfo import ZoneInfo

import yfinance as yf


def _reliable_prev_close(
    ticker_obj: "yf.Ticker", today_et: date, fallback: float
) -> float:
    """
    Return a trustworthy previous close for the day-P&L math.

    fast_info["previousClose"] can roll forward to today's close once the regular
    session ends — pairing it with today's lastPrice then yields day_pnl ~= 0 even
    on a big mover. The daily history is unambiguous, so we take the close of the
    most recent trading day strictly *before* today's US Eastern date. This holds
    whether or not today's bar has posted yet (if it hasn't, the last bar already
    IS the previous close).

    auto_adjust=False keeps 'Close' as the raw close so it's on the same
    (unadjusted) basis as fast_info's lastPrice — an adjusted close would mismatch
    on/after ex-dividend dates. Falls back to `fallback` (fast_info's
    previousClose) if history is unavailable (e.g. Yahoo throttling).
    """
    try:
        hist = ticker_obj.history(period="7d", interval="1d", auto_adjust=False)
        closes = hist["Close"].dropna()
        for ts, close in zip(reversed(closes.index), reversed(closes.values)):
            if ts.date() < today_et:
                return float(close)
    except Exception as e:
        print(f"[stocks] history() previous-close lookup failed: {e}")
    return fallback


def fetch_quotes(tickers: List[str]) -> Dict[str, dict]:
    """
    Fetch a live quote for each ticker.

    Returns a dict keyed by ticker symbol:
        {
          "AAPL": {
            "ticker": "AAPL",
            "price": 192.32,
            "prev_close": 189.50,
            "change": 2.82,
            "change_percent": 1.49,
          },
          ...
        }

    Tickers that can't be priced (unknown symbol, or Yahoo returned nothing) are
    skipped, so the caller should not assume every input ticker is present.
    """
    quotes: Dict[str, dict] = {}
    today_et = datetime.now(ZoneInfo("America/New_York")).date()

    for ticker in tickers:
        try:
            tk = yf.Ticker(ticker)
            info = tk.fast_info
            price = info.get("lastPrice")
            prev_close = info.get("previousClose")
        except Exception as e:
            print(f"[stocks] Failed to fetch quote for '{ticker}': {e}")
            continue

        # An unknown/delisted symbol comes back with no price — skip it rather
        # than emitting a bogus $0 row.
        if price is None or prev_close is None:
            print(f"[stocks] No quote returned for '{ticker}' — skipping")
            continue

        price = float(price)
        # Prefer the daily-history previous close over fast_info's, which can roll
        # forward after the close and zero out the day's P&L. fast_info's value is
        # the fallback if history is unavailable.
        prev_close = _reliable_prev_close(tk, today_et, fallback=float(prev_close))
        change = price - prev_close
        change_percent = (change / prev_close * 100) if prev_close else 0.0

        quotes[ticker] = {
            "ticker": ticker,
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_percent": change_percent,
        }

    return quotes


def _extract_article(item: dict, ticker: str) -> dict:
    """
    Normalize one yfinance news item into our compact, data-only shape.

    Current yfinance nests the fields under "content"; older versions used a
    flat dict. We tolerate both.
    """
    content = item.get("content", item)

    url = ""
    for url_key in ("clickThroughUrl", "canonicalUrl"):
        link = content.get(url_key)
        if isinstance(link, dict) and link.get("url"):
            url = link["url"]
            break
    # Flat/legacy schema fallback.
    if not url:
        url = content.get("link", "")

    provider = content.get("provider")
    source = provider.get("displayName", "") if isinstance(provider, dict) else ""
    if not source:
        source = content.get("publisher", "")

    return {
        "title": content.get("title", ""),
        "summary": content.get("summary", "") or content.get("description", ""),
        "source": source,
        "url": url,
        "time_published": content.get("pubDate", "") or content.get("displayTime", ""),
        "tickers": [ticker],
    }


def fetch_news(tickers: List[str], limit: int = 10) -> List[dict]:
    """
    Fetch recent news across the given tickers.

    yfinance exposes news per ticker, so we pull each ticker's headlines and tag
    every article with its source ticker. Returns a list of compact, data-only
    article dicts capped at `limit`:
        {"title", "summary", "source", "url", "time_published", "tickers"}

    Returns an empty list if there are no tickers or no news is available.
    """
    if not tickers:
        return []

    # Spread the cap across tickers so one noisy ticker doesn't crowd out the
    # rest, but always allow at least a couple of items per ticker.
    per_ticker = max(2, limit // len(tickers))

    articles: List[dict] = []
    for ticker in tickers:
        try:
            items = yf.Ticker(ticker).news or []
        except Exception as e:
            print(f"[stocks] Failed to fetch news for '{ticker}': {e}")
            continue

        for item in items[:per_ticker]:
            articles.append(_extract_article(item, ticker))

    return articles[:limit]
