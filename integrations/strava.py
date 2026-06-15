"""
strava.py — workout data for the health-sync agent, via the Strava v3 API.

Strava is the source of truth for workouts. Three jobs:
  - get_recent_activities(days)  → normalized list of recent workouts, enriched
                                   with per-activity detail (calories etc.)
  - get_athlete_stats()          → all-time + recent rolling totals by sport
  - _refresh_access_token()      → swap the long-lived refresh token for a fresh
                                   short-lived access token

AUTH NOTE (per the agent's contract): every public function refreshes its own
access token up front. Strava access tokens are short-lived (~6h), so rather
than caching one we just exchange the refresh token before each call. The
refresh token itself lives in STRAVA_REFRESH_TOKEN and is long-lived; Strava
currently returns the same refresh token on each exchange, but if it ever
rotates one back we log a loud warning so you know to update .env.

SECURITY: activity `name` (and description) are user-authored free text. Treat
them as untrusted when handing them to an LLM — the agent wraps the activity
list as untrusted data (see the prompt-injection note in BaseAgent.call_claude).
"""

import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"

# Network timeouts (seconds). Token/detail calls are small; the activity list
# can be larger so it gets a touch more headroom.
_TIMEOUT = 20

# Strava reports everything in SI (meters, m/s). This module converts to
# imperial for display: distances in miles, elevation in feet, pace in min/mile,
# speed in mph. These are the only conversion factors used.
_METERS_PER_MILE = 1609.344
_METERS_PER_FOOT = 0.3048
_MPS_TO_MPH = 2.2369362920544


def _refresh_access_token() -> str:
    """
    Exchange the stored refresh token for a fresh access token.

    Called at the start of every public function in this module — access tokens
    are short-lived, so we don't bother caching one.
    """
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            "Strava credentials missing — set STRAVA_CLIENT_ID, "
            "STRAVA_CLIENT_SECRET and STRAVA_REFRESH_TOKEN in .env"
        )

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=_TIMEOUT,
    )
    _raise_for_strava(resp)
    payload = resp.json()

    # Strava normally hands back the same refresh token, but if it ever rotates
    # one we'd silently keep using a dead token next run. Surface it loudly so
    # the value in .env can be updated. (We never write to .env ourselves.)
    new_refresh = payload.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        print(
            "[strava] ⚠️  Strava rotated the refresh token. Update "
            "STRAVA_REFRESH_TOKEN in .env to the new value or the next run "
            "will fail to authenticate."
        )

    access_token = payload.get("access_token")
    if not access_token:
        raise RuntimeError("Strava token exchange returned no access_token")
    return access_token


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _raise_for_strava(resp: requests.Response) -> None:
    """
    Like resp.raise_for_status(), but folds Strava's JSON error body into the
    message so failures are actionable. A bare "401 Unauthorized" hides the most
    common cause — a refresh token authorized without the `activity:read` scope,
    which Strava reports as a `missing` `activity:read_permission` field. We
    catch that specific case and say exactly how to fix it.
    """
    if resp.ok:
        return

    body = resp.text or ""
    if "activity:read_permission" in body:
        raise RuntimeError(
            "Strava rejected the request: the token is missing the "
            "`activity:read` scope. Re-authorize the app with "
            "`scope=activity:read_all` (and `read,profile:read_all` as needed), "
            "then update STRAVA_REFRESH_TOKEN in .env with the new refresh "
            f"token. (HTTP {resp.status_code} from {resp.url})"
        )
    raise RuntimeError(
        f"Strava request failed: HTTP {resp.status_code} from {resp.url} — "
        f"{body[:300]}"
    )


def _fmt_pace(seconds_per_mile: Optional[float]) -> Optional[str]:
    """Render seconds-per-mile as 'm:ss/mi'. None passes through untouched."""
    if not seconds_per_mile or seconds_per_mile <= 0:
        return None
    minutes, secs = divmod(int(round(seconds_per_mile)), 60)
    return f"{minutes}:{secs:02d}/mi"


def _normalize_activity(a: dict) -> dict:
    """
    Flatten one Strava activity (summary or detail) into our compact shape.

    Strava reports distance in meters, time in seconds, speed in m/s. We convert
    to imperial display units — distance in miles, elevation in feet, pace in
    min/mile, speed in mph — so the agent can render without re-deriving units
    everywhere.

    `calories` only exists on the *detailed* activity payload, so it's None for
    activities we couldn't enrich.
    """
    distance_m = a.get("distance") or 0.0
    moving_time_s = a.get("moving_time") or 0
    distance_mi = distance_m / _METERS_PER_MILE

    # Pace only makes sense with both distance and time. Caller decides whether
    # it's meaningful for the sport (runs/walks yes, rides usually no).
    pace_s_per_mile = (moving_time_s / distance_mi) if distance_mi > 0 else None

    speed_mps = a.get("average_speed")
    elevation_m = a.get("total_elevation_gain") or 0.0

    return {
        "id": a.get("id"),
        "name": a.get("name", ""),                       # user-authored → untrusted
        "type": a.get("sport_type") or a.get("type", "Workout"),
        "date": a.get("start_date_local") or a.get("start_date", ""),
        "distance_mi": round(distance_mi, 2),
        "moving_time_s": moving_time_s,
        "elapsed_time_s": a.get("elapsed_time") or 0,
        "elevation_gain_ft": round(elevation_m / _METERS_PER_FOOT, 1),
        "average_heartrate": a.get("average_heartrate"),  # only if HR recorded
        "max_heartrate": a.get("max_heartrate"),
        "average_speed_mph": round(speed_mps * _MPS_TO_MPH, 2) if speed_mps else None,
        "average_pace": _fmt_pace(pace_s_per_mile),
        "calories": a.get("calories"),                    # detail-only
        "has_heartrate": bool(a.get("has_heartrate")),
    }


def _fetch_activity_detail(token: str, activity_id: int) -> Optional[dict]:
    """
    Fetch the detailed payload for one activity (adds calories, gear, etc.).

    Returns None on failure so a single bad/again-later activity doesn't sink
    the whole weekly pull — the caller falls back to the summary record.
    """
    try:
        resp = requests.get(
            f"{API_BASE}/activities/{activity_id}",
            headers=_auth_headers(token),
            params={"include_all_efforts": "false"},
            timeout=_TIMEOUT,
        )
        _raise_for_strava(resp)
        return resp.json()
    except (requests.exceptions.RequestException, RuntimeError) as e:
        print(f"[strava] Couldn't fetch detail for activity {activity_id}: {e}")
        return None


def get_recent_activities(days: int = 7, with_detail: bool = True) -> List[dict]:
    """
    Fetch all activities from the last `days` days, normalized.

    Each record carries: name, type, date, distance, duration, elevation,
    average/max heart rate, average pace, and calories.

    Strava's activity *list* endpoint returns summary records that omit
    calories, so when `with_detail` is True we make a follow-up detail call per
    activity to fill it in. A typical week is a handful of activities, so the
    extra calls are cheap; set `with_detail=False` to skip them if you're near
    Strava's rate limit and don't need calories.

    Returns newest-first. Returns an empty list if there were no activities.
    """
    token = _refresh_access_token()
    after = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    summaries: List[dict] = []
    page = 1
    per_page = 200
    while True:
        resp = requests.get(
            f"{API_BASE}/athlete/activities",
            headers=_auth_headers(token),
            params={"after": after, "per_page": per_page, "page": page},
            timeout=_TIMEOUT,
        )
        _raise_for_strava(resp)
        batch = resp.json()
        if not batch:
            break
        summaries.extend(batch)
        # A short page means we've reached the end — stop paginating.
        if len(batch) < per_page:
            break
        page += 1

    activities: List[dict] = []
    for summary in summaries:
        detail = None
        if with_detail and summary.get("id") is not None:
            detail = _fetch_activity_detail(token, summary["id"])
        # Detail is a superset of summary; fall back to summary if it failed.
        activities.append(_normalize_activity(detail or summary))

    # Newest first — Strava returns oldest-first when using `after`.
    activities.sort(key=lambda x: x["date"], reverse=True)
    return activities


def _normalize_totals(totals: Optional[dict]) -> dict:
    """Flatten one Strava 'totals' block into compact, imperial numbers."""
    totals = totals or {}
    distance_m = totals.get("distance") or 0.0
    return {
        "count": totals.get("count", 0),
        "distance_mi": round(distance_m / _METERS_PER_MILE, 2),
        "moving_time_s": totals.get("moving_time", 0),
        "elevation_gain_ft": round((totals.get("elevation_gain") or 0.0) / _METERS_PER_FOOT, 1),
    }


def get_athlete_stats() -> dict:
    """
    Fetch the athlete's rolling + lifetime totals (the figures behind Strava's
    profile page): recent (trailing ~4 weeks) and all-time totals for runs,
    rides and swims.

    Returns:
        {
          "recent": {"run": {...}, "ride": {...}, "swim": {...}},
          "all_time": {"run": {...}, "ride": {...}, "swim": {...}},
        }
    where each {...} is {count, distance_mi, moving_time_s, elevation_gain_ft}.
    """
    token = _refresh_access_token()

    # The stats endpoint is keyed by athlete id, so resolve "me" first.
    me = requests.get(
        f"{API_BASE}/athlete", headers=_auth_headers(token), timeout=_TIMEOUT
    )
    _raise_for_strava(me)
    athlete_id = me.json().get("id")
    if athlete_id is None:
        raise RuntimeError("Strava /athlete returned no id")

    resp = requests.get(
        f"{API_BASE}/athletes/{athlete_id}/stats",
        headers=_auth_headers(token),
        timeout=_TIMEOUT,
    )
    _raise_for_strava(resp)
    s = resp.json()

    return {
        "recent": {
            "run": _normalize_totals(s.get("recent_run_totals")),
            "ride": _normalize_totals(s.get("recent_ride_totals")),
            "swim": _normalize_totals(s.get("recent_swim_totals")),
        },
        "all_time": {
            "run": _normalize_totals(s.get("all_run_totals")),
            "ride": _normalize_totals(s.get("all_ride_totals")),
            "swim": _normalize_totals(s.get("all_swim_totals")),
        },
    }
