"""
Offline unit tests for the governance-wired email-digest agent.

These exercise execute()'s structured-output path — JSON parsing into
DigestOutput, the Tier 1 eval checks, and the Discord markdown rendering — with
every external dependency mocked. No Gmail, Claude, Supabase, Voyage, or Discord
calls happen here, so this file is safe for CI.

The pattern mirrors test_email_triage_governance.py: build the agent with
__new__ (skips BaseAgent.__init__, which would construct the API clients), stub
the attributes execute() touches, patch the module-level list_recent_emails and
get_email_body, and patch call_claude on the class.
"""

import json

import pytest
from unittest.mock import patch, MagicMock

from agents.email_digest import EmailDigestAgent
from agents.schemas import DigestOutput
from evals.checks import (
    check_digest_delta_validity,
    check_digest_summaries_not_empty,
)


# ── Fake data ────────────────────────────────────────────────────────────────

FAKE_EMAILS = [
    {"id": "id001", "from": "newsletter@understandingwar.org",
     "subject": "Russian Offensive Campaign Assessment",
     "snippet": "ISW situation report"},
    {"id": "id002", "from": "alerts@arxiv.org",
     "subject": "New paper on transformer scaling",
     "snippet": "arXiv research digest"},
]

VALID_DIGEST_JSON = json.dumps({
    "isw": [{
        "email_id": "id001",
        "title": "Russian Offensive Campaign Assessment",
        "summary": "ISW reports incremental Russian gains near the eastern front "
                   "with no major breakthroughs in the last 24 hours.",
        "is_delta": True,
        "delta_basis": "2026-06-20",
    }],
    "research": [{
        "email_id": "id002",
        "title": "New paper on transformer scaling",
        "summary": "A new arXiv paper finds compute-optimal scaling holds beyond "
                   "prior parameter regimes using a revised loss-fit method.",
        "is_delta": False,
        "delta_basis": None,
    }],
})


def _make_agent() -> EmailDigestAgent:
    """
    Build an EmailDigestAgent without running BaseAgent.__init__ (which would
    spin up the Anthropic/Supabase/Voyage clients). Stub the attributes that
    execute() and the run() eval hook read.
    """
    agent = EmailDigestAgent.__new__(EmailDigestAgent)
    agent._eval_results = []
    agent.supabase = MagicMock()
    agent.voyage = MagicMock()
    agent.anthropic = MagicMock()
    # recall_memory hits Voyage/Supabase; stub it to a trusted-context string.
    agent.recall_memory = MagicMock(return_value="No prior context found.")
    return agent


# ── Tests ────────────────────────────────────────────────────────────────────

def test_valid_json_parses_into_digest_output():
    with patch("agents.email_digest.notify_error"):
        with patch("agents.email_digest.list_recent_emails",
                   return_value=FAKE_EMAILS):
            with patch("agents.email_digest.get_email_body",
                       return_value="full email body text"):
                with patch.object(EmailDigestAgent, "call_claude",
                                  return_value=VALID_DIGEST_JSON):
                    agent = _make_agent()
                    result = agent.execute()

                    assert result.structured_output is not None
                    assert result.metadata["isw_count"] == 1
                    assert result.metadata["research_count"] == 1
                    assert result.metadata["delta_count"] == 1
                    assert result.metadata["eval_passed"] is True
                    # The 🔄 indicator marks the is_delta item in the markdown.
                    assert "🔄" in result.content


def test_is_delta_true_with_null_basis_fails_delta_validity():
    output = DigestOutput.model_validate({
        "isw": [{
            "email_id": "id001",
            "title": "Claimed update with no basis",
            "summary": "This summary asserts it is a delta but names no prior.",
            "is_delta": True,
            "delta_basis": None,
        }],
        "research": [],
    })
    passed, msg = check_digest_delta_validity(output)
    assert passed is False
    assert "Claimed update with no basis" in msg


def test_empty_summary_fails_summaries_not_empty():
    output = DigestOutput.model_validate({
        "isw": [],
        "research": [{
            "email_id": "id002",
            "title": "Paper with no summary",
            "summary": "too short",  # under the 20-char threshold
            "is_delta": False,
            "delta_basis": None,
        }],
    })
    passed, msg = check_digest_summaries_not_empty(output)
    assert passed is False
    assert "Paper with no summary" in msg


def test_malformed_json_raises_exception():
    # The error path posts the raw response to agent-logs via notify_error;
    # mock it so the offline test never reaches the real Discord webhook.
    with patch("agents.email_digest.notify_error") as mock_notify:
        with patch("agents.email_digest.list_recent_emails",
                   return_value=FAKE_EMAILS):
            with patch("agents.email_digest.get_email_body",
                       return_value="full email body text"):
                with patch.object(EmailDigestAgent, "call_claude",
                                  return_value="this is not json at all"):
                    agent = _make_agent()
                    # A parse failure must propagate so base.py run() marks the
                    # run as error rather than posting garbage.
                    with pytest.raises(Exception):
                        agent.execute()
                    mock_notify.assert_called_once()
