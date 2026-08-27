import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime

from database import get_tgf_cooldown, set_tgf_cooldown
from commands.staff import is_staff_member
from config import TGF_LOG_CHANNEL_ID, TGF_COOLDOWN_DAYS

QUESTIONS = [
    "What is your Minecraft username?",
    "What is your Discord username?",
    "How old are you?",
    "How long have you been a member of the mctier community?",
    "How much time can you actively dedicate to the server?",
    "Are you familiar with the rules and can you follow them?",
    "What would you do if another regulator made a mistake?",
    "Why is a regulator's neutrality important?",
    "What do you think about hate speech and toxic behavior?",
    "What do you do if two players argue during a test?",
    "What would you do if you weren't sure about something?",
    "Do you think a regulator's job is more about checking ELOs, or helping players?",
    "Do you have any similar staff experience?",
    "Do you think a regulator's job is more about moderating or maintaining activity?"
]

class TGFActionModal(discord.ui.Modal):
    def __init__(self, action: str, applicant: discord.User):
        title = "Accept Application" if action == "accept" else "Reject Application"
        super().__init__(title=title)
        self.action = action
        self.applicant = applicant

        self.reason = discord.ui.TextInput(
            label="Justification / Note",
            style=discord.TextStyle.paragraph,
            placeholder="Write the reason for the decision...",
            required=True
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        status_text = "🟢 **ACCEPTED**" if self.action == "accept" else "🔴 **REJECTED**"
        color = discord.Color.green() if self.action == "accept" else discord.Color.red()

        original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
        
        if original_embed:
            new_embed = original_embed.copy()
            new_embed.color = color
            new_embed.add_field(name="Review", value=f"{status_text}\n**Reviewer:** {interaction.user.mention}\n**Reason:** {self.reason.value}", inline=False)
            await interaction.message.edit(embed=new_embed, view=None)

        try:
            dm_embed = discord.Embed(
                title=f"TGF Application Review - {status_text}",
                description=f"Your application has been reviewed.\n\n**Reviewer:** {interaction.user.display_name}\n**Reason:** {self.reason.value}",
                color=color
            )
            await self.applicant.send(embed=dm_embed)
        except Exception:
            pass

        await interaction.followup.send(f"✅ Application successfully {self.action}ed!", ephemeral=True)

class TGFDecisionView(discord.ui.View):
    def __init__(self, applicant: discord.User):
        super().__init__(timeout=None)
        self.applicant = applicant

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="tgf_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You don't have permission for this!", ephemeral=True)
        await interaction.response.send_modal(TGFActionModal("accept", self.applicant))

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="tgf_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ You don't have permission for this!", ephemeral=True)
        await interaction.response.send_modal(TGFActionModal("reject", self.applicant))

class TGFPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply for Regulator", style=discord.ButtonStyle.primary, custom_id="tgf_apply_button")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user

        cooldown_dt = await get_tgf_cooldown(user.id)
        if cooldown_dt:
            timestamp = int(cooldown_dt.timestamp())
            return await interaction.response.send_message(
                f"❌ You already applied recently! You can apply again: <t:{timestamp}:R>",
                ephemeral=True
            )

        try:
            dm_channel = await user.create_dm()
            await dm_channel.send("👋 Hi! The TGF application process is starting. You have 60 minutes to answer the questions.")
            await interaction.response.send_message("📩 I've sent you the questions in a private message (DM)!", ephemeral=True)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I can't send you a private message! Please enable DMs in your server settings.", ephemeral=True)

        asyncio.create_task(self.run_interview(interaction, user, dm_channel))

    async def run_interview(self, interaction: discord.Interaction, user: discord.User, dm_channel: discord.DMChannel):
        answers = []
        
        def check(m):
            return m.author.id == user.id and m.channel.id == dm_channel.id

        for i, question in enumerate(QUESTIONS, 1):
            embed = discord.Embed(
                title=f"Question {i}/{len(QUESTIONS)}",
                description=question,
                color=discord.Color.purple()
            )
            await dm_channel.send(embed=embed)

            try:
                msg = await interaction.client.wait_for("message", check=check, timeout=3600)
                answers.append((question, msg.content))
            except asyncio.TimeoutError:
                return await dm_channel.send("⏱️ The 60 minutes are up! Your application was aborted.")

        log_channel = interaction.guild.get_channel(TGF_LOG_CHANNEL_ID) if interaction.guild else None
        if log_channel:
            log_embed = discord.Embed(
                title=f"📥 New TGF Application: {user.display_name}",
                description=f"**Applicant:** {user.mention} ({user.id})",
                color=discord.Color.purple(),
                timestamp=datetime.datetime.now(datetime.timezone.utc)
            )
            for q, a in answers:
                log_embed.add_field(name=q, value=a[:1020] if a else "Empty", inline=False)

            await log_channel.send(embed=log_embed, view=TGFDecisionView(user))

        await set_tgf_cooldown(user.id, days=TGF_COOLDOWN_DAYS)
        await dm_channel.send("✅ Thank you! Your application has been sent to the Staff team for review.")

class TGFCommandCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="tgfpanel", description="Places the TGF application panel (Admin)")
    async def tgfpanel(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ This command requires administrator permission!", ephemeral=True)

        embed = discord.Embed(
            title="MCTier | TGF Application",
            description="Choose which position you'd like to apply for by clicking the button below!",
            color=discord.Color.purple()
        )
        embed.add_field(
            name="**Important information:**",
            value=(
                "**1.** You can apply for a given position once every 30 days.\n"
                "**2.** You need to fill out the application in a private message (DM).\n"
                "**3.** You have at most 60 minutes to complete it.\n"
                "**4.** Your answers will be reviewed by Staff."
            ),
            inline=False
        )

        await interaction.channel.send(embed=embed, view=TGFPanelView())
        await interaction.response.send_message("✅ TGF Panel successfully posted!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TGFCommandCog(bot))
