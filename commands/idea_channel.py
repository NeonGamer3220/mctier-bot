"""
MCTier Bot - Idea Channel (commands/idea_channel.py)

/ideachannel set <channel>   -> sets the ideas channel
/ideachannel remove          -> clears the setting
/ideachannel info            -> shows the current setting

If someone sends a message in the configured channel, the bot deletes the
original message and reposts it as a "New idea!" embed, reacting to it
with ✅ / ❌ so people can vote by reacting. Discord tracks and displays
the vote counts natively, so nothing needs to be stored for this.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    get_idea_channel_id_async, set_idea_channel_id_async, remove_idea_channel_id_async
)

log = logging.getLogger("mctier.commands.idea_channel")

APPROVE_EMOJI = "✅"
REJECT_EMOJI = "❌"


# ==========================================
# EMBED BUILDING
# ==========================================
def build_idea_embed(author: discord.abc.User, content: str) -> discord.Embed:
    embed = discord.Embed(
        title="💡 New idea!",
        description=(
            f"**Idea by:** {author.mention} | {author}\n\n"
            f"React with {APPROVE_EMOJI} to support this, or {REJECT_EMOJI} to reject it.\n\n"
            f"> {content}"
        ),
        color=discord.Color.gold()
    )
    return embed


# ==========================================
# COG
# ==========================================
class IdeaChannelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ideachannel = app_commands.Group(
        name="ideachannel",
        description="Settings for the ideas channel.",
        default_permissions=discord.Permissions(administrator=True)
    )

    @ideachannel.command(name="set", description="Sets the channel where ideas can be posted.")
    @app_commands.describe(channel="The channel where the idea embeds will appear.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await set_idea_channel_id_async(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ Ideas channel set to: {channel.mention}\n"
            f"From now on, every message sent here will automatically become an idea embed that people can vote on with {APPROVE_EMOJI}/{REJECT_EMOJI} reactions.",
            ephemeral=True
        )

    @ideachannel.command(name="remove", description="Clears the configured ideas channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel(self, interaction: discord.Interaction) -> None:
        await remove_idea_channel_id_async(interaction.guild.id)
        await interaction.response.send_message("✅ The ideas channel setting has been cleared.", ephemeral=True)

    @ideachannel.command(name="info", description="Shows the currently configured ideas channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def info(self, interaction: discord.Interaction) -> None:
        channel_id = await get_idea_channel_id_async(interaction.guild.id)
        if not channel_id:
            return await interaction.response.send_message("ℹ️ No ideas channel is currently configured.", ephemeral=True)

        channel = interaction.guild.get_channel(channel_id)
        mention = channel.mention if channel else f"`{channel_id}` (channel not found)"
        await interaction.response.send_message(f"ℹ️ Current ideas channel: {mention}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        channel_id = await get_idea_channel_id_async(message.guild.id)
        if not channel_id or message.channel.id != channel_id:
            return

        content = message.content.strip()
        attachments = message.attachments

        if not content and not attachments:
            return

        # If someone would send an empty message (e.g. just a command), ignore it
        if content.startswith("/"):
            return

        author = message.author
        can_delete = message.channel.permissions_for(message.guild.me).manage_messages

        try:
            embed = build_idea_embed(author, content or "*(attachment only)*")
            if attachments:
                embed.set_image(url=attachments[0].url)

            sent = await message.channel.send(embed=embed)
            await sent.add_reaction(APPROVE_EMOJI)
            await sent.add_reaction(REJECT_EMOJI)

            if can_delete:
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
        except Exception as exc:
            log.error("Error creating the idea embed: %s", exc)

    @set_channel.error
    @remove_channel.error
    @info.error
    async def idea_error_handler(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ This command requires administrator permission!", ephemeral=True)
        else:
            log.error("Error in the ideachannel command: %s", error)
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ An error occurred: `{error}`", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(IdeaChannelCog(bot))
