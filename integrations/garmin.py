"""
garmin.py — workouts AND health metrics for the health-sync agent, via Garmin
Connect. This is the single source of truth for both sides of the sync.

Two public entry points:
  - get_recent_activities(days_back) → normalized list of recent WORKOUTS (what
    you did): name, type, distance, duration, HR, elevation, calories.
  - get_health_metrics(date=None)    → RECOVERY metrics (how you feel) that a
    workout log doesn't have: sleep, HRV, body battery, resting heart rate,
    daily steps and stress.

get_health_metrics logs in once and returns a single flat dict of yesterday's
metrics (or for an explicit date), already converted to friendly units (sleep in
hours, not seconds). Every metric is fetched independently and best-effort: if
Garmin has no data for it (or the call fails), that metric comes back as None
rather than sinking the whole pull. The agent forwards this dict to Claude
verbatim for the recovery read.

get_recent_activities returns the same compact, imperial activity shape the agent
already consumes (distances in miles, elevation in feet, moving time in seconds).
The device syncs activities to Garmin Connect directly, so this covers everything
the (now-removed) Strava integration used to provide.

AUTH NOTE: Garmin has no official API, so we use the `garminconnect` library,
which drives the same backend the mobile app uses. Garmin rate-limits *logins*
aggressively, so we cache the session tokens (under GARMIN_TOKENSTORE, default
~/.garminconnect) and only fall back to a full email/password login when the
cached tokens are missing or expired. Credentials live in GARMIN_EMAIL /
GARMIN_PASSWORD; we never write them anywhere.

All numeric work (unit conversion, picking start/end body-battery values) happens
here in Python, matching the agent's contract that Claude never does arithmetic.
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from garminconnect import Garmin
from dotenv import load_dotenv

load_dotenv()

_SECONDS_PER_HOUR = 3600.0

# Garmin reports activity distance/elevation in SI (meters). We convert to the
# imperial display units the agent already works in — distance in miles,
# elevation in feet — so the health-sync compute path is unchanged from when
# Strava supplied these numbers already-converted. (Numbers in Python, not Claude.)
_METERS_PER_MILE = 1609.344
_METERS_PER_FOOT = 0.3048

# Where we cache Garmin session tokens so a daily run doesn't re-login (and trip
# Garmin's login rate limit) every time. Override with GARMIN_TOKENSTORE.
_TOKENSTORE = os.getenv("GARMIN_TOKENSTORE", "").strip() or os.path.expanduser("~/.garminconnect")


# ── Authentication ──────────────────────────────────────────────────────────

def _login() -> Garmin:
    """
    Return an authenticated Garmin client.

    `client.login(tokenstore)` does the right thing on its own: it first tries to
    load a cached token session from `tokenstore` (no credentials, no network
    login → no rate limit), and only falls back to a full email/password login
    when the cache is missing or expired — automatically writing the fresh
    tokens back to `tokenstore` for next time. So we just pass the path and let
    the library manage the cache; no manual dump.

    This matters: Garmin aggressively rate-limits the *login* endpoint (HTTP
    429). Re-logging in every run trips it and escalates to longer lockouts, so
    the cached-token path is what keeps a daily run healthy. If you're currently
    seeing 429s, you're IP-rate-limited from earlier logins — wait for it to
    clear; once one login succeeds the tokens cache and later runs skip login.
    """
    email = os.getenv("GARMIN_EMAIL", "").strip()
    password = os.getenv("GARMIN_PASSWORD", "").strip()
    if not (email and password):
        raise RuntimeError(
            "Garmin credentials missing — set GARMIN_EMAIL and GARMIN_PASSWORD "
            "in .env"
        )

    client = Garmin(email=email, password=password)
    client.login(_TOKENSTORE)  # loads cache if present, else logs in + caches
    return client


# ── Per-metric fetchers (each best-effort → None on missing/failure) ─────────
#
# Each takes the live client + an ISO date string and returns a small dict (or a
# scalar) of just the fields we care about, or None if Garmin has nothing for
# that day. They never raise: a missing metric must not sink the others.

def _sleep(client: Garmin, date: str) -> Optional[dict]:
    """Sleep duration (hours), score, and stage breakdown (hours)."""
    try:
        data = client.get_sleep_data(date) or {}
        dto = data.get("dailySleepDTO") or {}

        total_s = dto.get("sleepTimeSeconds")
        if not total_s:
            return None  # no sleep recorded for the night

        # Score lives under sleepScores.overall.value; absent on some devices.
        score = None
        overall = (dto.get("sleepScores") or {}).get("overall") or {}
        if isinstance(overall.get("value"), (int, float)):
            score = int(overall["value"])

        def _hours(seconds) -> Optional[float]:
            return round(seconds / _SECONDS_PER_HOUR, 2) if seconds else None

        stages = {
            "deep_h": _hours(dto.get("deepSleepSeconds")),
            "light_h": _hours(dto.get("lightSleepSeconds")),
            "rem_h": _hours(dto.get("remSleepSeconds")),
            "awake_h": _hours(dto.get("awakeSleepSeconds")),
        }
        # Drop the stage block entirely if the device reported no stages.
        if not any(v is not None for v in stages.values()):
            stages = None

        return {
            "duration_h": round(total_s / _SECONDS_PER_HOUR, 2),
            "score": score,
            "stages": stages,
        }
    except Exception as e:
        print(f"[garmin] sleep unavailable: {e}")
        return None


def _hrv(client: Garmin, date: str) -> Optional[dict]:
    """Overnight HRV average (ms) + Garmin's HRV status label."""
    try:
        data = client.get_hrv_data(date) or {}
        summary = data.get("hrvSummary") or {}
        avg = summary.get("lastNightAvg")
        if avg is None:
            return None
        return {
            "last_night_avg_ms": avg,
            "weekly_avg_ms": summary.get("weeklyAvg"),
            "status": summary.get("status"),  # e.g. BALANCED / UNBALANCED / LOW
        }
    except Exception as e:
        print(f"[garmin] HRV unavailable: {e}")
        return None


def _body_battery_level(row) -> Optional[int]:
    """
    Pull the battery level (0–100) out of one bodyBatteryValuesArray row.

    Rows look like [epoch_ms, status_str, level, ...]; the exact index drifts
    between library/device versions, so rather than hard-code a position we take
    the value that's a plausible 0–100 level (the epoch timestamp is far larger).
    """
    if not isinstance(row, (list, tuple)):
        return None
    for v in row:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100:
            return int(v)
    return None


def _body_battery(client: Garmin, date: str) -> Optional[dict]:
    """Body battery at start and end of day, plus the day's high/low."""
    try:
        data = client.get_body_battery(date) or []
        if not data:
            return None

        # One dict per day; we asked for a single day, so take the first.
        values = data[0].get("bodyBatteryValuesArray") or []
        levels = [lvl for lvl in (_body_battery_level(r) for r in values) if lvl is not None]
        if not levels:
            return None

        return {
            "start": levels[0],
            "end": levels[-1],
            "high": max(levels),
            "low": min(levels),
        }
    except Exception as e:
        print(f"[garmin] body battery unavailable: {e}")
        return None


def _resting_hr(client: Garmin, date: str) -> Optional[int]:
    """Resting heart rate (bpm) for the day."""
    try:
        data = client.get_rhr_day(date) or {}
        metrics = (
            (data.get("allMetrics") or {}).get("metricsMap") or {}
        ).get("WELLNESS_RESTING_HEART_RATE") or []
        for entry in metrics:
            value = entry.get("value")
            if isinstance(value, (int, float)):
                return int(value)
        return None
    except Exception as e:
        print(f"[garmin] resting HR unavailable: {e}")
        return None


def _steps(client: Garmin, date: str) -> Optional[int]:
    """Total step count for the day (summed from the intraday buckets)."""
    try:
        buckets = client.get_steps_data(date) or []
        total = sum(b.get("steps") or 0 for b in buckets if isinstance(b, dict))
        return total or None
    except Exception as e:
        print(f"[garmin] steps unavailable: {e}")
        return None


def _stress(client: Garmin, date: str) -> Optional[int]:
    """Average all-day stress score (0–100). Garmin uses negatives for 'no data'."""
    try:
        data = client.get_stress_data(date) or {}
        avg = data.get("avgStressLevel")
        if not isinstance(avg, (int, float)) or avg < 0:
            return None
        return int(avg)
    except Exception as e:
        print(f"[garmin] stress unavailable: {e}")
        return None


# ── Public entry point ───────────────────────────────────────────────────────

def get_health_metrics(date: Optional[str] = None) -> dict:
    """
    Fetch yesterday's Garmin recovery metrics as one flat dict.

    Args:
        date: ISO date 'YYYY-MM-DD' to fetch. Defaults to yesterday (Garmin
              finalizes a day's sleep/HRV overnight, so yesterday is the most
              recent complete picture).

    Returns a dict shaped like:
        {
          "date": "2026-06-14",
          "sleep": {"duration_h": 7.5, "score": 85,
                    "stages": {"deep_h":1.2,"light_h":4.1,"rem_h":1.8,"awake_h":0.4}}
                   | None,
          "hrv": {"last_night_avg_ms": 45, "weekly_avg_ms": 48, "status": "BALANCED"}
                 | None,
          "body_battery": {"start": 28, "end": 76, "high": 80, "low": 22} | None,
          "resting_hr_bpm": 52 | None,
          "steps": 8123 | None,
          "stress_avg": 30 | None,
        }

    Any metric Garmin has no data for (or that fails to fetch) comes back as
    None. Login failure still raises — that's a real, actionable problem.
    """
    if date is None:
        date = (datetime.now() - timedelta(days=1)).date().isoformat()

    client = _login()

    return {
        "date": date,
        "sleep": _sleep(client, date),
        "hrv": _hrv(client, date),
        "body_battery": _body_battery(client, date),
        "resting_hr_bpm": _resting_hr(client, date),
        "steps": _steps(client, date),
        "stress_avg": _stress(client, date),
    }


# ── Workouts (activities) ─────────────────────────────────────────────────────

def _display_type(type_key: Optional[str]) -> str:
    """
    Turn Garmin's activityType.typeKey ('running', 'strength_training') into a
    readable label ('Running', 'Strength Training'). Falls back to 'Workout' when
    the type is missing, mirroring the default the agent used under Strava.
    """
    if not type_key or not isinstance(type_key, str):
        return "Workout"
    return type_key.replace("_", " ").title()


def _normalize_activity(a: dict) -> dict:
    """
    Flatten one Garmin Connect activity into the compact, imperial shape the
    health-sync agent consumes — the exact same keys the old Strava integration
    emitted, so compute_weekly_stats / _to_activities need no changes.

    Garmin reports distance/elevation in meters and durations in seconds. We
    convert distance→miles and elevation→feet here (moving time stays in seconds;
    the agent converts to minutes). Every field is best-effort: anything Garmin
    didn't record comes back as None rather than crashing the pull.
    """
    distance_m = a.get("distance") or 0.0

    # Prefer moving time; Garmin omits movingDuration for some sports (e.g.
    # strength training), so fall back to the total timer duration.
    moving_time_s = a.get("movingDuration")
    if not moving_time_s:
        moving_time_s = a.get("duration") or 0

    elevation_m = a.get("elevationGain")  # None for indoor/no-baro activities

    return {
        "id": a.get("activityId"),
        "name": a.get("activityName") or "",      # user-authored → untrusted
        "type": _display_type((a.get("activityType") or {}).get("typeKey")),
        "date": a.get("startTimeLocal") or a.get("startTimeGMT", ""),
        "distance_mi": round(distance_m / _METERS_PER_MILE, 2),
        "moving_time_s": int(moving_time_s or 0),
        "elevation_gain_ft": (
            round(elevation_m / _METERS_PER_FOOT, 1) if elevation_m else 0.0
        ),
        "average_heartrate": a.get("averageHR"),   # only if HR was recorded
        "max_heartrate": a.get("maxHR"),
        "calories": a.get("calories"),
    }


def _within_window(date_str: str, cutoff: datetime) -> bool:
    """
    True if an activity's local start time is on/after `cutoff`. Garmin's
    startTimeLocal is 'YYYY-MM-DD HH:MM:SS'. If it can't be parsed we keep the
    activity (over-fetching a stale one is safer than silently dropping a real
    workout) and log it.
    """
    if not date_str:
        return True
    try:
        started = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        print(f"[garmin] couldn't parse activity date {date_str!r}; keeping it")
        return True
    return started >= cutoff


def get_recent_activities(days_back: int = 7) -> list[dict]:
    """
    Fetch recent workouts from Garmin Connect, normalized to the agent's shape.

    Each record carries: id, name, type, date, distance_mi, moving_time_s,
    elevation_gain_ft, average_heartrate, max_heartrate, calories. Distances are
    already in miles and elevation in feet (converted here); moving time is in
    seconds (the agent converts to minutes). Missing fields come back as None.

    Garmin's API has no date-range filter, so we over-fetch the most recent
    `days_back * 2` activities via get_activities(0, days_back*2) and trim to
    those started within the last `days_back` days. Returns newest-first, or an
    empty list if there were none (or the activities call failed — a workout pull
    failing must not sink the recovery read, same best-effort contract as the
    per-metric fetchers).

    Login failure still raises (via _login) — that's a real, actionable problem.
    """
    client = _login()

    cutoff = datetime.now() - timedelta(days=days_back)
    try:
        raw = client.get_activities(0, days_back * 2) or []
    except Exception as e:
        print(f"[garmin] activities unavailable: {e}")
        return []

    activities = [
        _normalize_activity(a) for a in raw if isinstance(a, dict)
    ]
    activities = [a for a in activities if _within_window(a["date"], cutoff)]

    # Newest first, matching what the agent expects for "yesterday's workout".
    activities.sort(key=lambda x: x["date"], reverse=True)
    return activities


# ── Direct-run harness (hits Garmin live; no other side effects) ──────────────

if __name__ == "__main__":
    import json
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    print("── recent activities ──")
    print(json.dumps(get_recent_activities(), indent=2))
    print("\n── health metrics ──")
    print(json.dumps(get_health_metrics(), indent=2))
