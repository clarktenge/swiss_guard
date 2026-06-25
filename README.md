# 🛡️ swiss_guard

> Personal AI agent workflow that automates what I really don't enjoy doing.

Swiss Guard is a multi-agent intelligence system that runs daily on a schedule, surfaces what matters, and reports into a unified dashboard. Each agent has a defined role.

---

## Agents

| Agent | Schedule | Role |
|---|---|---|
| `email-triage` | 7:00 AM | Sorts inbox into urgent, opportunities, sales, uncategorized |
| `email-digest` | 7:15 AM | ISW summaries, research papers, article digests |
| `market-report` | 5:00 PM (weekdays) | Portfolio P&L, market context, competitor moves |
| `health-sync` | 6:30 AM | Strava activity, weekly fitness trends |
| `weekly-report` | 8:00 PM (Sunday) | Full week recap — workouts, work, opportunities |
| `job-scout` | 8:00 AM daily | New job postings from target company career pages |

---

## Stack

- **Agents** — Anthropic SDK (Claude), written in Python
- **Orchestration** — Github Actions (scheduled workflows, one per agent)
- **Memory** — Supabase (Postgres + pgvector) + Voyage AI embeddings
- **Dashboard** — Retool (v1) → React + TypeScript (v2)
- **Integrations** — Gmail, Strava, Garmin, yfinance

---

## Status

🚧 Active development — started 6/10/2026

**V1 Complete** - Finished 6/16/2026, all six agents live on daily schedule



- [x] Architecture + planning
- [x] Base agent class + memory layer
- [x] Discord server setup
- [x] Email triage + digest agents
- [x] Market report agent
- [x] Health sync agent
- [x] Job scout agent
- [x] Weekly report agent
- [x] Github Actions Scheduler
      
---

## Roadmap -v2
**v1 fixes**
- [x] email-triage: tighten urgency criteria — sales emails incorrectly flagged urgent
- [x] email-digest: JournalClub.io returns title only — investigate full body extraction
- [x] market-report: output cuts off mid-sentence — fix Discord chunking
- [x] weekly-report: review week score logic — scoring seems deflated relative to actual week

**New work**
- [x] Cost tracking — Claude API spend per agent, per week, total monthly
- [x] Data governance layer — email-triage (Pydantic + tier 1 evals live)
- [ ] Data governance rollout - remaining 5 agents
- [ ] **Agent 6 — `study-prep`** — interview prep agent for Forward Deployed/Applied AI roles (Palantir, Anduril, Onebrief). Daily vocab/concepts, twice-weekly case scenarios, weekly coding problem, biweekly SQL drill. Own Discord channel. Ships as a one-way generator first; a lightweight local reaction-listener bot may follow later for interactive grading
- [ ] React dashboard — once the above is stable

---

## Setup

```bash
git clone https://github.com/clarktenge/swiss_guard
cd swiss_guard
cp .env.example .env
# Fill in your API keys — see docs/architecture.md
```

See [`docs/architecture.md`](docs/architecture.md) for full stack decisions and reasoning.
