"""
Offline unit tests for the governance-wired email-triage agent.

These exercise execute()'s structured-output path — JSON parsing into
TriageOutput, the Tier 1 eval checks, and the Discord markdown rendering —
with every external dependency mocked. No Gmail, Claude, Supabase, Voyage, or
Discord calls happen here, so this file is safe for CI.

The pattern throughout: build the agent with __new__ (skips BaseAgent.__init__,
which would construct the API clients), stub the attributes execute() touches,
patch the module-level list_recent_emails, and patch call_claude on the class.
"""

import json

import pytest
from unittest.mock import patch, MagicMock

from agents.email_triage import EmailTriageAgent


# ── Fake data ────────────────────────────────────────────────────────────────

FAKE_EMAILS = [
    {"id": "id001", "from": "boss@work.com", "subject": "Urgent meeting",
     "snippet": "Need you now", "received_at": "Mon, 23 Jun 2026 09:00:00"},
    {"id": "id002", "from": "shop@brand.com", "subject": "50% off today only",
     "snippet": "Sale ends tonight", "received_at": "Mon, 23 Jun 2026 08:00:00"},
    {"id": "id003", "from": "jobs@company.com", "subject": "New role posted",
     "snippet": "ML Engineer opening", "received_at": "Mon, 23 Jun 2026 07:00:00"},
]

VALID_TRIAGE_JSON = json.dumps({
    "urgent": [{"email_id": "id001", "from_": "boss@work.com",
                "subject": "Urgent meeting", "reason": "Needs response today",
                "confidence": 0.95}],
    "opportunities": [{"email_id": "id003", "from_": "jobs@company.com",
                       "subject": "New role posted", "reason": "ML role",
                       "confidence": 0.8}],
    "sales": [{"email_id": "id002", "from_": "shop@brand.com",
               "subject": "50% off today only", "reason": "Promotional",
               "confidence": 0.9, "brand": "Brand", "expires_at": None}],
    "uncategorized": []
})


def _make_agent() -> EmailTriageAgent:
    """
    Build an EmailTriageAgent without running BaseAgent.__init__ (which would
    spin up the Anthropic/Supabase/Voyage clients). Stub the attributes that
    execute() and the run() eval hook read.
    """
    agent = EmailTriageAgent.__new__(EmailTriageAgent)
    agent._eval_results = []
    agent.supabase = MagicMock()
    agent.voyage = MagicMock()
    agent.anthropic = MagicMock()
    return agent


# ── Tests ────────────────────────────────────────────────────────────────────

def test_execute_returns_triage_output():
    with patch("agents.email_triage.notify_error"):
        with patch("agents.email_triage.list_recent_emails",
                   return_value=FAKE_EMAILS):
            with patch.object(EmailTriageAgent, "call_claude",
                              return_value=VALID_TRIAGE_JSON):
                agent = _make_agent()
                result = agent.execute()

                assert result.structured_output is not None
                assert result.metadata["email_count"] == 3
                assert result.metadata["eval_passed"] is True


def test_conservation_check_catches_dropped_email():
    # Same JSON as VALID_TRIAGE_JSON but id002 is dropped from every bucket.
    dropped_json = json.dumps({
        "urgent": [{"email_id": "id001", "from_": "boss@work.com",
                    "subject": "Urgent meeting", "reason": "Needs response today",
                    "confidence": 0.95}],
        "opportunities": [{"email_id": "id003", "from_": "jobs@company.com",
                           "subject": "New role posted", "reason": "ML role",
                           "confidence": 0.8}],
        "sales": [],
        "uncategorized": []
    })
    with patch("agents.email_triage.notify_error"):
        with patch("agents.email_triage.list_recent_emails",
                   return_value=FAKE_EMAILS):
            with patch.object(EmailTriageAgent, "call_claude",
                              return_value=dropped_json):
                agent = _make_agent()
                result = agent.execute()

                assert agent._eval_results, "eval results should be populated"
                failed = [r for r in agent._eval_results if not r["passed"]]
                assert failed, "expected at least one failing check"
                assert any(r["check"] == "conservation" for r in failed)
                assert result.metadata["eval_passed"] is False


def test_malformed_json_raises_exception():
    # The error path posts the raw response to agent-logs via notify_error;
    # mock it so the offline test never reaches the real Discord webhook.
    with patch("agents.email_triage.notify_error") as mock_notify:
        with patch("agents.email_triage.list_recent_emails",
                   return_value=FAKE_EMAILS[:1]):
            with patch.object(EmailTriageAgent, "call_claude",
                              return_value="this is not json at all"):
                agent = _make_agent()
                # A parse failure must propagate so base.py run() marks the run
                # as error rather than posting garbage.
                with pytest.raises(Exception):
                    agent.execute()
                # And the failure must have been reported to agent-logs.
                mock_notify.assert_called_once()


def test_discord_content_is_not_empty():
    two_email_json = json.dumps({
        "urgent": [{"email_id": "id001", "from_": "boss@work.com",
                    "subject": "Urgent meeting", "reason": "Needs response today",
                    "confidence": 0.95}],
        "opportunities": [{"email_id": "id003", "from_": "jobs@company.com",
                           "subject": "New role posted", "reason": "ML role",
                           "confidence": 0.8}],
        "sales": [],
        "uncategorized": []
    })
    with patch("agents.email_triage.notify_error"):
        with patch("agents.email_triage.list_recent_emails",
                   return_value=[FAKE_EMAILS[0], FAKE_EMAILS[2]]):
            with patch.object(EmailTriageAgent, "call_claude",
                              return_value=two_email_json):
                agent = _make_agent()
                result = agent.execute()

                assert isinstance(result.content, str)
                assert result.content.strip()
                lowered = result.content.lower()
                assert "urgent" in lowered or "opportunities" in lowered


def test_code_fence_stripped_before_parse():
    fenced_json = f"```json\n{VALID_TRIAGE_JSON}\n```"
    with patch("agents.email_triage.notify_error"):
        with patch("agents.email_triage.list_recent_emails",
                   return_value=FAKE_EMAILS):
            with patch.object(EmailTriageAgent, "call_claude",
                              return_value=fenced_json):
                agent = _make_agent()
                result = agent.execute()  # must not raise despite the fences

                assert result.structured_output is not None
