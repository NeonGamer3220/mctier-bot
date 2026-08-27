"""
MCTier Bot - Main Entry Point (main.py)
"""

import asyncio
import logging
import os
import sys
import discord
from discord.ext import commands

from config import config

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("mctier.main")

# List of cogs/extensions to load (commands.panels REMOVED)
INITIAL_EXTENSIONS = [
    "commands.profile",
    "commands.linking",
    "commands.tgf",
    "commands.tier_system",
    "commands.staff",
    "commands.ban_enforcement",
    "commands.tester_role_sync",
    "commands.spin",
    "commands.support_ticket",
    "commands.notifications",
    "commands.weekly_report",
    "commands.send_message",
    "commands.idea_channel",
]

# Discord Bot Intents setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

_persistent_views_registered = False


def register_persistent_views() -> None:
    """
    Registers all 'static' (non-unique, ticket/user-independent)
    button/dropdown panel Views, so they keep working AFTER a restart
    without having to resend the panel.

    This applies to the dropdown menu of the ping/queue/hightest panels
    (PanelSelectView), as well as the TGF panel, since their
    custom_id is fixed and does not depend on a specific user/ticket.
    """
    global _persistent_views_registered
    if _persistent_views_registered:
        return

    from commands.tier_ui import PanelSelectView
    from commands.tgf import TGFPanelView
    from commands.idea_channel import IdeaVoteView

    for mode_type in ("Modern", "Legacy"):
        for action_type in ("ping", "queue", "hightest"):
            bot.add_view(PanelSelectView(mode_type, action_type))

    bot.add_view(TGFPanelView())
    bot.add_view(IdeaVoteView())

    _persistent_views_registered = True
    log.info("Persistent panel Views registered (ping/queue/hightest/tgf/idea).")


@bot.event
async def on_ready():
    log.info("Main bot started: %s (ID: %s)", bot.user, bot.user.id)

    register_persistent_views()

    try:
        # 1. Clear any server-level (Guild) command duplicates
        for guild in bot.guilds:
            bot.tree.clear_commands(guild=guild)
            await bot.tree.sync(guild=guild)
        
        # 2. Sync the global commands
        synced = await bot.tree.sync()
        log.info("Successfully cleared and synced %d global commands.", len(synced))
    except Exception as exc:
        log.error("Error syncing commands: %s", exc)


async def main():
    async with bot:
        # Load cogs
        for ext in INITIAL_EXTENSIONS:
            try:
                await bot.load_extension(ext)
                log.info("Successfully loaded extension: %s", ext)
            except Exception as exc:
                log.error("Error loading extension %s: %s", ext, exc)

        # Start the bot using the token
        token = os.getenv("DISCORD_TOKEN") or getattr(config, "DISCORD_TOKEN", None)
        if not token:
            log.critical("DISCORD_TOKEN is not set among the environment variables!")
            return

        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot stopped by the user.")
