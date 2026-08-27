import discord
from discord.ext import commands
from discord import app_commands
from database import (
    get_linked_minecraft_name_async, 
    generate_link_code_async,
    unlink_minecraft_account_async
)

class LinkingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="link", description="Request a code to link your Minecraft account!")
    async def link(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Check whether it's already linked
        existing = await get_linked_minecraft_name_async(interaction.user.id)
        if existing:
            await interaction.followup.send(f"❌ You are already linked with this account: **{existing}**\nUse the `/unlink` command to unlink it!", ephemeral=True)
            return
            
        # Generate the code and save it to the database
        code = await generate_link_code_async(interaction.user.id)
        
        if not code:
            await interaction.followup.send("❌ An error occurred while generating the code in the database!", ephemeral=True)
            return
        
        embed = discord.Embed(
            title="🔗 Link Account",
            description=(
                f"✅ Your code has been successfully generated!\n\n"
                f"Join the Minecraft server and type this command:\n"
                f"**`/link {code}`**\n\n"
                f"⏱️ *The code expires in 10 minutes!*\n"
                f"🌐 **Server IP:** `chaosffa.kinetic.host`"
            ),
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unlink", description="Unlink your Minecraft account")
    async def unlink(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        success = await unlink_minecraft_account_async(interaction.user.id)
        if success:
            await interaction.followup.send("✅ You successfully unlinked your Minecraft account!", ephemeral=True)
        else:
            await interaction.followup.send("❌ You weren't linked to any Minecraft account.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(LinkingCog(bot))
