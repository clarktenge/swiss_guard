from agents.base import BaseAgent, AgentResult

class TestAgent(BaseAgent):
    @property
    def agent_id(self):
        return "test"

    def execute(self):
        return AgentResult(content="swiss_guard is alive")

agent = TestAgent()
agent.run()