# Architecture

## What this is
Swiss guard is a team of agents that automates daily, repetitive taks.

I am a habitual email checker. I check my email more often than I check my text messages. I rotate through my three primary emails. 
- Personal (Venmo, Job Alerts, Email subscrciptions, etc)
- Business (Job, Amazon locker, Finance updates, etc)
- School (Department notifications, grade updates, alerts, etc)

However, my emails recently have begun to get extremely cluttered. If I go on a weekend trip, or am too busy to keep up to date, they stack up fast. I start rushing through them, not absorbing any information, but clicking through them so that notification symbol goes away.

I wanted to solve this and that's exactly why I wanted to build swiss guard.

I wanted a team of agents that would go through all three of my emails, classify them, flag for importance, and summarize the dense articles, research papers, and updates I get.

Then I wanted to build more on that. I decided, if I'm already bulidng a team of agents and an information pipeline, why not integrate other services and repetitive tasks in my digital life.

So I decided to add an agent that tracks my financials, how they are moving, and key insights into what the company is doing now.

Then I decided to add an agent to track my health stats. I've always hated having to switch between Garmin and Apple health to view my actual health statistics, so why not build an Agent to compile that information and summarize what I need to know.

Overall, this project was built to explore AI agentic infrastructure, build a production level project, and automate the things in my life that I spend the most time on.

## Stack Decisions

### Agents - Anthropic SDK (Python)
I used the Anthropic SDK directly instead of a framework like LangChain. I wanted to dive into the reasoning loop and understand its intricacies. Using the SDK means I can explain every call, tool defintion, and decision the agent makes.

### Orchestration - n8n
I used n8n for scheduling and agent dependcies instead of writing my own job queue. I am most interested in what the agents do, not how jobs get queued. n8n handles retries, scheduling, and dependecy resolution so I can focus on the agent logic. It's a system used in real production systems so its trustworthy for my needs.

### Memory - Supabase + pgvector + VoyageAI
Agents are stateless by default, meaning every run starts completely blank. I built a memory layer so agents can retrieve information that is semantically relevant to past outputs before subsequent runs. Supabase handles the storages, pgvector handles the similarity search, and Voyage AI generates the embeddings. Keeping the memory in Postgres means I can query directly to understand exactly what the agent is doing and what it is retrieving.

### Dashboard - Discord (v1) -> React (v2)
For v1, I used a private Discord server instead of building out a frontend. Each agent posts to its own channel when it runs. Discord is already open every day for my work and I have it on my PC, laptop, and phone. It also requires zero frontend work, meaning I can focus all my time on the agent logic. React for v2 once the agents are solid and I want a strong portfolio demo.


## Agent Design
To-do

## Memory Design
To-do

## What I'd do differently
To-do

## Open Questions
To-do