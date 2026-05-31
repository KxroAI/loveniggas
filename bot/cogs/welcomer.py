"""
Welcomer Cog
Sends a customizable welcome message when a member joins.
Uses aiosqlite for settings storage.
Supports placeholders: {user.mention}, {user.name}, {user.id}, {server.name}, {member.count}
"""

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from ..config import BOT_OWNER_ID
from ..utils import create_embed, create_error_embed

DB_PATH = "welcomer.db"

DEFAULT_MESSAGE = "Welcome {user.mention} to **{server.name}**! 🎉 You are member **#{member.count}**."

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS welcomer_settings (
                guild_id   INTEGER PRIMARY KEY,
                channel_id INTEGER,
                message    TEXT    DEFAULT '{default}',
                embed      INTEGER DEFAULT 1,
                enabled    INTEGER DEFAULT 1
            )
        """.format(default=DEFAULT_MESSAGE.replace("'", "''")))
        await db.commit()


async def _get_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM welcomer_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _upsert_settings(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        exists = await (
            await db.execute("SELECT guild_id FROM welcomer_settings WHERE guild_id = ?", (guild_id,))
        ).fetchone()
        if exists:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            await db.execute(
                f"UPDATE welcomer_settings SET {sets} WHERE guild_id = ?",
                (*kwargs.values(), guild_id),
            )
        else:
            kwargs["guild_id"] = guild_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            await db.execute(
                f"INSERT INTO welcomer_settings ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
        await db.commit()


def _build_message(template: str, member: discord.Member) -> str:
    return (
        template
        .replace("{user.mention}", member.mention)
        .replace("{user.name}", member.display_name)
        .replace("{user.id}", str(member.id))
        .replace("{server.name}", member.guild.name)
        .replace("{member.count}", str(member.guild.member_count))
    )


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class WelcomerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await _init_db()

    # ── on_member_join ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        settings = await _get_settings(member.guild.id)
        if not settings or not settings.get("enabled") or not settings.get("channel_id"):
            return

        channel = member.guild.get_channel(settings["channel_id"])
        if not channel:
            return

        message = _build_message(settings.get("message") or DEFAULT_MESSAGE, member)

        if settings.get("embed", 1):
            embed = discord.Embed(
                description=message,
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name=f"Welcome to {member.guild.name}!",
                icon_url=member.guild.icon.url if member.guild.icon else None,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(
                text=f"Member #{member.guild.member_count}",
                icon_url=member.display_avatar.url,
            )
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                pass
        else:
            try:
                await channel.send(message)
            except discord.Forbidden:
                pass

    # ── /welcomer setup ───────────────────────────────────────────────────

    @commands.hybrid_group(name="welcomer", description="Configure the welcome message system", with_app_command=True)
    @commands.guild_only()
    async def welcomer(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @welcomer.command(name="setup", description="Set the channel for welcome messages")
    @app_commands.describe(channel="The channel to send welcome messages in")
    @commands.guild_only()
    async def welcomer_setup(self, ctx: commands.Context, channel: discord.TextChannel):
        if not ctx.author.guild_permissions.manage_guild and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Server** permission."), ephemeral=True)

        settings = await _get_settings(ctx.guild.id)
        msg = settings.get("message", DEFAULT_MESSAGE) if settings else DEFAULT_MESSAGE
        await _upsert_settings(ctx.guild.id, channel_id=channel.id, message=msg, enabled=1)

        await ctx.send(
            embed=create_embed(
                title="✅ Welcomer Configured",
                description=f"Welcome messages will be sent to {channel.mention}.\n\nUse `/welcomer message` to customize the message.",
            )
        )

    @welcomer.command(name="message", description="Set a custom welcome message")
    @app_commands.describe(message="The welcome message. Supports: {user.mention}, {user.name}, {server.name}, {member.count}")
    @commands.guild_only()
    async def welcomer_message(self, ctx: commands.Context, *, message: str):
        if not ctx.author.guild_permissions.manage_guild and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Server** permission."), ephemeral=True)

        await _upsert_settings(ctx.guild.id, message=message)
        await ctx.send(
            embed=create_embed(
                title="✅ Welcome Message Updated",
                description=f"**New message:**\n{message}",
            )
        )

    @welcomer.command(name="embed", description="Toggle between embed and plain text welcome messages")
    @app_commands.describe(enabled="True for embed, False for plain text")
    @commands.guild_only()
    async def welcomer_embed(self, ctx: commands.Context, enabled: bool = True):
        if not ctx.author.guild_permissions.manage_guild and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Server** permission."), ephemeral=True)

        await _upsert_settings(ctx.guild.id, embed=int(enabled))
        mode = "embed" if enabled else "plain text"
        await ctx.send(embed=create_embed(description=f"✅ Welcome messages will now be sent as **{mode}**."))

    @welcomer.command(name="disable", description="Disable welcome messages for this server")
    @commands.guild_only()
    async def welcomer_disable(self, ctx: commands.Context):
        if not ctx.author.guild_permissions.manage_guild and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Server** permission."), ephemeral=True)

        await _upsert_settings(ctx.guild.id, enabled=0)
        await ctx.send(embed=create_embed(description="✅ Welcome messages have been **disabled**."))

    @welcomer.command(name="test", description="Send a test welcome message to see how it looks")
    @commands.guild_only()
    async def welcomer_test(self, ctx: commands.Context):
        if not ctx.author.guild_permissions.manage_guild and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Server** permission."), ephemeral=True)

        settings = await _get_settings(ctx.guild.id)
        if not settings or not settings.get("channel_id"):
            return await ctx.send(
                embed=create_error_embed("Welcomer is not set up. Run `/welcomer setup <channel>` first."),
                ephemeral=True,
            )

        message = _build_message(settings.get("message") or DEFAULT_MESSAGE, ctx.author)

        if settings.get("embed", 1):
            embed = discord.Embed(
                description=message,
                color=discord.Color.green(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_author(
                name=f"Welcome to {ctx.guild.name}!",
                icon_url=ctx.guild.icon.url if ctx.guild.icon else None,
            )
            embed.set_thumbnail(url=ctx.author.display_avatar.url)
            embed.set_footer(text=f"Member #{ctx.guild.member_count}", icon_url=ctx.author.display_avatar.url)
            await ctx.send(content="**(Test welcome message)**", embed=embed)
        else:
            await ctx.send(f"**(Test welcome message)**\n{message}")

    @welcomer.command(name="view", description="View the current welcomer settings")
    @commands.guild_only()
    async def welcomer_view(self, ctx: commands.Context):
        settings = await _get_settings(ctx.guild.id)
        if not settings:
            return await ctx.send(
                embed=create_error_embed("Welcomer is not configured for this server."), ephemeral=True
            )

        channel = ctx.guild.get_channel(settings.get("channel_id") or 0)
        embed = create_embed(title="👋 Welcomer Settings")
        embed.add_field(name="Status", value="✅ Enabled" if settings.get("enabled") else "❌ Disabled")
        embed.add_field(name="Channel", value=channel.mention if channel else "Not set")
        embed.add_field(name="Style", value="Embed" if settings.get("embed", 1) else "Plain text")
        embed.add_field(
            name="Message",
            value=settings.get("message") or DEFAULT_MESSAGE,
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WelcomerCog(bot))
