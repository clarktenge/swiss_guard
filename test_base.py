# ─────────────────────────────────────────────────────────────────────────────
# ⚠️  LIVE smoke test — NOT a free/offline unit test. Run manually only.
# Running this hits real services, COSTS MONEY, and has side effects:
#   • generates a Voyage AI embedding (billed)
#   • inserts rows into Supabase (agent_runs + agent_outputs)
#   • posts to your Discord webhook
# ─────────────────────────────────────────────────────────────────────────────
from agents.base import BaseAgent, AgentResult

class TestAgent(BaseAgent):
    @property
    def agent_id(self):
        return "test"

    def execute(self):
        return AgentResult(content="swiss_guard is alive")

agent = TestAgent()
agent.run()