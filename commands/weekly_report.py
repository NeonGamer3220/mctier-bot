import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import datetime
from config import SUPABASE_URL, SUPABASE_KEY

class WeeklyReportCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="report", description="Weekly summary report on testers and regulators.")
    @app_commands.checks.has_permissions(administrator=True) # Or adjust the permission as needed
    async def weekly_report(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        if not SUPABASE_URL or not SUPABASE_KEY:
            await interaction.followup.send("❌ The Supabase configuration (URL or KEY) is missing from config.py.")
            return

        # Start timestamp for the last 7 days (ISO format, UTC)
        seven_days_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }

        base_supabase_url = SUPABASE_URL.rstrip('/')

        try:
            async with aiohttp.ClientSession() as session:
                
                # --- 1. QUERY TESTERS (tests table, based on the tester_id column) ---
                tests_url = f"{base_supabase_url}/rest/v1/tests?created_at=gte.{seven_days_ago}&select=tester_id"
                async with session.get(tests_url, headers=headers) as resp:
                    if resp.status == 200:
                        tests_data = await resp.json()
                    else:
                        tests_data = []

                # Count testers based on tester_id
                tester_counts = {}
                for row in tests_data:
                    t_id = row.get("tester_id")
                    if t_id:
                        tester_counts[t_id] = tester_counts.get(t_id, 0) + 1

                # --- 2. QUERY REGULATORS (discord_notifications table) ---
                notif_url = f"{base_supabase_url}/rest/v1/discord_notifications?created_at=gte.{seven_days_ago}&select=username,player_discord_id"
                async with session.get(notif_url, headers=headers) as resp:
                    if resp.status == 200:
                        notif_data = await resp.json()
                    else:
                        notif_data = []

                # Count regulators
                regulator_counts = {}
                for row in notif_data:
                    reg_key = row.get("player_discord_id") or row.get("username")
                    if reg_key:
                        regulator_counts[reg_key] = regulator_counts.get(reg_key, 0) + 1

                # --- BUILD EMBED ---
                embed = discord.Embed(
                    title="📊 Weekly Performance Report",
                    description="Aggregated statistics for testers and regulators over the last **7 days**:",
                    color=discord.Color.blurple()
                )

                # Format the testers list
                if tester_counts:
                    sorted_testers = sorted(tester_counts.items(), key=lambda x: x[1], reverse=True)
                    tester_lines = []
                    for t_id, count in sorted_testers:
                        if str(t_id).isdigit():
                            tester_lines.append(f"• <@{t_id}> – **{count}** test(s)")
                        else:
                            tester_lines.append(f"• `{t_id}` – **{count}** test(s)")
                    tester_text = "\n".join(tester_lines)
                else:
                    tester_text = "*No tests were carried out in the last 7 days.*"

                embed.add_field(name="⚔️ Testers (Completed tests)", value=tester_text, inline=False)

                # Format the regulators list
                if regulator_counts:
                    sorted_regulators = sorted(regulator_counts.items(), key=lambda x: x[1], reverse=True)
                    reg_lines = []
                    for r_key, count in sorted_regulators:
                        if str(r_key).isdigit():
                            reg_lines.append(f"• <@{r_key}> – **{count}** high result(s)")
                        else:
                            reg_lines.append(f"• `{r_key}` – **{count}** high result(s)")
                        reg_text = "\n".join(reg_lines)
                else:
                    reg_text = "*No high results were recorded in the last 7 days.*"

                embed.add_field(name="🛡️ Regulators (Website recordings)", value=reg_text, inline=False)

                embed.set_footer(text=f"Period: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')} - Previous 7 days")

                await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"[REPORT ERROR] {e}")
            await interaction.followup.send(f"❌ An error occurred while generating the report: {str(e)}")

async def setup(bot):
    await bot.add_cog(WeeklyReportCog(bot))
