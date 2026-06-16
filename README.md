# 🛡️ swiss_guard

> Personal AI agent workflow that automates what I really don't enjoy doing.

Swiss Guard is a multi-agent intelligence system that runs daily on a schedule, surfaces what matters, and reports into a unified dashboard. Each agent has a defined role.

---

## Agents

| Agent | Schedule | Role |
|---|---|---|
| `email-triage` | 7:00 AM | Urgent emails, grade changes, job leads, sales |
| `email-digest` | 7:15 AM | ISW summaries, research papers, article digests |
| `market-report` | 5:00 PM (weekdays) | Portfolio P&L, market context, competitor moves |
| `health-sync` | 6:30 AM | Strava activity, weekly fitness trends |
| `weekly-report` | 8:00 PM (Sunday) | Full week recap — workouts, work, opportunities |
| `job-scout` | 8:00 AM daily | New job postings from target company career pages |

---

## Stack

- **Agents** — Anthropic SDK (Claude), written in Python
- **Orchestration** — n8n (scheduling, retries, agent dependencies)
- **Memory** — Supabase (Postgres + pgvector) + Voyage AI embeddings
- **Dashboard** — Retool (v1) → React + TypeScript (v2)
- **Integrations** — Gmail, Strava, Garmin, Alpha Vantage

---

## Status

🚧 Active development — started 6/10/2026

- [x] Architecture + planning
- [x] Base agent class + memory layer
- [x] Discord server setup
- [x] Email triage + digest agents
- [x] Market report agent
- [x] Health sync agent
- [x] Job scout agent
- [ ] Weekly report agent
- [ ] React dashboard (v2)

---

## Setup

```bash
git clone https://github.com/clarktenge/swiss_guard
cd swiss_guard
cp .env.example .env
# Fill in your API keys — see docs/architecture.md
```

See [`docs/architecture.md`](docs/architecture.md) for full stack decisions and reasoning.
