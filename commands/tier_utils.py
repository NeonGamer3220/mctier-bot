"""
MCTier Bot - Tier Utils (commands/tier_utils.py)
Exact category identifiers and inactivity structures.
"""

import discord
import time
import io
import datetime
import aiohttp

from config import ARCHIVE_CHANNEL_ID
from database import (
    get_cooldown_expiry_async, set_cooldown_async, delete_cooldown_async,
    is_dm_optout_async, set_dm_optout_async, save_ticket_archive_async
)


async def fetch_3d_skin_file(mc_username: str, filename: str = "skin.png"):
    """Downloads a 3D render of the player's Minecraft skin and returns it as a
    discord.File, ready to be attached to a message. Returns None on failure
    (e.g. unknown/unlinked username or the render service being unreachable)."""
    if not mc_username:
        return None
    url = f"https://starlightskins.lunareclipse.studio/render/full/{mc_username}/full"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                return discord.File(fp=io.BytesIO(data), filename=filename)
    except Exception:
        return None

MODERN_CATEGORY_ID = 1469766438238687496
MODERN_QUEUE_CATEGORY_ID = 1478400462225936496

THEME_LIGHT_PURPLE = 0x9b59b6
THEME_LIGHT_BLUE = 0x3498db

ACTIVE_QUEUES = {}  # queue_ch_id: { "players": [...], "testers": [...], "gamemode": ..., "msg_id": ... }
INACTIVE_TICKETS = {} # channel_id: { "owner_id": ..., "warned": bool, "warn_time": ... }
VALID_HT_TIERS = ["HT1", "HT2", "HT3", "HT4", "HT5", "LT1", "LT2", "LT3", "LT4", "LT5"]
ALLOWED_QUEUE_TIERS = ["UNRANKED", "LT5", "HT5", "LT4", "HT4", "LT3"]  # Max LT3 can be given from a regular queue test; above that it must be recorded on the tierlist website
HIGHTEST_OPTIONS = [
    ("High Test - HT1", "HT1", "⚔️"),
    ("High Test - HT2", "HT2", "⚔️"),
    ("High Test - HT3", "HT3", "⚔️"),
    ("High Test - HT4", "HT4", "⚔️"),
    ("High Test - HT5", "HT5", "⚔️"),
]


async def is_dm_optout(user_id: int) -> bool:
    """Whether the player has opted out of the bot's test-result/feedback DMs. Backed by the database."""
    return await is_dm_optout_async(user_id)


async def set_dm_optout(user_id: int) -> None:
    """Records that the player no longer wants to receive these DMs. Backed by the database."""
    await set_dm_optout_async(user_id)


def get_ticket_category(guild: discord.Guild):
    return guild.get_channel(MODERN_CATEGORY_ID)

def get_queue_category(guild: discord.Guild):
    return guild.get_channel(MODERN_QUEUE_CATEGORY_ID)

async def check_timeout(user_id: int, gamemode: str):
    """Checks whether the player is on a testing cooldown for this gamemode. Backed by the database."""
    expires = await get_cooldown_expiry_async(user_id, gamemode)
    if expires:
        remaining = (expires - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            return True, f"{mins}m {secs}s"
    return False, ""

async def set_cooldown(user_id: int, gamemode: str, duration_seconds: int = 3600):
    """Records a testing cooldown for the player in this gamemode. Backed by the database."""
    await set_cooldown_async(user_id, gamemode, duration_seconds)

async def update_queue_message(message: discord.Message, q_data: dict, mode_key: str):
    players = q_data["players"]
    testers = q_data["testers"]
    
    players_text = ""
    if not players:
        players_text = "*- Empty -*"
    else:
        lines = []
        for p in players:
            status_icon = p.get('status', '⏳ WAITING')
            lines.append(f"{status_icon} <@{p['id']}> (**{p['mc']}**)")
        players_text = "\n".join(lines)

    testers_text = ""
    if not testers:
        testers_text = "*- No active tester -*"
    else:
        testers_text = "\n".join(f"🛡️ <@{t}>" for t in testers)

    desc = f"**Spots:** {len(players)}/20\n\n**Players in queue:**\n{players_text}\n**Active Testers:**\n{testers_text}"
    
    embed = message.embeds[0]
    embed.description = desc
    await message.edit(embed=embed)


async def archive_channel(channel: discord.abc.Messageable, closed_by: discord.abc.User, reason: str = "") -> None:
    """
    Saves the channel's full message history to a .txt transcript, sends it to
    the archive channel, and records it in the database's ticket_archives table.
    If ARCHIVE_CHANNEL_ID is not set, it silently skips this.
    """
    if not ARCHIVE_CHANNEL_ID:
        return

    guild = getattr(channel, "guild", None)
    archive_chan = guild.get_channel(ARCHIVE_CHANNEL_ID) if guild else None
    if not archive_chan:
        return

    lines = []
    msg_count = 0
    try:
        async for msg in channel.history(limit=2000, oldest_first=True):
            msg_count += 1
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content or ""
            for e in msg.embeds:
                title = e.title or ""
                desc = e.description or ""
                content += f"\n  [EMBED] {title} - {desc}"
            for a in msg.attachments:
                content += f"\n  [ATTACHMENT] {a.url}"
            lines.append(f"[{ts}] {author}: {content}")
    except Exception:
        pass

    transcript_text = "\n".join(lines) if lines else "(No messages)"
    buffer = io.BytesIO(transcript_text.encode("utf-8"))
    filename = f"transcript-{channel.name}.txt"

    embed = discord.Embed(
        title=f"🗄️ Ticket Archived: #{channel.name}",
        description=f"Closed by: {closed_by.mention if hasattr(closed_by, 'mention') else closed_by}\nReason: {reason or '-'}\nMessage count: {msg_count}",
        color=discord.Color.dark_grey(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    try:
        archive_msg = await archive_chan.send(embed=embed, file=discord.File(fp=buffer, filename=filename))
    except Exception:
        return

    try:
        await save_ticket_archive_async(
            channel_name=channel.name,
            closed_by=str(closed_by),
            reason=reason,
            message_count=msg_count,
            archive_channel_id=ARCHIVE_CHANNEL_ID,
            archive_message_id=archive_msg.id,
        )
    except Exception:
        pass
