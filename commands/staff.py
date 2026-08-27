import discord
from discord.ext import commands
from discord import app_commands
import datetime

from config import (
    MODE_LIST, RANKS, POINTS, TICKET_TYPES, GAMEMODE_DISPLAY_NAMES,
    WEBSITE_URL, STAFF_ROLE_ID, REGULATOR_ROLE_ID,
    TESTER_ROLE_ID, EXTRA_STAFF_ROLE_IDS, ALLOWED_USER_IDS,
    DEBUG_ALLOWED_USERS, DEBUG_ALLOWED_ROLES,
    normalize_gamemode, get_gamemode_display_name, 
    get_gamemode_indicator, get_rank_value_min
)
from database import api_post_elo_instant, supabase_select

def is_staff_member(member: discord.Member) -> bool:
    if DEBUG_ALLOWED_USERS and member.id in DEBUG_ALLOWED_USERS:
        return True
    if DEBUG_ALLOWED_ROLES:
        if any(role.id in DEBUG_ALLOWED_ROLES for role in member.roles):
            return True
    if member.id in ALLOWED_USER_IDS:
        return True
    if any(role.id in [STAFF_ROLE_ID, REGULATOR_ROLE_ID, TESTER_ROLE_ID] + EXTRA_STAFF_ROLE_IDS for role in member.roles):
        return True
    return False

def is_regulator_member(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return is_staff_member(member)

class StaffCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="bulkimport", description="Bulk result import from a file (Admin/Regulator)")
    async def bulkimport(self, interaction: discord.Interaction, file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        if not is_regulator_member(interaction.user):
            await interaction.followup.send("❌ You don't have permission to use this command.", ephemeral=True)
            return

        try:
            content = await file.read()
            data = content.decode('utf-8')
            lines = data.strip().split('\n')
            success_count = 0

            for line in lines:
                parts = line.strip().split()
                if len(parts) < 3: 
                    continue
                username, mode, rank = parts[0], parts[1].lower(), parts[2].upper()
                mode_display = get_gamemode_display_name(mode)
                
                save_success = await api_post_elo_instant(
                    username=username, 
                    mode=mode_display, 
                    elo=rank, 
                    tester=interaction.user.display_name
                )
                if save_success: 
                    success_count += 1

            await interaction.followup.send(f"✅ Successfully imported/updated: {success_count} entries.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error during import: {e}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(StaffCog(bot))
