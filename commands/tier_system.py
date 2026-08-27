"""
MCTier Bot - Tier System Panel Commands and Inactivity Monitor (commands/tier_system.py)
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import time
import asyncio

from commands.tier_ui import PanelSelectView
from commands.tier_utils import INACTIVE_TICKETS, archive_channel, is_dm_optout
from database import get_expired_cooldowns_async, delete_cooldown_async, list_ticket_archives_async
from config import STAFF_ROLE_ID, REGULATOR_ROLE_ID, get_gamemode_display_name


class TierSystemCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.inactivity_checker.start()
        self.cooldown_notifier.start()

    def cog_unload(self):
        self.inactivity_checker.cancel()
        self.cooldown_notifier.cancel()

    @tasks.loop(minutes=5)
    async def inactivity_checker(self):
        now = time.time()
        to_delete = []
        for ch_id, data in list(INACTIVE_TICKETS.items()):
            channel = self.bot.get_channel(ch_id)
            if not channel:
                to_delete.append(ch_id)
                continue

            try:
                last_act = data.get("last_activity", now)
                diff = now - last_act

                if not data["warned"] and diff >= 48 * 3600:
                    data["warned"] = True
                    data["warn_time"] = now
                    owner = channel.guild.get_member(data["owner_id"])
                    mention = owner.mention if owner else f"<@{data['owner_id']}>"
                    await channel.send(f"⚠️ {mention} Since no message has been sent for 48 hours, this ticket will be automatically closed in 4 hours if you don't reply!")
                
                elif data["warned"] and (now - data["warn_time"]) >= 4 * 3600:
                    await channel.send("🔒 The ticket was automatically closed due to inactivity.")
                    to_delete.append(ch_id)
                    await asyncio.sleep(2)
                    owner = channel.guild.get_member(data["owner_id"])
                    await archive_channel(channel, owner or self.bot.user, reason="Automatic closure due to inactivity (48h + 4h)")
                    await channel.delete(reason="Automatic closure due to inactivity (48h + 4h)")
            except Exception:
                pass

        for ch_id in to_delete:
            INACTIVE_TICKETS.pop(ch_id, None)

    @inactivity_checker.before_loop
    async def before_inactivity_checker(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def cooldown_notifier(self):
        expired_rows = await get_expired_cooldowns_async()

        for row in expired_rows:
            user_id = int(row["discord_id"])
            gamemode = row["gamemode"]
            await delete_cooldown_async(user_id, gamemode)

            if await is_dm_optout(user_id):
                continue

            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
                label = get_gamemode_display_name(gamemode)
                embed = discord.Embed(
                    title="⏳ Your cooldown has expired!",
                    description=f"Your testing cooldown in **{label}** has expired, you can now sign up for a test again!",
                    color=discord.Color.green()
                )
                await user.send(embed=embed)
            except Exception:
                pass

    @cooldown_notifier.before_loop
    async def before_cooldown_notifier(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        ch_id = message.channel.id
        if ch_id in INACTIVE_TICKETS:
            data = INACTIVE_TICKETS[ch_id]
            data["last_activity"] = time.time()
            if data["warned"]:
                data["warned"] = False
                await message.channel.send("✅ New message received, the 48-hour countdown has restarted!")

    def _is_regulator_or_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator:
            return True
        role_ids = {r.id for r in member.roles}
        return bool(role_ids & {STAFF_ROLE_ID, REGULATOR_ROLE_ID})

    @app_commands.command(name="ticketadd", description="Adds a user to the current ticket/channel.")
    @app_commands.describe(user="The user to add.")
    async def ticketadd(self, interaction: discord.Interaction, user: discord.Member):
        if not self._is_regulator_or_staff(interaction.user):
            return await interaction.response.send_message("❌ Only regulators or staff members can add a user to a ticket!", ephemeral=True)

        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("❌ This command can only be used in a text channel/ticket!", ephemeral=True)

        try:
            await interaction.channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Failed to add: `{e}`", ephemeral=True)

        if interaction.channel.id in INACTIVE_TICKETS:
            INACTIVE_TICKETS[interaction.channel.id]["last_activity"] = time.time()
            INACTIVE_TICKETS[interaction.channel.id]["warned"] = False

        await interaction.response.send_message(f"✅ {user.mention} was added to the ticket by {interaction.user.mention}.")

    @app_commands.command(name="ticketremove", description="Removes a user from the current ticket/channel.")
    @app_commands.describe(user="The user to remove.")
    async def ticketremove(self, interaction: discord.Interaction, user: discord.Member):
        if not self._is_regulator_or_staff(interaction.user):
            return await interaction.response.send_message("❌ Only regulators or staff members can remove a user from a ticket!", ephemeral=True)

        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message("❌ This command can only be used in a text channel/ticket!", ephemeral=True)

        try:
            await interaction.channel.set_permissions(user, view_channel=False, send_messages=False, read_message_history=False)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Failed to remove: `{e}`", ephemeral=True)

        await interaction.response.send_message(f"✅ {user.mention} was removed from the ticket by {interaction.user.mention}.")

    @app_commands.command(name="archives", description="Lists the most recently archived tickets.")
    @app_commands.describe(count="How many recent archives to list (max 25).", player="Filter by Minecraft name / channel name (optional).")
    @app_commands.checks.has_permissions(administrator=True)
    async def archives(self, interaction: discord.Interaction, count: int = 10, player: str = None):
        await interaction.response.defer(ephemeral=True)
        entries = await list_ticket_archives_async(limit=max(1, min(count, 25)), player=player)

        if not entries:
            return await interaction.followup.send("📭 No results found.", ephemeral=True)

        embed = discord.Embed(title="🗄️ Most Recently Archived Tickets", color=discord.Color.dark_grey())
        for e in entries:
            jump = f"https://discord.com/channels/{interaction.guild.id}/{e.get('archive_channel_id')}/{e.get('archive_message_id')}"
            embed.add_field(
                name=f"#{e.get('channel_name')}",
                value=f"Closed by: {e.get('closed_by')}\nReason: {e.get('reason') or '-'}\nMessages: {e.get('message_count')}\n[Open]({jump})",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="pingpanel", description="Sends the ping panel (dropdown).")
    @app_commands.describe(channel="The target channel to send the panel to.")
    @app_commands.checks.has_permissions(administrator=True)
    async def pingpanel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        embed = discord.Embed(
            title="🔔 Notifications & Pings",
            description="Choose a category for notifications from the dropdown menu below!",
            color=discord.Color.blue()
        )
        embed.set_footer(text="MCTier Management System")
        await target_channel.send(embed=embed, view=PanelSelectView("ping"))
        await interaction.response.send_message(f"✅ Ping panel sent to: {target_channel.mention}", ephemeral=True)

    @app_commands.command(name="queuepanel", description="Sends the queue panel (dropdown).")
    @app_commands.describe(channel="The target channel to send the panel to.")
    @app_commands.checks.has_permissions(administrator=True)
    async def queuepanel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        embed = discord.Embed(
            title="🎮 Queue Panel",
            description="Choose a gamemode from the menu below to open the queue.",
            color=discord.Color.green()
        )
        embed.set_footer(text="MCTier Management System")
        await target_channel.send(embed=embed, view=PanelSelectView("queue"))
        await interaction.response.send_message(f"✅ Queue panel sent to: {target_channel.mention}", ephemeral=True)

    @app_commands.command(name="hightestpanel", description="Sends the high tier test panel (dropdown).")
    @app_commands.describe(channel="The target channel to send the panel to.")
    @app_commands.checks.has_permissions(administrator=True)
    async def hightestpanel(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        target_channel = channel or interaction.channel
        embed = discord.Embed(
            title="⚔️ High Tier Tests",
            description="Choose a High Tier level from the menu below to open the ticket.",
            color=discord.Color.purple()
        )
        embed.set_footer(text="MCTier Management System")
        await target_channel.send(embed=embed, view=PanelSelectView("hightest"))
        await interaction.response.send_message(f"✅ High-Test panel sent to: {target_channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(TierSystemCog(bot))
