"""
Guild Events Cog
Handles guild-level events (join, leave, update, etc.)
"""

from discord.ext import commands


class GuildEventsCog(commands.Cog, name="GuildEvents"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    await bot.add_cog(GuildEventsCog(bot))
