import discord
from discord.ext import commands
import aiosqlite

from ..config import BOT_OWNER_ID


async def _open_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect("db/anti.db")
    await db.execute("""CREATE TABLE IF NOT EXISTS whitelisted_users (
        guild_id INTEGER, user_id INTEGER,
        ban BOOLEAN DEFAULT FALSE, kick BOOLEAN DEFAULT FALSE, prune BOOLEAN DEFAULT FALSE,
        botadd BOOLEAN DEFAULT FALSE, serverup BOOLEAN DEFAULT FALSE, memup BOOLEAN DEFAULT FALSE,
        chcr BOOLEAN DEFAULT FALSE, chdl BOOLEAN DEFAULT FALSE, chup BOOLEAN DEFAULT FALSE,
        rlcr BOOLEAN DEFAULT FALSE, rlup BOOLEAN DEFAULT FALSE, rldl BOOLEAN DEFAULT FALSE,
        meneve BOOLEAN DEFAULT FALSE, mngweb BOOLEAN DEFAULT FALSE, mngstemo BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (guild_id, user_id))""")
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


FIELDS = {
    "ban": "Ban", "kick": "Kick", "prune": "Prune", "botadd": "Bot Add",
    "serverup": "Server Update", "memup": "Member Update",
    "chcr": "Channel Create", "chdl": "Channel Delete", "chup": "Channel Update",
    "rlcr": "Role Create", "rlup": "Role Update", "rldl": "Role Delete",
    "meneve": "Mention Everyone", "mngweb": "Manage Webhooks",
}


class WhitelistCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /whitelist ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="whitelist", aliases=["wl"],
                             description="Whitelist a member from antinuke actions")
    @commands.guild_only()
    async def whitelist(self, ctx: commands.Context, member: discord.Member):
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
                if await c.fetchone():
                    return await ctx.send(f"❌ {member.mention} is already whitelisted. Use `{ctx.prefix}unwhitelist` first.", ephemeral=True)

            await db.execute("INSERT INTO whitelisted_users (guild_id, user_id) VALUES (?, ?)",
                             (ctx.guild.id, member.id))
            await db.commit()
        finally:
            await db.close()

        options = [discord.SelectOption(label=name, value=key) for key, name in FIELDS.items()]
        select = discord.ui.Select(placeholder="Choose permissions to whitelist",
                                   min_values=1, max_values=len(options), options=options)
        btn_all = discord.ui.Button(label="Whitelist for ALL Permissions", style=discord.ButtonStyle.primary)

        def desc(selected: set) -> str:
            return "\n".join(f"{'✅' if k in selected else '❌'} : **{n}**" for k, n in FIELDS.items())

        embed = discord.Embed(title=ctx.guild.name, color=0x000000, description=desc(set()))
        embed.add_field(name="Executor", value=ctx.author.mention, inline=True)
        embed.add_field(name="Target", value=member.mention, inline=True)
        embed.set_thumbnail(url=self.bot.user.avatar.url)

        view = discord.ui.View(timeout=60)
        view.add_item(select)
        view.add_item(btn_all)
        msg = await ctx.send(embed=embed, view=view)

        async def select_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This menu isn't for you.", ephemeral=True)
            selected = set(select.values)
            db2 = await _open_db()
            try:
                for col in selected:
                    await db2.execute(
                        f"UPDATE whitelisted_users SET {col} = ? WHERE guild_id = ? AND user_id = ?",
                        (True, ctx.guild.id, member.id))
                await db2.commit()
            finally:
                await db2.close()
            embed.description = desc(selected)
            view.stop()
            await i.response.edit_message(embed=embed, view=None)

        async def btn_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This button isn't for you.", ephemeral=True)
            all_keys = list(FIELDS.keys())
            db2 = await _open_db()
            try:
                sets = ", ".join(f"{k} = ?" for k in all_keys)
                vals = [True] * len(all_keys) + [ctx.guild.id, member.id]
                await db2.execute(f"UPDATE whitelisted_users SET {sets} WHERE guild_id = ? AND user_id = ?", vals)
                await db2.commit()
            finally:
                await db2.close()
            embed.description = desc(set(all_keys))
            view.stop()
            await i.response.edit_message(embed=embed, view=None)

        select.callback = select_cb
        btn_all.callback = btn_cb

        try:
            await self.bot.wait_for(
                "interaction",
                check=lambda i: i.message and i.message.id == msg.id and i.user.id == ctx.author.id,
                timeout=60)
        except Exception:
            await msg.edit(view=None)

    # ── /whitelisted ───────────────────────────────────────────────────────────

    @commands.hybrid_command(name="whitelisted", aliases=["wlist"],
                             description="Show all whitelisted users in this server")
    @commands.guild_only()
    async def whitelisted(self, ctx: commands.Context):
        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send("❌ Only the Server Owner, Extra Owner, or Bot Owner can use this command.", ephemeral=True)
            if not await _antinuke_enabled(ctx.guild.id, db):
                return await ctx.send(f"Antinuke is not enabled. Use `{ctx.prefix}antinuke enable` first.", ephemeral=True)
            async with db.execute("SELECT user_id FROM whitelisted_users WHERE guild_id = ?",
                                  (ctx.guild.id,)) as c:
                rows = await c.fetchall()
        finally:
            await db.close()

        if not rows:
            return await ctx.send("No whitelisted users found.", ephemeral=True)
        embed = discord.Embed(
            title=f"Whitelisted Users — {ctx.guild.name}", color=0x000000,
            description=", ".join(f"<@{r[0]}>" for r in rows))
        await ctx.send(embed=embed)

    # ── /whitelistreset ────────────────────────────────────────────────────────

    @commands.hybrid_command(name="whitelistreset", aliases=["wlreset"],
                             description="Clear all whitelisted users")
    @commands.guild_only()
    async def whitelistreset(self, ctx: commands.Context):
        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send("❌ Only the Server Owner, Extra Owner, or Bot Owner can use this command.", ephemeral=True)
            if not await _antinuke_enabled(ctx.guild.id, db):
                return await ctx.send(f"Antinuke is not enabled. Use `{ctx.prefix}antinuke enable` first.", ephemeral=True)
            async with db.execute("SELECT 1 FROM whitelisted_users WHERE guild_id = ?", (ctx.guild.id,)) as c:
                if not await c.fetchone():
                    return await ctx.send("No whitelisted users to reset.", ephemeral=True)
            await db.execute("DELETE FROM whitelisted_users WHERE guild_id = ?", (ctx.guild.id,))
            await db.commit()
        finally:
            await db.close()
        embed = discord.Embed(title="✅ Whitelist Reset", color=0x000000,
                              description=f"All whitelisted users for **{ctx.guild.name}** have been removed.")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(WhitelistCog(bot))
