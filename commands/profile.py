"""
MCTier Bot - Profile Command (commands/profile.py)
"""

import logging
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    LEGACY_TICKET_TYPES,
    get_gamemode_display_name,
    get_gamemode_indicator,
    normalize_gamemode,
)
from database import (
    arun,
    db,
    get_linked_minecraft_name_async,
)

log = logging.getLogger("mctier.commands.profile")

LEGACY_KEYS = {key.lower() for _, key, _ in LEGACY_TICKET_TYPES}


def _columns(entries: list[str], columns: int = 3) -> list[str]:
    """Splits the entries into `columns` roughly equal-length lists,
    so they can be displayed side by side as inline fields
    (3 inline fields in a Discord embed = 3 columns)."""
    if not entries:
        return []
    result = [[] for _ in range(columns)]
    for i, entry in enumerate(entries):
        result[i % columns].append(entry)
    return ["\n".join(col) if col else "\u200b" for col in result]

class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="View your own or another player's profile.")
    @app_commands.describe(
        user="The Discord user whose profile you want to view.",
        minecraft_name="Or search directly by Minecraft name."
    )
    async def profile(
        self, 
        interaction: discord.Interaction, 
        user: discord.User | None = None,
        minecraft_name: str | None = None
    ) -> None:
        await interaction.response.defer()

        target_user = user
        mc_name = minecraft_name
        discord_id = None

        if mc_name:
            if db._client:
                resp = db._client.table("linked_accounts").select("discord_id").ilike("minecraft_name", mc_name).execute()
                if resp.data and len(resp.data) > 0:
                    discord_id = resp.data[0].get("discord_id")
        elif target_user:
            discord_id = target_user.id
            mc_name = await get_linked_minecraft_name_async(discord_id)
        else:
            target_user = interaction.user
            discord_id = target_user.id
            mc_name = await get_linked_minecraft_name_async(discord_id)

        if not mc_name:
            search_term = minecraft_name or (target_user.display_name if target_user else "Given user")
            await interaction.followup.send(
                f"❌ No linked Minecraft account was found for **{search_term}**!",
                ephemeral=True
            )
            return

        display_discord_user = self.bot.get_user(discord_id) if discord_id else None
        mention_str = display_discord_user.mention if display_discord_user else (f"<@{discord_id}>" if discord_id else "*No Discord ID*")

        embed = discord.Embed(
            title=f"👤 Player Profile: {mc_name}",
            color=discord.Color.from_rgb(163, 136, 238)
        )
        embed.add_field(name="Minecraft Name", value=f"`{mc_name}`", inline=True)
        embed.add_field(name="Discord Account", value=mention_str, inline=True)
        embed.set_thumbnail(url=f"https://minotar.net/helm/{mc_name}/256.png")

        modern_results = []
        legacy_results = []

        if db._client:
            try:
                tests_resp = db._client.table("tests").select("*").ilike("username", mc_name).execute()
                tests_data = tests_resp.data if tests_resp.data else []
            except Exception as e:
                log.error("Error fetching tests for profile: %s", e)
                tests_data = []

            for row in tests_data:
                raw_mode = row.get("gamemode", "")
                rank = row.get("rank", "Unranked")
                norm_mode = normalize_gamemode(raw_mode)
                display_name = get_gamemode_display_name(raw_mode)

                indicator = get_gamemode_indicator(norm_mode)
                entry = f"{indicator} **{display_name}:** `{rank}`"

                if norm_mode in LEGACY_KEYS:
                    legacy_results.append(entry)
                else:
                    modern_results.append(entry)

        # --- Modern results, in 3 columns ---
        embed.add_field(name="📊 Modern Tier Results", value="\u200b", inline=False)
        if modern_results:
            for col in _columns(modern_results, 3):
                embed.add_field(name="\u200b", value=col[:1024], inline=True)
        else:
            embed.add_field(name="\u200b", value="*No modern results recorded.*", inline=False)

        # --- Legacy results, in 3 columns ---
        embed.add_field(name="📜 Legacy Tier Results", value="\u200b", inline=False)
        if legacy_results:
            for col in _columns(legacy_results, 3):
                embed.add_field(name="\u200b", value=col[:1024], inline=True)
        else:
            embed.add_field(name="\u200b", value="*No legacy results recorded.*", inline=False)

        embed.set_footer(text=f"MCTier • Retrieved: {interaction.created_at.strftime('%Y-%m-%d %H:%M')}")

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
