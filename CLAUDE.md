# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Swiss Guard is a personal multi-agent system. Six single-purpose agents run on a
schedule (GitHub Actions), each fetch some data, ask Claude for the qualitative
part, and post a report to a per-agent Discord channel. State, memory, and eval
results live in one Supabase (Postgres + pgvector) database. Read
`docs/architecture.md` and `docs/governance.md` for the reasoning behind the
design — they are the source of truth for *why*, and the decisions there
("numbers in Python, narrative from Claude"; SDK not a framework; fail-closed
governance) are load-bearing, not incidental.

## Project conventions
- All agents inherit from BaseAgent in agents/base.py
- execute() is the only method each agent implements
- Structured output via Pydantic schemas in agents/schemas.py
- Eval checks in evals/checks.py, results logged via evals/logger.py
- Never touch live agent files without explicit instruction
- Never read .env

## Current state
- Governance Phase 2 complete on: email_triage, email_digest, 
  health_sync, market_report, weekly_report
- job_scout governance not yet implemented
- React dashboard not yet built

## Testing rules
- Offline tests live in tests/offline/ — safe to run with pytest
- Live tests live in tests/live/ — require real credentials, never 
  run in CI
- Always mock notify_error, list_recent_emails, call_claude in 
  offline tests

## Do not touch
- venv/
- .env
- Any live agent during a refactor pass unless explicitly asked

## Commands

```bash
# Run an agent end-to-end (the path GitHub Actions uses): hits Gmail/Strava/etc.,
# calls Claude, logs to Supabase, posts to Discord. Needs a populated .env.
python -c "from agents.email_triage import EmailTriageAgent; EmailTriageAgent().run()"

# Preview a single agent WITHOUT side effects: most agents have a __main__ block
# that calls execute() only — hits external data + Claude but skips run()'s
# Supabase logging, Discord post, and Voyage embedding.
python agents/email_triage.py

# Offline tests — fully mocked (no Gmail/Claude/Supabase/Voyage/Discord), free,
# CI-safe. This is the default test suite. Run a single file or test:
pytest tests/offline/
pytest tests/offline/test_email_triage_governance.py
pytest tests/offline/test_email_triage_governance.py::test_name

# Weekly Claude-cost summary from agent_runs (reads Supabase; run from repo root):
python scripts/cost_report.py
```

`tests/live/` are **manual smoke tests that cost money and have side effects**
(real Voyage embeddings, Supabase inserts, Discord posts). Several are bare
scripts that execute on import rather than pytest functions — do not point `pytest`
at `tests/live/`. Only run them deliberately.

There is no build step or linter configured. Target runtime is Python 3.12 (see
the workflows). Dependencies: `pip install -r requirements.txt`.

## Architecture

### The one structural decision: `BaseAgent.run()` is the template, `execute()` is the agent

`agents/base.py` holds *all* shared orchestration. Every agent subclasses
`BaseAgent` and implements only two things: the `agent_id` property and
`execute() -> AgentResult`. `run()` wraps `execute()` and does everything else:
inserts the `agent_runs` row, accumulates token usage / estimated cost, saves the
output (embedded into `agent_outputs` for memory), persists eval results, posts to
Discord, and records success/error. **Do not override `run()`.** This means
`run()` is the highest-leverage and highest-blast-radius code in the repo — a bug
there hits every agent.

Adding an agent = write one `execute()` method, add a Discord webhook mapping in
`integrations/discord_notify.py` (`AGENT_WEBHOOK_MAP`), and add a workflow under
`.github/workflows/`. No plumbing to re-wire.

### `AgentResult` is the contract between `execute()` and `run()`

- `content` — markdown posted to Discord and saved to memory.
- `structured_output` — typed dict (a Pydantic `model_dump()`) saved to
  `agent_outputs.structured_output` so the eval layer has typed data to assert on.
- `embed` / `followup` — optional Discord presentation (rich card; long
  plain-text tail that won't fit an embed field).

### Numbers in Python, narrative from Claude

For any quantitative agent (market-report, health-sync, weekly-report) **every
numeric field is computed in Python**; Claude only writes the `narrative`. The
Pydantic schemas in `agents/schemas.py` document this per-field. Never let the
model produce a number that an eval check then has to trust — compute it, and
have the model explain it. The Tier 1 numeric-consistency checks exist to catch
the totals and their source list drifting apart.

### Structured output + evals ("governance")

The agents are being migrated from free-form markdown to a structured pipeline:
Claude returns JSON → validate into a Pydantic model (`agents/schemas.py`) → run
deterministic Tier 1 checks (`evals/checks.py`) → render the validated object to
the same Discord markdown. The agent stashes check results on
`self._eval_results` during `execute()`; `run()` persists them via
`evals/logger.py` into the `eval_results` table. A validation failure should
`raise` so `run()` marks the run `error` rather than posting garbage.

What the commits/README call "governance rollout" is this structured+eval
migration reaching each agent. The *full* governance gate described in
`docs/governance.md` (capability floor, action-class classifier, approvals
precondition) is intentional scaffolding for when an agent first takes an external
action — it is **not yet wired into `run()`**. All current agents are READ_ONLY.

### Prompt-injection boundary

Email/web content is attacker-controlled. Never concatenate it into the trusted
`user_prompt`. Pass it through `call_claude(..., untrusted_data=...)`, which fences
it with a "treat as data, never instructions" guard. `email_triage._sanitize_email`
additionally scrubs quotes/control chars from sender/subject/snippet, and the
triage prompt now asks Claude to return *decisions only* (ids + reason), not to
echo attacker text back — the human-facing fields are reconstructed in Python from
the original fetch. Keep that pattern when handling external text.

### Memory

`recall_memory(query)` embeds the query with Voyage (`voyage-3`) and calls the
`match_agent_outputs` Supabase RPC for semantically similar past outputs of the
*same* agent, formatted for pasting into a system prompt. It fails soft (returns
a "no context" string) — there is no most-recent-outputs fallback. Note: changing
the embedding model invalidates every stored vector (old/new live in different
spaces) and requires re-embedding the table.

### Integrations & config

- `integrations/` — one module per external service (gmail, strava, garmin,
  stocks/yfinance, job_boards, discord_notify). Discord uses **per-channel
  webhooks**, not a bot; messages are chunked under Discord's char limit.
- `config/companies.py` — job-scout target companies. `ats` field routes to a
  fetch strategy (greenhouse/lever/ashby JSON APIs, or `custom` → host-based
  dispatch in `integrations/job_boards.py`). For which custom career portals are
  crackable vs. hard Cloudflare-blocked and the technique per platform, see the
  `job-scout-blocked-portals` memory before re-investigating any custom host.
- `db/` — `schema.sql` plus numbered `migration_00N.sql`. Core tables:
  `agent_runs`, `agent_outputs` (with `embedding` vector + `structured_output`
  jsonb), `eval_results`, `holdings`, `approvals`.

## Conventions

- The model is `claude-sonnet-4-6`, set in `base.py:call_claude`. The cost
  constants there (`SONNET_*_COST_PER_MTOK`) must stay in sync with that model.
- Cost/token accounting accumulates across *all* `call_claude` calls in a run
  (some agents make several chunked calls), so always go through `call_claude`
  rather than calling `self.anthropic` directly — otherwise tokens go untracked.
- Output is emoji-heavy; direct-run `__main__` blocks call
  `sys.stdout.reconfigure(encoding="utf-8")` because the default Windows console
  (cp1252) crashes on it. Keep that when adding a direct-run harness.
- Secrets come from `.env` (see `.env.example`); in CI they come from GitHub
  Actions secrets, wired per-workflow. `credentials.json` / `token.json` are
  gitignored.
