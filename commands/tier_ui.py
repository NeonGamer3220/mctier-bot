"""
MCTier Bot - Tier UI & Modals (commands/tier_ui.py)
High Test suggestion submission modal (does not close the channel immediately) and tier-based High Test options.
"""

import discord
import asyncio
import time
from config import TICKET_TYPES, ALL_TICKET_TYPES, get_gamemode_display_name, get_rank_full_name, STAFF_ROLE_ID, REGULATOR_ROLE_ID, RANKS, MODERN_RESULT_CHANNEL_ID, LOG_CHANNEL_ID, TESTER_ROLE_ID
from commands.tier_utils import (
    ACTIVE_QUEUES, INACTIVE_TICKETS, VALID_HT_TIERS, ALLOWED_QUEUE_TIERS,
    get_ticket_category, get_queue_category, update_queue_message, 
    set_cooldown, check_timeout, THEME_LIGHT_PURPLE, archive_channel,
    is_dm_optout, set_dm_optout, fetch_3d_skin_file
)
from commands.ban_enforcement import is_banned_by_role
from database import get_linked_minecraft_name_async, save_test_result_supabase, get_player_rank_async


def _find_gamemode_tester_role(guild: discord.Guild, gamemode_label: str):
    """Looks up the gamemode-specific Tester role on the server, matching
    either the "{label} Tester" or "{label} Teszter" (Hungarian) naming."""
    for suffix in ("Tester", "Teszter"):
        role = discord.utils.get(guild.roles, name=f"{gamemode_label} {suffix}")
        if role:
            return role
    return None


def _can_give_tiers(member: discord.Member) -> bool:
    """Only the Tester role (or admin) can click the 'Next' button
    and give/record a tier."""
    if member.guild_permissions.administrator:
        return True
    return any(r.id == TESTER_ROLE_ID for r in member.roles)


def _can_open_queue(member: discord.Member, guild: discord.Guild, gamemode_label: str):
    """Decides whether the member can open the queue for a given gamemode.

    - Admin / Staff / Regulator can always open it.
    - Otherwise the member must have the general TESTER_ROLE_ID
      ("Tester") role, AND - if a role with that name exists on the
      server - the "{gamemode_label} Tester" (e.g. "Sword Tester")
      gamemode-specific role as well. If someone only has the general
      Tester role but not the one for the specific gamemode, they
      cannot open the queue in that mode.

    Return value: (allowed: bool, error_message: str | None)
    """
    if member.guild_permissions.administrator:
        return True, None

    role_ids = {r.id for r in member.roles}
    if role_ids & {STAFF_ROLE_ID, REGULATOR_ROLE_ID}:
        return True, None

    general_tester_role = guild.get_role(TESTER_ROLE_ID)
    if not general_tester_role or general_tester_role not in member.roles:
        return False, "❌ You don't have permission to open a queue: you need the **Tester** role."

    gamemode_role = _find_gamemode_tester_role(guild, gamemode_label)
    if not gamemode_role or gamemode_role not in member.roles:
        return False, f"❌ You don't have permission for this gamemode: you're missing the **{gamemode_label} Tester** role."

    return True, None


class HighTestNoteModal(discord.ui.Modal, title="Submit Note"):
    def __init__(self, player_id: int, player_mc: str, gamemode: str):
        super().__init__()
        self.player_id = player_id
        self.player_mc = player_mc
        self.gamemode = gamemode

        self.note_input = discord.ui.TextInput(
            label="Note / Opinion",
            placeholder="Write your suggestion or the test details...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1500
        )
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        note_text = self.note_input.value.strip()
        user = interaction.user

        embed = discord.Embed(
            title=f"💬 Note received ({get_gamemode_display_name(self.gamemode)})",
            description=note_text,
            color=discord.Color.gold()
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url if user.display_avatar else None)
        embed.add_field(name="Player Involved", value=f"<@{self.player_id}> (**{self.player_mc}**)", inline=False)
        embed.set_footer(text="MCTier Management System")

        if interaction.channel.id in INACTIVE_TICKETS:
            INACTIVE_TICKETS[interaction.channel.id]["last_activity"] = time.time()
            INACTIVE_TICKETS[interaction.channel.id]["warned"] = False

        reg_ping = f"<@&{REGULATOR_ROLE_ID}>" if REGULATOR_ROLE_ID else ""
        await interaction.channel.send(content=reg_ping or None, embed=embed)
        await interaction.followup.send("✅ Note successfully submitted to the ticket!", ephemeral=True)


class HighTestSuggestionModal(discord.ui.Modal, title="Submit Tier Suggestion"):
    def __init__(self, player_id: int, player_mc: str, gamemode: str):
        super().__init__()
        self.player_id = player_id
        self.player_mc = player_mc
        self.gamemode = gamemode

        self.tier_input = discord.ui.TextInput(
            label="Javasolt Tier",
            placeholder="pl. LT2, HT1",
            required=True,
            max_length=20
        )
        self.note_input = discord.ui.TextInput(
            label="Note / Justification (optional)",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=1000
        )
        self.add_item(self.tier_input)
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tier = self.tier_input.value.strip().upper()
        if tier not in VALID_HT_TIERS and tier != "UNRANKED":
            return await interaction.followup.send(f"❌ Invalid tier format: `{tier}`. Allowed: HT1-LT5, Unranked", ephemeral=True)

        note_text = self.note_input.value.strip()
        user = interaction.user

        embed = discord.Embed(
            title=f"📊 Tier Suggestion ({get_gamemode_display_name(self.gamemode)})",
            color=discord.Color.purple()
        )
        embed.add_field(name="Player", value=f"<@{self.player_id}> (**{self.player_mc}**)", inline=False)
        embed.add_field(name="Javasolt Tier", value=f"**{tier}**", inline=True)
        if note_text:
            embed.add_field(name="Note", value=note_text, inline=False)
        embed.set_footer(text=f"Suggested by: {user.display_name} | Awaiting review from a Regulator")

        if interaction.channel.id in INACTIVE_TICKETS:
            INACTIVE_TICKETS[interaction.channel.id]["last_activity"] = time.time()
            INACTIVE_TICKETS[interaction.channel.id]["warned"] = False

        reg_ping = f"<@&{REGULATOR_ROLE_ID}>" if REGULATOR_ROLE_ID else ""
        await interaction.channel.send(content=(reg_ping or None), embed=embed)
        await interaction.followup.send("✅ Tier suggestion submitted! A Regulator needs to review it and record it on the tierlist website.", ephemeral=True)


class HighTestTicketView(discord.ui.View):
    def __init__(self, player_id: int, player_mc: str, gamemode: str):
        super().__init__(timeout=None)
        self.player_id = player_id
        self.player_mc = player_mc
        self.gamemode = gamemode

    @discord.ui.button(label="📝 Tier Suggestion", style=discord.ButtonStyle.green, custom_id="hightest_suggest_btn")
    async def suggest_tier(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = HighTestSuggestionModal(
            player_id=self.player_id,
            player_mc=self.player_mc,
            gamemode=self.gamemode
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.gray, custom_id="hightest_close_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_staff = interaction.user.guild_permissions.administrator or any(r.id in [STAFF_ROLE_ID, REGULATOR_ROLE_ID] for r in interaction.user.roles)
        if not is_staff and interaction.user.id != self.player_id:
            return await interaction.response.send_message("❌ Only the player or staff can close this ticket!", ephemeral=True)

        if interaction.channel.id in INACTIVE_TICKETS:
            del INACTIVE_TICKETS[interaction.channel.id]

        await interaction.response.send_message("🔒 Ticket closed. The channel will be deleted in 3 seconds...", ephemeral=True)
        await archive_channel(interaction.channel, interaction.user, reason="High Test closed without a result")
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"High Test closed: {interaction.user.display_name}")
        except Exception:
            pass


class TestFeedbackModal(discord.ui.Modal, title="Rate the Test"):
    def __init__(self, player_id: int, gamemode_label: str):
        super().__init__()
        self.player_id = player_id
        self.gamemode_label = gamemode_label

        self.feedback_input = discord.ui.TextInput(
            label="Your feedback on the test",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000
        )
        self.add_item(self.feedback_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        log_chan = interaction.client.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
        embed = discord.Embed(
            title=f"⭐ Test Rating ({self.gamemode_label})",
            description=self.feedback_input.value.strip(),
            color=discord.Color.gold()
        )
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
        embed.set_footer(text=f"Discord ID: {interaction.user.id}")
        if log_chan:
            try:
                await log_chan.send(embed=embed)
            except Exception:
                pass
        await interaction.followup.send("✅ Thank you for the feedback!", ephemeral=True)


class TestFeedbackView(discord.ui.View):
    def __init__(self, player_id: int, gamemode_label: str):
        super().__init__(timeout=None)
        self.player_id = player_id
        self.gamemode_label = gamemode_label

    @discord.ui.button(label="⭐ Rate", style=discord.ButtonStyle.blurple, custom_id="dm_feedback_btn")
    async def give_feedback(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message("❌ This is not your notification!", ephemeral=True)
        await interaction.response.send_modal(TestFeedbackModal(self.player_id, self.gamemode_label))

    @discord.ui.button(label="🔕 Don't send more of these messages", style=discord.ButtonStyle.gray, custom_id="dm_optout_btn")
    async def opt_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player_id:
            return await interaction.response.send_message("❌ This is not your notification!", ephemeral=True)
        await set_dm_optout(interaction.user.id)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("🔕 Alright, we won't send you any more of these private messages!", ephemeral=True)


class TestResultModal(discord.ui.Modal, title="Record Test Result"):
    def __init__(self, player_id: int, player_mc: str, gamemode: str, queue_ch_id: int = None):
        super().__init__()
        self.player_id = player_id
        self.player_mc = player_mc
        self.gamemode = gamemode
        self.queue_ch_id = queue_ch_id

        self.tier_input = discord.ui.TextInput(
            label="Achieved Rank (Tier)",
            placeholder="e.g. LT3, HT2, Unranked",
            required=True,
            max_length=20
        )
        self.add_item(self.tier_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tier = self.tier_input.value.strip().upper()
        if tier not in ALLOWED_QUEUE_TIERS:
            return await interaction.followup.send(
                "❌ A regular queue test can only give **up to LT3**. If the player achieved a higher rank, open a **High Test** request for them in the appropriate mode!",
                ephemeral=True
            )

        guild = interaction.guild
        player_user = guild.get_member(self.player_id) or await guild.fetch_member(self.player_id)
        tester_user = interaction.user
        label = get_gamemode_display_name(self.gamemode)

        try:
            previous_rank = await get_player_rank_async(self.player_mc, label)
        except Exception:
            previous_rank = "Unranked"

        try:
            await save_test_result_supabase(player_user, self.player_mc, label, tier, tester_user, interaction)
        except Exception:
            pass

        await set_cooldown(self.player_id, self.gamemode, 3600)

        if self.queue_ch_id and self.queue_ch_id in ACTIVE_QUEUES:
            q_data = ACTIVE_QUEUES[self.queue_ch_id]
            q_data["players"] = [p for p in q_data["players"] if p["id"] != self.player_id]
            try:
                chan = guild.get_channel(self.queue_ch_id)
                if chan and q_data.get("msg_id"):
                    msg = await chan.fetch_message(q_data["msg_id"])
                    await update_queue_message(msg, q_data, self.gamemode)
            except Exception:
                pass

        await interaction.followup.send(f"✅ Successfully recorded! Player: **{self.player_mc}** | Rank: **{tier}**", ephemeral=True)

        # Post the result in the results channel
        results_chan = guild.get_channel(MODERN_RESULT_CHANNEL_ID) if MODERN_RESULT_CHANNEL_ID else None
        if results_chan:
            result_embed = discord.Embed(
                title="🏆 Test Results",
                color=discord.Color.from_rgb(255, 0, 0)
            )
            result_embed.add_field(name="Player", value=f"{player_user.mention} (**{self.player_mc}**)", inline=False)
            result_embed.add_field(name="Tester", value=tester_user.mention, inline=True)
            result_embed.add_field(name="Previous Rank", value=get_rank_full_name(previous_rank), inline=True)
            result_embed.add_field(name="Earned Rank", value=get_rank_full_name(tier), inline=True)
            try:
                skin_file = await fetch_3d_skin_file(self.player_mc)
                if skin_file:
                    result_embed.set_thumbnail(url=f"attachment://{skin_file.filename}")
                    await results_chan.send(content=player_user.mention, embed=result_embed, file=skin_file)
                else:
                    await results_chan.send(content=player_user.mention, embed=result_embed)
            except Exception:
                pass

        # DM the player, unless they've opted out of notifications
        if not await is_dm_optout(self.player_id):
            try:
                dm_embed = discord.Embed(
                    title="📋 Test Result",
                    description=f"Your **{label}** test was recorded by **{tester_user.display_name}**.\nResult: **{get_rank_full_name(tier)}**",
                    color=discord.Color.green()
                )
                await player_user.send(embed=dm_embed, view=TestFeedbackView(self.player_id, label))
            except Exception:
                pass

        await archive_channel(interaction.channel, tester_user, reason=f"Test result recorded: {tier}")

        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Test finished: {tester_user.display_name}")
        except Exception:
            pass


class TestTicketView(discord.ui.View):
    def __init__(self, player_id: int, player_mc: str, gamemode: str, queue_ch_id: int = None):
        super().__init__(timeout=None)
        self.player_id = player_id
        self.player_mc = player_mc
        self.gamemode = gamemode
        self.queue_ch_id = queue_ch_id

    @discord.ui.button(label="📝 Record Result", style=discord.ButtonStyle.green, custom_id="test_record_result")
    async def record_result(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _can_give_tiers(interaction.user):
            return await interaction.response.send_message("❌ Only the authorized role can give/record a tier!", ephemeral=True)

        modal = TestResultModal(
            player_id=self.player_id,
            player_mc=self.player_mc,
            gamemode=self.gamemode,
            queue_ch_id=self.queue_ch_id
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="test_close_no_result")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_staff = interaction.user.guild_permissions.administrator or any(r.id in [STAFF_ROLE_ID, REGULATOR_ROLE_ID] for r in interaction.user.roles)
        if not is_staff:
            return await interaction.response.send_message("❌ Only testers or regulators can close this ticket!", ephemeral=True)

        await interaction.response.send_message("🔒 Closing ticket in 5 seconds...")

        if self.queue_ch_id and self.queue_ch_id in ACTIVE_QUEUES:
            q_data = ACTIVE_QUEUES[self.queue_ch_id]
            q_data["players"] = [p for p in q_data["players"] if p["id"] != self.player_id]
            try:
                chan = interaction.guild.get_channel(self.queue_ch_id)
                if chan and q_data.get("msg_id"):
                    msg = await chan.fetch_message(q_data["msg_id"])
                    await update_queue_message(msg, q_data, self.gamemode)
            except Exception:
                pass

        await asyncio.sleep(5)
        await archive_channel(interaction.channel, interaction.user, reason="Test closed without a result")
        try:
            await interaction.channel.delete(reason=f"Test closed without a result: {interaction.user.display_name}")
        except Exception:
            pass


class QueueActiveView(discord.ui.View):
    def __init__(self, mode_key: str, tester_role: discord.Role):
        super().__init__(timeout=None)
        self.mode_key = mode_key
        self.tester_role = tester_role

    @discord.ui.button(label="➕ Join / ➖ Leave", style=discord.ButtonStyle.blurple, custom_id="queue_join_leave_toggle")
    async def join_leave_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user

        if is_banned_by_role(user):
            return await interaction.followup.send("❌ You are banned from tests!", ephemeral=True)

        mc_name = await get_linked_minecraft_name_async(user.id)
        if not mc_name:
            return await interaction.followup.send("❌ You need to link your Minecraft account first with the `/link` command!", ephemeral=True)

        ch_id = interaction.channel.id
        if ch_id not in ACTIVE_QUEUES:
            return await interaction.followup.send("❌ This queue is no longer active.", ephemeral=True)

        q_data = ACTIVE_QUEUES[ch_id]
        existing_player = next((p for p in q_data["players"] if p["id"] == user.id), None)

        if existing_player:
            q_data["players"] = [p for p in q_data["players"] if p["id"] != user.id]
            await update_queue_message(interaction.message, q_data, self.mode_key)
            await interaction.followup.send("✅ You successfully left the queue.", ephemeral=True)
        else:
            has_cd, cd_str = await check_timeout(user.id, self.mode_key)
            if has_cd:
                return await interaction.followup.send(f"⏱️ You are on cooldown in this gamemode! Time remaining: `{cd_str}`", ephemeral=True)

            if len(q_data["players"]) >= 20:
                return await interaction.followup.send("❌ The queue is full (20/20).", ephemeral=True)

            q_data["players"].append({
                "id": user.id,
                "mc": mc_name,
                "status": "⏳ WAITING"
            })

            await update_queue_message(interaction.message, q_data, self.mode_key)
            await interaction.followup.send(f"✅ You successfully joined the **{get_gamemode_display_name(self.mode_key)}** queue!", ephemeral=True)

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.green, custom_id="queue_next")
    async def next_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not _can_give_tiers(interaction.user):
            return await interaction.response.send_message("❌ Only the authorized role can call the next player!", ephemeral=True)

        ch_id = interaction.channel.id
        if ch_id not in ACTIVE_QUEUES:
            return await interaction.response.send_message("❌ No active queue found in this channel.", ephemeral=True)

        q_data = ACTIVE_QUEUES[ch_id]
        if not q_data["players"]:
            return await interaction.response.send_message("❌ There are no players in the queue!", ephemeral=True)

        target_player = next((p for p in q_data["players"] if p["status"] == "⏳ WAITING"), None)
        if not target_player:
            return await interaction.response.send_message("❌ There is no player who isn't already being tested!", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        target_player["status"] = "🧪 TESTING"
        try:
            await update_queue_message(interaction.message, q_data, self.mode_key)
        except Exception:
            pass

        guild = interaction.guild
        category = get_queue_category(guild)

        player_user = guild.get_member(target_player["id"]) or await guild.fetch_member(target_player["id"])
        regulator_role = guild.get_role(REGULATOR_ROLE_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            player_user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        if regulator_role:
            overwrites[regulator_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if self.tester_role:
            overwrites[self.tester_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        label = get_gamemode_display_name(self.mode_key)
        try:
            test_chan = await guild.create_text_channel(
                name=f"test-{target_player['mc'].lower()}",
                category=category,
                overwrites=overwrites,
                topic=f"Test room - {label} | Player: {target_player['mc']}"
            )
        except Exception as e:
            target_player["status"] = "⏳ WAITING"
            try:
                await update_queue_message(interaction.message, q_data, self.mode_key)
            except Exception:
                pass
            return await interaction.followup.send(f"❌ Failed to create test channel: `{e}`", ephemeral=True)

        embed = discord.Embed(
            title=f"⚔️ Test Room: {label}",
            description=f"Player: <@{target_player['id']}> (**{target_player['mc']}**)\nTester: {interaction.user.mention}\n\nClick the button below to record the result!",
            color=discord.Color.blue()
        )
        await test_chan.send(content=f"{player_user.mention} {interaction.user.mention}", embed=embed, view=TestTicketView(target_player['id'], target_player['mc'], self.mode_key, ch_id))
        await interaction.followup.send(f"✅ Next player called! Test channel: {test_chan.mention}", ephemeral=True)

        if not await is_dm_optout(target_player['id']):
            try:
                dm_embed = discord.Embed(
                    title="🎮 It's your turn!",
                    description=f"It's your turn in the **{label}** queue!\nYour test room: {test_chan.mention}\nTester: {interaction.user.display_name}",
                    color=discord.Color.blue()
                )
                await player_user.send(embed=dm_embed)
            except Exception:
                pass

    @discord.ui.button(label="🔒 Close", style=discord.ButtonStyle.gray, custom_id="queue_close")
    async def close_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_staff = interaction.user.guild_permissions.administrator or any(r.id in [STAFF_ROLE_ID, REGULATOR_ROLE_ID] for r in interaction.user.roles)
        if not is_staff and (self.tester_role and self.tester_role not in interaction.user.roles):
            return await interaction.response.send_message("❌ Only testers or admins can close the queue!", ephemeral=True)

        ch_id = interaction.channel.id
        if ch_id in ACTIVE_QUEUES:
            del ACTIVE_QUEUES[ch_id]

        await interaction.response.send_message("🔒 Queue closed. The channel will be deleted in 5 seconds...", ephemeral=True)
        await asyncio.sleep(5)
        await archive_channel(interaction.channel, interaction.user, reason="Queue closed")
        try:
            await interaction.channel.delete(reason=f"Queue closed: {interaction.user.display_name}")
        except Exception:
            pass


class PanelSelectView(discord.ui.View):
    def __init__(self, action_type: str):
        super().__init__(timeout=None)
        self.action_type = action_type

        options = []
        for lbl, key, emoji in TICKET_TYPES[:25]:
            emoji_str = str(emoji)
            try:
                parsed_emoji = discord.PartialEmoji.from_str(emoji_str)
                options.append(discord.SelectOption(label=lbl, value=key, emoji=parsed_emoji))
            except Exception:
                options.append(discord.SelectOption(label=lbl, value=key))

        if options:
            self.add_item(PanelSelect(options, action_type))


class PanelSelect(discord.ui.Select):
    def __init__(self, options, action_type: str):
        placeholders = {
            "ping": "Choose a notification category...",
            "queue": "Choose a gamemode for the queue...",
            "hightest": "Choose a High Tier level..."
        }
        super().__init__(
            placeholder=placeholders.get(action_type, "Choose..."),
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"panel_{action_type}"
        )
        self.action_type = action_type

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]  # e.g. "HT4" or a gamemode key
        guild = interaction.guild
        user = interaction.user

        # 1. PING PANEL
        if self.action_type == "ping":
            label = get_gamemode_display_name(key)
            role_name = f"{label} Queue"
            role = discord.utils.get(guild.roles, name=role_name) or discord.utils.get(guild.roles, name=label)
            
            if not role:
                return await interaction.response.send_message(f"❌ The `{role_name}` role was not found on the server!", ephemeral=True)

            if role in user.roles:
                await user.remove_roles(role, reason="Ping panel - unsubscribed")
                await interaction.response.send_message(f"❌ You have been **removed** from the **{label}** waitlist.", ephemeral=True)
            else:
                await user.add_roles(role, reason="Ping panel - subscribed")
                await interaction.response.send_message(f"✅ Added you to the **{label}** waitlist! You will get a notification when a queue opens.", ephemeral=True)
            return

        # 2. HIGHTEST PANEL (High Test Ticket - requesting a higher tier in a given gamemode)
        if self.action_type == "hightest":
            if is_banned_by_role(user):
                return await interaction.response.send_message("❌ You are banned from tests!", ephemeral=True)

            mc_name = await get_linked_minecraft_name_async(user.id)
            if not mc_name:
                return await interaction.response.send_message("❌ You need to link your Minecraft account first with the `/link` command!", ephemeral=True)

            await interaction.response.defer(ephemeral=True)

            label = get_gamemode_display_name(key)
            current_tier = await get_player_rank_async(mc_name, label)

            def rank_index(r):
                try:
                    return RANKS.index(r)
                except ValueError:
                    return -1

            if rank_index(current_tier) < RANKS.index("LT3"):
                return await interaction.followup.send(
                    f"❌ You can only open a High Test request in **{label}** mode if you have at least **LT3** rank in that mode! (Your current rank: {current_tier})",
                    ephemeral=True
                )

            category = get_ticket_category(guild)

            tester_role = _find_gamemode_tester_role(guild, label)
            regulator_role = guild.get_role(REGULATOR_ROLE_ID)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
                user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            }
            if tester_role:
                overwrites[tester_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            if regulator_role:
                overwrites[regulator_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

            try:
                ticket_chan = await guild.create_text_channel(
                    name=f"hightest-{key.lower()}-{mc_name.lower()}",
                    category=category,
                    overwrites=overwrites,
                    topic=f"High Test Ticket - {label} | Player: {mc_name} | Current rank: {current_tier}"
                )
            except Exception as e:
                return await interaction.followup.send(f"❌ Failed to create High Test channel: `{e}`", ephemeral=True)

            INACTIVE_TICKETS[ticket_chan.id] = {
                "owner_id": user.id,
                "warned": False,
                "last_activity": time.time()
            }

            reg_ping = f"<@&{REGULATOR_ROLE_ID}>" if regulator_role else ""
            embed = discord.Embed(
                title=f"⚔️ High Tier Test: {label}",
                description=(
                    f"Player: {user.mention} (**{mc_name}**)\n"
                    f"Current rank in this mode: **{current_tier}**\n\n"
                    f"This is a private High Test ticket. The tester/regulator can record the result here.\n\n"
                    f"**Inactivity**\nAny human message resets the 48-hour timer. A warning is sent 4 hours before automatic closure."
                ),
                color=discord.Color.purple()
            )
            await ticket_chan.send(content=f"{user.mention} {reg_ping}".strip(), embed=embed, view=HighTestTicketView(user.id, mc_name, key))
            return await interaction.followup.send(f"✅ High Test ticket successfully opened: {ticket_chan.mention}", ephemeral=True)

        # 3. QUEUE PANEL (Queue)
        label = get_gamemode_display_name(key)

        can_open, deny_reason = _can_open_queue(user, guild, label)
        if not can_open:
            return await interaction.response.send_message(deny_reason, ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        category = get_queue_category(guild)
        
        tester_role = _find_gamemode_tester_role(guild, label)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        if tester_role:
            overwrites[tester_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        try:
            queue_chan = await guild.create_text_channel(
                name=f"queue-{key.lower()}",
                category=category,
                overwrites=overwrites,
                topic=f"MCTier Queue - {label}"
            )
        except Exception as e:
            return await interaction.followup.send(f"❌ Failed to create channel: `{e}`", ephemeral=True)

        queue_role = discord.utils.get(guild.roles, name=f"{label} Queue")
        q_ping = queue_role.mention if queue_role else f"@{label} Queue"

        ACTIVE_QUEUES[queue_chan.id] = {
            "players": [], 
            "testers": [user.id], 
            "gamemode": key,
            "msg_id": None
        }

        emoji_str = "🎮"
        for l, k, e in ALL_TICKET_TYPES:
            if k == key:
                emoji_str = str(e)
                break

        desc = f"**Spots:** 0/20\n\n**Players in queue:**\n*- Empty -*\n\n**Active Testers:**\n🛡️ <@{user.id}>\n"
        embed = discord.Embed(
            title=f"{emoji_str} {label} Queue", 
            description=desc, 
            color=discord.Color(THEME_LIGHT_PURPLE)
        )
        
        msg = await queue_chan.send(content=f"🔔 {q_ping}", embed=embed, view=QueueActiveView(key, tester_role))
        ACTIVE_QUEUES[queue_chan.id]["msg_id"] = msg.id
        await interaction.followup.send(f"✅ Queue channel successfully opened: {queue_chan.mention}", ephemeral=True)
