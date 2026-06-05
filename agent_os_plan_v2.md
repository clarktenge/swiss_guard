# Personal Agent OS — Project Plan v2
### Focus: Agent architecture, memory, and deployment. Use good tools for everything else.

---

## The Philosophy

Your data science background already covers the AI fundamentals.
The gap you're filling is: how do agents actually get built, deployed, and evaluated?

**You own:** Agent logic, system prompts, tool definitions, memory design, context passing, eval criteria.
**Tools own:** Scheduling, database, embeddings, dashboard scaffolding, deployment.

Every decision in this stack follows one rule: does building this myself teach me something
about agents? If no, use the best available tool and move on.

---

## Tech Stack

### Agent Layer — where your time goes
| Piece             | Choice                  | Why                                                                 |
|-------------------|-------------------------|---------------------------------------------------------------------|
| LLM               | Anthropic SDK (direct)  | Clean, low abstraction, you see exactly what happens in every call  |
| Agent logic       | You write this          | The prompts, tools, and decision logic are the whole point          |
| Tool definitions  | You write these         | Defining what an agent can do is core agent architecture            |
| Memory design     | You design this         | Context passing between agents and across sessions = the real skill |

No LangChain. No CrewAI. The Anthropic SDK is clean enough that you don't need a wrapper,
and using one would hide the parts you're trying to understand.

### Infrastructure — get out of your way
| Piece             | Choice                  | Why                                                                 |
|-------------------|-------------------------|---------------------------------------------------------------------|
| Orchestration     | n8n (cloud)             | Visual workflow tool used in real production systems. Handles        |
|                   |                         | scheduling, retries, error handling. You focus on agents, not       |
|                   |                         | job queue plumbing.                                                 |
| Database          | Supabase (Postgres)     | Real SQL, pgvector built in, free tier, you own your data           |
| Vector storage    | pgvector extension      | Semantic memory lives in the same DB as everything else             |
| Embeddings        | Voyage AI API           | Best retrieval quality, simple API, designed for this use case      |
| Secrets           | .env + Supabase vault   | Keep keys out of git                                                |

### Dashboard
| Version           | Choice                  | Why                                                                 |
|-------------------|-------------------------|---------------------------------------------------------------------|
| v1 (weeks 1–3)    | Retool                  | Internal dashboard builder used at real companies. Ship in hours,   |
|                   |                         | not days. Lets you focus on agents while still having a real UI.    |
| v2 (weeks 4–6)    | React + TypeScript      | Once agents are solid, rebuild the dashboard as the portfolio piece |
|                   | + Tailwind + Recharts   | with real charts, design, and interactivity.                        |

### Integrations
| Service           | Method                  | Notes                                                               |
|-------------------|-------------------------|---------------------------------------------------------------------|
| Gmail             | Google OAuth + API      | Covers primary account. Route other addresses via Gmail forwarding  |
|                   |                         | with labels — agent filters by label.                              |
| Google Calendar   | Google Calendar API     | Same OAuth flow as Gmail                                            |
| Strava            | Strava OAuth API        | One-time setup, straightforward                                     |
| Garmin            | Garmin Health API       | Requires developer account (free). Worth setting up in week 4.     |
| Apple Health      | XML export → Supabase   | Export weekly, upload to Supabase storage, agent parses it         |
| Stock data        | Alpha Vantage (free)    | 25 req/day on free tier — enough for daily reports                 |

---

## The Agents

### Agent 1 — Email Triage
**Runs:** 7:00 AM daily via n8n
**What it does:**
- Scans last 24 hrs across all accounts (via Gmail labels)
- Flags urgent / time-sensitive emails
- Detects grade changes and calculates GPA impact
- Surfaces job and research opportunities
- Finds sales, drops, and discounts from subscribed brands

**What you'll learn building it:**
- How to write a system prompt that produces structured, reliable output
- How to define Gmail as a tool the agent can use
- How to handle variable-length context (100 emails vs 10)

---

### Agent 2 — Email Digest
**Runs:** 7:15 AM daily via n8n (after triage completes)
**What it does:**
- Deep summaries of ISW (Institute for the Study of War) emails
- Paragraph-length digests of research papers and articles
- Pulls prior ISW summaries from memory for continuity

**What you'll learn building it:**
- Memory retrieval — how to give an agent context from prior sessions
- Agent dependencies — how to make one agent wait for another
- Long-form summarization prompting

---

### Agent 3 — Market Report
**Runs:** 5:00 PM weekdays via n8n
**What it does:**
- Pulls your portfolio from Supabase
- Fetches live quotes and news via Alpha Vantage
- Synthesizes P&L, competitor moves, macro context, forward signals

**What you'll learn building it:**
- Tool chaining — agent calls API, gets data, passes to Claude for synthesis
- Structured output — getting Claude to return data your dashboard can render
- Grounding — how to keep an LLM report anchored to real numbers

---

### Agent 4 — Health Sync
**Runs:** 6:30 AM daily via n8n
**What it does:**
- Pulls last 7 days of activities from Strava
- Summarizes yesterday, week volume, recovery signals
- Compares week-over-week

**What you'll learn building it:**
- Working with numeric/structured data before sending to LLM
- How much pre-processing you should do vs. letting Claude handle it

---

### Agent 5 — Weekly Report
**Runs:** 8:00 PM Sunday via n8n
**What it does:**
- Workouts completed vs. planned
- Email volume and themes
- Academic activity from email parsing
- Opportunities pipeline from the week
- Week score + next week priorities

**What you'll learn building it:**
- Multi-source aggregation — pulling from multiple prior agent outputs
- How memory compounds — this agent reads the week's outputs, not raw data

---

## Memory Design

This is one of the most important things you'll learn in this project.

**The problem:** By default, every agent run starts with a blank slate. Claude has no idea
what happened yesterday. That makes summaries generic and misses continuity.

**The solution:** After every run, save the agent's output to Supabase with a vector embedding.
Before the next run, retrieve semantically relevant past outputs and inject them into the prompt.

**Why this matters for your career:** Stateful agents that can learn from their own history
are fundamentally more capable than stateless ones. Understanding how to design this memory
layer — what to store, how to retrieve it, when to inject it — is a genuine skill gap in
most early-career practitioners.

**Stack:** Supabase (Postgres) + pgvector + Voyage AI embeddings

---

## What You Should NOT Build Yourself

Be intentional about this. These things exist, work well, and building them from scratch
teaches you nothing about agents:

- A job scheduler (use n8n)
- A vector database (use pgvector in Supabase)
- An embedding model (use Voyage AI API)
- A dashboard UI in week 1 (use Retool)
- OAuth flows (use Google's official library)
- A REST API framework (use Express if you need one, or n8n webhooks)

---

## Roadmap

### Before 6/10 — Repo & Setup (This Week)
This is the week for decisions, not code.

- [ ] Create GitHub repo (see section below)
- [ ] Write a one-page architecture doc in the repo — your decisions and why
- [ ] Sign up for: Supabase, n8n cloud (free tier), Voyage AI, Alpha Vantage
- [ ] Set up Google Cloud project, enable Gmail + Calendar APIs, get OAuth credentials
- [ ] Set up Strava developer app, get client ID + secret
- [ ] Write your `.env.example` with every key you'll need

**Why this matters:** Starting a project with clear decisions and accounts ready means
your first coding session is productive instead of spent on setup. The architecture doc
also forces you to articulate your decisions before you build them.

---

### Week 1 (6/10) — Foundation + Email Triage Agent
**Goal:** One real agent running end-to-end, outputting to Retool dashboard.

- [ ] Initialize project structure (Node.js + TypeScript or Python — your choice)
- [ ] Connect Supabase — schema for agent runs, outputs, memory
- [ ] Enable pgvector extension in Supabase
- [ ] Set up Voyage AI embeddings helper function
- [ ] Write `BaseAgent` class — the pattern every agent follows
- [ ] Build Gmail integration — authenticate, list emails, fetch content
- [ ] Build `email-triage` agent — system prompt, tool definition, output structure
- [ ] Set up n8n workflow to run it at 7 AM
- [ ] Build Retool dashboard — one table showing agent runs and outputs

**Milestone:** Wake up on 6/11 or 6/12, check your phone, see the triage output was generated.

---

### Week 2 (6/17) — Memory + Email Digest
**Goal:** Agents with memory. Digest depends on triage output.

- [ ] Build memory save function — embed output, store in pgvector
- [ ] Build memory retrieval function — semantic search over prior outputs
- [ ] Update email-triage to save output to memory after each run
- [ ] Build `email-digest` agent — reads memory, calls Gmail for full content
- [ ] Configure n8n dependency — digest only runs after triage succeeds
- [ ] Expand Retool dashboard — show both agents, output viewer panel

**Milestone:** Email digest references and builds on yesterday's ISW summary.

---

### Week 3 (6/24) — Financial Agent + Portfolio UI
**Goal:** End-of-day market report with your real holdings.

- [ ] Add holdings table to Supabase
- [ ] Build Alpha Vantage integration
- [ ] Build `market-report` agent — tool chaining, structured output
- [ ] Set up n8n 5 PM weekday schedule
- [ ] Add portfolio CRUD to Retool — add/remove positions
- [ ] Finance tab in dashboard showing latest report

**Milestone:** 5 PM report lands in dashboard with real P&L and market context.

---

### Week 4 (7/1) — Health Agent + External APIs
**Goal:** Strava and Garmin data flowing into the system.

- [ ] Set up Strava OAuth + refresh token handling
- [ ] Build `health-sync` agent — activities, weekly volume, trends
- [ ] Set up Garmin API (or Apple Health XML fallback)
- [ ] n8n 6:30 AM schedule
- [ ] Health tab in Retool with activity charts

**Milestone:** Morning dashboard shows last night's sleep + yesterday's workout.

---

### Week 5 (7/8) — Weekly Report + React Dashboard v1
**Goal:** Full agent suite running. Start the portfolio-quality frontend.

- [ ] Build `weekly-report` agent — aggregates all prior agent outputs from memory
- [ ] Scaffold React dashboard — Vite + TypeScript + Tailwind
- [ ] Port agent status grid from Retool to React
- [ ] Port run history and output viewer
- [ ] Wire to your Supabase directly or via a thin API layer

---

### Week 6 (7/15) — Polish, Evals, Documentation
**Goal:** Something you'd be proud to show in an interview.

- [ ] Add output feedback (thumbs up/down per agent output) — this is your eval signal
- [ ] Build a simple eval view — agent success rate, avg latency, feedback trend
- [ ] Write `docs/architecture.md` — your decisions, why, what you'd change
- [ ] Record a 3-minute demo video walking through the system
- [ ] Clean up the GitHub repo — good README, setup instructions, example outputs

**Milestone:** System is fully documented, running daily, and ready to demo.

---

## GitHub Repo — Yes, Start It Now

**Start the repo this week, before you write a single line of code.** Here is why:

1. **Commit history tells a story.** An interviewer who sees commits from 6/7 through 7/20
   sees someone who planned deliberately and built iteratively. That matters.

2. **The architecture doc is a deliverable.** Writing down your decisions before you build
   them forces clarity and gives you something to reference in interviews.

3. **Issues as a backlog.** Use GitHub Issues for your feature list. One issue per agent,
   one per integration. It looks like real engineering process.

4. **README as resume.** A well-written README with an architecture diagram and demo GIF
   is the first thing a recruiter or hiring manager sees.

### Suggested repo structure

```
personal-agent-os/
│
├── README.md                  ← Architecture overview, demo GIF, setup guide
├── .env.example               ← Every key documented, no values
├── .gitignore
│
├── docs/
│   ├── architecture.md        ← Your decisions and why (write this first)
│   ├── agents.md              ← Spec for each agent
│   └── memory.md              ← How the memory layer works
│
├── agents/
│   ├── base.ts                ← BaseAgent class
│   ├── email-triage.ts
│   ├── email-digest.ts
│   ├── market-report.ts
│   ├── health-sync.ts
│   └── weekly-report.ts
│
├── memory/
│   ├── store.ts               ← Save output + embedding to Supabase
│   └── retrieve.ts            ← Semantic search over prior outputs
│
├── integrations/
│   ├── gmail.ts
│   ├── strava.ts
│   ├── stocks.ts
│   └── garmin.ts
│
├── db/
│   └── schema.sql             ← Supabase schema, runnable SQL
│
└── dashboard/                 ← React app (starts week 5)
    └── src/
```

### What to commit this week (before 6/10)

- `README.md` — project overview, what you're building, why
- `docs/architecture.md` — your stack decisions and reasoning
- `.env.example` — all keys stubbed out
- `db/schema.sql` — your Supabase schema
- GitHub Issues — one per agent, one per integration

That's a real project start. Not a blank repo with "initial commit."

---

## Language Choice — Python or TypeScript?

Given your data science background, Python is likely more natural. Here is the honest tradeoff:

**Python:**
- You already know it
- Native home for data work, great libraries
- Anthropic SDK is excellent in Python
- Slightly more friction for the React dashboard (separate repo/language)

**TypeScript:**
- Same language across agents and dashboard
- Slightly stronger typing for complex agent output shapes
- Less natural if your Python instincts are strong

**Recommendation:** Use Python for the agents, TypeScript for the dashboard.
They're separate concerns. Use the language that gets out of your way for each.

---

## What This Demonstrates to Onebrief

When you can walk through this system in an interview, you can speak to:

- **Agent architecture** — why you structured agents as you did, what the base class enforces
- **Memory design** — why semantic retrieval matters vs. just recency, what you store and why
- **Orchestration** — what n8n handles and why you didn't reinvent it (this shows judgment)
- **Evaluation** — how you know if an agent is working well, your feedback loop
- **Production thinking** — scheduling, failure handling, logging, secrets management

That's the conversation Onebrief wants to have. Every piece of this project earns you
something to say in that conversation.
EOF
