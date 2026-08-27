"""
MCTier Bot - SendMessage Command (commands/send_message.py)
/sendmessage <discordid> <type> <channel>

The command sends the appropriate text via DM to the (still off-server)
player, and then when the player joins the server, the bot automatically
adds them to the specified channel. For the "High ticket" type, it also
sends a reminder DM after 24 hours if the player hasn't joined by then.

Pending invites are stored in the database (Supabase `pending_invites`
table) instead of a local JSON file, so they survive a bot restart or
redeploy.
"""

import logging
import time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import db, arun

log = logging.getLogger("mctier.commands.send_message")

INVITE_URL = "https://discord.gg/7fanAQDxaN"

MESSAGE_TEMPLATES = {
    "magas": (
        "Hi! You've been queued for a high test on the MCTier server. If you'd like to play it, "
        "you'll have 48 hours to join the server, at which point the bot will automatically add you to the "
        "ticket, and the bot will also send a reminder message after 24 hours!\n"
        f"Join: {INVITE_URL}"
    ),
    "tournament": (
        "Hi! There is currently a tournament in progress on the MCTier server. If you'd like to play it, "
        "you'll have 24 hours to join the server, at which point the bot will automatically add you to your match.\n"
        f"Join: {INVITE_URL}"
    )
}

REMINDER_TEMPLATE = (
    "⏰ Reminder! A high test is still waiting for you on the MCTier server. "
    "24 hours of your 48-hour window have already passed, don't forget to join!\n"
    f"Join: {INVITE_URL}"
)

WINDOW_SECONDS = {
    "magas": 48 * 3600,
    "tournament": 24 * 3600
}


def _row_age_seconds(created_at_raw) -> float | None:
    if not created_at_raw:
        return None
    try:
        created_dt = datetime.fromisoformat(str(created_at_raw).replace("Z", "+00:00"))
        return time.time() - created_dt.timestamp()
    except Exception:
        return None


class SendMessageCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @app_commands.command(
        name="sendmessage",
        description="Send a DM to a player (High ticket / Tournament), with automatic channel access on join."
    )
    @app_commands.describe(
        discordid="The Discord ID of the target person.",
        tipus="The type of message.",
        csatorna="The channel the bot will automatically add the player to as soon as they join the server."
    )
    @app_commands.choices(tipus=[
        app_commands.Choice(name="High ticket", value="magas"),
        app_commands.Choice(name="Tournament", value="tournament"),
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def sendmessage(
        self,
        interaction: discord.Interaction,
        discordid: str,
        tipus: app_commands.Choice[str],
        csatorna: discord.TextChannel
    ) -> None:
        try:
            user_id = int(discordid.strip())
        except ValueError:
            return await interaction.response.send_message("❌ Invalid Discord ID!", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            target_user = await self.bot.fetch_user(user_id)
        except Exception:
            return await interaction.followup.send("❌ No user found with this ID!", ephemeral=True)

        message_text = MESSAGE_TEMPLATES[tipus.value]

        try:
            await target_user.send(message_text)
        except discord.Forbidden:
            return await interaction.followup.send(f"❌ {target_user.mention} has disabled private messages, delivery failed!", ephemeral=True)
        except Exception as exc:
            log.error("Error sending DM: %s", exc)
            return await interaction.followup.send(f"❌ An error occurred while sending the DM: `{exc}`", ephemeral=True)

        # Mark any older, still-pending invite of the same type for this user as completed,
        # so it doesn't also fire a reminder/auto-add alongside the new one.
        existing = await arun(db.get_pending_invite_for_user, user_id)
        for entry in existing:
            if entry.get("invite_type") == tipus.value:
                await arun(db.mark_invite_completed, entry["id"])

        await arun(db.create_pending_invite, user_id, tipus.value, csatorna.id)

        await interaction.followup.send(
            f"✅ Message sent to {target_user.mention} ({tipus.name}). As soon as they join the server, we'll automatically add them to the {csatorna.mention} channel.",
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        pending = await arun(db.get_pending_invite_for_user, member.id)
        if not pending:
            return

        for entry in pending:
            channel = member.guild.get_channel(entry["ticket_channel_id"])
            if not channel:
                continue
            try:
                await channel.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)
                label = "High Test" if entry["invite_type"] == "magas" else "Tournament"
                await channel.send(f"👋 {member.mention} joined! ({label})")
            except Exception as exc:
                log.error("Error adding member to channel: %s", exc)
            await arun(db.mark_invite_completed, entry["id"])

    @tasks.loop(minutes=30)
    async def reminder_loop(self):
        pending = await arun(db.list_pending_invites)
        if not pending:
            return

        for entry in pending:
            window = WINDOW_SECONDS.get(entry.get("invite_type"), 48 * 3600)
            age = _row_age_seconds(entry.get("created_at"))
            if age is None:
                continue

            if age >= window:
                # Deadline expired, mark as completed so it stops being tracked
                await arun(db.mark_invite_completed, entry["id"])
                continue

            if entry.get("invite_type") == "magas" and not entry.get("reminder_sent") and age >= 24 * 3600:
                try:
                    user = await self.bot.fetch_user(entry["discord_id"])
                    await user.send(REMINDER_TEMPLATE)
                except Exception:
                    pass
                await arun(db.mark_reminder_sent, entry["id"])

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SendMessageCog(bot))
