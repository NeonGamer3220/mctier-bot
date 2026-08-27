"""
MCTier Bot - Tester Role Sync (commands/tester_role_sync.py)

On the Player Management page (visible only to the OWNER admin), each
gamemode has a "Tester" checkbox in the `is_tester` column of the
Supabase `tests` table (per row, per gamemode). This cog periodically
(every 2 minutes) syncs the Discord roles based on this:

- General TESTER_ROLE_ID role: if a player has the Tester checkbox
  checked in ANY gamemode, they receive it; if not in any, it's removed.
- Per-gamemode "{Gamemode} Tester" role (e.g. "DiaSMP Tester"): only
  granted for the gamemode where the Tester checkbox is actually
  checked. So if someone has the general Tester role but not the
  DiaSMP Tester one, the queue-opening permission check
  (see commands/tier_ui.py) won't let them open the DiaSMP queue.

Player -> Discord ID resolution happens through the `linked_accounts`
table (the same pattern as in ban_enforcement.py).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import TESTER_ROLE_ID, ALL_TICKET_TYPES, config
from database import (
    get_tester_usernames_async,
    get_tester_gamemode_rows_async,
    get_discord_by_minecraft_async,
)

log = logging.getLogger("mctier.commands.tester_role_sync")

# All known gamemode labels (e.g. "DiaSMP") that can have a corresponding
# "{label} Tester" Discord role on the server.
_ALL_GAMEMODE_LABELS = [label for label, _key, _emoji in ALL_TICKET_TYPES]


class TesterRoleSyncCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sync_testers.start()

    def cog_unload(self):
        self.sync_testers.cancel()

    @tasks.loop(seconds=30)
    async def sync_testers(self):
        guilds = [g for g in self.bot.guilds if not config.guild_id or g.id == config.guild_id]
        if not guilds:
            guilds = list(self.bot.guilds)
        if not guilds:
            return

        try:
            tester_usernames = await get_tester_usernames_async()
        except Exception as exc:
            log.error("Error fetching Tester players: %s", exc)
            return

        try:
            gamemode_rows = await get_tester_gamemode_rows_async()
        except Exception as exc:
            log.error("Error fetching per-gamemode Tester rows: %s", exc)
            gamemode_rows = []

        discord_id_cache: dict[str, int | None] = {}

        async def resolve(username: str) -> int | None:
            if username in discord_id_cache:
                return discord_id_cache[username]
            try:
                discord_id = await get_discord_by_minecraft_async(username)
            except Exception as exc:
                log.error("Error resolving Discord ID (%s) via linked_accounts: %s", username, exc)
                discord_id = None
            discord_id_cache[username] = discord_id
            return discord_id

        # --- Who receives the general Tester role ---
        should_have_role: set[int] = set()
        for username in tester_usernames:
            discord_id = await resolve(username)
            if discord_id:
                should_have_role.add(discord_id)

        # --- discord_id -> {gamemode labels for which the Tester checkbox is set} ---
        should_have_gamemode_roles: dict[int, set[str]] = {}
        for row in gamemode_rows:
            username = row["username"]
            gamemode_label = row["gamemode"]
            discord_id = await resolve(username)
            if not discord_id:
                continue
            should_have_gamemode_roles.setdefault(discord_id, set()).add(gamemode_label)

        for guild in guilds:
            general_role = guild.get_role(TESTER_ROLE_ID)

            # --- Grant / remove the general Tester role ---
            if general_role:
                for discord_id in should_have_role:
                    await self._ensure_role(guild, general_role, discord_id, reason="Tester checkbox checked on the website (Owner)")

                for member in list(general_role.members):
                    if member.id not in should_have_role:
                        try:
                            await member.remove_roles(general_role, reason="No Tester checkbox checked on the website")
                            log.info("Tester role removed from %s (%s).", member, member.id)
                        except Exception as exc:
                            log.error("Error removing Tester role from %s: %s", member, exc)

            # --- Grant / remove per-gamemode "{label} Tester" / "{label} Teszter" roles ---
            for label in _ALL_GAMEMODE_LABELS:
                gm_role = None
                for suffix in ("Tester", "Teszter"):
                    gm_role = discord.utils.get(guild.roles, name=f"{label} {suffix}")
                    if gm_role:
                        break
                if not gm_role:
                    continue

                should_have_this: set[int] = {
                    discord_id
                    for discord_id, labels in should_have_gamemode_roles.items()
                    if label in labels
                }

                for discord_id in should_have_this:
                    await self._ensure_role(guild, gm_role, discord_id, reason=f"{label} Tester checkbox checked on the website (Owner)")

                for member in list(gm_role.members):
                    if member.id not in should_have_this:
                        try:
                            await member.remove_roles(gm_role, reason=f"No {label} Tester checkbox checked on the website")
                            log.info("%s Tester role removed from %s (%s).", label, member, member.id)
                        except Exception as exc:
                            log.error("Error removing the %s Tester role from %s: %s", label, member, exc)

    async def _ensure_role(self, guild, role, discord_id: int, reason: str) -> None:
        member = guild.get_member(discord_id)
        if not member:
            try:
                member = await guild.fetch_member(discord_id)
            except Exception:
                return
        if role not in member.roles:
            try:
                await member.add_roles(role, reason=reason)
                log.info("%s role added to %s (%s).", role.name, member, member.id)
            except Exception as exc:
                log.error("Failed to add the %s role to %s: %s", role.name, member, exc)

    @sync_testers.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="synctesters", description="Immediately re-syncs the Tester roles (Admin).")
    async def synctesters(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ This command requires administrator permission.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            await self.sync_testers()
        except Exception as exc:
            log.error("Error during manual Tester sync: %s", exc)
            return await interaction.followup.send(f"❌ An error occurred during the sync: {exc}", ephemeral=True)
        await interaction.followup.send("✅ Tester roles synced.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TesterRoleSyncCog(bot))
