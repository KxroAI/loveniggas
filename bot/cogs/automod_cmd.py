import discord
from discord.ext import commands
import aiosqlite

from ..config import BOT_OWNER_ID


# ── UI Views ──────────────────────────────────────────────────────────────────

class ShowRules(discord.ui.View):
    def __init__(self, author: discord.User, selected_events: list):
        super().__init__(timeout=60)
        self.author = author
        self.selected_events = selected_events

    @discord.ui.button(label="Show Rules", style=discord.ButtonStyle.secondary)
    async def show_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("This button isn't for you.", ephemeral=True)
        rules = {
            "Anti NSFW link":    "**Anti NSFW Link** — Blocks NSFW links. Punishment: Block message *(fixed)*",
            "Anti caps":         "**Anti Caps** — Triggers on >70% caps (msgs <45 chars ignored). Default: Mute 1 min",
            "Anti link":         "**Anti Link** — Triggers on any link (invites/Spotify/GIFs bypassed). Default: Mute 7 min",
            "Anti invites":      "**Anti Invites** — Triggers on Discord invites (own server bypassed). Default: Mute 12 min",
            "Anti emoji spam":   "**Anti Emoji Spam** — Triggers on >5 emojis per message. Default: Mute 1 min",
            "Anti mass mention": "**Anti Mass Mention** — Triggers on >4 mentions per message. Default: Mute 3 min",
            "Anti spam":         "**Anti Spam** — Triggers when >5 messages sent rapidly. Default: Mute 12 min",
        }
        text = "\n\n".join(rules[e] for e in self.selected_events if e in rules)
        embed = discord.Embed(title="Enabled Automod Rules", description=text, color=0x4D3164)
        embed.set_footer(text="Punishment type is changeable for every event except Anti NSFW.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ConfirmDisable(discord.ui.View):
    def __init__(self, author: discord.User):
        super().__init__(timeout=30)
        self.author = author
        self.value = None

    @discord.ui.button(label="Yes, disable", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("This button isn't for you.", ephemeral=True)
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("This button isn't for you.", ephemeral=True)
        self.value = False
        await interaction.response.defer()
        self.stop()


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _is_automod_enabled(guild_id: int) -> bool:
    async with aiosqlite.connect("db/automod.db") as db:
        async with db.execute("SELECT enabled FROM automod WHERE guild_id = ?", (guild_id,)) as c:
            r = await c.fetchone()
    return r is not None and r[0] == 1


async def _get_punishments(guild_id: int) -> list:
    async with aiosqlite.connect("db/automod.db") as db:
        async with db.execute(
            "SELECT event, punishment FROM automod_punishments WHERE guild_id = ? AND event != 'Anti NSFW link'",
            (guild_id,)) as c:
            return await c.fetchall()


async def _get_exempt(guild_id: int):
    async with aiosqlite.connect("db/automod.db") as db:
        async with db.execute("SELECT id FROM automod_ignored WHERE guild_id = ? AND type = 'role'", (guild_id,)) as c:
            roles = [discord.Object(r[0]) for r in await c.fetchall()]
        async with db.execute("SELECT id FROM automod_ignored WHERE guild_id = ? AND type = 'channel'", (guild_id,)) as c:
            channels = [discord.Object(r[0]) for r in await c.fetchall()]
    return roles, channels


async def _nsfw_enabled(guild_id: int) -> bool:
    async with aiosqlite.connect("db/automod.db") as db:
        async with db.execute(
            "SELECT 1 FROM automod_punishments WHERE guild_id = ? AND event = 'Anti NSFW link'", (guild_id,)) as c:
            return await c.fetchone() is not None


def _can_manage(ctx: commands.Context) -> bool:
    """True if user is BOT_OWNER_ID, guild owner, or their top role >= bot's top role."""
    if ctx.author.id == BOT_OWNER_ID:
        return True
    if ctx.author.id == ctx.guild.owner_id:
        return True
    return ctx.author.top_role.position >= ctx.guild.me.top_role.position


# ── AutoMod Cog ───────────────────────────────────────────────────────────────

class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.default_punishment = "Mute"
        self.bot.loop.create_task(self._init_db())

    async def _init_db(self):
        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS automod (guild_id INTEGER PRIMARY KEY, enabled INTEGER DEFAULT 0)")
            await db.execute("CREATE TABLE IF NOT EXISTS automod_punishments (guild_id INTEGER, event TEXT, punishment TEXT, PRIMARY KEY (guild_id, event))")
            await db.execute("CREATE TABLE IF NOT EXISTS automod_ignored (guild_id INTEGER, type TEXT, id INTEGER, PRIMARY KEY (guild_id, type, id))")
            await db.execute("CREATE TABLE IF NOT EXISTS automod_logging (guild_id INTEGER, log_channel INTEGER, PRIMARY KEY (guild_id))")
            await db.commit()

    # ══ automod (group) ════════════════════════════════════════════════════════

    @commands.hybrid_group(name="automod", description="Automod protection commands", aliases=["am"])
    @commands.guild_only()
    async def automod_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Automod Commands", color=0x4D3164,
                description=(
                    f"`{ctx.prefix}automod enable` — Enable automod\n"
                    f"`{ctx.prefix}automod disable` — Disable automod\n"
                    f"`{ctx.prefix}automod config` — View settings\n"
                    f"`{ctx.prefix}automod punishment` — Set punishments\n"
                    f"`{ctx.prefix}automod logging <#channel>` — Set log channel\n"
                    f"`{ctx.prefix}automod ignore channel/role` — Exempt channels/roles\n"
                    f"`{ctx.prefix}automod unignore channel/role` — Remove exemptions"
                ))
            embed.set_thumbnail(url=self.bot.user.avatar.url)
            await ctx.send(embed=embed)

    # ── automod enable ────────────────────────────────────────────────────────

    @automod_group.command(name="enable", description="Enable automod and select which events to watch")
    @commands.guild_only()
    async def automod_enable(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Your top role must be at the **same** position or **higher** than mine, or you must be the Bot Owner.",
                color=0x000000), ephemeral=True)
        guild_id = ctx.guild.id
        if await _is_automod_enabled(guild_id):
            embed = discord.Embed(
                title=f"Automod — {ctx.guild.name}",
                description=f"Automod is **already enabled**.\nTo disable: `{ctx.prefix}automod disable`",
                color=0x4D3164)
            embed.set_thumbnail(url=self.bot.user.avatar.url)
            return await ctx.send(embed=embed, ephemeral=True)

        events = ["Anti spam", "Anti caps", "Anti link", "Anti invites",
                  "Anti mass mention", "Anti emoji spam", "Anti NSFW link"]

        embed = discord.Embed(title=f"{ctx.guild.name} — Automod Setup", color=0x000000)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.description = "\n".join(f"❌ : {e}" for e in events)

        select = discord.ui.Select(
            placeholder="Select events to enable", min_values=1, max_values=len(events),
            options=[discord.SelectOption(label=e, value=e) for e in events])
        btn_all = discord.ui.Button(label="Enable All Events", style=discord.ButtonStyle.primary)
        btn_cancel = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.danger)

        view = discord.ui.View(timeout=60)
        view.add_item(select)
        view.add_item(btn_all)
        view.add_item(btn_cancel)

        async def select_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This menu isn't for you.", ephemeral=True)
            await self._do_enable(ctx, i, guild_id, select.values)

        async def all_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This button isn't for you.", ephemeral=True)
            await self._do_enable(ctx, i, guild_id, events)

        async def cancel_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This button isn't for you.", ephemeral=True)
            for item in view.children:
                item.disabled = True
            await i.response.edit_message(content="Setup cancelled.", embed=embed, view=view)

        select.callback = select_cb
        btn_all.callback = all_cb
        btn_cancel.callback = cancel_cb
        await ctx.send(embed=embed, view=view)

    async def _do_enable(self, ctx: commands.Context, i: discord.Interaction,
                         guild_id: int, selected_events: list):
        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("INSERT OR REPLACE INTO automod (guild_id, enabled) VALUES (?, 1)", (guild_id,))
            for event in selected_events:
                await db.execute(
                    "INSERT OR REPLACE INTO automod_punishments (guild_id, event, punishment) VALUES (?, ?, ?)",
                    (guild_id, event, self.default_punishment))
            await db.commit()

        if "Anti NSFW link" in selected_events:
            exempt_roles, exempt_channels = await _get_exempt(guild_id)
            nsfw_keywords = ["porn", "xxx", "adult", "sex", "nsfw", "xnxx", "onlyfans", "brazzers",
                             "xhamster", "xvideos", "pornhub", "redtube", "livejasmin", "youporn",
                             "tube8", "pornhat", "swxvid", "ixxx"]
            try:
                await i.guild.create_automod_rule(
                    name="Anti NSFW Links",
                    event_type=discord.AutoModRuleEventType.message_send,
                    trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword,
                                                   keyword_filter=nsfw_keywords),
                    actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)],
                    enabled=True, exempt_roles=exempt_roles, exempt_channels=exempt_channels,
                    reason="Automod — Anti NSFW Link setup")
            except (discord.Forbidden, discord.HTTPException):
                pass

        all_events = ["Anti spam", "Anti caps", "Anti link", "Anti invites",
                      "Anti mass mention", "Anti emoji spam", "Anti NSFW link"]
        embed = discord.Embed(title="✅ Automod Enabled", color=0x000000)
        embed.description = "\n".join(
            f"{'✅' if e in selected_events else '❌'} : {e}" for e in all_events)

        log_btn = discord.ui.Button(label="Enable Logging Channel", style=discord.ButtonStyle.success)

        async def log_cb(li: discord.Interaction):
            if li.user.id != ctx.author.id:
                return await li.response.send_message("This button isn't for you.", ephemeral=True)
            if not li.guild.me.guild_permissions.manage_channels:
                return await li.response.send_message("I need Manage Channels permission.", ephemeral=True)
            for ch in li.guild.channels:
                if ch.name == "automod-logs":
                    return await li.response.send_message("A channel named `automod-logs` already exists.", ephemeral=True)
            try:
                overwrites = {
                    li.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    li.guild.me: discord.PermissionOverwrite(view_channel=True),
                }
                log_channel = await li.guild.create_text_channel("automod-logs", overwrites=overwrites)
                async with aiosqlite.connect("db/automod.db") as db:
                    await db.execute("INSERT OR REPLACE INTO automod_logging (guild_id, log_channel) VALUES (?, ?)",
                                     (guild_id, log_channel.id))
                    await db.commit()
                await li.response.send_message(f"Logging channel {log_channel.mention} created.", ephemeral=True)
            except discord.HTTPException as e:
                await li.response.send_message(f"Failed to create channel: {e}", ephemeral=True)

        log_btn.callback = log_cb
        final_view = ShowRules(ctx.author, selected_events)
        final_view.add_item(log_btn)
        await i.response.edit_message(content="Setup completed.", embed=embed, view=final_view)

    # ── automod disable ───────────────────────────────────────────────────────

    @automod_group.command(name="disable", description="Disable automod and clear all settings")
    @commands.guild_only()
    async def automod_disable(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Your top role must be at the **same** position or **higher** than mine, or you must be the Bot Owner.",
                color=0x000000), ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(embed=discord.Embed(
                title="Automod Not Enabled",
                description=f"Use `{ctx.prefix}automod enable` to enable automod first.",
                color=0x000000), ephemeral=True)

        embed = discord.Embed(
            title="Disable Automod — Confirmation",
            description="**Are you sure?** This will remove all events, punishments, exemptions and logging settings.",
            color=0x4D3164)
        embed.set_thumbnail(url=self.bot.user.avatar.url)

        view = ConfirmDisable(ctx.author)
        msg = await ctx.send(embed=embed, view=view)
        await view.wait()

        if view.value is None:
            embed.title = "Timed Out"
            embed.description = "Automod disable was cancelled (no response in time)."
            return await msg.edit(embed=embed, view=None)

        if not view.value:
            embed.title = "Cancelled"
            embed.description = "Automod disable was cancelled."
            return await msg.edit(embed=embed, view=None)

        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("DELETE FROM automod WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM automod_punishments WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM automod_ignored WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM automod_logging WHERE guild_id = ?", (guild_id,))
            await db.commit()

        try:
            rules = await ctx.guild.fetch_automod_rules()
            for rule in rules:
                if rule.name == "Anti NSFW Links":
                    await rule.delete(reason="Automod disabled")
        except (discord.Forbidden, discord.HTTPException):
            pass

        embed.title = "✅ Automod Disabled"
        embed.description = (f"Automod has been disabled for **{ctx.guild.name}**.\n"
                             "All settings cleared. Use `{ctx.prefix}automod enable` to re-enable.")
        await msg.edit(embed=embed, view=None)

    # ── automod punishment ────────────────────────────────────────────────────

    @automod_group.command(name="punishment", aliases=["punish"],
                           description="Set the punishment type for automod events")
    @commands.guild_only()
    async def automod_punishment(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Your top role must be at the **same** position or **higher** than mine, or you must be the Bot Owner.",
                color=0x000000), ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(embed=discord.Embed(
                title="Automod Not Enabled",
                description=f"Use `{ctx.prefix}automod enable` to enable automod first.",
                color=0x000000), ephemeral=True)

        current = await _get_punishments(guild_id)
        if not current:
            return await ctx.send("No automod events configured.", ephemeral=True)

        embed = discord.Embed(title=f"Automod Punishments — {ctx.guild.name}", color=0x000000)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        embed.set_footer(text="Tip: Keep Mute to protect against raids without perma-banning.")
        for event, pun in current:
            embed.add_field(name=event, value=pun or "None", inline=False)

        events = [e for e, _ in current]
        sel = discord.ui.Select(
            placeholder="Select event(s) to update", min_values=1, max_values=len(events),
            options=[discord.SelectOption(label=e) for e in events])
        view = discord.ui.View(timeout=60)
        view.add_item(sel)

        async def sel_cb(i: discord.Interaction):
            if i.user.id != ctx.author.id:
                return await i.response.send_message("This menu isn't for you.", ephemeral=True)
            selected = sel.values
            pun_view = discord.ui.View(timeout=30)
            for p in ["Mute", "Kick", "Ban"]:
                btn = discord.ui.Button(label=p, style=discord.ButtonStyle.danger)

                async def pun_cb(bi: discord.Interaction, punishment=p, sel_events=selected):
                    if bi.user.id != ctx.author.id:
                        return await bi.response.send_message("This button isn't for you.", ephemeral=True)
                    async with aiosqlite.connect("db/automod.db") as db:
                        for ev in sel_events:
                            await db.execute(
                                "INSERT OR REPLACE INTO automod_punishments (guild_id, event, punishment) VALUES (?, ?, ?)",
                                (guild_id, ev, punishment))
                        await db.commit()
                    updated = await _get_punishments(guild_id)
                    new_embed = discord.Embed(title=f"Updated Punishments — {ctx.guild.name}", color=0x000000)
                    new_embed.set_thumbnail(url=ctx.bot.user.avatar.url)
                    for ev, pn in updated:
                        new_embed.add_field(name=ev, value=pn or "None", inline=False)
                    await bi.response.edit_message(embed=new_embed, view=None)

                btn.callback = pun_cb
                pun_view.add_item(btn)

            await i.response.send_message(
                f"Setting punishment for: **{', '.join(selected)}** — choose:", view=pun_view)

        sel.callback = sel_cb
        await ctx.send(embed=embed, view=view)

    # ── automod config ────────────────────────────────────────────────────────

    @automod_group.command(name="config", aliases=["settings", "show", "view"],
                           description="View current automod configuration")
    @commands.guild_only()
    async def automod_config(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Your top role must be at the **same** position or **higher** than mine, or you must be the Bot Owner.",
                color=0x000000), ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(embed=discord.Embed(
                title="Automod Not Enabled",
                description=f"Use `{ctx.prefix}automod enable` to enable automod first.",
                color=0x000000), ephemeral=True)

        current = await _get_punishments(guild_id)
        embed = discord.Embed(title=f"Automod Config — {ctx.guild.name}", color=0x4D3164)
        embed.set_footer(text="Use automod punishment to change punishments.")
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else self.bot.user.avatar.url)

        for event, pun in current:
            embed.add_field(name=event, value=pun or "None", inline=False)

        if await _nsfw_enabled(guild_id):
            embed.add_field(name="Anti NSFW Links", value="Block Message", inline=False)

        async with aiosqlite.connect("db/automod.db") as db:
            async with db.execute("SELECT log_channel FROM automod_logging WHERE guild_id = ?", (guild_id,)) as c:
                row = await c.fetchone()

        if row and row[0]:
            ch = ctx.guild.get_channel(row[0])
            embed.add_field(name="Logging Channel", value=ch.mention if ch else "Deleted Channel", inline=False)
        else:
            embed.add_field(name="Logging Channel", value="Not set", inline=False)

        await ctx.send(embed=embed)

    # ── automod logging ───────────────────────────────────────────────────────

    @automod_group.command(name="logging", description="Set the automod log channel")
    @commands.guild_only()
    async def automod_logging(self, ctx: commands.Context, channel: discord.TextChannel):
        if not _can_manage(ctx):
            return await ctx.send(embed=discord.Embed(
                title="❌ Access Denied",
                description="Your top role must be at the **same** position or **higher** than mine, or you must be the Bot Owner.",
                color=0x000000), ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(embed=discord.Embed(
                title="Automod Not Enabled",
                description=f"Use `{ctx.prefix}automod enable` to enable automod first.",
                color=0x000000), ephemeral=True)

        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("INSERT OR REPLACE INTO automod_logging (guild_id, log_channel) VALUES (?, ?)",
                             (guild_id, channel.id))
            await db.commit()

        embed = discord.Embed(
            title=f"Automod Settings — {ctx.guild.name}",
            description=f"✅ Logging channel set to {channel.mention}.\nUse `{ctx.prefix}automod config` to view all settings.",
            color=0x4D3164)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        await ctx.send(embed=embed)

    # ══ ignore (subgroup) ══════════════════════════════════════════════════════

    @automod_group.group(name="ignore", aliases=["exempt"],
                         description="Exempt channels or roles from automod")
    @commands.guild_only()
    async def ignore_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Automod Ignore", color=0x000000,
                description=(
                    f"`{ctx.prefix}automod ignore channel #channel` — Exempt a channel\n"
                    f"`{ctx.prefix}automod ignore role @role` — Exempt a role\n"
                    f"`{ctx.prefix}automod ignore show` — View exemptions\n"
                    f"`{ctx.prefix}automod ignore reset` — Clear all exemptions"
                ))
            await ctx.send(embed=embed)

    @ignore_group.command(name="channel", description="Exempt a channel from automod")
    @commands.guild_only()
    async def ignore_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        async with aiosqlite.connect("db/automod.db") as db:
            async with db.execute("SELECT 1 FROM automod_ignored WHERE guild_id = ? AND type = 'channel' AND id = ?",
                                  (guild_id, channel.id)) as c:
                if await c.fetchone():
                    return await ctx.send(f"❌ {channel.mention} is already exempted.", ephemeral=True)
            async with db.execute("SELECT COUNT(*) FROM automod_ignored WHERE guild_id = ? AND type = 'channel'",
                                  (guild_id,)) as c:
                if (await c.fetchone())[0] >= 10:
                    return await ctx.send("You can only exempt up to 10 channels.", ephemeral=True)
            await db.execute("INSERT OR REPLACE INTO automod_ignored (guild_id, type, id) VALUES (?, 'channel', ?)",
                             (guild_id, channel.id))
            await db.commit()

        if await _nsfw_enabled(guild_id):
            try:
                for rule in await ctx.guild.fetch_automod_rules():
                    if rule.name == "Anti NSFW Links":
                        await rule.edit(exempt_channels=list(rule.exempt_channels) + [channel],
                                        reason="Automod ignore channel")
                        break
            except discord.HTTPException:
                pass

        embed = discord.Embed(title="✅ Channel Exempted",
                              description=f"{channel.mention} is now exempt from automod.", color=0x000000)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        await ctx.send(embed=embed)

    @ignore_group.command(name="role", description="Exempt a role from automod")
    @commands.guild_only()
    async def ignore_role(self, ctx: commands.Context, role: discord.Role):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        async with aiosqlite.connect("db/automod.db") as db:
            async with db.execute("SELECT 1 FROM automod_ignored WHERE guild_id = ? AND type = 'role' AND id = ?",
                                  (guild_id, role.id)) as c:
                if await c.fetchone():
                    return await ctx.send(f"❌ {role.mention} is already exempted.", ephemeral=True)
            async with db.execute("SELECT COUNT(*) FROM automod_ignored WHERE guild_id = ? AND type = 'role'",
                                  (guild_id,)) as c:
                if (await c.fetchone())[0] >= 10:
                    return await ctx.send("You can only exempt up to 10 roles.", ephemeral=True)
            await db.execute("INSERT OR REPLACE INTO automod_ignored (guild_id, type, id) VALUES (?, 'role', ?)",
                             (guild_id, role.id))
            await db.commit()

        if await _nsfw_enabled(guild_id):
            try:
                for rule in await ctx.guild.fetch_automod_rules():
                    if rule.name == "Anti NSFW Links":
                        await rule.edit(exempt_roles=list(rule.exempt_roles) + [role],
                                        reason="Automod ignore role")
                        break
            except discord.HTTPException:
                pass

        embed = discord.Embed(title="✅ Role Exempted",
                              description=f"{role.mention} is now exempt from automod.", color=0x000000)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        await ctx.send(embed=embed)

    @ignore_group.command(name="show", aliases=["view", "list"],
                          description="Show all exempted channels and roles")
    @commands.guild_only()
    async def ignore_show(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        async with aiosqlite.connect("db/automod.db") as db:
            async with db.execute("SELECT type, id FROM automod_ignored WHERE guild_id = ?", (guild_id,)) as c:
                items = await c.fetchall()

        if not items:
            return await ctx.send("No exempted channels or roles found.", ephemeral=True)

        ch_lines, role_lines = [], []
        for t, oid in items:
            if t == "channel":
                ch = ctx.guild.get_channel(oid)
                ch_lines.append(ch.mention if ch else f"Deleted Channel (ID: {oid})")
            else:
                r = ctx.guild.get_role(oid)
                role_lines.append(r.mention if r else f"Deleted Role (ID: {oid})")

        embed = discord.Embed(title="Automod Exemptions", color=0x000000)
        embed.add_field(name="Channels", value="\n".join(ch_lines) or "None", inline=False)
        embed.add_field(name="Roles", value="\n".join(role_lines) or "None", inline=False)
        await ctx.send(embed=embed)

    @ignore_group.command(name="reset", description="Clear all automod exemptions")
    @commands.guild_only()
    async def ignore_reset(self, ctx: commands.Context):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("DELETE FROM automod_ignored WHERE guild_id = ?", (guild_id,))
            await db.commit()

        embed = discord.Embed(title="✅ Exemptions Cleared",
                              description="All exempted channels and roles have been removed.", color=0x4D3164)
        embed.set_thumbnail(url=self.bot.user.avatar.url)
        await ctx.send(embed=embed)

    # ══ unignore (subgroup) ════════════════════════════════════════════════════

    @automod_group.group(name="unignore", aliases=["unexempt"],
                         description="Remove exemptions from automod")
    @commands.guild_only()
    async def unignore_group(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="Automod Unignore", color=0x000000,
                description=(
                    f"`{ctx.prefix}automod unignore channel #channel` — Remove channel exemption\n"
                    f"`{ctx.prefix}automod unignore role @role` — Remove role exemption"
                ))
            await ctx.send(embed=embed)

    @unignore_group.command(name="channel", description="Remove a channel from automod exemptions")
    @commands.guild_only()
    async def unignore_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        if await _nsfw_enabled(guild_id):
            try:
                for rule in await ctx.guild.fetch_automod_rules():
                    if rule.name == "Anti NSFW Links":
                        new_ch = [ch for ch in rule.exempt_channels if ch.id != channel.id]
                        await rule.edit(exempt_channels=new_ch, reason="Automod unignore channel")
                        break
            except discord.HTTPException:
                pass

        async with aiosqlite.connect("db/automod.db") as db:
            result = await db.execute(
                "DELETE FROM automod_ignored WHERE guild_id = ? AND type = 'channel' AND id = ?",
                (guild_id, channel.id))
            await db.commit()

        if result.rowcount > 0:
            embed = discord.Embed(title="✅ Exemption Removed",
                                  description=f"{channel.mention} is no longer exempt.", color=0x000000)
        else:
            embed = discord.Embed(title="❌ Not Found",
                                  description=f"{channel.mention} is not in the exemptions list.", color=0x000000)
        await ctx.send(embed=embed)

    @unignore_group.command(name="role", description="Remove a role from automod exemptions")
    @commands.guild_only()
    async def unignore_role(self, ctx: commands.Context, role: discord.Role):
        if not _can_manage(ctx):
            return await ctx.send("❌ Access Denied.", ephemeral=True)
        guild_id = ctx.guild.id
        if not await _is_automod_enabled(guild_id):
            return await ctx.send(f"Automod is not enabled. Use `{ctx.prefix}automod enable` first.", ephemeral=True)

        if await _nsfw_enabled(guild_id):
            try:
                for rule in await ctx.guild.fetch_automod_rules():
                    if rule.name == "Anti NSFW Links":
                        new_r = [r for r in rule.exempt_roles if r.id != role.id]
                        await rule.edit(exempt_roles=new_r, reason="Automod unignore role")
                        break
            except discord.HTTPException:
                pass

        async with aiosqlite.connect("db/automod.db") as db:
            result = await db.execute(
                "DELETE FROM automod_ignored WHERE guild_id = ? AND type = 'role' AND id = ?",
                (guild_id, role.id))
            await db.commit()

        if result.rowcount > 0:
            embed = discord.Embed(title="✅ Exemption Removed",
                                  description=f"{role.mention} is no longer exempt.", color=0x000000)
        else:
            embed = discord.Embed(title="❌ Not Found",
                                  description=f"{role.mention} is not in the exemptions list.", color=0x000000)
        await ctx.send(embed=embed)

    # ── Cleanup on guild remove ───────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        async with aiosqlite.connect("db/automod.db") as db:
            await db.execute("DELETE FROM automod WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM automod_punishments WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM automod_ignored WHERE guild_id = ?", (guild.id,))
            await db.execute("DELETE FROM automod_logging WHERE guild_id = ?", (guild.id,))
            await db.commit()


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModCog(bot))
