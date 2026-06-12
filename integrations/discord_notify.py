import os
import requests
from dotenv import load_dotenv
from typing import Optional, List

load_dotenv()

# Map agent IDs to their webhook URL env var names.
# Each channel gets its own webhook — immutable, no name-matching fragility.
AGENT_WEBHOOK_MAP = {
    "email-triage":  "DISCORD_WEBHOOK_EMAIL_TRIAGE",
    "email-digest":  "DISCORD_WEBHOOK_EMAIL_DIGEST",
    "market-report": "DISCORD_WEBHOOK_MARKET_REPORT",
    "health-sync":   "DISCORD_WEBHOOK_HEALTH_SYNC",
    "weekly-report": "DISCORD_WEBHOOK_WEEKLY_REPORT",
    "test":          "DISCORD_WEBHOOK_AGENT_LOGS",
}

DEFAULT_WEBHOOK_ENV = "DISCORD_WEBHOOK_AGENT_LOGS"
DISCORD_MAX_CHARS = 1900


def _get_webhook_url(agent_id: str) -> Optional[str]:
    """Resolve the webhook URL for a given agent. Returns None if not set."""
    env_key = AGENT_WEBHOOK_MAP.get(agent_id, DEFAULT_WEBHOOK_ENV)
    url = os.getenv(env_key)
    if not url:
        print(f"[discord] No webhook configured for '{agent_id}' (env: {env_key})")
    return url


def _chunk_message(text: str) -> List[str]:
    """
    Split a message into Discord-safe chunks under DISCORD_MAX_CHARS.
    Splits on newlines where possible, falls back to hard character
    split for lines that exceed the limit on their own.
    """
    if len(text) <= DISCORD_MAX_CHARS:
        return [text]

    chunks = []
    current = ""

    for line in text.splitlines(keepends=True):
        # If a single line is longer than the limit, hard-split it
        if len(line) > DISCORD_MAX_CHARS:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(line), DISCORD_MAX_CHARS):
                chunks.append(line[i:i + DISCORD_MAX_CHARS])
            continue

        if len(current) + len(line) > DISCORD_MAX_CHARS:
            if current:
                chunks.append(current)
            current = line
        else:
            current += line

    if current:
        chunks.append(current)

    return chunks


def _post(webhook_url: str, content: str) -> bool:
    """POST a single message chunk to a Discord webhook. Returns True on success."""
    try:
        response = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[discord] HTTP error: {e}")
        return False


def notify(agent_id: str, content: str, success: bool = True) -> None:
    """
    Send an agent output to its Discord channel via webhook.

    Usage in base.py:
        notify(self.agent_id, result.content)
    """
    webhook_url = _get_webhook_url(agent_id)
    if not webhook_url:
        return

    status = "✅" if success else "❌"
    header = f"{status} **{agent_id}**\n\n"
    chunks = _chunk_message(content)

    _post(webhook_url, header + chunks[0])

    for chunk in chunks[1:]:
        _post(webhook_url, chunk)

    print(f"[discord] Notified #{agent_id}")


def notify_error(agent_id: str, error: str) -> None:
    """Send an error notification to the agent-logs webhook."""
    webhook_url = os.getenv(DEFAULT_WEBHOOK_ENV)
    if not webhook_url:
        print("[discord] No agent-logs webhook configured")
        return

    content = f"❌ **{agent_id} failed**\n```{error[:1800]}```"
    _post(webhook_url, content)