"""
MCTier Bot - Idea Channel (commands/idea_channel.py)

/ideachannel-set <channel>   -> sets the ideas channel
/ideachannel-remove          -> clears the setting
/ideachannel-info            -> shows the current setting

If someone sends a message in the configured channel, the bot deletes the
original message and sends a "New idea!" embed with ✅ / ❌ voting buttons
instead. The buttons are persistent and keep working after a restart.
"""

import json
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("mctier.commands.idea_channel")

CONFIG_FILE = "idea_channel_config.json"
VOTES_FILE = "idea_votes.json"


# ==========================================
# JSON HELPER FUNCTIONS
# ==========================================
def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.error("Error saving %s: %s", path, exc)


def get_idea_channel_id(guild_id: int) -> int | None:
    config = _load_json(CONFIG_FILE)
    value = config.get(str(guild_id))
    return int(value) if value else None


def set_idea_channel_id(guild_id: int, channel_id: int) -> None:
    config = _load_json(CONFIG_FILE)
    config[str(guild_id)] = channel_id
    _save_json(CONFIG_FILE, config)


def remove_idea_channel_id(guild_id: int) -> None:
    config = _load_json(CONFIG_FILE)
    if str(guild_id) in config:
        del config[str(guild_id)]
        _save_json(CONFIG_FILE, config)


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
    stored/read based on the actually clicked message
    (interaction.message.id), so this single View instance can be
    used for every idea message, even after a restart.
    """

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _handle_vote(self, interaction: discord.Interaction, vote: str) -> None:
        message = interaction.message
        votes = _load_json(VOTES_FILE)
        entry = votes.get(str(message.id))

        if entry is None:
            # If it isn't recorded yet for some reason (e.g. an old message), create it.
            author_id = None
            if message.embeds and message.embeds[0].description:
                pass
            entry = {"approve": [], "reject": [], "author_id": author_id, "content": ""}

        approve = set(entry.get("approve", []))
        reject = set(entry.get("reject", []))
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

        entry["approve"] = list(approve)
        entry["reject"] = list(reject)
        votes[str(message.id)] = entry
        _save_json(VOTES_FILE, votes)

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
        set_idea_channel_id(interaction.guild.id, channel.id)
        await interaction.response.send_message(
            f"✅ Ideas channel set to: {channel.mention}\n"
            f"From now on, every message sent here will automatically become an idea embed with voting buttons.",
            ephemeral=True
        )

    @ideachannel.command(name="remove", description="Clears the configured ideas channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_channel(self, interaction: discord.Interaction) -> None:
        remove_idea_channel_id(interaction.guild.id)
        await interaction.response.send_message("✅ The ideas channel setting has been cleared.", ephemeral=True)

    @ideachannel.command(name="info", description="Shows the currently configured ideas channel.")
    @app_commands.checks.has_permissions(administrator=True)
    async def info(self, interaction: discord.Interaction) -> None:
        channel_id = get_idea_channel_id(interaction.guild.id)
        if not channel_id:
            return await interaction.response.send_message("ℹ️ No ideas channel is currently configured.", ephemeral=True)

        channel = interaction.guild.get_channel(channel_id)
        mention = channel.mention if channel else f"`{channel_id}` (channel not found)"
        await interaction.response.send_message(f"ℹ️ Current ideas channel: {mention}", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        channel_id = get_idea_channel_id(message.guild.id)
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

            votes = _load_json(VOTES_FILE)
            votes[str(sent.id)] = {
                "approve": [],
                "reject": [],
                "author_id": author.id,
                "guild_id": message.guild.id,
                "content": content
            }
            _save_json(VOTES_FILE, votes)

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
