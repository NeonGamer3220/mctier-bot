"""
MCTier Bot - Support Ticket Panel (commands/support_ticket.py)

Tracks open support/help tickets in memory (not persisted to disk), the
same way the tier queue/ticket system does elsewhere in this bot. This
just needs to know "does this user currently have an open ticket
channel", which the channel's own existence already guarantees - so
there's nothing here that actually needs database persistence across a
restart.
"""

import discord
from discord.ext import commands
from discord import app_commands
import time
import asyncio

from config import STAFF_ROLE_ID, HELP_TICKET_CATEGORY_ID

PANEL_COLOR = 0xB026FF

# channel_id: { "owner_id": ..., "last_msg_time": ..., "warned": bool }
OPEN_HELP_TICKETS: dict[int, dict] = {}


def user_has_open_help_ticket(guild: discord.Guild, user_id: int) -> bool:
    for ch_id, info in list(OPEN_HELP_TICKETS.items()):
        if info.get("owner_id") == user_id:
            if guild.get_channel(ch_id):
                return True
            # Channel no longer exists (e.g. bot restarted and it was deleted meanwhile) - clean it up.
            OPEN_HELP_TICKETS.pop(ch_id, None)
    return False


class SupportTicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="close_support_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        ch = interaction.channel
        OPEN_HELP_TICKETS.pop(ch.id, None)

        await ch.send("🔒 The ticket will be deleted in 5 seconds...")
        await asyncio.sleep(5)
        try:
            await ch.delete()
        except Exception:
            pass


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 Open Support Request", style=discord.ButtonStyle.primary, custom_id="open_support_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        if user_has_open_help_ticket(guild, interaction.user.id):
            return await interaction.followup.send("❌ You already have an open support ticket!", ephemeral=True)

        category = guild.get_channel(HELP_TICKET_CATEGORY_ID) if HELP_TICKET_CATEGORY_ID else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        staff_role = guild.get_role(STAFF_ROLE_ID) if STAFF_ROLE_ID else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        ch_name = f"help-{interaction.user.name}".lower()[:99]
        channel = await guild.create_text_channel(name=ch_name, category=category, overwrites=overwrites)

        OPEN_HELP_TICKETS[channel.id] = {
            "owner_id": interaction.user.id,
            "last_msg_time": time.time(),
            "warned": False,
        }

        embed = discord.Embed(
            title="🎫 MCTier | Support Request",
            description=f"Welcome {interaction.user.mention}!\n\nPlease describe in detail what we can help you with. The Staff team will respond soon.",
            color=PANEL_COLOR
        )
        await channel.send(content=f"{interaction.user.mention} {staff_role.mention if staff_role else ''}", embed=embed, view=SupportTicketCloseView())
        await interaction.followup.send(f"✅ Support request created: {channel.mention}", ephemeral=True)


class TicketPanelCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ticketpanel", description="Places the MCTier support request ticket panel. (Admin)")
    async def ticketpanel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admins only!", ephemeral=True)

        embed = discord.Embed(
            title="🎫 MCTier Ticket",
            description=(
                "If you need help, open a request.\n\n"
                "**Important**\nYou can only have one open support request at a time.\n\n"
                "**Automatic closure**\nThe ticket automatically closes after 48 hours of inactivity."
            ),
            color=PANEL_COLOR
        )
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message("✅ Panel placed!", ephemeral=True)


async def setup(bot):
    await bot.add_cog(TicketPanelCog(bot))
