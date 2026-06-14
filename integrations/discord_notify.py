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


def _post(webhook_url: str, payload: dict) -> bool:
    """POST a single payload to a Discord webhook. Returns True on success."""
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"[discord] HTTP error: {e}")
        return False


def notify(
    agent_id: str,
    content: str,
    success: bool = True,
    embed: Optional[dict] = None,
) -> bool:
    """
    Send an agent output to its Discord channel via webhook.
    Returns True only if every chunk was delivered.

    If `embed` is given, the message is posted as a single Discord embed
    (rich card) instead of the chunked plain-text `content`. The `content`
    string is still what gets saved to memory/Supabase upstream; the embed is
    purely the Discord presentation.

    Usage in base.py:
        notify(self.agent_id, result.content, embed=result.embed)
    """
    webhook_url = _get_webhook_url(agent_id)
    if not webhook_url:
        return False

    if embed is not None:
        if _post(webhook_url, {"embeds": [embed]}):
            print(f"[discord] Notified #{agent_id} (embed)")
            return True
        print(f"[discord] Failed to deliver embed for #{agent_id}")
        return False

    status = "✅" if success else "❌"
    header = f"{status} **{agent_id}**\n\n"

    # Chunk the header together with the content so its length counts against
    # the limit. Prepending it to chunks[0] afterward could push that first
    # message past Discord's hard 2000-char cap.
    chunks = _chunk_message(header + content)

    results = [_post(webhook_url, {"content": chunk}) for chunk in chunks]
    delivered = sum(results)

    if delivered == len(chunks):
        print(f"[discord] Notified #{agent_id} ({delivered} chunk(s))")
        return True

    print(
        f"[discord] Partial delivery for #{agent_id}: "
        f"{delivered}/{len(chunks)} chunk(s) sent"
    )
    return False


def notify_error(agent_id: str, error: str) -> bool:
    """Send an error notification to the agent-logs webhook."""
    webhook_url = os.getenv(DEFAULT_WEBHOOK_ENV)
    if not webhook_url:
        print("[discord] No agent-logs webhook configured")
        return False

    # Neutralize backtick runs in the error so they can't close the code block
    # early and mangle the message. A zero-width space (U+200B) keeps it looking
    # identical. chr() avoids putting an invisible character in the source.
    zwsp = chr(0x200b)
    safe_error = error[:1800].replace("```", f"`{zwsp}`{zwsp}`")
    content = f"❌ **{agent_id} failed**\n```{safe_error}```"
    return _post(webhook_url, {"content": content})
