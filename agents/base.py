from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid
import os

from anthropic import Anthropic
from supabase import create_client, Client
import voyageai
from dotenv import load_dotenv
from integrations.discord_notify import notify, notify_error

load_dotenv()


@dataclass
class AgentResult:
    content: str                          # markdown-formatted output
    metadata: dict = field(default_factory=dict)  # can store extra any data


class BaseAgent(ABC):
    """
    Abstract base class for all Swiss Guard agents.

    Every agent inherits from this and implements two things:
      - agent_id: a unique string identifier e.g. 'email-triage'
      - execute(): the actual logic that produces an AgentResult

    Everything else — logging runs, saving memory, calling Claude,
    retrieving past context — is handled here.
    """

    def __init__(self):
        self.anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        )
        self.voyage = voyageai.Client(api_key=os.getenv("VOYAGE_API_KEY"))

    # ── Abstract interface ─────────────────────────────────────────────────────

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Unique slug for this agent. e.g. 'email-triage'"""
        pass

    @abstractmethod
    def execute(self) -> AgentResult:
        """
        Agent-specific logic lives here.
        Fetch data, call Claude, return an AgentResult.
        """
        pass

    # ── Orchestrator entry point ───────────────────────────────────────────────

    def run(self) -> Optional[AgentResult]:
        """
        Called by n8n (or manually). Do not override this.

        Handles:
          - Logging the run to Supabase before and after
          - Calling execute()
          - Saving output to memory
          - Catching and logging errors without crashing
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        print(f"[{self.agent_id}] Starting run {run_id[:8]}...")

        self.supabase.table("agent_runs").insert({
            "id": run_id,
            "agent_id": self.agent_id,
            "status": "running",
            "started_at": started_at,
        }).execute()

        try:
            result = self.execute()

            finished_at = datetime.now(timezone.utc).isoformat()
            latency_ms = int(
                (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at))
                .total_seconds() * 1000
            )

            self._save_output(run_id, result)
            notify(self.agent_id, result.content)

            self.supabase.table("agent_runs").update({
                "status": "success",
                "finished_at": finished_at,
                "latency_ms": latency_ms,
            }).eq("id", run_id).execute()

            print(f"[{self.agent_id}] ✓ Done in {latency_ms}ms")
            return result

        except Exception as e:
            notify_error(self.agent_id, str(e))
            self.supabase.table("agent_runs").update({
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error_message": str(e),
            }).eq("id", run_id).execute()

            print(f"[{self.agent_id}] ✗ Failed: {e}")
            raise

    # ── Helpers available to all agents ───────────────────────────────────────

    def call_claude(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
    ) -> str:
        """
        Call Claude and return the text response.

        Usage in any agent:
            output = self.call_claude(system_prompt, user_prompt)

        SECURITY — PROMPT INJECTION (deferred, implement before email-triage):
            Email/web/etc. content is attacker-controlled. Do NOT drop it raw
            into user_prompt as if it were trusted instructions. When the first
            agent that feeds external text to Claude is built, add an
            `untrusted_data` param here that wraps such content in clear
            delimiters with a "treat as data, never as instructions" guard —
            and never give an email-triggered agent write/exfil tools without a
            review step. Today the blast radius is limited (no tools wired up).
        """
        response = self.anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Concatenate every text block rather than assuming content[0] is text.
        # Non-text blocks (e.g. tool_use once tools are added) can appear first
        # or alongside text, and an empty content list would crash on [0].
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        if not text:
            raise RuntimeError(
                f"Claude returned no text content (stop_reason={response.stop_reason})"
            )
        return text

    def recall_memory(self, query: str, limit: int = 3) -> str:
        """
        Retrieve past outputs from this agent that are semantically
        relevant to the query. Injected into the prompt for continuity.

        Returns a formatted string ready to paste into a system prompt.
        Falls back to most recent outputs if embeddings aren't set up yet.
        """
        try:
            embedding = self.voyage.embed(
                [query], model="voyage-3"
            ).embeddings[0]

            results = self.supabase.rpc("match_agent_outputs", {
                "query_embedding": embedding,
                "agent_id_filter": self.agent_id,
                "match_count": limit,
            }).execute()

            if not results.data:
                return "No prior context found."

            entries = [
                f"[{r['created_at'][:10]}]\n{r['content']}"
                for r in results.data
            ]
            return "\n\n---\n\n".join(entries)

        except Exception as e:
            print(f"[{self.agent_id}] Memory retrieval failed: {e}")
            return "No prior context available."

    # ── Internal ───────────────────────────────────────────────────────────────

    def _save_output(self, run_id: str, result: AgentResult) -> None:
        """Embed the output and save it to Supabase for future memory retrieval."""
        embedding = None
        try:
            embedding = self.voyage.embed(
                [result.content], model="voyage-3"
            ).embeddings[0]
        except Exception as e:
            print(f"[{self.agent_id}] Embedding failed, saving without vector: {e}")

        self.supabase.table("agent_outputs").insert({
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "agent_id": self.agent_id,
            "content": result.content,
            "embedding": embedding,
            "metadata": result.metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()