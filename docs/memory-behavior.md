# Memory that changes behavior

The memory layer currently retrieves prior outputs and injects them into the
prompt (`recall_memory()` in `base.py`, backed by pgvector and the
`match_agent_outputs` SQL function). That's retrieval. It is not yet *use*. An
agent that pulls yesterday's summary into context but writes today's output the
same way it would have anyway has memory in the way a packrat has an archive —
present, not load-bearing.

This document is about the difference between an agent that *has* context and an
agent whose *behavior changes* because of it.

## The test for whether memory is real

Here's the bar I'm holding the memory layer to: if I delete the memory and rerun
the agent, the output should be meaningfully different. If it's the same, the
memory wasn't doing anything and I should stop paying the retrieval cost. Every
memory feature below is designed so that this test passes — removing memory
visibly degrades the output.

## email-digest: deltas instead of re-summaries

This is the clearest case. ISW publishes daily, and the reports are continuous —
today's developments build on yesterday's. The naive agent summarizes each day's
report in isolation. The memory-using agent should recognize that it summarized a
related report yesterday and produce *what changed* rather than restating
everything.

How it works:
1. Before summarizing, the agent retrieves its most recent ISW summaries scoped
   to ISW specifically (not just "recent outputs" — the retrieval is filtered by
   source so a research-paper summary doesn't pollute ISW context).
2. The prompt explicitly instructs: if today's report covers a situation the
   prior summary already established, write the *delta* — what advanced, what
   reversed, what's new — and mark `is_delta = true` with a pointer to the prior
   output it built on.
3. If the report is genuinely new ground, summarize fresh and mark
   `is_delta = false`.

The output schema carries `is_delta` and `delta_basis` precisely so the eval can
verify the agent isn't *claiming* continuity it didn't use. That's the loop:
memory changes behavior (deltas), the schema records that it did, the eval
confirms the claim is real.

## scoped retrieval, not "recent stuff"

The current `recall_memory()` falls back to most-recent outputs when embeddings
aren't available, and otherwise does a similarity search across all of an agent's
history. That's too blunt. Two refinements:

- **Source scoping.** ISW context should retrieve ISW history, market context
  should retrieve market history. A summary's relevance is mostly determined by
  what it's *about*, and source is a strong, cheap proxy I already have in
  metadata. Filter on it before similarity ranking.
- **Recency weighting.** For continuity-driven agents, last night's summary is
  almost always more relevant than a semantically-similar one from three weeks
  ago. Pure cosine similarity doesn't know that. A light recency tiebreaker —
  prefer recent among similarly-relevant results — matches how the continuity
  actually works.

## what memory should NOT do

Worth stating, because over-memory is a real failure mode:

- It shouldn't accumulate unboundedly into the prompt. More context isn't better
  — it's more tokens, more latency, and more chance the model anchors on stale
  information. Retrieval is capped at a small number of items and scoped tightly.
- It shouldn't make the agent stateful in ways I can't inspect. Everything in
  memory is a row in `agent_outputs` I can read in plain SQL. There's no opaque
  agent state living somewhere I can't query. If I want to know why the agent did
  something, I can pull exactly the context it had.
- It shouldn't be used where it doesn't change behavior. `email-triage` doesn't
  need memory — yesterday's triage doesn't change how I categorize today's mail.
  Forcing memory onto it would be cargo-culting. Only the agents whose output
  genuinely depends on history get it.

## what breaks first

- **pgvector recall at volume.** The `ivfflat` index I'm using trades exact
  search for speed by clustering vectors into lists. At low volume (my case, a
  few hundred outputs) recall is effectively perfect. As the vector count grows
  into the tens of thousands, ivfflat starts missing relevant results unless I
  tune the `lists` and `probes` parameters, and eventually I'd move to `hnsw` or
  a dedicated vector store. But that's a problem I'm thousands of outputs away
  from, and prematurely solving it would be exactly the over-engineering I'm
  trying to avoid.
- **embedding drift.** If I change embedding models, old vectors and new ones
  live in different spaces and similarity search silently degrades. The fix is
  re-embedding the whole table on a model change. Cheap now, expensive later —
  worth knowing before it bites.
- **the recency-vs-similarity tension.** My recency weighting is a heuristic. At
  some point a genuinely-relevant old summary will lose to a recent irrelevant
  one. I'd rather have that failure (and see it in the delta eval) than not weight
  recency at all, but it's a known tradeoff, not a solved problem.

## why pgvector at all

Colocating vectors with the relational data is the whole reason. My memory isn't
just embeddings — it's embeddings attached to outputs attached to runs attached to
agents, and I query across all of that. A dedicated vector DB would mean two
systems to keep in sync and a join across a network boundary every time I want
"the summary AND its run metadata." pgvector lets me do it in one SQL query
against one database. At my scale that consolidation is worth more than the
marginal recall a specialized store would buy. The point at which that flips is
the ivfflat ceiling above — and I can see it coming.
