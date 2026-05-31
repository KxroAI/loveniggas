"""
Ticket System Cog
Full ticket system with persistent buttons, logs, and staff controls.
Uses aiosqlite for settings storage.
"""

import asyncio
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

from ..config import BOT_OWNER_ID, PH_TIMEZONE
from ..utils import create_embed, create_error_embed

DB_PATH = "tickets.db"

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id    INTEGER PRIMARY KEY,
                category_id INTEGER,
                support_role_id INTEGER,
                log_channel_id  INTEGER,
                ticket_count    INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id    INTEGER PRIMARY KEY,
                guild_id      INTEGER NOT NULL,
                user_id       INTEGER NOT NULL,
                ticket_number INTEGER NOT NULL,
                status        TEXT    DEFAULT 'open',
                created_at    TEXT    NOT NULL
            )
        """)
        await db.commit()


async def _get_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _set_settings(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await (
            await db.execute("SELECT guild_id FROM ticket_settings WHERE guild_id = ?", (guild_id,))
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            await db.execute(
                f"UPDATE ticket_settings SET {sets} WHERE guild_id = ?",
                (*kwargs.values(), guild_id),
            )
        else:
            kwargs["guild_id"] = guild_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            await db.execute(
                f"INSERT INTO ticket_settings ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
        await db.commit()


async def _get_ticket(channel_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _create_ticket(channel_id: int, guild_id: int, user_id: int, ticket_number: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO tickets (channel_id, guild_id, user_id, ticket_number, status, created_at) VALUES (?,?,?,?,?,?)",
            (channel_id, guild_id, user_id, ticket_number, "open", datetime.now(timezone.utc).isoformat()),
        )
        await db.execute(
            "UPDATE ticket_settings SET ticket_count = ticket_count + 1 WHERE guild_id = ?",
            (guild_id,),
        )
        await db.commit()


async def _set_ticket_status(channel_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tickets SET status = ? WHERE channel_id = ?", (status, channel_id)
        )
        await db.commit()


async def _delete_ticket_record(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM tickets WHERE channel_id = ?", (channel_id,))
        await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENT VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class TicketCreateButton(discord.ui.View):
    """Persistent view for the ticket panel — survives bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📩  Open a Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_create_btn",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user  = interaction.user

        settings = await _get_settings(guild.id)
        if not settings or not settings.get("category_id"):
            return await interaction.followup.send(
                "❌ Ticket system is not set up in this server.", ephemeral=True
            )

        # Check for an existing open ticket
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
                (guild.id, user.id),
            ) as cur:
                existing = await cur.fetchone()
        if existing:
            ch = guild.get_channel(existing[0])
            if ch:
                return await interaction.followup.send(
                    f"❌ You already have an open ticket: {ch.mention}", ephemeral=True
                )

        category = guild.get_channel(settings["category_id"])
        if not category or not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send(
                "❌ Ticket category not found. Please ask an admin to run `/ticket setup` again.",
                ephemeral=True,
            )

        ticket_num = (settings.get("ticket_count") or 0) + 1
        channel_name = f"ticket-{ticket_num:04d}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True, manage_messages=True
            ),
        }

        if settings.get("support_role_id"):
            role = guild.get_role(settings["support_role_id"])
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )

        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket #{ticket_num} opened by {user}",
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ I don't have permission to create channels in that category.", ephemeral=True
            )

        await _create_ticket(channel.id, guild.id, user.id, ticket_num)

        embed = discord.Embed(
            title=f"🎫 Ticket #{ticket_num:04d}",
            description=(
                f"Hello {user.mention}! Support staff will be with you shortly.\n\n"
                "Please describe your issue and wait for a response.\n\n"
                "Use the buttons below to manage this ticket."
            ),
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f"Opened by {user.display_name}", icon_url=user.display_avatar.url)

        close_view = TicketControlView()
        await channel.send(content=user.mention, embed=embed, view=close_view)

        if settings.get("log_channel_id"):
            log_ch = guild.get_channel(settings["log_channel_id"])
            if log_ch:
                log_embed = discord.Embed(
                    title="📂 Ticket Opened",
                    description=f"**User:** {user.mention}\n**Channel:** {channel.mention}\n**Ticket #:** {ticket_num:04d}",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc),
                )
                try:
                    await log_ch.send(embed=log_embed)
                except discord.Forbidden:
                    pass

        await interaction.followup.send(
            f"✅ Your ticket has been created: {channel.mention}", ephemeral=True
        )


class TicketControlView(discord.ui.View):
    """Buttons inside the ticket channel for close/delete."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒  Close Ticket", style=discord.ButtonStyle.secondary, custom_id="ticket_close_btn")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _do_close(interaction)

    @discord.ui.button(label="🗑️  Delete Ticket", style=discord.ButtonStyle.danger, custom_id="ticket_delete_btn")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await _do_delete(interaction)


async def _do_close(interaction: discord.Interaction):
    await interaction.response.defer()
    channel = interaction.channel
    ticket  = await _get_ticket(channel.id)

    if not ticket:
        return await interaction.followup.send("❌ This isn't a tracked ticket channel.", ephemeral=True)

    settings = await _get_settings(interaction.guild.id)
    allowed  = False
    if interaction.user.guild_permissions.manage_channels:
        allowed = True
    if settings and settings.get("support_role_id"):
        role = interaction.guild.get_role(settings["support_role_id"])
        if role and role in interaction.user.roles:
            allowed = True
    if interaction.user.id == ticket["user_id"]:
        allowed = True

    if not allowed:
        return await interaction.followup.send(
            "❌ Only the ticket owner or support staff can close this ticket.", ephemeral=True
        )

    if ticket["status"] == "closed":
        return await interaction.followup.send("❌ This ticket is already closed.", ephemeral=True)

    await _set_ticket_status(channel.id, "closed")
    user = interaction.guild.get_member(ticket["user_id"])
    if user:
        try:
            await channel.set_permissions(user, view_channel=False)
        except discord.Forbidden:
            pass

    embed = discord.Embed(
        description=f"🔒 Ticket closed by {interaction.user.mention}.",
        color=discord.Color.orange(),
    )
    reopen_view = ReopenView()
    await interaction.followup.send(embed=embed, view=reopen_view)

    if settings and settings.get("log_channel_id"):
        log_ch = interaction.guild.get_channel(settings["log_channel_id"])
        if log_ch:
            log_embed = discord.Embed(
                title="🔒 Ticket Closed",
                description=f"**Channel:** {channel.mention}\n**Closed by:** {interaction.user.mention}",
                color=discord.Color.orange(),
                timestamp=datetime.now(timezone.utc),
            )
            try:
                await log_ch.send(embed=log_embed)
            except discord.Forbidden:
                pass


async def _do_delete(interaction: discord.Interaction):
    await interaction.response.defer()
    channel = interaction.channel
    ticket  = await _get_ticket(channel.id)

    if not ticket:
        return await interaction.followup.send("❌ This isn't a tracked ticket channel.", ephemeral=True)

    if not interaction.user.guild_permissions.manage_channels:
        settings = await _get_settings(interaction.guild.id)
        allowed  = False
        if settings and settings.get("support_role_id"):
            role = interaction.guild.get_role(settings["support_role_id"])
            if role and role in interaction.user.roles:
                allowed = True
        if not allowed:
            return await interaction.followup.send(
                "❌ Only support staff can delete tickets.", ephemeral=True
            )

    settings = await _get_settings(interaction.guild.id)
    if settings and settings.get("log_channel_id"):
        log_ch = interaction.guild.get_channel(settings["log_channel_id"])
        if log_ch:
            log_embed = discord.Embed(
                title="🗑️ Ticket Deleted",
                description=f"**Channel:** #{channel.name}\n**Deleted by:** {interaction.user.mention}",
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc),
            )
            try:
                await log_ch.send(embed=log_embed)
            except discord.Forbidden:
                pass

    await _delete_ticket_record(channel.id)
    await interaction.followup.send("🗑️ Deleting ticket in 3 seconds…", ephemeral=True)
    await asyncio.sleep(3)
    try:
        await channel.delete(reason=f"Ticket deleted by {interaction.user}")
    except discord.Forbidden:
        pass


class ReopenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔓  Re-open", style=discord.ButtonStyle.success, custom_id="ticket_reopen_btn")
    async def reopen(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        channel = interaction.channel
        ticket  = await _get_ticket(channel.id)
        if not ticket:
            return await interaction.followup.send("❌ Ticket record not found.", ephemeral=True)
        if not interaction.user.guild_permissions.manage_channels:
            settings = await _get_settings(interaction.guild.id)
            allowed  = False
            if settings and settings.get("support_role_id"):
                role = interaction.guild.get_role(settings["support_role_id"])
                if role and role in interaction.user.roles:
                    allowed = True
            if not allowed:
                return await interaction.followup.send(
                    "❌ Only support staff can reopen tickets.", ephemeral=True
                )
        user = interaction.guild.get_member(ticket["user_id"])
        if user:
            try:
                await channel.set_permissions(
                    user, view_channel=True, send_messages=True, read_message_history=True
                )
            except discord.Forbidden:
                pass
        await _set_ticket_status(channel.id, "open")
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"🔓 Ticket reopened by {interaction.user.mention}.",
                color=discord.Color.green(),
            )
        )
        self.stop()


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        bot.add_view(TicketCreateButton())
        bot.add_view(TicketControlView())
        bot.add_view(ReopenView())

    async def cog_load(self):
        await _init_db()

    # ── /ticket setup ─────────────────────────────────────────────────────

    @commands.hybrid_group(name="ticket", description="Ticket system commands", with_app_command=True)
    @commands.guild_only()
    async def ticket(self, ctx: commands.Context):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @ticket.command(name="setup", description="Set up the ticket system for this server")
    @app_commands.describe(
        category="Category where ticket channels will be created",
        support_role="Role that can see and manage tickets",
        log_channel="Channel to log ticket activity",
    )
    @commands.guild_only()
    async def ticket_setup(
        self,
        ctx: commands.Context,
        category: discord.CategoryChannel,
        support_role: discord.Role = None,
        log_channel: discord.TextChannel = None,
    ):
        if not ctx.author.guild_permissions.administrator and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Administrator** permission."), ephemeral=True)

        await ctx.defer()
        await _set_settings(
            ctx.guild.id,
            category_id=category.id,
            support_role_id=support_role.id if support_role else None,
            log_channel_id=log_channel.id if log_channel else None,
        )

        desc = f"**Category:** {category.mention}\n"
        if support_role:
            desc += f"**Support Role:** {support_role.mention}\n"
        if log_channel:
            desc += f"**Log Channel:** {log_channel.mention}\n"
        desc += "\nRun `/ticket panel` to post the ticket creation panel."

        await ctx.send(embed=create_embed(title="✅ Ticket System Configured", description=desc))

    # ── /ticket panel ─────────────────────────────────────────────────────

    @ticket.command(name="panel", description="Post the ticket creation panel in this channel")
    @commands.guild_only()
    async def ticket_panel(self, ctx: commands.Context):
        if not ctx.author.guild_permissions.administrator and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Administrator** permission."), ephemeral=True)

        settings = await _get_settings(ctx.guild.id)
        if not settings:
            return await ctx.send(
                embed=create_error_embed("Please run `/ticket setup` first."), ephemeral=True
            )

        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=(
                "Need help? Click the button below to open a support ticket.\n"
                "Our staff will assist you as soon as possible."
            ),
            color=discord.Color.blurple(),
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_footer(text=ctx.guild.name)

        await ctx.channel.send(embed=embed, view=TicketCreateButton())
        if hasattr(ctx, "interaction") and ctx.interaction:
            await ctx.send("✅ Ticket panel posted!", ephemeral=True)

    # ── /ticket close ─────────────────────────────────────────────────────

    @ticket.command(name="close", description="Close the current ticket")
    @commands.guild_only()
    async def ticket_close(self, ctx: commands.Context):
        if ctx.interaction:
            await _do_close(ctx.interaction)
        else:
            ticket = await _get_ticket(ctx.channel.id)
            if not ticket:
                return await ctx.send(embed=create_error_embed("This is not a ticket channel."))
            await _set_ticket_status(ctx.channel.id, "closed")
            await ctx.send(embed=discord.Embed(
                description=f"🔒 Ticket closed by {ctx.author.mention}.",
                color=discord.Color.orange(),
            ))

    # ── /ticket delete ────────────────────────────────────────────────────

    @ticket.command(name="delete", description="Delete (permanently remove) the current ticket channel")
    @commands.guild_only()
    async def ticket_delete(self, ctx: commands.Context):
        if not ctx.author.guild_permissions.manage_channels and ctx.author.id != BOT_OWNER_ID:
            return await ctx.send(embed=create_error_embed("You need **Manage Channels** permission."), ephemeral=True)
        ticket = await _get_ticket(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=create_error_embed("This is not a ticket channel."))
        await ctx.send("🗑️ Deleting this ticket in 3 seconds…")
        await asyncio.sleep(3)
        await _delete_ticket_record(ctx.channel.id)
        try:
            await ctx.channel.delete(reason=f"Ticket deleted by {ctx.author}")
        except discord.Forbidden:
            pass

    # ── /ticket add ───────────────────────────────────────────────────────

    @ticket.command(name="add", description="Add a member to the current ticket")
    @app_commands.describe(member="The member to add to this ticket")
    @commands.guild_only()
    async def ticket_add(self, ctx: commands.Context, member: discord.Member):
        ticket = await _get_ticket(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=create_error_embed("This is not a ticket channel."), ephemeral=True)
        await ctx.channel.set_permissions(
            member, view_channel=True, send_messages=True, read_message_history=True
        )
        await ctx.send(
            embed=create_embed(description=f"✅ {member.mention} has been added to this ticket.")
        )

    # ── /ticket remove ────────────────────────────────────────────────────

    @ticket.command(name="remove", description="Remove a member from the current ticket")
    @app_commands.describe(member="The member to remove from this ticket")
    @commands.guild_only()
    async def ticket_remove(self, ctx: commands.Context, member: discord.Member):
        ticket = await _get_ticket(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=create_error_embed("This is not a ticket channel."), ephemeral=True)
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.send(
            embed=create_embed(description=f"✅ {member.mention} has been removed from this ticket.")
        )

    # ── /ticket info ──────────────────────────────────────────────────────

    @ticket.command(name="info", description="View current ticket info")
    @commands.guild_only()
    async def ticket_info(self, ctx: commands.Context):
        ticket = await _get_ticket(ctx.channel.id)
        if not ticket:
            return await ctx.send(embed=create_error_embed("This is not a ticket channel."), ephemeral=True)
        user = ctx.guild.get_member(ticket["user_id"])
        embed = create_embed(title=f"🎫 Ticket #{ticket['ticket_number']:04d}")
        embed.add_field(name="Owner", value=user.mention if user else f"<@{ticket['user_id']}>")
        embed.add_field(name="Status", value=ticket["status"].title())
        embed.add_field(name="Opened", value=f"<t:{int(datetime.fromisoformat(ticket['created_at']).timestamp())}:R>", inline=False)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
