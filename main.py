"""
MCTier Bot - Main Entry Point (main.py)
"""

import asyncio
import logging
import os
import sys
import discord
from discord import app_commands
from discord.ext import commands

from config import config, BOT_COMMANDS_CHANNEL_ID, HELP_TICKET_CATEGORY_ID

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("mctier.main")

from commands.tier_utils import MODERN_CATEGORY_ID, MODERN_QUEUE_CATEGORY_ID

# List of cogs/extensions to load (commands.panels REMOVED)
INITIAL_EXTENSIONS = [
    "commands.profile",
    "commands.linking",
    "commands.tier_system",
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

# Channel categories that count as "inside a ticket" for the BOT_COMMANDS
# restriction below - the tier test/queue tickets and the support tickets.
TICKET_CATEGORY_IDS = {MODERN_CATEGORY_ID, MODERN_QUEUE_CATEGORY_ID, HELP_TICKET_CATEGORY_ID}


class RestrictedCommandTree(app_commands.CommandTree):
    """
    If BOT_COMMANDS is set, restricts every slash command to that one
    channel, or to inside an active ticket (test/queue/high-test/support
    channels). Server admins are always exempt, so they can still place
    panels, run /report, etc. from anywhere. If BOT_COMMANDS isn't set,
    this check does nothing and every command works everywhere as before.
    """

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not BOT_COMMANDS_CHANNEL_ID or not interaction.guild:
            return True

        channel = interaction.channel
        if channel and channel.id == BOT_COMMANDS_CHANNEL_ID:
            return True

        category_id = getattr(channel, "category_id", None)
        if category_id in TICKET_CATEGORY_IDS:
            return True

        if interaction.user.guild_permissions.administrator:
            return True

        bot_commands_channel = interaction.guild.get_channel(BOT_COMMANDS_CHANNEL_ID)
        location = bot_commands_channel.mention if bot_commands_channel else "the bot-commands channel"
        await interaction.response.send_message(
            f"❌ You can only use bot commands in {location}, or inside an active ticket.",
            ephemeral=True
        )
        return False


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
                # This bot only runs in one server, so sync commands as guild-scoped
                # only. Guild syncs are instant (seconds) unlike global syncs (up to
                # an hour), and registering the same commands both globally AND to
                # the guild causes Discord to show every command TWICE in the
                # slash-command picker for that guild - so we deliberately skip the
                # global sync when a guild is configured.
                guild_obj = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                guild_synced = await self.tree.sync(guild=guild_obj)
                log.info("Instantly synced %d commands to guild %s.", len(guild_synced), guild_id)

                # One-time cleanup: earlier versions of this bot also registered
                # commands globally, which stick around on Discord's side and keep
                # showing up as duplicates alongside the guild-scoped ones above
                # until they're explicitly cleared. Wiping the (now-empty) global
                # tree removes those leftovers.
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                log.info("Cleared leftover global commands.")
            else:
                # No guild configured - fall back to a global sync (can take up to
                # an hour to propagate on Discord's side).
                synced = await self.tree.sync()
                log.info("Successfully synced %d global commands.", len(synced))
        except Exception as exc:
            log.error("Error syncing commands: %s", exc)


bot = MCTierBot(command_prefix="!", intents=intents, tree_cls=RestrictedCommandTree)

_persistent_views_registered = False


def register_persistent_views(bot: commands.Bot) -> None:
    """
    Registers all 'static' (non-unique, ticket/user-independent)
    button/dropdown panel Views, so they keep working AFTER a restart
    without having to resend the panel.

    This applies to the dropdown menu of the ping/queue/hightest panels
    (PanelSelectView), since their custom_id is fixed and does not
    depend on a specific user/ticket.
    """
    global _persistent_views_registered
    if _persistent_views_registered:
        return

    from commands.tier_ui import PanelSelectView

    for action_type in ("ping", "queue", "hightest"):
        bot.add_view(PanelSelectView(action_type))

    _persistent_views_registered = True
    log.info("Persistent panel Views registered (ping/queue/hightest).")


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
