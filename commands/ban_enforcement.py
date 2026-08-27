"""
MCTier Bot - Ban Enforcement (commands/ban_enforcement.py)

Bans are managed by the website admin panel, which writes to the Supabase
`bans` table (username, discord_id, reason, duration_key, expires_at,
active, banned_by, image_url, created_at).

This cog periodically (every 5 minutes) queries Supabase for active
(active=true) bans, and syncs the Discord banned role (BANNED_ROLE_ID)
based on that:

- If a player has an active, not-yet-expired ban in the table, but
  doesn't have the role -> it is added.
- If a ban has expired (expires_at < now) -> the role is removed, and
  the row is set to inactive (`active = false`) in Supabase.
- If a member has the role but there's no corresponding active ban in
  Supabase (e.g. it was lifted on the website) -> the role is removed.

The `discord_id` field can be empty in the table (e.g. if the ban was
only issued by Minecraft username); in that case the bot tries to look
up the corresponding Discord ID from the `linked_accounts` table.
"""

import logging
import time

import discord
from discord.ext import commands, tasks

from config import BANNED_ROLE_ID, config
from database import get_active_bans_async, deactivate_ban_async, get_discord_by_minecraft_async

log = logging.getLogger("mctier.commands.ban_enforcement")


def _parse_expires_at(value) -> float | None:
    """Converts the Supabase 'timestamp with time zone' field to a Unix timestamp."""
    if not value:
        return None
    try:
        from datetime import datetime
        # Supabase returns it in ISO format, e.g. "2026-08-20T12:00:00+00:00"
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.timestamp()
    except Exception:
        return None


def is_banned_by_role(member: discord.Member) -> bool:
    if not member or not hasattr(member, "roles"):
        return False
    return any(r.id == BANNED_ROLE_ID for r in member.roles)


class BanEnforcementCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sync_bans.start()

    def cog_unload(self):
        self.sync_bans.cancel()

    async def _resolve_discord_id(self, ban_row: dict) -> int | None:
        raw_id = ban_row.get("discord_id")
        if raw_id:
            try:
                return int(raw_id)
            except (TypeError, ValueError):
                pass

        username = ban_row.get("username")
        if username:
            try:
                return await get_discord_by_minecraft_async(username)
            except Exception as exc:
                log.error("Error resolving Discord ID (%s) via linked_accounts: %s", username, exc)
        return None

    @tasks.loop(minutes=5)
    async def sync_bans(self):
        guilds = [g for g in self.bot.guilds if not config.guild_id or g.id == config.guild_id]
        if not guilds:
            guilds = list(self.bot.guilds)
        if not guilds:
            return

        try:
            active_bans = await get_active_bans_async()
        except Exception as exc:
            log.error("Error fetching active bans: %s", exc)
            return

        now = time.time()
        should_be_banned: set[int] = set()

        for ban_row in active_bans:
            expires_at = _parse_expires_at(ban_row.get("expires_at"))

            discord_id = await self._resolve_discord_id(ban_row)

            # Expired ban -> deactivate in Supabase, remove role
            if expires_at is not None and now >= expires_at:
                ban_id = ban_row.get("id")
                if ban_id is not None:
                    await deactivate_ban_async(ban_id)
                if discord_id:
                    await self._remove_role_everywhere(guilds, discord_id, reason="Ban expired (Supabase)")
                continue

            if discord_id:
                should_be_banned.add(discord_id)
                await self._ensure_role(guilds, discord_id, ban_row, reason="Syncing website ban (Supabase)")

        # Remove the role from those who have it but no longer have an active ban row
        for guild in guilds:
            role = guild.get_role(BANNED_ROLE_ID)
            if not role:
                continue
            for member in list(role.members):
                if member.id not in should_be_banned:
                    try:
                        await member.remove_roles(role, reason="No active ban in Supabase (lifted on the website)")
                        log.info("Banned role removed from %s (%s) since there is no active ban.", member, member.id)
                    except Exception as exc:
                        log.error("Error removing role from %s: %s", member, exc)

    async def _ensure_role(self, guilds, discord_id: int, ban_row: dict, reason: str) -> None:
        for guild in guilds:
            role = guild.get_role(BANNED_ROLE_ID)
            if not role:
                continue
            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                except Exception:
                    continue
            if role not in member.roles:
                try:
                    await member.add_roles(role, reason=reason)
                    log.info("Banned role added to %s (%s) (%s).", member, member.id, ban_row.get("reason", ""))
                except Exception as exc:
                    log.error("Failed to add the banned role to %s: %s", member, exc)

    async def _remove_role_everywhere(self, guilds, discord_id: int, reason: str) -> None:
        for guild in guilds:
            role = guild.get_role(BANNED_ROLE_ID)
            if not role:
                continue
            member = guild.get_member(discord_id)
            if not member:
                try:
                    member = await guild.fetch_member(discord_id)
                except Exception:
                    continue
            if role in member.roles:
                try:
                    await member.remove_roles(role, reason=reason)
                    log.info("Banned role removed from %s (%s) (%s).", member, member.id, reason)
                except Exception as exc:
                    log.error("Failed to remove the banned role from %s: %s", member, exc)

    @sync_bans.before_loop
    async def before_sync(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BanEnforcementCog(bot))
