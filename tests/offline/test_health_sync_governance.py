"""
Offline unit tests for the governance-wired health-sync agent.

These exercise execute()'s structured-output path — building the typed
HealthOutput from Python-computed numbers, the Tier 1 numeric-consistency check,
and the Discord markdown rendering — with every external dependency mocked. No
Strava, Garmin, Claude, Supabase, Voyage, or Discord calls happen here, so this
file is safe for CI.

Same pattern as test_email_triage_governance: build the agent with __new__ (skips
BaseAgent.__init__, which would construct the API clients), stub the attributes
execute() touches, patch the module-level get_recent_activities, patch
_load_prior_week_stats, and patch call_claude on the class.
"""

from unittest.mock import patch, MagicMock

from agents.health_sync import HealthSyncAgent


# ── Fake data ────────────────────────────────────────────────────────────────

# Normalized Strava activities (the shape integrations.strava produces).
FAKE_ACTIVITIES = [
    {"id": 1, "name": "Morning Run", "type": "Run",
     "date": "2026-06-24T07:00:00", "distance_mi": 5.0, "moving_time_s": 2400,
     "elevation_gain_ft": 120.0, "average_heartrate": 150, "calories": 480},
    {"id": 2, "name": "Evening Ride", "type": "Ride",
     "date": "2026-06-23T18:00:00", "distance_mi": 18.25, "moving_time_s": 3600,
     "elevation_gain_ft": 640.0, "average_heartrate": 138, "calories": 720},
]

FAKE_NARRATIVE = "Solid week of mixed training. Nice ride yesterday."


def _make_agent() -> HealthSyncAgent:
    """
    Build a HealthSyncAgent without running BaseAgent.__init__ (which would spin
    up the Anthropic/Supabase/Voyage clients). Stub the attributes execute() and
    the run() eval hook read. Garmin is disabled so no live call is attempted.
    """
    agent = HealthSyncAgent.__new__(HealthSyncAgent)
    agent._eval_results = []
    agent.supabase = MagicMock()
    agent.voyage = MagicMock()
    agent.anthropic = MagicMock()
    agent.garmin_data = None
    agent.fetch_garmin = False
    return agent


# ── Tests ────────────────────────────────────────────────────────────────────

def test_execute_returns_health_output():
    with patch("agents.health_sync.get_recent_activities",
               return_value=FAKE_ACTIVITIES):
        with patch.object(HealthSyncAgent, "_load_prior_week_stats",
                          return_value=None):
            with patch.object(HealthSyncAgent, "call_claude",
                              return_value=FAKE_NARRATIVE):
                agent = _make_agent()
                result = agent.execute()

                assert result.structured_output is not None
                assert result.metadata["activity_count"] == 2
                assert result.metadata["eval_passed"] is True
                # Numbers are computed in Python, narrative comes from Claude.
                so = result.structured_output
                assert so["week_activity_count"] == 2
                assert abs(so["week_distance_miles"] - 23.25) < 0.001
                assert so["narrative"] == FAKE_NARRATIVE


def test_numeric_consistency_check_passes():
    with patch("agents.health_sync.get_recent_activities",
               return_value=FAKE_ACTIVITIES):
        with patch.object(HealthSyncAgent, "_load_prior_week_stats",
                          return_value=None):
            with patch.object(HealthSyncAgent, "call_claude",
                              return_value=FAKE_NARRATIVE):
                agent = _make_agent()
                agent.execute()

                assert agent._eval_results, "eval results should be populated"
                consistency = [r for r in agent._eval_results
                               if r["check"] == "numeric_consistency"]
                assert consistency, "numeric_consistency check should run"
                assert consistency[0]["passed"] is True


def test_vs_last_week_distance_computed():
    # Prior week was 20 mi; this week is 23.25 mi → +16.2%.
    with patch("agents.health_sync.get_recent_activities",
               return_value=FAKE_ACTIVITIES):
        with patch.object(HealthSyncAgent, "_load_prior_week_stats",
                          return_value={"total_distance_mi": 20.0,
                                        "activity_count": 1,
                                        "total_moving_time_s": 1800}):
            with patch.object(HealthSyncAgent, "call_claude",
                              return_value=FAKE_NARRATIVE):
                agent = _make_agent()
                result = agent.execute()

                pct = result.structured_output["vs_last_week_distance"]
                assert pct == 16.2, pct


def test_empty_week_still_builds_output():
    # No Strava activities and no Garmin → early return, but governance still
    # produces a structured output and runs the Tier 1 check.
    with patch("agents.health_sync.get_recent_activities", return_value=[]):
        with patch.object(HealthSyncAgent, "_load_prior_week_stats",
                          return_value=None):
            agent = _make_agent()
            result = agent.execute()

            assert result.structured_output is not None
            assert result.structured_output["week_activity_count"] == 0
            assert result.metadata["eval_passed"] is True
            assert result.content.strip()
