"""
MCTier Bot - Idea Channel (commands/idea_channel.py)

/ideachannel set <channel>   -> sets the ideas channel
/ideachannel remove          -> clears the setting
/ideachannel info            -> shows the current setting

If someone sends a message in the configured channel, the bot deletes the
original message and sends a "New idea!" embed with ✅ / ❌ voting buttons
instead. The buttons are persistent and keep working after a restart.
All settings and votes are stored in the database.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from database import (
    get_idea_channel_id_async, set_idea_channel_id_async, remove_idea_channel_id_async,
    get_idea_vote_async, save_idea_vote_async
)

log = logging.getLogger("mctier.commands.idea_channel")


# ==========================================
# EMBED BUILDING
# ==========================================
def build_idea_embed(author: discord.abc.User, content: str, approve: list, reject: list) -> discord.Embed:
    embed = discord.Embed(
        title="💡 New idea!",
        description=(
            f"**Idea by:** {author.mention} | {author}\n\n"
            f"✅ **I support this**       ❌ **I reject this**\n\n"
            f"> {content}"
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"👍 {len(approve)} in favor  •  👎 {len(reject)} against")
    return embed


# ==========================================
# PERSISTENT VOTING VIEW
# ==========================================
class IdeaVoteView(discord.ui.View):
    """
    A persistent View with static custom_ids. Votes are always
    stored/read (in the database) based on the actually clicked
    message (interaction.message.id), so this single View instance can
    be used for every idea message, even after a restart.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _handle_vote(self, interaction: discord.Interaction, vote: str) -> None:
        message = interaction.message
        entry = await get_idea_vote_async(message.id)

        if entry is None:
            entry = {"approve": [], "reject": [], "author_id": None, "guild_id": interaction.guild_id, "content": ""}

        approve = set(entry.get("approve") or [])
        reject = set(entry.get("reject") or [])
        uid = interaction.user.id

        if vote == "approve":
            if uid in approve:
                approve.discard(uid)
            else:
                approve.add(uid)
                reject.discard(uid)
        else:
            if uid in reject:
                reject.discard(uid)
            else:
                reject.add(uid)
                approve.discard(uid)

        await save_idea_vote_async(
            message_id=message.id,
            guild_id=entry.get("guild_id") or interaction.guild_id,
            author_id=entry.get("author_id"),
            content=entry.get("content", ""),
            approve=list(approve),
            reject=list(reject),
        )

        # Update button labels
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == "idea_vote_approve":
                    child.label = str(len(approve))
                elif child.custom_id == "idea_vote_reject":
                    child.label = str(len(reject))

        embed = message.embeds[0] if message.embeds else None
        if embed:
            embed.set_footer(text=f"👍 {len(approve)} in favor  •  👎 {len(reject)} against")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="0", emoji="✅", style=discord.ButtonStyle.success, custom_id="idea_vote_approve")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_vote(interaction, "approve")

    @discord.ui.button(label="0", emoji="❌", style=discord.ButtonStyle.danger, custom_id="idea_vote_reject")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle_vote(interaction, "reject")


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
            f"From now on, every message sent here will automatically become an idea embed with voting buttons.",
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
            embed = build_idea_embed(author, content or "*(attachment only)*", [], [])
            if attachments:
                embed.set_image(url=attachments[0].url)

            view = IdeaVoteView()
            sent = await message.channel.send(embed=embed, view=view)

            await save_idea_vote_async(
                message_id=sent.id,
                guild_id=message.guild.id,
                author_id=author.id,
                content=content,
                approve=[],
                reject=[],
            )

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
