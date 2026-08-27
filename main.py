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


class MCTierBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Load cogs
        for ext in INITIAL_EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Successfully loaded extension: %s", ext)
            except Exception as exc:
                log.error("Error loading extension %s: %s", ext, exc)

        register_persistent_views(self)

        # Command sync - runs once, at actual startup (not on every reconnect).
        try:
            guild_id = getattr(config, "guild_id", 0) or int(os.getenv("GUILD_ID", "0"))
            if guild_id:
                # Instant sync: copy the global command tree straight into the
                # dev/production guild, so new/changed commands show up there
                # within seconds instead of waiting on Discord's global rollout.
                guild_obj = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                guild_synced = await self.tree.sync(guild=guild_obj)
                log.info("Instantly synced %d commands to guild %s.", len(guild_synced), guild_id)
            else:
                log.warning("GUILD_ID is not set - skipping instant guild sync, only the slow global sync will run.")

            # Global sync - still needed so the commands are available in any
            # other server the bot might be in, but can take up to an hour
            # to propagate on Discord's side.
            synced = await self.tree.sync()
            log.info("Successfully synced %d global commands.", len(synced))
        except Exception as exc:
            log.error("Error syncing commands: %s", exc)


bot = MCTierBot(command_prefix="!", intents=intents)

_persistent_views_registered = False


def register_persistent_views(bot: commands.Bot) -> None:
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

    for action_type in ("ping", "queue", "hightest"):
        bot.add_view(PanelSelectView(action_type))

    bot.add_view(TGFPanelView())
    bot.add_view(IdeaVoteView())

    _persistent_views_registered = True
    log.info("Persistent panel Views registered (ping/queue/hightest/tgf/idea).")


@bot.event
async def on_ready():
    log.info("Main bot started: %s (ID: %s)", bot.user, bot.user.id)


async def main():
    async with bot:
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
