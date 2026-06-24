# Architecture


## What it is

Swiss Guard is a set of small, single-purpose agents that run on a schedule, each
doing one job, reporting into Discord. Email triage, deep summaries, an end-of-day
market report, a health summary, a weekly recap. The design goal was to have a team of agents, each with a specific job.

## Shape of the system

```
schedule (GitHub Actions)
   → agent.run()  [base.py]
        → execute()        agent-specific: fetch data, call Claude
        → save_output()    embed + store in Supabase
        → notify           Discord webhook
```

The eval hook and the governance classifier are scaffolded but not yet wired
into `run()` — they're in-progress and don't run on the live path today.

Everything an agent shares — run logging, memory write, the governance gate, the
Discord notify, error handling — lives in `BaseAgent.run()`. Each agent only
implements `execute()`. That's the one structural decision the whole thing rests
on: the orchestration is identical across agents, so adding an agent is writing
one method, not re-wiring the plumbing. The cost is that `run()` is now the most
important code in the repo and every agent inherits its bugs. Allows me to focus on debugging one function vrs 5.

## Decisions

### Anthropic SDK directly, not a framework

I call the model through the SDK and handle the loop myself rather than using
LangChain or similar. The reason is that for a system this size, the framework
would be more code to understand than the thing it replaces. The agent loop is
fetch → prompt → parse → store. I can hold that in my head. A framework would
abstract it into machinery I'd have to learn to debug, and the abstraction would
earn its keep only if I had many more agents or much more complex control flow.
**What breaks first:** if I ever need agents calling agents calling tools in deep
chains, hand-rolling that orchestration gets painful and a framework starts
paying off. I'm nowhere near that.

### GitHub Actions for scheduling

Scheduling, retries, and "run B after A succeeds" are solved problems, and GitHub Actions
solves them with a UI I can see the state of. I didn't want to write and babysit a
cron-plus-queue system whose only job is to call my Python on time. I am more interested in the code behind the agents, not scheduling coce.
**What breaks first:** GitHub Actions is a separate service to keep running, and the coupling
between "GitHub Actions knows the schedule" and "the code knows what to do" means the
schedule lives outside the repo. If that split ever causes a drift bug, or if I
want the whole thing to deploy as one unit, I'd pull scheduling into the codebase
(APScheduler or a simple queue worker). For now the visibility GitHub Actions gives me is
worth the extra moving part.

### Supabase (Postgres) + pgvector for memory and state

One database holds everything: agent runs, outputs, the vector embeddings for
memory, holdings, approvals. The reason is consolidation, my memory is embeddings attached to outputs attached to runs.
Keeping vectors in the same database as the relational data means "find me
similar past summaries and their run metadata" is one query, not a join across two
systems. A dedicated vector store (Pinecone, etc.) would be a second system to
sync and would buy me better recall at a scale I'm thousands of records away from.
**What breaks first:** the `ivfflat` vector index trades exactness for speed. At a
few hundred outputs, recall is effectively perfect. Into the tens of thousands,
I'd need to tune `lists`/`probes` or move to `hnsw`, and eventually a specialized
store. That's the first thing that cracks but it cracks slowly and visibly, so
I'll see it coming in the delta evals before it's a real problem.

### Voyage for embeddings

Better retrieval quality than the obvious alternatives for the price, and a free
tier that vastly exceeds what this project will use. No deeper reason. It's the
embedding provider, it's plumbing, the interesting decisions are upstream of it.
**What breaks first:** changing embedding models invalidates every stored vector,
since old and new vectors live in different spaces. A model swap means re-embedding
the whole table. Cheap now, gets expensive as history grows. If i want to change it, its a thing to do early.

### Discord instead of a dashboard, for v1

The output of these agents is mostly text that I want to be able to glance at on my phone. Discord
gives me push notifications, a channel per agent, and zero frontend code. A
dashboard would be a portfolio piece but a worse daily tool, and I'd be building UI
instead of agents. I switched from a bot to webhooks after realizing a bot means a
persistent connection and login-per-message rate limits for what is fundamentally
one-way notification. Webhooks are an HTTP POST, which is the shape of the
problem. **What breaks first:** Discord can't show charts or let me approve a DRAFT
with a button. The moment governance needs real interactive approval, or the market
report wants a graph, the webhook model runs out and I build the React dashboard
(v2). 

### Numbers computed in Python, never by the model

Across market-report and health-sync, every quantitative field is computed in code
and only the qualitative narrative comes from Claude. This is the decision I'd
defend hardest. An LLM reading prices and writing "you're up $340" is a liability.
It'll be confidently wrong at some rate. Python computing $340 and the model
explaining the *why* around it cannot be arithmetically wrong. It also cleanly
separates failure domains: a wrong number is a code bug, a wrong story is a prompt
problem, and I always know which kind of failure I'm looking at.

## How I know it's working

The eval layer (see `docs/evals/`) is what turns "it ran" into "it ran correctly."
Two tiers: deterministic checks that don't need a model (schema validity, every
input email accounted for, the arithmetic reconciles) and a narrow LLM judge for
the things assertions can't reach (is this summary faithful, is this "urgent"
actually urgent). Results write to a record keyed per run, so I get a trend line.
That trend is the real asset as the individual outputs are disposable, but the
record of how well the system has been doing is the thing I'd protect and the thing
that tells me whether a change helped or hurt.

## What I'd do next

In rough order of value: finish converting every agent to structured + validated
output; make the email-digest memory actually produce deltas and prove it in the
eval; build the DRAFT approval flow once I have an agent that needs it; then the
React dashboard when Discord's lack of interactivity actually starts costing me.
Notably *not* on this list: a framework, a rules engine, a second datastore, or
anything else that solves a problem I don't have yet. The discipline is keeping the
system as small as the job requires and no smaller.
