"""
MCTier Bot - Full Config Module
All original gamemodes, Elo settings and the new object-oriented architecture.
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# BASIC SETTINGS AND DISCORD IDs
# ==========================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
STAFF_ROLE_ID = int(os.getenv("STAFF_ROLE_ID", "0"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
EXTRA_STAFF_ROLE_IDS = [int(os.getenv("EXTRA_STAFF_ROLE_IDS", "0"))] if os.getenv("EXTRA_STAFF_ROLE_IDS") else []
ALLOWED_USER_IDS = [int(x.strip()) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip()]
BOT_COMMANDS_CHANNEL_ID = int(os.getenv("BOT_COMMANDS", "0"))
QUEUES_CATEGORY = int(os.getenv("QUEUES_CATEGORY", "0"))

REGULATOR_ROLE_ID = int(os.getenv("REGULATOR_ROLE_ID", "0"))
TESTER_ROLE_ID = int(os.getenv("TESTER_ROLE_ID", "0"))

BAN_CHANNEL_ID = int(os.getenv("BAN_CHANNEL_ID", "0"))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "1496272517759897751"))
HIGH_TEST_CHANNEL_ID = int(os.getenv("HIGH_TEST_CHANNEL_ID", "0"))
HELP_TICKET_CATEGORY_ID = int(os.getenv("HELP_TICKET_CATEGORY_ID", "1524391860687339733"))
BANNED_ROLE_ID = int(os.getenv("BANNED_ROLE_ID", "1496877749388972143"))
TIER_RESULTS_CHANNEL_ID = int(os.getenv("TIER_RESULTS_CHANNEL_ID", "0"))
ARCHIVE_CHANNEL_ID = int(os.getenv("ARCHIVE_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1505522005028503582"))
MODERN_RESULT_CHANNEL_ID = int(os.getenv("RESULTS_CHANNEL_ID", "1469752490965864651"))

# ==========================================
# SYSTEM AND WEBSITE SETTINGS
# ==========================================
USE_SUPABASE_API = True
SUPABASE_URL = os.getenv("SUPABASE_URL", "ENTER_YOUR_SUPABASE_URL_HERE")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_PG_URL = os.getenv("SUPABASE_PG_URL", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

WEBSITE_URL = os.getenv("WEBSITE_URL", "").rstrip("/")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")
MINECRAFT_API_URL = os.getenv("MINECRAFT_API_URL", "http://localhost:8080").rstrip("/")

HTTP_TIMEOUT_SECONDS = 10
COOLDOWN_SECONDS = 30 * 24 * 60 * 60
TESTS_TABLE = "tests"

# Linking settings
LINK_CODE_LENGTH = 8
LINK_CODE_EXPIRY_MINUTES = 10

# ==========================================
# GAMEMODES AND RANKS (DATABASE)
# ==========================================
TICKET_TYPES = [
    ("Vanilla", "vanilla", "<:vanilla:1542249778375692348>"),
    ("UHC", "uhc", "<:uhc:1542249797925474385>"),
    ("Pot", "pot", "<:pot:1542249910466912376>"),
    ("NethPot", "nethpot", "<:nethpot:1542249946906894426>"),
    ("SMP", "smp", "<:smp:1542249842485624863>"),
    ("Sword", "sword", "<:sword:1542249819874271333>"),
    ("Axe", "axe", "<:axe:1542249745819504670>"),
    ("Mace", "mace", "<:mace:1542249881274421350>"),
]

# Combined list for all gamemodes
ALL_TICKET_TYPES = TICKET_TYPES

MODE_LIST = [t[0] for t in ALL_TICKET_TYPES]
GAMEMODE_DISPLAY_TO_KEY = {display.lower(): key for display, key, _ in ALL_TICKET_TYPES}

RANKS = [
    "Unranked", "LT5", "HT5", "LT4", "HT4", 
    "LT3", "HT3", "LT2", "HT2", "LT1", "HT1"
]

RANK_FULL_NAMES = {
    "Unranked": "Unranked",
    "LT5": "Low Tier 5", "HT5": "High Tier 5",
    "LT4": "Low Tier 4", "HT4": "High Tier 4",
    "LT3": "Low Tier 3", "HT3": "High Tier 3",
    "LT2": "Low Tier 2", "HT2": "High Tier 2",
    "LT1": "Low Tier 1", "HT1": "High Tier 1",
}

def get_rank_full_name(rank: str) -> str:
    if not rank:
        return "Unranked"
    return RANK_FULL_NAMES.get(rank.strip().upper(), rank)

POINTS = {
    "Unranked": 0, "LT5": 1, "HT5": 2, "LT4": 3, "HT4": 4,
    "LT3": 6, "HT3": 10, "LT2": 16, "HT2": 22, "LT1": 40, "HT1": 60,
}

GAMEMODE_ALIASES = {
    "nethpot": "nethpot", "uhc": "uhc",
}

GAMEMODE_DISPLAY_NAMES = {
    "vanilla": "Vanilla", "uhc": "UHC", "pot": "Pot", "nethpot": "NethPot",
    "smp": "SMP", "sword": "Sword", "axe": "Axe", "mace": "Mace",
}

GAMEMODE_INDICATORS = {
    "mace": "<:mace:1542249881274421350>", 
    "sword": "<:sword:1542249819874271333>",
    "vanilla": "<:vanilla:1542249778375692348>", 
    "uhc": "<:uhc:1542249797925474385>",
    "pot": "<:pot:1542249910466912376>", 
    "nethpot": "<:nethpot:1542249946906894426>",
    "smp": "<:smp:1542249842485624863>", 
    "axe": "<:axe:1542249745819504670>",
}

# ==========================================
# SIMPLE HELPER FUNCTIONS
# ==========================================
def normalize_gamemode(mode: str) -> str:
    if not mode:
        return mode
    normalized = mode.lower().strip()
    return GAMEMODE_ALIASES.get(normalized, normalized)

def get_gamemode_display_name(mode_key: str) -> str:
    if not mode_key:
        return mode_key
    if mode_key in GAMEMODE_DISPLAY_NAMES:
        return GAMEMODE_DISPLAY_NAMES[mode_key]
    return GAMEMODE_DISPLAY_NAMES.get(mode_key.lower().strip(), mode_key)

def get_gamemode_indicator(mode_key: str, is_open: bool = True) -> str:
    if is_open:
        return GAMEMODE_INDICATORS.get(mode_key.lower().strip(), "🟢")
    return "🔴"

def get_rank_value_min(rank: str) -> int:
    return POINTS.get(rank, 0)

# ==========================================
# COMPATIBILITY CLASS (FOR THE NEW BOT COMPONENTS)
# ==========================================
@dataclass
class Config:
    bot_token: str = DISCORD_TOKEN or ""
    guild_id: int = GUILD_ID
    ticket_category_id: int = TICKET_CATEGORY_ID
    results_channel_id: int = int(os.getenv("RESULTS_CHANNEL_ID", "0"))
    tier_results_channel_id: int = TIER_RESULTS_CHANNEL_ID
    regulator_role_id: int = REGULATOR_ROLE_ID
    staff_role_id: int = STAFF_ROLE_ID
    banned_role_id: int = BANNED_ROLE_ID
    supabase_url: str = SUPABASE_URL
    supabase_key: str = SUPABASE_KEY
    auto_start_poll_seconds: int = int(os.getenv("AUTO_START_POLL_SECONDS", "30"))

config = Config()
