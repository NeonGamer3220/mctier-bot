"""
MCTier Bot - Tier Utils (commands/tier_utils.py)
Exact category identifiers and inactivity structures.
"""

import discord
import time
import json
import os
import io
import datetime
import aiohttp

from config import ARCHIVE_CHANNEL_ID


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
LEGACY_CATEGORY_ID = 1520523939225276536

MODERN_QUEUE_CATEGORY_ID = 1478400462225936496
LEGACY_QUEUE_CATEGORY_ID = 1520384820612567202

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

COOLDOWNS = {}  # (user_id, gamemode): timestamp

ARCHIVE_INDEX_FILE = "ticket_archives.json"
DM_OPTOUT_FILE = "dm_optout.json"


def is_dm_optout(user_id: int) -> bool:
    if not os.path.exists(DM_OPTOUT_FILE):
        return False
    try:
        with open(DM_OPTOUT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return user_id in data
    except Exception:
        return False


def set_dm_optout(user_id: int):
    data = []
    if os.path.exists(DM_OPTOUT_FILE):
        try:
            with open(DM_OPTOUT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = []
    if user_id not in data:
        data.append(user_id)
    try:
        with open(DM_OPTOUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def get_ticket_category(guild: discord.Guild, is_legacy: bool):
    cat_id = LEGACY_CATEGORY_ID if is_legacy else MODERN_CATEGORY_ID
    return guild.get_channel(cat_id)

def get_queue_category(guild: discord.Guild, is_legacy: bool):
    cat_id = LEGACY_QUEUE_CATEGORY_ID if is_legacy else MODERN_QUEUE_CATEGORY_ID
    return guild.get_channel(cat_id)

def check_timeout(user_id: int, gamemode: str):
    key = (user_id, gamemode)
    if key in COOLDOWNS:
        remaining = COOLDOWNS[key] - time.time()
        if remaining > 0:
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            return True, f"{mins}p {secs}mp"
    return False, ""

def set_cooldown(user_id: int, gamemode: str, duration_seconds: int = 3600):
    COOLDOWNS[(user_id, gamemode)] = time.time() + duration_seconds

async def update_queue_message(message: discord.Message, q_data: dict, mode_key: str):
    players = q_data["players"]
    testers = q_data["testers"]
    
    players_text = ""
    if not players:
        players_text = "*- Empty -*"
    else:
        for i, p in enumerate(players, 1):
            status_icon = p.get('status', '⏳ WAITING')
            players_text += f"`{i}.` <@{p['id']}> (**{p['mc']}**) - `{status_icon}`\n"

    testers_text = ""
    for t_id in testers:
        testers_text += f"🛡️ <@{t_id}>\n"
    if not testers_text:
        testers_text = "*- No active tester -*"

    desc = f"**Spots:** {len(players)}/20\n\n**Players in queue:**\n{players_text}\n**Active Testers:**\n{testers_text}"
    
    embed = message.embeds[0]
    embed.description = desc
    await message.edit(embed=embed)


def _load_archive_index() -> list:
    if not os.path.exists(ARCHIVE_INDEX_FILE):
        return []
    try:
        with open(ARCHIVE_INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_archive_index(data: list):
    try:
        with open(ARCHIVE_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


async def archive_channel(channel: discord.abc.Messageable, closed_by: discord.abc.User, reason: str = "") -> None:
    """
    Saves the channel's full message history to a .txt transcript, sends it to
    the archive channel, and records it in a searchable index (ticket_archives.json).
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

    index = _load_archive_index()
    index.append({
        "channel_name": channel.name,
        "channel_id": channel.id,
        "closed_by": str(closed_by),
        "closed_by_id": getattr(closed_by, "id", None),
        "reason": reason,
        "message_count": msg_count,
        "archive_message_id": archive_msg.id,
        "archive_channel_id": ARCHIVE_CHANNEL_ID,
        "closed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    })
    _save_archive_index(index)
