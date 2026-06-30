"""
Offline unit tests for the governance classification layer.

Two things are under test:

  1. agents/governance.py:classify_output() — that it returns the declared
     capability class for a known agent, and FAILS CLOSED (returns 'ACTION', the
     most restrictive class) for an agent_id nobody added to the floor table.

  2. base.py's wiring of the previously-dead governance columns — that
     _save_output() now writes both eval_passed and governance_class into the
     agent_outputs insert payload, and that run() resolves agent_runs.eval_status
     to 'no_checks' (not an error, and not a misleading 'passed') when an agent
     ran no eval checks at all.

Everything external (Supabase, Voyage, Anthropic, Discord) is mocked, so this
file is CI-safe. The pattern mirrors tests/offline/test_email_triage_governance.py:
build the agent without BaseAgent.__init__ and stub the attributes the code reads.
"""

from unittest.mock import patch, MagicMock

from agents.base import BaseAgent, AgentResult
from agents.governance import classify_output


# ── A minimal concrete agent for exercising base.py plumbing ──────────────────

class _FakeAgent(BaseAgent):
    """
    Smallest possible BaseAgent subclass. We override __init__ so it never
    constructs the real Anthropic/Supabase/Voyage clients (BaseAgent.__init__
    would), and instead drop in MagicMocks for the ones the code under test
    touches. agent_id is parameterized so a single class covers both the
    known-agent and unknown-agent cases.
    """

    def __init__(self, agent_id: str = "email-triage"):
        self._agent_id = agent_id
        self._eval_results = []          # no checks unless a test sets them
        self.supabase = MagicMock()
        self.voyage = MagicMock()        # .embed(...).embeddings[0] returns a mock
        self.anthropic = MagicMock()
        self.input_tokens = 0
        self.output_tokens = 0

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def execute(self) -> AgentResult:
        return AgentResult(content="hello world")


def _outputs_insert_payload(agent: _FakeAgent) -> dict:
    """
    Pull the dict passed to supabase.table('agent_outputs').insert(...). Because
    self.supabase is one MagicMock, every .table(...) call returns the same child
    mock, so .insert.call_args holds the agent_outputs payload (the only insert
    _save_output makes).
    """
    return agent.supabase.table.return_value.insert.call_args.args[0]


def _runs_update_payload(agent: _FakeAgent) -> dict:
    """Pull the dict passed to the agent_runs .update(...) in run()'s success path."""
    return agent.supabase.table.return_value.update.call_args.args[0]


# ── classify_output() ─────────────────────────────────────────────────────────

def test_classify_known_agent_returns_read_only():
    # Every current agent is declared READ_ONLY in the capability floor.
    result = AgentResult(content="anything")
    assert classify_output("email-triage", result) == "READ_ONLY"


def test_classify_unknown_agent_fails_closed_to_action():
    # An agent_id not in AGENT_CAPABILITY_FLOOR must default to ACTION, the most
    # restrictive class — proving the system fails closed, not open.
    result = AgentResult(content="anything")
    assert classify_output("totally-unknown-agent", result) == "ACTION"


# ── _save_output() writes the real governance columns ─────────────────────────

def test_save_output_includes_governance_class_and_eval_passed():
    agent = _FakeAgent("email-triage")
    agent._eval_results = [
        {"check": "schema_valid", "passed": True, "message": "ok"},
    ]

    agent._save_output("run-123", AgentResult(content="hello world"))

    payload = _outputs_insert_payload(agent)
    # Both previously-dead columns must now be present in the insert.
    assert "governance_class" in payload
    assert "eval_passed" in payload
    assert payload["governance_class"] == "READ_ONLY"
    assert payload["eval_passed"] is True


def test_save_output_eval_passed_is_none_when_no_checks():
    # No checks ran -> eval_passed is None (the "we never looked" value), which
    # is distinct from False ("we looked and it failed").
    agent = _FakeAgent("job-scout")
    agent._eval_results = []

    agent._save_output("run-123", AgentResult(content="hello world"))

    payload = _outputs_insert_payload(agent)
    assert payload["eval_passed"] is None


def test_save_output_eval_passed_false_when_a_check_fails():
    agent = _FakeAgent("email-triage")
    agent._eval_results = [
        {"check": "schema_valid", "passed": True, "message": "ok"},
        {"check": "conservation", "passed": False, "message": "dropped one"},
    ]

    agent._save_output("run-123", AgentResult(content="hello world"))

    assert _outputs_insert_payload(agent)["eval_passed"] is False


# ── run() resolves eval_status ────────────────────────────────────────────────

def test_run_eval_status_no_checks_when_agent_sets_none():
    # An agent that never populates self._eval_results must end with
    # eval_status='no_checks' — and crucially must NOT raise.
    agent = _FakeAgent("job-scout")
    with patch("agents.base.notify"), patch("agents.base.notify_raw"), \
            patch("agents.base.notify_error"):
        agent.run()

    payload = _runs_update_payload(agent)
    assert payload["status"] == "success"
    assert payload["eval_status"] == "no_checks"


def test_run_eval_status_passed_when_all_checks_pass():
    agent = _FakeAgent("email-triage")
    # execute() runs first and would normally set this; simulate a passing run by
    # having execute populate _eval_results.
    agent.execute = lambda: _set_results_and_return(
        agent, [{"check": "c", "passed": True, "message": "ok"}]
    )
    # run() imports log_eval_results locally with `from evals.logger import ...`,
    # which reads the attribute at call time — so patch it on evals.logger to
    # keep the non-empty-results path from hitting real Supabase.
    with patch("agents.base.notify"), patch("agents.base.notify_raw"), \
            patch("agents.base.notify_error"), \
            patch("evals.logger.log_eval_results"):
        agent.run()

    assert _runs_update_payload(agent)["eval_status"] == "passed"


def test_run_eval_status_failed_when_a_check_fails():
    agent = _FakeAgent("email-triage")
    agent.execute = lambda: _set_results_and_return(
        agent, [{"check": "c", "passed": False, "message": "bad"}]
    )
    with patch("agents.base.notify"), patch("agents.base.notify_raw"), \
            patch("agents.base.notify_error"), \
            patch("evals.logger.log_eval_results"):
        agent.run()

    assert _runs_update_payload(agent)["eval_status"] == "failed"


def _set_results_and_return(agent: _FakeAgent, results: list) -> AgentResult:
    """Helper: mimic an execute() that ran eval checks before returning."""
    agent._eval_results = results
    return AgentResult(content="hello world")
