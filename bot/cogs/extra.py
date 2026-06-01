"""
Extras Cog
Slash commands: steal (context menu), autoresponder, autoreact, voicemaster.
"""

import os
import re
from io import BytesIO

import aiohttp
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks


DB_PATH = "db/extras.db"

SUCCESS = "<:check:1408031262312108102>"
FAIL = "<:cross:1408031235057385564>"


# ── DATABASE SETUP ─────────────────────────────────────────────────────────────

async def init_db():
    os.makedirs("db", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS autoresponders (
            guild INTEGER,
            trigger TEXT,
            response TEXT
        );

        CREATE TABLE IF NOT EXISTS autoreacts (
            guild INTEGER,
            trigger TEXT,
            emoji TEXT
        );

        CREATE TABLE IF NOT EXISTS voicemaster (
            guild_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            interface_id INTEGER,
            joinvc_id INTEGER,
            msg_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS vc_owners (
            channel_id INTEGER PRIMARY KEY,
            owner_id INTEGER
        );
        """)
        await db.commit()


# ── VOICEMASTER PANEL ──────────────────────────────────────────────────────────

class VoiceMasterView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _get_member_vc(self, interaction: discord.Interaction):
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.voice or not member.voice.channel:
            await interaction.response.send_message(
                f"{FAIL} You must be in a voice channel to use this.", ephemeral=True
            )
            return None, None

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT owner_id FROM vc_owners WHERE channel_id=?",
                (member.voice.channel.id,)
            ) as cursor:
                row = await cursor.fetchone()

        if not row or row[0] != member.id:
            await interaction.response.send_message(
                f"{FAIL} You don't own this voice channel.", ephemeral=True
            )
            return None, None

        return member.voice.channel, member

    @discord.ui.button(emoji="🔒", style=discord.ButtonStyle.gray, custom_id="vm_lock")
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                await vc.set_permissions(interaction.guild.default_role, connect=False)
                await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)

    @discord.ui.button(emoji="🔓", style=discord.ButtonStyle.gray, custom_id="vm_unlock")
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                await vc.set_permissions(interaction.guild.default_role, connect=True)
                await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)

    @discord.ui.button(emoji="🙈", style=discord.ButtonStyle.gray, custom_id="vm_hide")
    async def hide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                await vc.set_permissions(interaction.guild.default_role, view_channel=False)
                await interaction.response.send_message("🙈 Channel hidden.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)

    @discord.ui.button(emoji="👁️", style=discord.ButtonStyle.gray, custom_id="vm_unhide")
    async def unhide(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                await vc.set_permissions(interaction.guild.default_role, view_channel=True)
                await interaction.response.send_message("👁️ Channel visible.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)

    @discord.ui.button(emoji="➕", style=discord.ButtonStyle.gray, custom_id="vm_plus")
    async def plus(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                limit = (vc.user_limit or 0) + 1
                await vc.edit(user_limit=limit)
                await interaction.response.send_message(f"➕ User limit set to {limit}.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)

    @discord.ui.button(emoji="➖", style=discord.ButtonStyle.gray, custom_id="vm_minus")
    async def minus(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc, member = await self._get_member_vc(interaction)
        if vc:
            try:
                limit = max((vc.user_limit or 1) - 1, 0)
                await vc.edit(user_limit=limit)
                await interaction.response.send_message(f"➖ User limit set to {limit}.", ephemeral=True)
            except discord.Forbidden:
                await interaction.response.send_message(f"{FAIL} Missing permissions.", ephemeral=True)


# ── EXTRAS COG ────────────────────────────────────────────────────────────────

class ExtrasCog(commands.Cog, name="Extras"):

    # ── Slash groups ──────────────────────────────────────────────────────────
    ar = app_commands.Group(name="ar", description="Autoresponder commands")
    react = app_commands.Group(name="react", description="Autoreact commands")
    vm = app_commands.Group(name="vm", description="VoiceMaster commands")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.steal_ctx = app_commands.ContextMenu(
            name="Steal Emoji/Sticker",
            callback=self._steal_callback,
        )
        bot.tree.add_command(self.steal_ctx)
        bot.loop.create_task(self._startup())

    async def _startup(self):
        await init_db()
        self.cleanup_vc.start()
        self.bot.add_view(VoiceMasterView(self.bot))

    def cog_unload(self):
        self.bot.tree.remove_command("Steal Emoji/Sticker", type=discord.AppCommandType.message)
        self.cleanup_vc.cancel()

    # ── STEAL (right-click context menu) ──────────────────────────────────────

    async def _steal_callback(self, interaction: discord.Interaction, message: discord.Message):
        if not interaction.guild:
            return await interaction.response.send_message(f"{FAIL} Server only.", ephemeral=True)
        member = interaction.guild.get_member(interaction.user.id)
        if not member or not member.guild_permissions.manage_emojis:
            return await interaction.response.send_message(
                f"{FAIL} You need **Manage Emojis** permission.", ephemeral=True
            )

        emojis = re.findall(r"<(a?):(\w+):(\d+)>", message.content)
        stickers = list(message.stickers)
        attachments = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]

        if not emojis and not stickers and not attachments:
            return await interaction.response.send_message(
                f"{FAIL} No emoji, sticker, or image found in that message.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        stolen = []
        async with aiohttp.ClientSession() as session:
            for animated_flag, name, emoji_id in emojis:
                ext = "gif" if animated_flag == "a" else "png"
                url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
                try:
                    async with session.get(url) as resp:
                        data = await resp.read()
                    new_emoji = await interaction.guild.create_custom_emoji(
                        name=name, image=data, reason=f"Stolen by {interaction.user}"
                    )
                    stolen.append(str(new_emoji))
                except discord.HTTPException as e:
                    await interaction.followup.send(f"{FAIL} Couldn't steal emoji `{name}`: {e}", ephemeral=True)

            for sticker in stickers:
                try:
                    async with session.get(sticker.url) as resp:
                        data = await resp.read()
                    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", sticker.name)[:32] or "sticker"
                    await interaction.guild.create_sticker(
                        name=safe_name, description="Stolen sticker",
                        emoji="⭐", file=discord.File(BytesIO(data), filename="sticker.png"),
                        reason=f"Stolen by {interaction.user}",
                    )
                    stolen.append(f"sticker `{safe_name}`")
                except discord.HTTPException as e:
                    await interaction.followup.send(f"{FAIL} Couldn't steal sticker `{sticker.name}`: {e}", ephemeral=True)

            for attachment in attachments:
                try:
                    async with session.get(attachment.url) as resp:
                        data = await resp.read()
                    name = re.sub(r"[^a-zA-Z0-9_]", "_", attachment.filename.rsplit(".", 1)[0])[:32] or "emoji"
                    new_emoji = await interaction.guild.create_custom_emoji(
                        name=name, image=data, reason=f"Stolen by {interaction.user}"
                    )
                    stolen.append(str(new_emoji))
                except discord.HTTPException as e:
                    await interaction.followup.send(f"{FAIL} Couldn't steal image `{attachment.filename}`: {e}", ephemeral=True)

        if stolen:
            await interaction.followup.send(f"{SUCCESS} Stolen: {' '.join(stolen)}", ephemeral=True)

    # ── ADD EMOJI ─────────────────────────────────────────────────────────────

    @app_commands.command(name="addemoji", description="Add any emoji to this server — no manual uploading needed")
    @app_commands.describe(emoji="Paste any custom emoji here (e.g. <:name:id> or <a:name:id>)")
    @app_commands.default_permissions(manage_emojis=True)
    async def addemoji(self, interaction: discord.Interaction, emoji: str):
        if not interaction.guild:
            return await interaction.response.send_message(f"{FAIL} Server only.", ephemeral=True)

        matches = re.findall(r"<(a?):(\w+):(\d+)>", emoji)
        if not matches:
            return await interaction.response.send_message(
                f"{FAIL} That doesn't look like a custom emoji. Paste it like `<:name:id>` or `<a:name:id>`.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        added = []
        failed = []
        async with aiohttp.ClientSession() as session:
            for animated_flag, name, emoji_id in matches:
                ext = "gif" if animated_flag == "a" else "png"
                url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            failed.append(f"`{name}` (download failed)")
                            continue
                        data = await resp.read()
                    new_emoji = await interaction.guild.create_custom_emoji(
                        name=name,
                        image=data,
                        reason=f"Added via /addemoji by {interaction.user}",
                    )
                    added.append(str(new_emoji))
                except discord.HTTPException as e:
                    failed.append(f"`{name}`: {e}")

        lines = []
        if added:
            lines.append(f"{SUCCESS} Added: {' '.join(added)}")
        if failed:
            lines.append(f"{FAIL} Failed: " + ", ".join(failed))
        await interaction.followup.send("\n".join(lines) or f"{FAIL} Nothing was added.", ephemeral=True)

    # ── AUTORESPONDER ─────────────────────────────────────────────────────────

    @ar.command(name="add", description="Add an autoresponder trigger")
    @app_commands.describe(trigger="Word or phrase to trigger on", response="What the bot replies")
    @app_commands.default_permissions(manage_messages=True)
    async def ar_add(self, interaction: discord.Interaction, trigger: str, response: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO autoresponders VALUES (?, ?, ?)",
                (interaction.guild_id, trigger.lower(), response),
            )
            await db.commit()
        await interaction.response.send_message(
            f"{SUCCESS} Autoresponder added for trigger `{trigger}`", ephemeral=True
        )

    @ar.command(name="remove", description="Remove an autoresponder trigger")
    @app_commands.describe(trigger="The trigger to remove")
    @app_commands.default_permissions(manage_messages=True)
    async def ar_remove(self, interaction: discord.Interaction, trigger: str):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "DELETE FROM autoresponders WHERE guild=? AND trigger=?",
                (interaction.guild_id, trigger.lower()),
            )
            await db.commit()
        if cur.rowcount:
            await interaction.response.send_message(
                f"{SUCCESS} Removed autoresponder for `{trigger}`", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{FAIL} Trigger `{trigger}` not found.", ephemeral=True
            )

    @ar.command(name="list", description="List all autoresponders in this server")
    async def ar_list(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await db.execute_fetchall(
                "SELECT trigger, response FROM autoresponders WHERE guild=?",
                (interaction.guild_id,),
            )
        if not rows:
            return await interaction.response.send_message(
                f"{FAIL} No autoresponders set for this server.", ephemeral=True
            )
        lines = "\n".join(f"`{t}` → {r}" for t, r in rows)
        embed = discord.Embed(title="Autoresponders", description=lines, color=0x7289DA)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── AUTOREACT ─────────────────────────────────────────────────────────────

    @react.command(name="add", description="Add an autoreact trigger")
    @app_commands.describe(trigger="Word or phrase to trigger on", emoji="Emoji to react with")
    @app_commands.default_permissions(manage_messages=True)
    async def react_add(self, interaction: discord.Interaction, trigger: str, emoji: str):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO autoreacts VALUES (?, ?, ?)",
                (interaction.guild_id, trigger.lower(), emoji),
            )
            await db.commit()
        await interaction.response.send_message(
            f"{SUCCESS} Autoreact added: `{trigger}` → {emoji}", ephemeral=True
        )

    @react.command(name="remove", description="Remove an autoreact trigger")
    @app_commands.describe(trigger="The trigger to remove")
    @app_commands.default_permissions(manage_messages=True)
    async def react_remove(self, interaction: discord.Interaction, trigger: str):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "DELETE FROM autoreacts WHERE guild=? AND trigger=?",
                (interaction.guild_id, trigger.lower()),
            )
            await db.commit()
        if cur.rowcount:
            await interaction.response.send_message(
                f"{SUCCESS} Removed autoreact for `{trigger}`", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{FAIL} Trigger `{trigger}` not found.", ephemeral=True
            )

    @react.command(name="list", description="List all autoreacts in this server")
    async def react_list(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await db.execute_fetchall(
                "SELECT trigger, emoji FROM autoreacts WHERE guild=?",
                (interaction.guild_id,),
            )
        if not rows:
            return await interaction.response.send_message(
                f"{FAIL} No autoreacts set for this server.", ephemeral=True
            )
        lines = "\n".join(f"`{t}` → {e}" for t, e in rows)
        embed = discord.Embed(title="Autoreacts", description=lines, color=0x7289DA)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── MESSAGE LISTENER (autoresponder + autoreact) ───────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content.lower()
        words = re.findall(r"\b\w+\b", content)

        async with aiosqlite.connect(DB_PATH) as db:
            ars = await db.execute_fetchall(
                "SELECT trigger, response FROM autoresponders WHERE guild=?",
                (message.guild.id,),
            )
            reacts = await db.execute_fetchall(
                "SELECT trigger, emoji FROM autoreacts WHERE guild=?",
                (message.guild.id,),
            )

        for trigger, response in ars:
            if content.strip() == trigger:
                try:
                    await message.reply(response)
                except discord.HTTPException:
                    pass
                break

        for trigger, emoji in reacts:
            if (
                trigger in words
                or any(trigger == f"<@{m.id}>" or trigger == f"<@!{m.id}>" for m in message.mentions)
                or any(trigger == f"<@&{r.id}>" for r in message.role_mentions)
            ):
                try:
                    await message.add_reaction(emoji)
                except (discord.HTTPException, discord.NotFound):
                    pass
                break

    # ── VOICEMASTER ───────────────────────────────────────────────────────────

    @vm.command(name="setup", description="Set up VoiceMaster in this server")
    @app_commands.default_permissions(administrator=True)
    async def vm_setup(self, interaction: discord.Interaction):
        guild = interaction.guild
        required = discord.Permissions(manage_channels=True, move_members=True, manage_permissions=True)
        if not guild.me.guild_permissions >= required:
            return await interaction.response.send_message(
                f"{FAIL} I need **Manage Channels**, **Move Members**, and **Manage Permissions**.",
                ephemeral=True,
            )

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT category_id FROM voicemaster WHERE guild_id=?", (guild.id,)
            ) as cursor:
                if await cursor.fetchone():
                    return await interaction.response.send_message(
                        f"{FAIL} VoiceMaster is already set up. Use `/vm remove` first.", ephemeral=True
                    )

        await interaction.response.defer()
        try:
            category = await guild.create_category("VoiceMaster")
            joinvc = await category.create_voice_channel("➕ Join to Create")
            interface = await category.create_text_channel(
                "vm-interface",
                overwrites={guild.default_role: discord.PermissionOverwrite(send_messages=False)},
            )
            embed = discord.Embed(
                title="VoiceMaster Interface",
                description=(
                    "**Manage your voice channel:**\n\n"
                    "🔒 Lock / 🔓 Unlock — control who can join\n"
                    "🙈 Hide / 👁️ Show — control visibility\n"
                    "➕ / ➖ — adjust user limit"
                ),
                color=0x7289DA,
            )
            msg = await interface.send(embed=embed, view=VoiceMasterView(self.bot))

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO voicemaster VALUES (?,?,?,?,?)",
                    (guild.id, category.id, interface.id, joinvc.id, msg.id),
                )
                await db.commit()

            await interaction.followup.send(f"{SUCCESS} VoiceMaster setup complete in {category.mention}!")
        except discord.Forbidden:
            await interaction.followup.send(f"{FAIL} Missing permissions to create channels.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"{FAIL} Error during setup: {e}", ephemeral=True)

    @vm.command(name="remove", description="Remove VoiceMaster from this server")
    @app_commands.default_permissions(administrator=True)
    async def vm_remove(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT category_id, interface_id, joinvc_id FROM voicemaster WHERE guild_id=?",
                (guild.id,),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await interaction.response.send_message(
                    f"{FAIL} VoiceMaster is not set up in this server.", ephemeral=True
                )

            category_id, interface_id, joinvc_id = row
            for cid in [joinvc_id, interface_id, category_id]:
                ch = guild.get_channel(cid)
                if ch:
                    try:
                        await ch.delete()
                    except discord.HTTPException:
                        pass

            await db.execute("DELETE FROM voicemaster WHERE guild_id=?", (guild.id,))
            await db.commit()

        await interaction.response.send_message(f"{SUCCESS} VoiceMaster removed.")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if before.channel == after.channel:
            return

        if after.channel:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT joinvc_id, category_id FROM voicemaster WHERE guild_id=?",
                    (member.guild.id,),
                ) as cursor:
                    row = await cursor.fetchone()

            if row and after.channel.id == row[0]:
                category = member.guild.get_channel(row[1])
                if not category:
                    return
                try:
                    new_vc = await category.create_voice_channel(f"{member.display_name}'s VC")
                    await member.move_to(new_vc)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            "INSERT OR REPLACE INTO vc_owners VALUES (?,?)", (new_vc.id, member.id)
                        )
                        await db.commit()
                except (discord.Forbidden, Exception):
                    pass

        if before.channel:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT owner_id FROM vc_owners WHERE channel_id=?", (before.channel.id,)
                ) as cursor:
                    row = await cursor.fetchone()
                if row and len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                    except discord.HTTPException:
                        pass
                    await db.execute("DELETE FROM vc_owners WHERE channel_id=?", (before.channel.id,))
                    await db.commit()

    @tasks.loop(hours=1)
    async def cleanup_vc(self):
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await db.execute_fetchall("SELECT channel_id FROM vc_owners")
            for (channel_id,) in rows:
                ch = self.bot.get_channel(channel_id)
                if not ch or len(ch.members) == 0:
                    if ch:
                        try:
                            await ch.delete()
                        except discord.HTTPException:
                            pass
                    await db.execute("DELETE FROM vc_owners WHERE channel_id=?", (channel_id,))
            await db.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(ExtrasCog(bot))
