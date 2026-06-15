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

from agents.health_sync import compute_weekly_stats, _week_over_week


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


def run_offline_checks():
    test_compute_weekly_stats()
    test_empty_week()
    test_week_over_week()
    print("\nAll offline checks passed ✅")


# ── Part 2: live smoke test (opt-in) ────────────────────────────────────────

RUN_LIVE = False  # flip to True, or pass `live` on the command line


def run_live():
    from agents.health_sync import HealthSyncAgent

    print("\n⚠️  Running LIVE health-sync (Strava + Claude + Discord + Supabase)…\n")
    agent = HealthSyncAgent()  # garmin_data=None for now

    # run() = full pipeline (execute → Supabase logging → Discord post).
    # Swap for agent.execute() to preview the markdown with no side effects.
    result = agent.run()
    print(result.content)


if __name__ == "__main__":
    run_offline_checks()
    if RUN_LIVE or "live" in sys.argv[1:]:
        run_live()
