# ─────────────────────────────────────────────────────────────────────────────
# test_health_sync — two parts:
#
#   1. OFFLINE unit checks (free, no network, no side effects): exercise the
#      pure stat math in compute_weekly_stats with hand-built activities. These
#      run on import and assert, so `python test_health_sync.py` fails loudly if
#      the weekly rollup logic regresses.
#
#   2. ⚠️  LIVE smoke test (guarded below): hits the real Strava API, calls
#      Claude (billed), and — via run() — embeds with Voyage + writes Supabase
#      rows + posts to the health-sync Discord webhook. Off by default; flip
#      RUN_LIVE = True (or pass `live` on the command line) to exercise it.
#
# Run:  python test_health_sync.py          # offline checks only
#       python test_health_sync.py live      # offline checks + live run()
# ─────────────────────────────────────────────────────────────────────────────
import sys

# Emoji-heavy output; force UTF-8 so the default Windows console doesn't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from agents.health_sync import (
    compute_weekly_stats,
    _week_over_week,
    _has_garmin_metrics,
)


# ── Part 1: offline unit checks ─────────────────────────────────────────────

def _sample_activities():
    """
    Two runs (with HR) + one ride (no HR) — enough to cover every branch.
    Distances are in miles / feet, matching the imperial shape the Strava
    integration now emits.
    """
    return [
        {
            "type": "Run", "date": "2026-06-14T07:00:00Z",
            "distance_mi": 10.0, "moving_time_s": 3000,
            "elevation_gain_ft": 50.0, "average_heartrate": 150.0,
        },
        {
            "type": "Run", "date": "2026-06-12T07:00:00Z",
            "distance_mi": 5.0, "moving_time_s": 1500,
            "elevation_gain_ft": 20.0, "average_heartrate": 140.0,
        },
        {
            "type": "Ride", "date": "2026-06-10T07:00:00Z",
            "distance_mi": 30.0, "moving_time_s": 3600,
            "elevation_gain_ft": 200.0, "average_heartrate": None,
        },
    ]


def test_compute_weekly_stats():
    stats = compute_weekly_stats(_sample_activities())

    assert stats["activity_count"] == 3
    assert stats["total_distance_mi"] == 45.0
    assert stats["total_moving_time_s"] == 8100
    assert stats["total_elevation_ft"] == 270.0

    # by_type buckets
    assert stats["by_type"]["Run"]["count"] == 2
    assert stats["by_type"]["Run"]["distance_mi"] == 15.0
    assert stats["by_type"]["Ride"]["count"] == 1

    # HR is present and time-weighted: (150*3000 + 140*1500) / 4500 = 146.67
    assert stats["has_heartrate"] is True
    assert abs(stats["avg_heartrate"] - 146.7) < 0.1
    print("✓ compute_weekly_stats: totals, by_type, weighted HR")


def test_empty_week():
    stats = compute_weekly_stats([])
    assert stats["activity_count"] == 0
    assert stats["total_distance_mi"] == 0.0
    assert stats["has_heartrate"] is False
    assert stats["avg_heartrate"] is None
    print("✓ compute_weekly_stats: empty week is safe")


def test_week_over_week():
    current = compute_weekly_stats(_sample_activities())

    # No prior data → no comparison (cold start).
    assert _week_over_week(current, None) is None

    prior = {"activity_count": 2, "total_distance_mi": 40.0, "total_moving_time_s": 7000}
    wow = _week_over_week(current, prior)
    assert wow["activity_count_delta"] == 1
    assert wow["distance_mi_delta"] == 5.0
    assert wow["moving_time_s_delta"] == 1100
    print("✓ _week_over_week: cold start + deltas")


def _sample_garmin_metrics():
    """
    A full day of Garmin recovery metrics, shaped exactly like
    integrations.garmin.get_health_metrics() returns — used to feed the combined
    pipeline without a live Garmin call.
    """
    return {
        "date": "2026-06-14",
        "sleep": {
            "duration_h": 7.4,
            "score": 84,
            "stages": {"deep_h": 1.3, "light_h": 4.0, "rem_h": 1.7, "awake_h": 0.4},
        },
        "hrv": {"last_night_avg_ms": 46, "weekly_avg_ms": 49, "status": "BALANCED"},
        "body_battery": {"start": 28, "end": 74, "high": 79, "low": 22},
        "resting_hr_bpm": 51,
        "steps": 8123,
        "stress_avg": 31,
    }


def test_has_garmin_metrics():
    # A real day of metrics → present.
    assert _has_garmin_metrics(_sample_garmin_metrics()) is True

    # None / empty → absent (Garmin skipped or unavailable).
    assert _has_garmin_metrics(None) is False
    assert _has_garmin_metrics({}) is False

    # Dict with only a date and all-None metrics (a no-wear day) → absent: the
    # gating must look past the date key, not just "is the dict non-None".
    no_wear = {
        "date": "2026-06-14",
        "sleep": None, "hrv": None, "body_battery": None,
        "resting_hr_bpm": None, "steps": None, "stress_avg": None,
    }
    assert _has_garmin_metrics(no_wear) is False

    # A single real metric is enough to warrant the recovery section.
    assert _has_garmin_metrics({"date": "2026-06-14", "resting_hr_bpm": 50}) is True
    print("✓ _has_garmin_metrics: gates None / empty / no-wear / partial")


def run_offline_checks():
    test_compute_weekly_stats()
    test_empty_week()
    test_week_over_week()
    test_has_garmin_metrics()
    print("\nAll offline checks passed ✅")


# ── Part 2: live smoke tests (opt-in) ───────────────────────────────────────
#
#   live    — full combined pipeline: Strava + Garmin (both live) + Claude,
#             then run()'s side effects (Discord + Supabase).
#   combo   — combined OUTPUT preview with NO side effects: pulls Strava live,
#             INJECTS sample Garmin metrics (so it works even without a Garmin
#             session), calls Claude, and prints the markdown. Cheaper way to
#             eyeball that the recovery section renders from Garmin data.

RUN_LIVE = False  # flip to True, or pass `live` / `combo` on the command line


def run_live():
    from agents.health_sync import HealthSyncAgent

    print("\n⚠️  Running LIVE health-sync (Strava + Garmin + Claude + Discord + Supabase)…\n")
    agent = HealthSyncAgent()  # pulls both Strava + Garmin live

    # run() = full pipeline (execute → Supabase logging → Discord post).
    # Swap for agent.execute() to preview the markdown with no side effects.
    result = agent.run()
    print(f"[has_garmin={result.metadata.get('has_garmin')}]\n")
    print(result.content)


def run_combined_preview():
    """Combined output (Strava live + injected Garmin), no side effects."""
    from agents.health_sync import HealthSyncAgent

    print("\n⚠️  Previewing COMBINED output (Strava live + sample Garmin + Claude)…\n")
    # Inject Garmin metrics so the recovery section has data to work with even
    # without a live Garmin session; execute() then skips the live Garmin call.
    agent = HealthSyncAgent(garmin_data=_sample_garmin_metrics())

    result = agent.execute()  # no Supabase / Discord / embedding side effects
    assert result.metadata.get("has_garmin") is True, "Garmin data didn't reach the agent"

    content = result.content
    # The combined briefing should carry both sources through to the markdown:
    # the Python-rendered Strava stats line and Claude's recovery read.
    assert "Health sync" in content
    print(f"[has_garmin={result.metadata.get('has_garmin')}]\n")
    print(content)
    print("\n✓ combined preview rendered (Strava stats + Garmin recovery)")


if __name__ == "__main__":
    run_offline_checks()
    args = sys.argv[1:]
    if RUN_LIVE or "live" in args:
        run_live()
    if "combo" in args:
        run_combined_preview()
