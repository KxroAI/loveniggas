import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
import asyncio
from discord.ui import LayoutView, Container, Section, TextDisplay, Separator, Thumbnail, Button, View

from ..config import BOT_OWNER_ID


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _open_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect("db/anti.db")
    await db.execute("CREATE TABLE IF NOT EXISTS antinuke (guild_id INTEGER PRIMARY KEY, status BOOLEAN)")
    await db.execute("CREATE TABLE IF NOT EXISTS extraowners (guild_id INTEGER, owner_id INTEGER, PRIMARY KEY (guild_id, owner_id))")
    await db.commit()
    return db


async def _is_privileged(user_id: int, guild: discord.Guild, db: aiosqlite.Connection) -> bool:
    """BOT_OWNER_ID, guild owner, or a registered extra owner."""
    if user_id == BOT_OWNER_ID:
        return True
    if user_id == guild.owner_id:
        return True
    async with db.execute("SELECT 1 FROM extraowners WHERE guild_id = ? AND owner_id = ?",
                          (guild.id, user_id)) as c:
        return await c.fetchone() is not None


# ── Extra-owner subgroup ──────────────────────────────────────────────────────

class AntinukeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        db = await _open_db()
        await db.close()

    # ══ /antinuke (group) ══════════════════════════════════════════════════════

    @commands.hybrid_group(name="antinuke", description="Antinuke protection commands",
                           aliases=["anti", "antiwizz"])
    @commands.guild_only()
    async def antinuke_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            prefix = ctx.prefix
            embed = discord.Embed(
                title="Antinuke",
                color=0x000000,
                description=(
                    f"Protect your server with Antinuke!\n\n"
                    f"**Enable:** `{prefix}antinuke enable` or `/antinuke enable`\n"
                    f"**Disable:** `{prefix}antinuke disable` or `/antinuke disable`"
                )
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            await ctx.send(embed=embed)

    # ── antinuke enable ───────────────────────────────────────────────────────

    @antinuke_group.command(name="enable", description="Enable antinuke protection (17 modules)")
    @commands.guild_only()
    async def antinuke_enable(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send(
                    embed=discord.Embed(title="❌ Access Denied", color=0x000000,
                                       description="Only the Server Owner, an Extra Owner, or the Bot Owner can use this command."),
                    ephemeral=True)
            async with db.execute("SELECT status FROM antinuke WHERE guild_id = ?", (guild_id,)) as c:
                row = await c.fetchone()
        finally:
            await db.close()

        if row and row[0]:
            embed = discord.Embed(
                title=f"Security Settings — {ctx.guild.name}", color=0x000000,
                description=f"Antinuke is **already enabled**.\nTo disable: `{ctx.prefix}antinuke disable`")
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            return await ctx.send(embed=embed, ephemeral=True)

        await ctx.defer()
        setup_embed = discord.Embed(title="Antinuke Setup", description="✅ Initializing Quick Setup!", color=0x000000)
        msg = await ctx.send(embed=setup_embed)

        if not ctx.guild.me.guild_permissions.administrator:
            setup_embed.description += "\n⚠️ Setup failed: missing **Administrator** permission."
            return await msg.edit(embed=setup_embed)

        await asyncio.sleep(1)
        setup_embed.description += "\n✅ Checking role positions..."
        await msg.edit(embed=setup_embed)

        await asyncio.sleep(1)
        setup_embed.description += "\n✅ Creating Antinuke Supreme role..."
        await msg.edit(embed=setup_embed)

        try:
            role = await ctx.guild.create_role(
                name="Antinuke Supreme", color=0x4D3164,
                permissions=discord.Permissions(administrator=True),
                hoist=False, mentionable=False, reason="Antinuke setup")
            await ctx.guild.me.add_roles(role)
        except discord.Forbidden:
            setup_embed.description += "\n⚠️ Failed: insufficient permissions to create role."
            return await msg.edit(embed=setup_embed)
        except discord.HTTPException as e:
            setup_embed.description += f"\n⚠️ Failed: {e}"
            return await msg.edit(embed=setup_embed)

        await asyncio.sleep(1)
        setup_embed.description += "\n✅ Positioning role at top..."
        await msg.edit(embed=setup_embed)
        try:
            await ctx.guild.edit_role_positions(positions={role: 1})
        except (discord.Forbidden, discord.HTTPException):
            pass

        await asyncio.sleep(1)
        setup_embed.description += "\n✅ Activating all antinuke modules..."
        await msg.edit(embed=setup_embed)

        db = await _open_db()
        try:
            await db.execute("INSERT OR REPLACE INTO antinuke (guild_id, status) VALUES (?, ?)", (guild_id, True))
            await db.commit()
        finally:
            await db.close()

        await asyncio.sleep(1)
        await msg.delete()

        modules = [
            "Anti Ban", "Anti Kick", "Anti Bot Add", "Anti Channel Create", "Anti Channel Delete",
            "Anti Channel Update", "Anti Everyone/Here", "Anti Role Create", "Anti Role Delete",
            "Anti Role Update", "Anti Member Update", "Anti Guild Update", "Anti Integration",
            "Anti Webhook Create", "Anti Webhook Delete", "Anti Webhook Update", "Anti Prune",
        ]
        s = Section(
            TextDisplay(
                f"# **Security Settings — {ctx.guild.name}**\n"
                f"> Tip: Keep my role at the **top** of the role list with **Administrator** for best results.\n\n"
                f"> __**{len(modules)} Modules Enabled**__\n"
                f">>> {chr(10).join(f'✅ **{m}**' for m in modules)}"
            ),
            accessory=Thumbnail(media=discord.UnfurledMediaItem(url=self.bot.user.display_avatar.url), description="Enabled"),
            id=1,
        )
        v = LayoutView(timeout=None)
        v.add_item(Container(s, Separator(), TextDisplay("-# Antinuke successfully enabled")))
        await ctx.send(view=v)

        btn_v = View()
        btn_v.add_item(Button(label="Show Punishment Types", custom_id="antinuke_show_punishment"))
        await ctx.send(view=btn_v)

    # ── antinuke disable ──────────────────────────────────────────────────────

    @antinuke_group.command(name="disable", description="Disable antinuke protection")
    @commands.guild_only()
    async def antinuke_disable(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send(
                    embed=discord.Embed(title="❌ Access Denied", color=0x000000,
                                       description="Only the Server Owner, an Extra Owner, or the Bot Owner can use this command."),
                    ephemeral=True)
            async with db.execute("SELECT status FROM antinuke WHERE guild_id = ?", (guild_id,)) as c:
                row = await c.fetchone()

            if not row or not row[0]:
                embed = discord.Embed(
                    title=f"Security Settings — {ctx.guild.name}", color=0x000000,
                    description=f"Antinuke is not enabled.\nTo enable: `{ctx.prefix}antinuke enable`")
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                return await ctx.send(embed=embed, ephemeral=True)

            await db.execute("DELETE FROM antinuke WHERE guild_id = ?", (guild_id,))
            await db.commit()
        finally:
            await db.close()

        s = Section(
            TextDisplay(f"# **Security Settings — {ctx.guild.name}**\n> Antinuke has been **disabled**.\n> To re-enable: `{ctx.prefix}antinuke enable`"),
            accessory=Thumbnail(media=discord.UnfurledMediaItem(url=self.bot.user.display_avatar.url), description="Disabled"),
            id=1)
        v = LayoutView(timeout=None)
        v.add_item(Container(s, Separator(), TextDisplay("-# Antinuke disabled")))
        await ctx.send(view=v)

    # ══ /antinuke extraowner (subgroup) ═══════════════════════════════════════

    @antinuke_group.group(name="extraowner", description="Manage extra owners for antinuke commands",
                          aliases=["eo"])
    @commands.guild_only()
    async def extraowner(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Extra Owner Commands", color=0x000000,
                description=(
                    f"`{ctx.prefix}antinuke extraowner add @user` — Grant extra-owner access\n"
                    f"`{ctx.prefix}antinuke extraowner remove @user` — Revoke extra-owner access\n"
                    f"`{ctx.prefix}antinuke extraowner list` — List extra owners"
                ))
            await ctx.send(embed=embed)

    @extraowner.command(name="add", description="Grant a member extra-owner access to antinuke commands")
    @commands.guild_only()
    async def extraowner_add(self, ctx: commands.Context, member: discord.Member):
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send("❌ Only the server owner or Bot Owner can add extra owners.", ephemeral=True)
        db = await _open_db()
        try:
            async with db.execute("SELECT 1 FROM extraowners WHERE guild_id = ? AND owner_id = ?",
                                  (ctx.guild.id, member.id)) as c:
                if await c.fetchone():
                    return await ctx.send(f"❌ {member.mention} is already an extra owner.", ephemeral=True)
            await db.execute("INSERT INTO extraowners (guild_id, owner_id) VALUES (?, ?)", (ctx.guild.id, member.id))
            await db.commit()
        finally:
            await db.close()
        embed = discord.Embed(title="✅ Extra Owner Added", color=0x000000,
                              description=f"{member.mention} can now use antinuke and whitelist commands.")
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @extraowner.command(name="remove", description="Revoke a member's extra-owner access")
    @commands.guild_only()
    async def extraowner_remove(self, ctx: commands.Context, member: discord.Member):
        if ctx.author.id != ctx.guild.owner_id and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send("❌ Only the server owner or Bot Owner can remove extra owners.", ephemeral=True)
        db = await _open_db()
        try:
            result = await db.execute("DELETE FROM extraowners WHERE guild_id = ? AND owner_id = ?",
                                      (ctx.guild.id, member.id))
            await db.commit()
        finally:
            await db.close()
        if result.rowcount == 0:
            return await ctx.send(f"❌ {member.mention} is not an extra owner.", ephemeral=True)
        embed = discord.Embed(title="✅ Extra Owner Removed", color=0x000000,
                              description=f"{member.mention} has been removed from extra owners.")
        await ctx.send(embed=embed)

    @extraowner.command(name="list", description="List all extra owners in this server")
    @commands.guild_only()
    async def extraowner_list(self, ctx: commands.Context):
        db = await _open_db()
        try:
            if not await _is_privileged(ctx.author.id, ctx.guild, db):
                return await ctx.send("❌ Only the Server Owner, an Extra Owner, or the Bot Owner can use this command.", ephemeral=True)
            async with db.execute("SELECT owner_id FROM extraowners WHERE guild_id = ?", (ctx.guild.id,)) as c:
                rows = await c.fetchall()
        finally:
            await db.close()
        if not rows:
            return await ctx.send("No extra owners set for this server.", ephemeral=True)
        embed = discord.Embed(title=f"Extra Owners — {ctx.guild.name}", color=0x000000,
                              description=", ".join(f"<@{r[0]}>" for r in rows))
        await ctx.send(embed=embed)

    # ── Punishment button listener ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.data and interaction.data.get("custom_id") == "antinuke_show_punishment":
            s = Section(
                TextDisplay(
                    "# **Punishment Types (Unwhitelisted Admins/Mods)**\n"
                    "> **Anti Ban:** Ban executor\n"
                    "> **Anti Kick:** Ban executor\n"
                    "> **Anti Bot Add:** Ban the bot inviter\n"
                    "> **Anti Channel Create/Delete/Update:** Ban executor\n"
                    "> **Anti Everyone/Here:** Delete message & 1-hour timeout\n"
                    "> **Anti Role Create/Delete/Update:** Ban executor\n"
                    "> **Anti Member Update:** Ban executor\n"
                    "> **Anti Guild Update:** Ban executor\n"
                    "> **Anti Integration:** Ban executor\n"
                    "> **Anti Webhook Create/Delete/Update:** Ban executor\n"
                    "> **Anti Prune:** Ban executor\n\n"
                    "> *For member updates, action is taken only if the added role carries dangerous permissions.*"
                ),
                accessory=Thumbnail(media=discord.UnfurledMediaItem(url=interaction.client.user.display_avatar.url), description="Punishments"),
                id=1,
            )
            v = LayoutView(timeout=None)
            v.add_item(Container(s, Separator(), TextDisplay("-# Punishments are fixed per event type")))
            await interaction.response.send_message(view=v, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntinukeCog(bot))
