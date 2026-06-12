import discord
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Map agent IDs to their Discord channel names
AGENT_CHANNELS = {
    "email-triage":  "📧-email-triage",
    "email-digest":  "📰-email-digest",
    "market-report": "📊-market-report",
    "health-sync":   "🏃-health-sync",
    "weekly-report": "📋-weekly-report",
    "test":          "⚙️-agent-logs",
}


async def _send(channel_name: str, content: str, success: bool = True):
    """Internal async function that sends a message to a Discord channel."""
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        try:
            guild = discord.utils.get(
                client.guilds,
                id=int(os.getenv("DISCORD_GUILD_ID"))
            )
            if not guild:
                print("[discord] Server not found")
                return

            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not channel:
                print(f"[discord] Channel #{channel_name} not found")
                return

            # Split long messages — Discord has a 2000 char limit per message
            chunks = [content[i:i+1900] for i in range(0, len(content), 1900)]
            for chunk in chunks:
                await channel.send(chunk)

        finally:
            await client.close()

    await client.start(os.getenv("DISCORD_BOT_TOKEN"))


def notify(agent_id: str, content: str, success: bool = True):
    """
    Send an agent output to its Discord channel.
    Call this from base.py after saving output to Supabase.

    Usage:
        notify("email-triage", result.content)
    """
    channel_name = AGENT_CHANNELS.get(agent_id, "⚙️-agent-logs")

    # Strip the emoji prefix for matching — Discord stores names without emoji
    clean_name = channel_name.split("-", 1)[-1] if "-" in channel_name else channel_name

    status = "✅" if success else "❌"
    formatted = f"{status} **{agent_id}**\n\n{content}"

    try:
        asyncio.run(_send(clean_name, formatted, success))
        print(f"[discord] Posted to #{clean_name}")
    except Exception as e:
        print(f"[discord] Failed to post: {e}")


def notify_error(agent_id: str, error: str):
    """Send an error notification to agent-logs."""
    logs_channel = "agent-logs"
    formatted = f"❌ **{agent_id} failed**\n```{error}```"
    try:
        asyncio.run(_send(logs_channel, formatted, success=False))
    except Exception as e:
        print(f"[discord] Failed to post error: {e}")