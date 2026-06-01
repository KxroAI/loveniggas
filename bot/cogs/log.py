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

    # ── PREFIX COMMAND LOGGING ─────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context):
        """Log every prefix command invocation to the log channel."""
        self.bot.command_count += 1

        try:
            log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
            if not log_channel:
                log_channel = await self.bot.fetch_channel(LOG_CHANNEL_ID)
            if not log_channel:
                return

            cmd_name = ctx.command.qualified_name if ctx.command else "Unknown"

            # Build args string from the raw message (strip prefix + command name)
            raw_args = ctx.message.content.strip()
            # Remove the invoking prefix+name to show just arguments
            prefix_used = ctx.prefix or ""
            invoked_with = ctx.invoked_with or ""
            args_str = raw_args[len(prefix_used) + len(invoked_with):].strip() or "None"

            server_name = ctx.guild.name if ctx.guild else "Direct Message"
            server_id   = f"`{ctx.guild.id}`" if ctx.guild else "`N/A`"
            channel_name = (
                ctx.channel.name
                if ctx.guild and hasattr(ctx.channel, "name")
                else "Direct Message"
            )
            channel_id = f"`{ctx.channel.id}`" if ctx.channel else "`N/A`"

            embed = create_embed(
                title="📝 Command Used",
                description=(
                    f"**Command:** ``{prefix_used}{cmd_name}``\n"
                    f"**User:** {ctx.author.mention} (``{ctx.author.id}``)\n"
                    f"**Server:** {server_name} ({server_id})\n"
                    f"**Channel:** {channel_name} ({channel_id})\n"
                    f"**Arguments:**\n{args_str}"
                ),
            )

            await log_channel.send(embed=embed)

        except Exception as e:
            print(f"[LOG] Prefix command log error: {e}")

    # ── SLASH COMMAND LOGGING ──────────────────────────────────────────────────

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

            server_name = interaction.guild.name if interaction.guild else "Direct Message"
            server_id   = f"`{interaction.guild.id}`" if interaction.guild else "`N/A`"
            channel_name = (
                interaction.channel.name
                if interaction.guild and hasattr(interaction.channel, "name")
                else "Direct Message"
            )
            channel_id = f"`{interaction.channel.id}`" if interaction.channel else "`N/A`"

            embed = create_embed(
                title="📝 Command Used",
                description=(
                    f"**Command:** ``/{cmd_name}``\n"
                    f"**User:** {interaction.user.mention} (``{interaction.user.id}``)\n"
                    f"**Server:** {server_name} ({server_id})\n"
                    f"**Channel:** {channel_name} ({channel_id})\n"
                    f"**Arguments:**\n{args_str}"
                ),
            )

            await log_channel.send(embed=embed)

        except Exception as e:
            print(f"[LOG] Error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LogCog(bot))
