import discord
from discord.ext import commands
import aiosqlite

from ..config import BOT_OWNER_ID


async def _open_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect("db/anti.db")
    await db.execute("""CREATE TABLE IF NOT EXISTS whitelisted_users (
        guild_id INTEGER, user_id INTEGER, PRIMARY KEY (guild_id, user_id))""")
    await db.commit()
    return db


async def _is_privileged(user_id: int, guild: discord.Guild, db: aiosqlite.Connection) -> bool:
    if user_id == BOT_OWNER_ID or user_id == guild.owner_id:
        return True
    async with db.execute("SELECT 1 FROM extraowners WHERE guild_id = ? AND owner_id = ?",
                          (guild.id, user_id)) as c:
        return await c.fetchone() is not None


async def _antinuke_enabled(guild_id: int, db: aiosqlite.Connection) -> bool:
    async with db.execute("SELECT status FROM antinuke WHERE guild_id = ?", (guild_id,)) as c:
        row = await c.fetchone()
    return bool(row and row[0])


class UnwhitelistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="unwhitelist", aliases=["unwl"],
                             description="Remove a member from the antinuke whitelist")
    @commands.guild_only()
    async def unwhitelist(self, ctx: commands.Context, member: discord.Member):
        if ctx.guild.member_count < 5:
            return await ctx.send("Your server doesn't meet the 5 member requirement.", ephemeral=True)

        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send("❌ Only the Server Owner, Extra Owner, or Bot Owner can use this command.", ephemeral=True)
            if not await _antinuke_enabled(ctx.guild.id, db):
                return await ctx.send(f"Antinuke is not enabled. Use `{ctx.prefix}antinuke enable` first.", ephemeral=True)
            async with db.execute("SELECT 1 FROM whitelisted_users WHERE guild_id = ? AND user_id = ?",
                                  (ctx.guild.id, member.id)) as c:
                if not await c.fetchone():
                    return await ctx.send(f"❌ {member.mention} is not whitelisted.", ephemeral=True)
            await db.execute("DELETE FROM whitelisted_users WHERE guild_id = ? AND user_id = ?",
                             (ctx.guild.id, member.id))
            await db.commit()
        finally:
            await db.close()

        embed = discord.Embed(
            title="✅ User Unwhitelisted", color=0x000000,
            description=f"{member.mention} has been removed from the whitelist.\nAntinuke will now take action against them if triggered.")
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(UnwhitelistCog(bot))
