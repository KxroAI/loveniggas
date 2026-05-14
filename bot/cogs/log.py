"""
Log Cog
Logs every slash command invocation to the configured log channel.
"""

from collections import deque

import discord
from discord.ext import commands

from ..config import LOG_CHANNEL_ID
from ..utils import create_embed


class LogCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._seen: set[int] = set()
        self._seen_order: deque[int] = deque(maxlen=500)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.application_command:
            return

        if interaction.id in self._seen:
            return

        if len(self._seen_order) == 500:
            self._seen.discard(self._seen_order[0])
        self._seen_order.append(interaction.id)
        self._seen.add(interaction.id)

        self.bot.command_count += 1

        try:
            log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
            if not log_channel:
                log_channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            if not log_channel:
                return

            cmd_name = interaction.command.name if interaction.command else "Unknown"
            if hasattr(interaction.command, "parent") and interaction.command.parent:
                cmd_name = f"{interaction.command.parent.name} {cmd_name}"

            raw_options = (interaction.data or {}).get("options", [])
            if raw_options and raw_options[0].get("type") in (1, 2):
                raw_options = raw_options[0].get("options", [])
            args_str = "\n".join(
                f"`{opt['name']}`: {opt.get('value', '')}" for opt in raw_options
            ) if raw_options else "None"

            embed = create_embed(
                title="📝 Command Used",
                description=(
                    f"**Command:** `/{cmd_name}`\n"
                    f"**User:** {interaction.user.mention} (`{interaction.user.id}`)\n"
                    f"**Server:** {interaction.guild.name if interaction.guild else 'DM'}\n"
                    f"**Channel:** {interaction.channel.name if hasattr(interaction.channel, 'name') else 'DM'}\n"
                    f"**Arguments:**\n{args_str}"
                ),
            )

            await log_channel.send(embed=embed)

        except Exception as e:
            print(f"[LOG] Error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LogCog(bot))
