"""
MCTier Bot - Database Modul
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, TypeVar

from supabase import Client, create_client
from config import config

log = logging.getLogger("mctier.database")

T = TypeVar("T")


async def arun(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


class Database:
    def __init__(self) -> None:
        self._client: Client | None = None
        self._init_client()

    def _init_client(self) -> None:
        if config.supabase_url and config.supabase_key:
            try:
                self._client = create_client(config.supabase_url, config.supabase_key)
                log.info("Supabase database connection successfully established.")
            except Exception as exc:
                log.error("Error creating Supabase client: %s", exc)
                self._client = None
        else:
            log.warning("Supabase URL or Key is missing from the configuration!")

    # --- Linked accounts ---
    def get_linked_account(self, discord_id: int) -> dict | None:
        if not self._client:
            return None
        resp = self._client.table("linked_accounts").select("*").eq("discord_id", discord_id).execute()
        return resp.data[0] if resp.data else None

    def link_account(self, discord_id: int, minecraft_name: str, uuid: str = "") -> dict:
        if not self._client:
            return {}
        data = {
            "discord_id": discord_id,
            "minecraft_name": minecraft_name,
            "uuid": uuid,
            "linked_at": datetime.now(timezone.utc).isoformat()
        }
        resp = self._client.table("linked_accounts").upsert(data, on_conflict="discord_id").execute()
        return resp.data[0] if resp.data else {}

    def unlink_account(self, discord_id: int) -> bool:
        if not self._client:
            return False
        resp = self._client.table("linked_accounts").delete().eq("discord_id", discord_id).execute()
        return bool(resp.data)

    # --- Tournaments & Matches ---
    def create_tournament(self, name: str, end_time: datetime, queue_message_id: int, guild_id: int, ticket_category_id: int, results_channel_id: int, regulator_role_id: int) -> dict:
        if not self._client:
            return {}
        data = {
            "name": name,
            "status": "pending",
            "end_time": end_time.isoformat(),
            "queue_message_id": queue_message_id,
            "guild_id": guild_id,
            "ticket_category_id": ticket_category_id,
            "results_channel_id": results_channel_id,
            "regulator_role_id": regulator_role_id,
            "current_round": 0
        }
        resp = self._client.table("tournaments").insert(data).execute()
        return resp.data[0] if resp.data else {}

    def get_tournament(self, tournament_id: str) -> dict | None:
        if not self._client:
            return None
        resp = self._client.table("tournaments").select("*").eq("id", tournament_id).execute()
        return resp.data[0] if resp.data else None

    def update_tournament(self, tournament_id: str, **kwargs: Any) -> dict:
        if not self._client:
            return {}
        resp = self._client.table("tournaments").update(kwargs).eq("id", tournament_id).execute()
        return resp.data[0] if resp.data else {}

    def list_pending_tournaments(self) -> list[dict]:
        if not self._client:
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        resp = self._client.table("tournaments").select("*").eq("status", "pending").lte("end_time", now_iso).execute()
        return resp.data or []

    def add_tournament_player(self, tournament_id: str, discord_id: int, minecraft_name: str) -> dict:
        if not self._client:
            return {}
        data = {"tournament_id": tournament_id, "discord_id": discord_id, "minecraft_name": minecraft_name}
        resp = self._client.table("tournament_players").upsert(data, on_conflict="tournament_id,discord_id").execute()
        return resp.data[0] if resp.data else {}

    def get_tournament_players(self, tournament_id: str) -> list[dict]:
        if not self._client:
            return []
        resp = self._client.table("tournament_players").select("*").eq("tournament_id", tournament_id).execute()
        return resp.data or []

    def create_match(self, tournament_id: str, round_number: int, player1_discord_id: int, player2_discord_id: int, player1_mc: str, player2_mc: str, ticket_channel_id: int) -> dict:
        if not self._client:
            return {}
        data = {
            "tournament_id": tournament_id,
            "round_number": round_number,
            "player1_discord_id": player1_discord_id,
            "player2_discord_id": player2_discord_id,
            "player1_mc": player1_mc,
            "player2_mc": player2_mc,
            "ticket_channel_id": ticket_channel_id,
            "winner_discord_id": None
        }
        resp = self._client.table("matches").insert(data).execute()
        return resp.data[0] if resp.data else {}

    def get_unresolved_matches(self, tournament_id: str) -> list[dict]:
        if not self._client:
            return []
        resp = self._client.table("matches").select("*").eq("tournament_id", tournament_id).is_("winner_discord_id", "null").execute()
        return resp.data or []

    def set_match_winner(self, match_id: str, winner_discord_id: int) -> dict:
        if not self._client:
            return {}
        resp = self._client.table("matches").update({"winner_discord_id": winner_discord_id}).eq("id", match_id).execute()
        return resp.data[0] if resp.data else {}

    # --- Invite rendszer ---
    def create_pending_invite(self, discord_id: int, invite_type: str, ticket_channel_id: int) -> dict:
        if not self._client:
            return {}
        data = {"discord_id": discord_id, "invite_type": invite_type, "ticket_channel_id": ticket_channel_id}
        resp = self._client.table("pending_invites").insert(data).execute()
        return resp.data[0] if resp.data else {}

    def get_pending_invite_for_user(self, discord_id: int) -> list[dict]:
        if not self._client:
            return []
        resp = self._client.table("pending_invites").select("*").eq("discord_id", discord_id).eq("completed", False).execute()
        return resp.data or []

    def mark_invite_completed(self, invite_id: str) -> None:
        if not self._client:
            return
        self._client.table("pending_invites").update({"completed": True}).eq("id", invite_id).execute()

    def get_due_reminders(self) -> list[dict]:
        if not self._client:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        resp = self._client.table("pending_invites").select("*") \
            .eq("invite_type", "magas") \
            .eq("reminder_sent", False) \
            .eq("completed", False) \
            .lte("created_at", cutoff.isoformat()) \
            .execute()
        return resp.data or []

    def mark_reminder_sent(self, invite_id: str) -> None:
        if not self._client:
            return
        self._client.table("pending_invites").update({"reminder_sent": True}).eq("id", invite_id).execute()


db = Database()

# ======================================================================
# BASIC COMPATIBILITY FUNCTIONS FOR EXISTING COGS
# ======================================================================

def supabase_select(table: str, match_column: str, match_value: Any) -> list[dict]:
    if not db._client:
        return []
    resp = db._client.table(table).select("*").eq(match_column, match_value).execute()
    return resp.data or []

async def get_linked_minecraft_name_async(discord_id: int) -> str | None:
    acc = await arun(db.get_linked_account, discord_id)
    return acc.get("minecraft_name") if acc else None

async def get_tgf_cooldown(discord_id: int) -> "datetime | None":
    # If you have a TGF cooldown table in Supabase, it can be queried here.
    # The "expires_at" column name must be used (that is what the Supabase
    # table has), and expired (past) cooldowns are not taken into account.
    res = await arun(supabase_select, "tgf_cooldowns", "discord_id", discord_id)
    if not res:
        return None
    raw = res[0].get("expires_at")
    if not raw:
        return None
    try:
        expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    if expires <= datetime.now(timezone.utc):
        return None
    return expires

# ======================================================================
# MISSING COMPATIBILITY FUNCTIONS FOR THE COGS
# ======================================================================

async def api_post_elo_instant(*args: Any, **kwargs: Any) -> dict:
    """Temporary stub for the instant Elo update."""
    log.info("api_post_elo_instant called")
    return {"status": "ok"}

async def set_tgf_cooldown(discord_id: int, days: int = 14) -> bool:
    """Record a TGF cooldown."""
    if not db._client:
        return False
    until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    # IMPORTANT: in the Supabase "tgf_cooldowns" table the column is named
    # "expires_at", not "cooldown_until" — that used to throw a NOT NULL error.
    resp = await arun(
        lambda: db._client.table("tgf_cooldowns").upsert(
            {"discord_id": discord_id, "expires_at": until},
            on_conflict="discord_id"
        ).execute()
    )
    return bool(resp.data)

async def generate_link_code_async(discord_id: int) -> str:
    """Generate a linking code for the player."""
    import random
    import string
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    if db._client:
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        db._client.table("pending_codes").upsert({
            "discord_id": discord_id,
            "code": code,
            "expires_at": expires_at
        }).execute()
    return code

async def get_discord_by_minecraft_async(minecraft_name: str) -> int | None:
    """Look up a Discord ID by Minecraft name."""
    if not db._client:
        return None
    resp = db._client.table("linked_accounts").select("discord_id").ilike("minecraft_name", minecraft_name).execute()
    if resp.data:
        return int(resp.data[0]["discord_id"])
    return None

async def unlink_minecraft_account_async(discord_id: int) -> bool:
    """Unlink an account asynchronously."""
    return await arun(db.unlink_account, discord_id)

async def save_test_result_supabase(player_user: discord.Member, player_mc: str, gamemode: str, tier: str, tester_user: discord.Member, interaction: discord.Interaction):
    """
    Saves the test result to the Supabase database (tests table: username, gamemode, rank, points, created_at).

    The website (/api/tests) only accepts real tier codes (LT5..HT1) as
    rank — the "UNRANKED"/"Unranked" text is NOT a valid tier there, so
    it is never written literally into the rank field. If the tester
    records an "Unranked" result, the existing row is deleted (the player
    becomes untested again in that gamemode) instead of saving invalid data.
    """
    from config import POINTS
    if not db._client:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        existing = await arun(supabase_select, "tests", "username", player_mc)
        existing_row = next((r for r in existing if str(r.get("gamemode", "")).strip().lower() == gamemode.strip().lower()), None)

        clean_tier = str(tier or "").strip().upper()

        if clean_tier in ("", "UNRANKED"):
            if existing_row and existing_row.get("id") is not None:
                await arun(lambda: db._client.table("tests").delete().eq("id", existing_row["id"]).execute())
            return

        pts = POINTS.get(clean_tier, 0)

        payload = {
            "username": player_mc,
            "gamemode": gamemode,
            "rank": clean_tier,
            "points": pts,
            "created_at": now
        }
        if existing_row and existing_row.get("id") is not None:
            await arun(lambda: db._client.table("tests").update(payload).eq("id", existing_row["id"]).execute())
        else:
            # The "id" column of the Supabase "tests" table has no default
            # (auto-increment/identity) value, so if we don't provide an id,
            # the insert fails with a "null value in column id" error. So here
            # we generate our own unique identifier (the same scheme used by
            # the manual recording flow).
            payload["id"] = int(time.time() * 1000)
            await arun(lambda: db._client.table("tests").insert(payload).execute())
    except Exception as e:
        print(f"Error saving result to Supabase: {e}")
        raise e


async def get_active_bans_async() -> list[dict]:
    """
    Returns all active (active=true) bans from the Supabase `bans` table.
    The website admin panel bans players from here, and the bot
    syncs the Discord banned role based on this.
    """
    if not db._client:
        return []
    try:
        resp = await arun(lambda: db._client.table("bans").select("*").eq("active", True).execute())
        return resp.data or []
    except Exception as exc:
        log.error("Error fetching active bans from Supabase: %s", exc)
        return []


async def get_tester_usernames_async() -> list[str]:
    """
    Returns the list of player names for whom at least one row in the
    Supabase `tests` table has `is_tester = true`. The website admin
    panel (Owner) sets this checkbox per gamemode; if a player has it
    checked in ANY mode, they receive the Tester Discord role.
    """
    if not db._client:
        return []
    try:
        resp = await arun(
            lambda: db._client.table("tests").select("username").eq("is_tester", True).execute()
        )
        rows = resp.data or []
        usernames = {str(r.get("username", "")).strip() for r in rows if r.get("username")}
        return [u for u in usernames if u]
    except Exception as exc:
        log.error("Error fetching Tester players from Supabase: %s", exc)
        return []


async def get_tester_gamemode_rows_async() -> list[dict]:
    """
    Returns the (username, gamemode) pairs from the Supabase `tests`
    table where `is_tester = true`. This is needed to sync the
    per-gamemode Tester Discord roles (e.g. "DiaSMP Tester") alongside
    the global TESTER_ROLE_ID role - a player should only have the
    Tester role for the gamemodes checked on the website (Owner admin).
    """
    if not db._client:
        return []
    try:
        resp = await arun(
            lambda: db._client.table("tests").select("username,gamemode").eq("is_tester", True).execute()
        )
        rows = resp.data or []
        result = []
        for r in rows:
            username = str(r.get("username", "")).strip()
            gamemode = str(r.get("gamemode", "")).strip()
            if username and gamemode:
                result.append({"username": username, "gamemode": gamemode})
        return result
    except Exception as exc:
        log.error("Error fetching per-gamemode Tester rows from Supabase: %s", exc)
        return []


async def deactivate_ban_async(ban_id: int) -> bool:
    """Mark an expired ban as inactive in the Supabase `bans` table."""
    if not db._client:
        return False
    try:
        await arun(lambda: db._client.table("bans").update({"active": False}).eq("id", ban_id).execute())
        return True
    except Exception as exc:
        log.error("Error deactivating ban with ID %s: %s", ban_id, exc)
        return False


async def get_player_rank_async(player_mc: str, gamemode_display: str) -> str:
    """Returns the player's current tier in a given gamemode (Unranked if no record)."""
    try:
        rows = await arun(supabase_select, "tests", "username", player_mc)
    except Exception:
        return "Unranked"
    for r in rows:
        if str(r.get("gamemode", "")).strip().lower() == gamemode_display.strip().lower():
            return str(r.get("rank", "Unranked")).upper()
    return "Unranked"
