"""
Giveaway Commands Cog
Handles giveaway creation, management, and entry tracking.
Uses a multi-step wizard with Modals and Component-based navigation.
"""

import random
import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict
from bson import ObjectId
import pytz

from ..config import PH_TIMEZONE, BOT_OWNER_ID
from ..database import db
from ..utils import create_embed, parse_duration, has_manage_guild


# ══════════════════════════════════════════════════════════════════════════════
# INVITE HISTORY PAGINATOR
# ══════════════════════════════════════════════════════════════════════════════

class InviteHistoryPaginator(ui.View):
    """Paginated view for invite history."""

    PAGE_SIZE = 10

    def __init__(self, entries: list[dict], inviter: discord.User, total: int):
        super().__init__(timeout=180)
        self.entries = entries
        self.inviter = inviter
        self.total = total
        self.current_page = 0
        self.max_page = max(0, (len(entries) - 1) // self.PAGE_SIZE)
        self._refresh_buttons()

    def _refresh_buttons(self):
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == "ih_prev":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "ih_next":
                    child.disabled = self.current_page == self.max_page

    def build_embed(self) -> discord.Embed:
        start = self.current_page * self.PAGE_SIZE
        page_entries = self.entries[start: start + self.PAGE_SIZE]

        lines = []
        for i, entry in enumerate(page_entries, start=start + 1):
            uid = entry.get("user_id", "?")
            joined_at = entry.get("joined_at")
            left_at = entry.get("left_at")
            join_ts = f"<t:{int(joined_at.timestamp())}:R>" if joined_at else "Unknown time"
            is_rejoin = entry.get("rejoin", False)
            rejoin_label = " *(rejoin)*" if is_rejoin else ""
            if left_at:
                status = f"~~<@{uid}>~~{rejoin_label} *(left <t:{int(left_at.timestamp())}:R>)*"
            else:
                status = f"<@{uid}>{rejoin_label}"
            lines.append(f"`{i}.` {status} — joined {join_ts}")

        embed = create_embed(
            title=f"📋 Invite History — {self.inviter.display_name}",
            description="\n".join(lines) if lines else "*No entries on this page.*",
        )
        embed.set_thumbnail(url=self.inviter.display_avatar.url)
        embed.set_footer(
            text=f"Page {self.current_page + 1}/{self.max_page + 1} • {self.total} total invite(s)"
        )
        return embed

    @ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray, custom_id="ih_prev")
    async def previous_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @ui.button(label="Next ▶️", style=discord.ButtonStyle.gray, custom_id="ih_next")
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = min(self.max_page, self.current_page + 1)
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY ENTRY VIEW (PERSISTENT)
# ══════════════════════════════════════════════════════════════════════════════

class GiveawayEntryView(ui.View):
    """Persistent view for giveaway entry button."""

    def __init__(
        self,
        giveaway_id: ObjectId,
        host_id: str,
        prize: str,
        end_time: datetime,
        winner_count: int,
        required_roles: list = None,
        message_requirement: int = None,
        invite_requirement: int = None,
        cog: "GiveawayCog" = None,
    ):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.host_id = host_id
        self.prize = prize
        self.end_time = end_time
        self.winner_count = winner_count
        self.required_roles = required_roles or []
        self.message_requirement = message_requirement
        self.invite_requirement = invite_requirement
        self.cog = cog

    @ui.button(label="🎉 Enter Giveaway", style=discord.ButtonStyle.green, custom_id="giveaway_enter")
    async def enter_giveaway(self, interaction: discord.Interaction, button: ui.Button):
        if not db.is_connected or db.giveaways is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        giveaway = db.giveaways.find_one({"_id": self.giveaway_id})

        if not giveaway:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        if giveaway.get("ended"):
            await interaction.response.send_message("❌ This giveaway has ended.", ephemeral=True)
            return

        if user_id in giveaway.get("entries", []):
            db.giveaways.update_one(
                {"_id": self.giveaway_id},
                {"$pull": {"entries": user_id}}
            )
            giveaway = db.giveaways.find_one({"_id": self.giveaway_id})
            await self._update_embed(interaction, giveaway)
            await interaction.response.send_message("❌ You left the giveaway.", ephemeral=True)
            return

        if self.required_roles:
            member_roles = [r.id for r in interaction.user.roles]
            if not any(r in member_roles for r in self.required_roles):
                role_mentions = ", ".join(f"<@&{r}>" for r in self.required_roles)
                await interaction.response.send_message(
                    f"❌ You need one of these roles: {role_mentions}",
                    ephemeral=True,
                )
                return

        if self.message_requirement and self.cog:
            gw_id = str(self.giveaway_id)
            msg_count = self.cog.message_counts.get(gw_id, {}).get(user_id, 0)
            if msg_count < self.message_requirement:
                await interaction.response.send_message(
                    f"❌ You need {self.message_requirement} messages to enter. You have {msg_count}.",
                    ephemeral=True,
                )
                return

        if self.invite_requirement and self.cog:
            gw_id = str(self.giveaway_id)
            invite_count = self.cog.invite_counts.get(gw_id, {}).get(user_id, 0)
            if invite_count < self.invite_requirement:
                await interaction.response.send_message(
                    f"❌ You need {self.invite_requirement} invites. You have {invite_count}.",
                    ephemeral=True,
                )
                return

        db.giveaways.update_one(
            {"_id": self.giveaway_id},
            {"$addToSet": {"entries": user_id}}
        )

        giveaway = db.giveaways.find_one({"_id": self.giveaway_id})
        await self._update_embed(interaction, giveaway)
        await interaction.response.send_message("✅ You entered the giveaway! Good luck!", ephemeral=True)

    async def _update_embed(self, interaction: discord.Interaction, giveaway: dict):
        """Update the giveaway embed with new entry count."""
        end_unix = int(giveaway["end_time"].timestamp())
        entry_count = len(giveaway.get("entries", []))

        embed = discord.Embed(title=f"**🎁 {giveaway['prize']}**", color=discord.Color.gold())
        embed.add_field(name="⏰ Ends", value=f"<t:{end_unix}:f> (<t:{end_unix}:R>)", inline=False)
        embed.add_field(name="🏆 Winners", value=str(giveaway["winner_count"]), inline=False)

        if giveaway.get("required_roles"):
            roles = ", ".join(f"<@&{r}>" for r in giveaway["required_roles"])
            embed.add_field(name="🎭 Required Roles", value=roles, inline=False)

        if giveaway.get("message_requirement"):
            embed.add_field(
                name="💬 Message Requirement",
                value=f"{giveaway['message_requirement']} message(s)",
                inline=False,
            )

        if giveaway.get("invite_requirement"):
            embed.add_field(
                name="📨 Invite Requirement",
                value=f"{giveaway['invite_requirement']} invite(s)",
                inline=False,
            )

        embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
        embed.set_footer(text=f"Entries {entry_count} | ID: {giveaway['_id']}")
        embed.timestamp = datetime.now(PH_TIMEZONE)
        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        try:
            await interaction.message.edit(embed=embed)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — STATE
# ══════════════════════════════════════════════════════════════════════════════

class GiveawayState:
    """Holds the in-progress wizard state for giveaway creation or editing."""

    def __init__(self, guild_id: int, channel_id: int, creator_id: int):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self.prize: str = ""
        self.duration: str = ""
        self.total_seconds: int = 0
        self.winner_count: int = 1
        self.required_role_ids: list[int] = []
        self.message_requirement: int | None = None
        self.invite_requirement: int | None = None
        self.is_edit: bool = False
        self.giveaway_doc: dict | None = None

    @classmethod
    def from_doc(cls, doc: dict) -> "GiveawayState":
        """Create an edit state pre-filled from a DB document."""
        state = cls(
            guild_id=int(doc["guild_id"]),
            channel_id=int(doc["channel_id"]),
            creator_id=int(doc["host_id"]),
        )
        state.is_edit = True
        state.giveaway_doc = doc
        state.prize = doc.get("prize", "")
        state.winner_count = doc.get("winner_count", 1)
        state.required_role_ids = doc.get("required_roles", []) or []
        state.message_requirement = doc.get("message_requirement")
        state.invite_requirement = doc.get("invite_requirement")
        return state


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _fmt_requirements(state: GiveawayState) -> str:
    lines = []
    if state.required_role_ids:
        roles = ", ".join(f"<@&{r}>" for r in state.required_role_ids)
        lines.append(f"🎭 **Required Roles:** {roles}")
    if state.message_requirement:
        lines.append(f"💬 **Message Requirement:** {state.message_requirement} message(s)")
    if state.invite_requirement:
        lines.append(f"📨 **Invite Requirement:** {state.invite_requirement} invite(s)")
    return "\n".join(lines) if lines else "*(None — anyone can enter)*"


def _active_list_embed(active: list, guild_name: str = "") -> discord.Embed:
    if not active:
        return discord.Embed(
            title="📋 Active Giveaways",
            description="There are no active giveaways in this server right now.",
            color=discord.Color.gold(),
        )
    lines = []
    for gw in active[:10]:
        end_unix = int(gw["end_time"].timestamp())
        entries = len(gw.get("entries", []))
        lines.append(
            f"🎁 **{gw['prize']}**\n"
            f"  ⏰ Ends: <t:{end_unix}:R> • 🏆 {gw['winner_count']} winner(s) • 👥 {entries} entr{'y' if entries == 1 else 'ies'}\n"
            f"  `ID: {gw['_id']}`"
        )
    e = discord.Embed(
        title=f"📋 Active Giveaways{f' — {guild_name}' if guild_name else ''}",
        description="\n\n".join(lines),
        color=discord.Color.gold(),
    )
    e.set_footer(text=f"{len(active)} active giveaway(s)")
    return e


async def _launch_giveaway(
    interaction: discord.Interaction,
    state: GiveawayState,
    cog: "GiveawayCog",
):
    """Post the giveaway message to the channel and save to DB."""
    if not db.is_connected or db.giveaways is None:
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="❌ Database Error",
                description="Could not connect to the database. Please try again.",
                color=discord.Color.red(),
            ),
            view=None,
        )
        return

    end_time_ph = datetime.now(PH_TIMEZONE) + timedelta(seconds=state.total_seconds)
    end_time_utc = end_time_ph.astimezone(pytz.UTC)
    end_unix = int(end_time_ph.timestamp())

    embed = discord.Embed(title=f"**🎁 {state.prize}**", color=discord.Color.gold())
    embed.add_field(name="⏰ Ends", value=f"<t:{end_unix}:f> (<t:{end_unix}:R>)", inline=False)
    embed.add_field(name="🏆 Winners", value=str(state.winner_count), inline=False)

    if state.required_role_ids:
        embed.add_field(name="🎭 Required Roles", value=", ".join(f"<@&{r}>" for r in state.required_role_ids), inline=False)
    if state.message_requirement:
        embed.add_field(name="💬 Message Requirement", value=f"{state.message_requirement} message(s)", inline=False)
    if state.invite_requirement:
        embed.add_field(name="📨 Invite Requirement", value=f"{state.invite_requirement} invite(s)", inline=False)

    embed.add_field(name="Hosted by", value=f"<@{state.creator_id}>", inline=False)
    embed.set_footer(text="Entries 0 | ID: Loading...")
    embed.timestamp = datetime.now(PH_TIMEZONE)
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    channel = interaction.guild.get_channel(state.channel_id) or interaction.channel
    gw_msg = await channel.send(embed=embed)

    giveaway_data = {
        "guild_id": str(state.guild_id),
        "channel_id": str(state.channel_id),
        "message_id": str(gw_msg.id),
        "host_id": str(state.creator_id),
        "prize": state.prize,
        "end_time": end_time_utc,
        "winner_count": state.winner_count,
        "required_roles": state.required_role_ids,
        "message_requirement": state.message_requirement,
        "invite_requirement": state.invite_requirement,
        "entries": [],
        "ended": False,
        "created_at": datetime.now(PH_TIMEZONE),
    }

    result = db.giveaways.insert_one(giveaway_data)
    giveaway_id = result.inserted_id

    embed.set_footer(text=f"Entries 0 | ID: {giveaway_id}")
    entry_view = GiveawayEntryView(
        giveaway_id=giveaway_id,
        host_id=str(state.creator_id),
        prize=state.prize,
        end_time=end_time_ph,
        winner_count=state.winner_count,
        required_roles=state.required_role_ids,
        message_requirement=state.message_requirement,
        invite_requirement=state.invite_requirement,
        cog=cog,
    )
    await gw_msg.edit(embed=embed, view=entry_view)

    asyncio.create_task(cog.schedule_end(giveaway_id, state.total_seconds))

    await interaction.response.edit_message(
        embed=discord.Embed(
            title="✅ Giveaway Launched!",
            description=(
                f"🎁 **{state.prize}** is now live!\n\n"
                f"⏰ Ends: <t:{end_unix}:R>\n"
                f"🏆 Winners: {state.winner_count}\n"
                f"📍 Channel: <#{state.channel_id}>"
            ),
            color=discord.Color.green(),
        ),
        view=BackToMenuView(cog, state.guild_id, state.channel_id, state.creator_id),
    )


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — MAIN MENU
# ══════════════════════════════════════════════════════════════════════════════

def _main_menu_embed() -> discord.Embed:
    e = discord.Embed(
        title="🎉 Giveaway Manager",
        description="Create and manage giveaways in your server.\nSelect an action below to get started.",
        color=discord.Color.gold(),
    )
    e.add_field(name="🎉 Create Giveaway", value="Start a new timed giveaway", inline=False)
    e.add_field(name="✏️ Edit Giveaway", value="Change the prize, winners, or requirements of an active giveaway", inline=False)
    e.add_field(name="🏁 End Giveaway", value="Force-end an active giveaway early", inline=False)
    e.add_field(name="🔄 Reroll Giveaway", value="Pick new winners for an ended giveaway", inline=False)
    e.add_field(name="📋 Active Giveaways", value="List all active giveaways in this server", inline=False)
    e.set_footer(text="What would you like to do?")
    return e


class MainMenuView(ui.View):
    def __init__(self, cog: "GiveawayCog", guild_id: int, channel_id: int, creator_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id

        select = ui.Select(
            placeholder="What would you like to do?",
            options=[
                discord.SelectOption(label="Create Giveaway", description="Start a new timed giveaway", value="create", emoji="🎉"),
                discord.SelectOption(label="Edit Giveaway", description="Change prize, winners, or requirements", value="edit", emoji="✏️"),
                discord.SelectOption(label="End Giveaway", description="Force-end an active giveaway early", value="end", emoji="🏁"),
                discord.SelectOption(label="Reroll Giveaway", description="Pick new winners for an ended giveaway", value="reroll", emoji="🔄"),
                discord.SelectOption(label="Active Giveaways", description="List all active giveaways", value="list", emoji="📋"),
            ],
            min_values=1, max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]

        if choice == "create":
            state = GiveawayState(self.guild_id, self.channel_id, self.creator_id)
            await interaction.response.send_modal(GiveawayDetailsModal(state, self.cog))

        elif choice == "edit":
            if not db.is_connected or db.giveaways is None:
                await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
                return
            active = list(db.giveaways.find({"guild_id": str(self.guild_id), "ended": {"$ne": True}}))
            if not active:
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="✏️ No Active Giveaways",
                        description="There are no active giveaways to edit right now.",
                        color=discord.Color.red(),
                    ),
                    view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
                )
                return
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✏️ Edit a Giveaway",
                    description="Select an active giveaway to edit its details or requirements.",
                    color=discord.Color.blurple(),
                ),
                view=EditSelectView(active, self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

        elif choice == "end":
            if not db.is_connected or db.giveaways is None:
                await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
                return
            active = list(db.giveaways.find({"guild_id": str(self.guild_id), "ended": {"$ne": True}}))
            if not active:
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="🏁 No Active Giveaways",
                        description="There are no active giveaways to end right now.",
                        color=discord.Color.red(),
                    ),
                    view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
                )
                return
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🏁 End a Giveaway",
                    description="Select an active giveaway to force-end early.",
                    color=discord.Color.orange(),
                ),
                view=GiveawaySelectView(active, "end", self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

        elif choice == "reroll":
            if not db.is_connected or db.giveaways is None:
                await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
                return
            ended = list(db.giveaways.find({"guild_id": str(self.guild_id), "ended": True}).sort("end_time", -1).limit(25))
            if not ended:
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="🔄 No Ended Giveaways",
                        description="There are no ended giveaways to reroll yet.",
                        color=discord.Color.red(),
                    ),
                    view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
                )
                return
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🔄 Reroll a Giveaway",
                    description="Select an ended giveaway to pick new winners.",
                    color=discord.Color.blurple(),
                ),
                view=GiveawaySelectView(ended, "reroll", self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

        elif choice == "list":
            if not db.is_connected or db.giveaways is None:
                await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
                return
            active = list(db.giveaways.find({"guild_id": str(self.guild_id), "ended": {"$ne": True}}))
            await interaction.response.edit_message(
                embed=_active_list_embed(active, interaction.guild.name),
                view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class BackToMenuView(ui.View):
    def __init__(self, cog: "GiveawayCog", guild_id: int, channel_id: int, creator_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id

    @ui.button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — END / REROLL SELECT
# ══════════════════════════════════════════════════════════════════════════════

class GiveawaySelectView(ui.View):
    def __init__(
        self,
        giveaways: list,
        action: str,
        cog: "GiveawayCog",
        guild_id: int,
        channel_id: int,
        creator_id: int,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.action = action
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self._giveaways = giveaways

        options = []
        for gw in giveaways[:25]:
            prize = gw.get("prize", "Unknown")[:40]
            end_unix = int(gw["end_time"].timestamp())
            status = "Ended" if gw.get("ended") else f"Ends <t:{end_unix}:R>"
            entries = len(gw.get("entries", []))
            options.append(discord.SelectOption(
                label=prize,
                description=f"{gw['winner_count']} winner(s) • {entries} entries",
                value=str(gw["_id"]),
                emoji="🎁",
            ))

        select = ui.Select(
            placeholder=f"Select a giveaway to {action}...",
            options=options,
            min_values=1, max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

        back_btn = ui.Button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, interaction: discord.Interaction):
        gw_id_str = interaction.data["values"][0]
        gw = next((g for g in self._giveaways if str(g["_id"]) == gw_id_str), None)
        if not gw:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return

        if self.action == "end":
            end_unix = int(gw["end_time"].timestamp())
            entries = len(gw.get("entries", []))
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🏁 Confirm End Giveaway",
                    description=(
                        f"Are you sure you want to force-end this giveaway?\n\n"
                        f"🎁 **Prize:** {gw['prize']}\n"
                        f"⏰ **Was ending:** <t:{end_unix}:R>\n"
                        f"🏆 **Winners:** {gw['winner_count']}\n"
                        f"👥 **Entries:** {entries}\n"
                        f"`ID: {gw['_id']}`"
                    ),
                    color=discord.Color.orange(),
                ),
                view=GiveawayActionConfirmView(gw, "end", self.cog, self.guild_id, self.channel_id, self.creator_id),
            )
        elif self.action == "reroll":
            if not gw.get("entries"):
                await interaction.response.edit_message(
                    embed=discord.Embed(
                        title="❌ No Entries",
                        description=f"**{gw['prize']}** had no entries — nothing to reroll.",
                        color=discord.Color.red(),
                    ),
                    view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
                )
                return
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🔄 Confirm Reroll",
                    description=(
                        f"Pick new winners for this giveaway?\n\n"
                        f"🎁 **Prize:** {gw['prize']}\n"
                        f"🏆 **Winners to pick:** {gw['winner_count']}\n"
                        f"👥 **Total entries:** {len(gw.get('entries', []))}\n"
                        f"`ID: {gw['_id']}`"
                    ),
                    color=discord.Color.blurple(),
                ),
                view=GiveawayActionConfirmView(gw, "reroll", self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class GiveawayActionConfirmView(ui.View):
    def __init__(
        self,
        gw: dict,
        action: str,
        cog: "GiveawayCog",
        guild_id: int,
        channel_id: int,
        creator_id: int,
    ):
        super().__init__(timeout=120)
        self.gw = gw
        self.action = action
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id

    @ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: ui.Button):
        if self.action == "end":
            await self.cog.end_giveaway(self.gw["_id"])
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ Giveaway Ended",
                    description=f"**{self.gw['prize']}** has been ended and winners have been selected.",
                    color=discord.Color.green(),
                ),
                view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

        elif self.action == "reroll":
            entries = self.gw.get("entries", [])
            winner_count = self.gw.get("winner_count", 1)
            new_winners = random.sample(entries, min(len(entries), winner_count))
            winner_mentions = ", ".join(f"<@{w}>" for w in new_winners)

            guild = self.cog.bot.get_guild(int(self.gw["guild_id"]))
            channel = guild.get_channel(int(self.gw["channel_id"])) if guild else None
            if channel:
                try:
                    original = await channel.fetch_message(int(self.gw["message_id"]))
                    await original.reply(
                        f"🔄 **Giveaway Re-Rolled!**\n🏆 **New Winner(s) for `{self.gw['prize']}`**: {winner_mentions}"
                    )
                except Exception:
                    pass

            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="✅ Rerolled Successfully!",
                    description=f"🏆 New winner(s) for **{self.gw['prize']}**:\n{winner_mentions}",
                    color=discord.Color.green(),
                ),
                view=BackToMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
            )

    @ui.button(label="↩️ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — STEP 1: DETAILS MODAL
# ══════════════════════════════════════════════════════════════════════════════

class GiveawayDetailsModal(ui.Modal, title="🎉 Giveaway Details"):
    prize = ui.TextInput(
        label="Prize",
        placeholder="What are you giving away?",
        max_length=256,
        required=True,
    )
    duration = ui.TextInput(
        label="Duration",
        placeholder="e.g. 30s, 10m, 2h, 1d",
        max_length=20,
        required=True,
    )
    winner_count = ui.TextInput(
        label="Number of Winners",
        placeholder="1",
        default="1",
        max_length=3,
        required=True,
    )

    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__()
        self.state = state
        self.cog_ref = cog
        if state.prize:
            self.prize.default = state.prize
        if state.duration:
            self.duration.default = state.duration
        if state.winner_count > 1:
            self.winner_count.default = str(state.winner_count)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            total_seconds = parse_duration(self.duration.value.strip())
            if total_seconds <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message(
                "❌ Invalid duration. Use formats like `30s`, `10m`, `2h`, `1d`.",
                ephemeral=True,
            )
            return

        try:
            wcount = int(self.winner_count.value.strip())
            if wcount <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message(
                "❌ Winner count must be a positive whole number.",
                ephemeral=True,
            )
            return

        self.state.prize = self.prize.value.strip()
        self.state.duration = self.duration.value.strip()
        self.state.total_seconds = total_seconds
        self.state.winner_count = wcount

        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — STEP 2: REQUIREMENTS
# ══════════════════════════════════════════════════════════════════════════════

def _step2_embed(state: GiveawayState) -> discord.Embed:
    end_time = datetime.now(PH_TIMEZONE) + timedelta(seconds=state.total_seconds)
    end_unix = int(end_time.timestamp())
    e = discord.Embed(
        title="🎉 Create Giveaway — Step 2 of 3",
        description=(
            f"**Add Entry Requirements** *(optional)*\n\n"
            f"🎁 **Prize:** {state.prize}\n"
            f"⏰ **Duration:** {state.duration} — ends <t:{end_unix}:R>\n"
            f"🏆 **Winners:** {state.winner_count}\n\n"
            f"**Current Requirements:**\n{_fmt_requirements(state)}\n\n"
            f"*Add role, message, or invite requirements below — or press **Next** to skip.*"
        ),
        color=discord.Color.gold(),
    )
    e.set_footer(text="Step 2 / 3 • Requirements (optional)")
    return e


class MessageReqModal(ui.Modal, title="💬 Message Requirement"):
    count = ui.TextInput(
        label="Minimum Messages Required",
        placeholder="e.g. 10",
        max_length=5,
        required=True,
    )

    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__()
        self.state = state
        self.cog_ref = cog
        if state.message_requirement:
            self.count.default = str(state.message_requirement)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.count.value.strip())
            if n <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message("❌ Enter a valid positive number.", ephemeral=True)
            return
        self.state.message_requirement = n
        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )


class InviteReqModal(ui.Modal, title="📨 Invite Requirement"):
    count = ui.TextInput(
        label="Minimum Invites Required",
        placeholder="e.g. 5",
        max_length=5,
        required=True,
    )

    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__()
        self.state = state
        self.cog_ref = cog
        if state.invite_requirement:
            self.count.default = str(state.invite_requirement)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = int(self.count.value.strip())
            if n <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message("❌ Enter a valid positive number.", ephemeral=True)
            return
        self.state.invite_requirement = n
        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )


class RoleSelectView(ui.View):
    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__(timeout=300)
        self.state = state
        self.cog_ref = cog

    @ui.select(cls=ui.RoleSelect, placeholder="Select required role(s)...", min_values=1, max_values=10)
    async def role_select(self, interaction: discord.Interaction, select: ui.RoleSelect):
        self.state.required_role_ids = [r.id for r in select.values]
        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Step2RequirementsView(ui.View):
    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__(timeout=300)
        self.state = state
        self.cog_ref = cog

        select = ui.Select(
            placeholder="Add or clear requirements...",
            options=[
                discord.SelectOption(label="Add Role Requirement", description="Members must have one of these roles", value="roles", emoji="🎭"),
                discord.SelectOption(label="Set Message Requirement", description="Members need a minimum message count", value="messages", emoji="💬"),
                discord.SelectOption(label="Set Invite Requirement", description="Members need a minimum invite count", value="invites", emoji="📨"),
                discord.SelectOption(label="Clear All Requirements", description="Remove all entry requirements", value="clear", emoji="🗑️"),
            ],
            min_values=1, max_values=1, row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

        back_btn = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

        next_btn = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        next_btn.callback = self._next
        self.add_item(next_btn)

    async def _on_select(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]
        if choice == "roles":
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="🎭 Select Required Roles",
                    description=(
                        f"Choose which roles members must have to enter.\n\n"
                        f"🎁 **Prize:** {self.state.prize}\n\n"
                        f"*Members only need one of the selected roles.*"
                    ),
                    color=discord.Color.gold(),
                ),
                view=RoleSelectView(self.state, self.cog_ref),
            )
        elif choice == "messages":
            await interaction.response.send_modal(MessageReqModal(self.state, self.cog_ref))
        elif choice == "invites":
            await interaction.response.send_modal(InviteReqModal(self.state, self.cog_ref))
        elif choice == "clear":
            self.state.required_role_ids = []
            self.state.message_requirement = None
            self.state.invite_requirement = None
            await interaction.response.edit_message(
                embed=_step2_embed(self.state),
                view=Step2RequirementsView(self.state, self.cog_ref),
            )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.send_modal(GiveawayDetailsModal(self.state, self.cog_ref))

    async def _next(self, interaction: discord.Interaction):
        if self.state.is_edit:
            await interaction.response.edit_message(
                embed=_edit_preview_embed(self.state),
                view=EditPreviewView(self.state, self.cog_ref),
            )
        else:
            await interaction.response.edit_message(
                embed=_step3_embed(self.state),
                view=Step3PreviewView(self.state, self.cog_ref),
            )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — STEP 3: PREVIEW & LAUNCH
# ══════════════════════════════════════════════════════════════════════════════

def _step3_embed(state: GiveawayState) -> discord.Embed:
    end_time = datetime.now(PH_TIMEZONE) + timedelta(seconds=state.total_seconds)
    end_unix = int(end_time.timestamp())
    e = discord.Embed(
        title="🎉 Create Giveaway — Step 3 of 3",
        description=(
            f"**Preview & Launch**\nReview your giveaway before posting.\n\n"
            f"🎁 **Prize:** {state.prize}\n"
            f"⏰ **Ends:** <t:{end_unix}:f> (<t:{end_unix}:R>)\n"
            f"🏆 **Winners:** {state.winner_count}\n\n"
            f"**Entry Requirements:**\n{_fmt_requirements(state)}"
        ),
        color=discord.Color.green(),
    )
    e.set_footer(text="Step 3 / 3 • Preview & Launch")
    return e


class Step3PreviewView(ui.View):
    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__(timeout=300)
        self.state = state
        self.cog_ref = cog

    @ui.button(label="🚀 Launch Giveaway", style=discord.ButtonStyle.success, row=0)
    async def launch(self, interaction: discord.Interaction, _: ui.Button):
        await _launch_giveaway(interaction, self.state, self.cog_ref)

    @ui.button(label="✏️ Edit Requirements", style=discord.ButtonStyle.secondary, row=0)
    async def edit_reqs(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_step2_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )

    @ui.button(label="✏️ Edit Details", style=discord.ButtonStyle.secondary, row=1)
    async def edit_details(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(GiveawayDetailsModal(self.state, self.cog_ref))

    @ui.button(label="🏠 Main Menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog_ref, self.state.guild_id, self.state.channel_id, self.state.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY WIZARD — EDIT FLOW
# ══════════════════════════════════════════════════════════════════════════════

class EditSelectView(ui.View):
    """Pick which active giveaway to edit."""

    def __init__(self, giveaways: list, cog: "GiveawayCog", guild_id: int, channel_id: int, creator_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.creator_id = creator_id
        self._giveaways = giveaways

        options = []
        for gw in giveaways[:25]:
            prize = gw.get("prize", "Unknown")[:40]
            end_unix = int(gw["end_time"].timestamp())
            entries = len(gw.get("entries", []))
            options.append(discord.SelectOption(
                label=prize,
                description=f"Ends <t:{end_unix}:R> • {gw['winner_count']} winner(s) • {entries} entries",
                value=str(gw["_id"]),
                emoji="🎁",
            ))

        select = ui.Select(
            placeholder="Select a giveaway to edit...",
            options=options,
            min_values=1, max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

        back_btn = ui.Button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, interaction: discord.Interaction):
        gw_id_str = interaction.data["values"][0]
        gw = next((g for g in self._giveaways if str(g["_id"]) == gw_id_str), None)
        if not gw:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return
        state = GiveawayState.from_doc(gw)
        await interaction.response.send_modal(EditGiveawayDetailsModal(state, self.cog))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog, self.guild_id, self.channel_id, self.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class EditGiveawayDetailsModal(ui.Modal, title="✏️ Edit Giveaway Details"):
    prize = ui.TextInput(
        label="Prize",
        placeholder="What are you giving away?",
        max_length=256,
        required=True,
    )
    winner_count = ui.TextInput(
        label="Number of Winners",
        placeholder="1",
        max_length=3,
        required=True,
    )
    new_duration = ui.TextInput(
        label="New End Time (optional)",
        placeholder="e.g. 1h, 30m — leave blank to keep current end time",
        max_length=20,
        required=False,
    )

    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__()
        self.state = state
        self.cog_ref = cog
        self.prize.default = state.prize
        self.winner_count.default = str(state.winner_count)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            wcount = int(self.winner_count.value.strip())
            if wcount <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message("❌ Winner count must be a positive whole number.", ephemeral=True)
            return

        new_dur = self.new_duration.value.strip()
        if new_dur:
            try:
                total_seconds = parse_duration(new_dur)
                if total_seconds <= 0:
                    raise ValueError()
                self.state.total_seconds = total_seconds
                self.state.duration = new_dur
            except Exception:
                await interaction.response.send_message(
                    "❌ Invalid duration. Use formats like `30m`, `2h`, `1d`.", ephemeral=True
                )
                return
        else:
            self.state.total_seconds = 0
            self.state.duration = ""

        self.state.prize = self.prize.value.strip()
        self.state.winner_count = wcount

        await interaction.response.edit_message(
            embed=_step2_embed(self.state) if self.state.total_seconds else _step2_edit_embed(self.state),
            view=Step2RequirementsView(self.state, self.cog_ref),
        )


def _step2_edit_embed(state: GiveawayState) -> discord.Embed:
    """Step 2 embed specifically for edit mode when no new duration was specified."""
    doc = state.giveaway_doc or {}
    end_unix = int(doc["end_time"].timestamp()) if doc.get("end_time") else 0
    e = discord.Embed(
        title="✏️ Edit Giveaway — Step 2 of 3",
        description=(
            f"**Update Entry Requirements** *(optional)*\n\n"
            f"🎁 **Prize:** {state.prize}\n"
            f"⏰ **End time:** <t:{end_unix}:f> (<t:{end_unix}:R>) *(unchanged)*\n"
            f"🏆 **Winners:** {state.winner_count}\n\n"
            f"**Current Requirements:**\n{_fmt_requirements(state)}\n\n"
            f"*Adjust requirements below — or press **Next** to keep them as-is.*"
        ),
        color=discord.Color.blurple(),
    )
    e.set_footer(text="Step 2 / 3 • Requirements")
    return e


def _edit_preview_embed(state: GiveawayState) -> discord.Embed:
    doc = state.giveaway_doc or {}
    if state.total_seconds:
        end_time = datetime.now(PH_TIMEZONE) + timedelta(seconds=state.total_seconds)
        end_unix = int(end_time.timestamp())
        end_line = f"<t:{end_unix}:f> (<t:{end_unix}:R>) *(changed)*"
    else:
        end_unix = int(doc["end_time"].timestamp()) if doc.get("end_time") else 0
        end_line = f"<t:{end_unix}:f> (<t:{end_unix}:R>) *(unchanged)*"

    e = discord.Embed(
        title="✏️ Edit Giveaway — Step 3 of 3",
        description=(
            f"**Preview Changes**\nReview your edits before saving.\n\n"
            f"🎁 **Prize:** {state.prize}\n"
            f"⏰ **Ends:** {end_line}\n"
            f"🏆 **Winners:** {state.winner_count}\n\n"
            f"**Entry Requirements:**\n{_fmt_requirements(state)}"
        ),
        color=discord.Color.blurple(),
    )
    e.set_footer(text="Step 3 / 3 • Preview & Save")
    return e


async def _apply_giveaway_edit(
    interaction: discord.Interaction,
    state: GiveawayState,
    cog: "GiveawayCog",
):
    """Apply edits to an existing giveaway in DB and update the live message."""
    if not db.is_connected or db.giveaways is None:
        await interaction.response.edit_message(
            embed=discord.Embed(title="❌ Database Error", description="Could not connect to database.", color=discord.Color.red()),
            view=None,
        )
        return

    doc = state.giveaway_doc
    giveaway_id = doc["_id"]

    updates: dict = {
        "prize": state.prize,
        "winner_count": state.winner_count,
        "required_roles": state.required_role_ids,
        "message_requirement": state.message_requirement,
        "invite_requirement": state.invite_requirement,
    }

    if state.total_seconds:
        new_end_ph = datetime.now(PH_TIMEZONE) + timedelta(seconds=state.total_seconds)
        new_end_utc = new_end_ph.astimezone(pytz.UTC)
        updates["end_time"] = new_end_utc
        end_unix = int(new_end_ph.timestamp())
    else:
        end_unix = int(doc["end_time"].timestamp())

    db.giveaways.update_one({"_id": giveaway_id}, {"$set": updates})

    guild = interaction.guild
    channel = guild.get_channel(int(doc["channel_id"])) if guild else None
    if channel:
        try:
            gw_msg = await channel.fetch_message(int(doc["message_id"]))
            entry_count = len(doc.get("entries", []))

            embed = discord.Embed(title=f"**🎁 {state.prize}**", color=discord.Color.gold())
            embed.add_field(name="⏰ Ends", value=f"<t:{end_unix}:f> (<t:{end_unix}:R>)", inline=False)
            embed.add_field(name="🏆 Winners", value=str(state.winner_count), inline=False)

            if state.required_role_ids:
                embed.add_field(name="🎭 Required Roles", value=", ".join(f"<@&{r}>" for r in state.required_role_ids), inline=False)
            if state.message_requirement:
                embed.add_field(name="💬 Message Requirement", value=f"{state.message_requirement} message(s)", inline=False)
            if state.invite_requirement:
                embed.add_field(name="📨 Invite Requirement", value=f"{state.invite_requirement} invite(s)", inline=False)

            embed.add_field(name="Hosted by", value=f"<@{doc['host_id']}>", inline=False)
            embed.set_footer(text=f"Entries {entry_count} | ID: {giveaway_id}")
            embed.timestamp = datetime.now(PH_TIMEZONE)
            if guild.icon:
                embed.set_thumbnail(url=guild.icon.url)

            await gw_msg.edit(embed=embed)
        except Exception:
            pass

    if state.total_seconds:
        asyncio.create_task(cog.schedule_end(giveaway_id, state.total_seconds))

    await interaction.response.edit_message(
        embed=discord.Embed(
            title="✅ Giveaway Updated!",
            description=(
                f"🎁 **{state.prize}** has been updated.\n\n"
                f"⏰ Ends: <t:{end_unix}:R>\n"
                f"🏆 Winners: {state.winner_count}\n"
                f"📍 Channel: <#{doc['channel_id']}>"
            ),
            color=discord.Color.green(),
        ),
        view=BackToMenuView(cog, state.guild_id, int(doc["channel_id"]), state.creator_id),
    )


class EditPreviewView(ui.View):
    def __init__(self, state: GiveawayState, cog: "GiveawayCog"):
        super().__init__(timeout=300)
        self.state = state
        self.cog_ref = cog

    @ui.button(label="💾 Save Changes", style=discord.ButtonStyle.success, row=0)
    async def save(self, interaction: discord.Interaction, _: ui.Button):
        await _apply_giveaway_edit(interaction, self.state, self.cog_ref)

    @ui.button(label="✏️ Edit Requirements", style=discord.ButtonStyle.secondary, row=0)
    async def edit_reqs(self, interaction: discord.Interaction, _: ui.Button):
        embed = _step2_embed(self.state) if self.state.total_seconds else _step2_edit_embed(self.state)
        await interaction.response.edit_message(embed=embed, view=Step2RequirementsView(self.state, self.cog_ref))

    @ui.button(label="✏️ Edit Details", style=discord.ButtonStyle.secondary, row=1)
    async def edit_details(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(EditGiveawayDetailsModal(self.state, self.cog_ref))

    @ui.button(label="🏠 Main Menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self.cog_ref, self.state.guild_id, self.state.channel_id, self.state.creator_id),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# GIVEAWAY COG
# ══════════════════════════════════════════════════════════════════════════════

class GiveawayCog(commands.Cog):
    """Giveaway management commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.message_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.invite_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.invited_user_map: dict[str, tuple[str, str]] = {}
        self.invite_cache: dict[int, dict[str, int]] = {}

    # ══════════════════════════════════════════════════════════════════════════
    # INVITE CACHE HELPERS
    # ══════════════════════════════════════════════════════════════════════════

    async def _cache_invites(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        old_cache = self.invite_cache.get(guild.id, {})

        try:
            new_invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return

        inviter_id: str | None = None
        for inv in new_invites:
            if inv.uses > old_cache.get(inv.code, 0) and inv.inviter:
                inviter_id = str(inv.inviter.id)
                break

        self.invite_cache[guild.id] = {inv.code: inv.uses for inv in new_invites}

        if not inviter_id:
            return

        guild_id = str(guild.id)
        user_id = str(member.id)

        if db.is_connected and db.invites is not None:
            try:
                already_invited = db.invites.find_one(
                    {"guild_id": guild_id, "invite_log.user_id": user_id}
                )

                if already_invited:
                    db.invites.update_one(
                        {"guild_id": guild_id, "user_id": already_invited["user_id"]},
                        {
                            "$addToSet": {"invited_users": user_id},
                            "$push": {
                                "invite_log": {
                                    "user_id": user_id,
                                    "joined_at": datetime.now(PH_TIMEZONE),
                                    "rejoin": True,
                                }
                            },
                        },
                    )
                else:
                    db.invites.update_one(
                        {"guild_id": guild_id, "user_id": inviter_id},
                        {
                            "$inc": {"total": 1},
                            "$addToSet": {"invited_users": user_id},
                            "$push": {
                                "invite_log": {
                                    "user_id": user_id,
                                    "joined_at": datetime.now(PH_TIMEZONE),
                                }
                            },
                        },
                        upsert=True,
                    )
            except Exception:
                pass

        if db.is_connected and db.giveaways is not None:
            active = db.giveaways.find({
                "guild_id": guild_id,
                "ended": {"$ne": True},
                "invite_requirement": {"$ne": None},
            })
            for giveaway in active:
                gw_id = str(giveaway["_id"])
                self.invite_counts[gw_id][inviter_id] += 1
                self.invited_user_map[user_id] = (gw_id, inviter_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not db.is_connected or db.invites is None:
            return

        guild_id = str(member.guild.id)
        user_id = str(member.id)

        doc = db.invites.find_one({"guild_id": guild_id, "invited_users": user_id})
        if not doc:
            return

        inviter_id = doc["user_id"]
        new_total = max(0, doc.get("total", 1) - 1)

        db.invites.update_one(
            {"guild_id": guild_id, "user_id": inviter_id},
            {
                "$set": {"total": new_total},
                "$pull": {"invited_users": user_id},
            },
        )

        db.invites.update_one(
            {
                "guild_id": guild_id,
                "user_id": inviter_id,
                "invite_log.user_id": user_id,
                "invite_log.left_at": {"$exists": False},
            },
            {"$set": {"invite_log.$.left_at": datetime.now(PH_TIMEZONE)}},
        )

        if db.giveaways is not None:
            active = db.giveaways.find({
                "guild_id": guild_id,
                "ended": {"$ne": True},
                "invite_requirement": {"$ne": None},
            })
            for giveaway in active:
                gw_id = str(giveaway["_id"])
                current = self.invite_counts[gw_id].get(inviter_id, 0)
                if current > 0:
                    self.invite_counts[gw_id][inviter_id] = current - 1

        if user_id in self.invited_user_map:
            del self.invited_user_map[user_id]

    # ══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════════════════════

    async def end_giveaway(self, giveaway_id: ObjectId):
        """End a giveaway and announce winners."""
        if not db.is_connected or db.giveaways is None:
            return

        gw_id_str = str(giveaway_id)

        if gw_id_str in self.message_counts:
            del self.message_counts[gw_id_str]
        if gw_id_str in self.invite_counts:
            del self.invite_counts[gw_id_str]

        to_remove = [uid for uid, (gw, _) in self.invited_user_map.items() if gw == gw_id_str]
        for uid in to_remove:
            del self.invited_user_map[uid]

        giveaway = db.giveaways.find_one({"_id": giveaway_id})
        if not giveaway or giveaway.get("ended"):
            return

        db.giveaways.update_one({"_id": giveaway_id}, {"$set": {"ended": True}})

        guild = self.bot.get_guild(int(giveaway["guild_id"]))
        if not guild:
            return

        channel = guild.get_channel(int(giveaway["channel_id"]))
        if not channel:
            return

        try:
            message = await channel.fetch_message(int(giveaway["message_id"]))
        except Exception:
            return

        entries = giveaway.get("entries", [])
        winner_count = giveaway["winner_count"]
        prize = giveaway["prize"]
        end_unix = int(giveaway["end_time"].timestamp())

        embed = discord.Embed(
            title=f"**🎁 {prize}**",
            color=discord.Color.green() if entries else discord.Color.red(),
        )
        embed.add_field(name="⏰ Ended", value=f"<t:{end_unix}:f>", inline=False)

        if entries:
            winners = random.sample(entries, min(len(entries), winner_count))
            winner_mentions = ", ".join(f"<@{w}>" for w in winners)
            embed.add_field(name="🏆 Winner(s)", value=winner_mentions, inline=False)
        else:
            embed.add_field(name="🏆 Winner(s)", value="No entries", inline=False)
            winner_mentions = None

        embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
        embed.set_footer(text=f"Entries {len(entries)} | ID: {giveaway_id}")
        embed.timestamp = datetime.now(PH_TIMEZONE)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        await message.edit(embed=embed, view=None)

        if entries and winner_mentions:
            await message.reply(f"🏆 **Winner(s)**: {winner_mentions}")

    async def schedule_end(self, giveaway_id: ObjectId, delay: float):
        """Schedule a giveaway to end after delay seconds."""
        await asyncio.sleep(delay)
        await self.end_giveaway(giveaway_id)

    # ══════════════════════════════════════════════════════════════════════════
    # MAIN COMMAND
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="giveaway", description="Open the Giveaway Manager — create, end, reroll, or list giveaways")
    async def giveaway(self, interaction: discord.Interaction):
        if not has_manage_guild(interaction, BOT_OWNER_ID):
            await interaction.response.send_message(
                "❌ You need **Manage Server** permission to use this.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=_main_menu_embed(),
            view=MainMenuView(self, interaction.guild.id, interaction.channel.id, interaction.user.id),
            ephemeral=True,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # INVITE COMMANDS
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="invites", description="Check how many members someone has invited to this server")
    @app_commands.describe(user="User to check (defaults to yourself)")
    async def invites(self, interaction: discord.Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user

        guild_id = str(interaction.guild.id)
        user_id = str(user.id)

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        doc = db.invites.find_one({"guild_id": guild_id, "user_id": user_id})
        total = doc.get("total", 0) if doc else 0
        invited_users = doc.get("invited_users", []) if doc else []

        embed = create_embed(
            title=f"📨 Invite Stats — {user.display_name}",
            description=f"{user.mention} has invited **{total}** member(s) to this server.",
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        if invited_users:
            preview = ", ".join(f"<@{uid}>" for uid in invited_users[:10])
            suffix = f" *(+{len(invited_users) - 10} more)*" if len(invited_users) > 10 else ""
            embed.add_field(name="Invited Members", value=preview + suffix, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="invitehistory", description="Show a full timestamped log of who a user has invited")
    @app_commands.describe(user="User to check (defaults to yourself)")
    async def invitehistory(self, interaction: discord.Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user

        guild_id = str(interaction.guild.id)
        user_id = str(user.id)

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        doc = db.invites.find_one({"guild_id": guild_id, "user_id": user_id})
        if not doc:
            await interaction.response.send_message(
                f"❌ No invite history found for {user.mention}.", ephemeral=True
            )
            return

        entries = doc.get("invite_log", [])
        total = doc.get("total", 0)

        if not entries:
            await interaction.response.send_message(
                f"📋 {user.mention} has **{total}** invite(s) recorded, but no detailed history is available yet "
                f"(history is only tracked from this version onward).",
                ephemeral=True,
            )
            return

        entries_sorted = sorted(
            entries,
            key=lambda e: e.get("joined_at") or datetime.min,
            reverse=True,
        )

        view = InviteHistoryPaginator(entries=entries_sorted, inviter=user, total=total)
        await interaction.response.send_message(embed=view.build_embed(), view=view)

    @app_commands.command(name="invitestats", description="Server-wide invite summary: total joins, leaves, and net active members")
    async def invitestats(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        await interaction.response.defer()

        docs = list(db.invites.find({"guild_id": guild_id}))

        if not docs:
            await interaction.followup.send("❌ No invite data recorded for this server yet.")
            return

        total_joins = sum(doc.get("total", 0) for doc in docs)
        total_inviters = len(docs)

        total_leaves = sum(
            sum(1 for entry in doc.get("invite_log", []) if entry.get("left_at"))
            for doc in docs
        )

        net_active = total_joins - total_leaves

        top_doc = max(docs, key=lambda d: d.get("total", 0), default=None)
        top_line = (
            f"<@{top_doc['user_id']}> with **{top_doc['total']}** invite(s)"
            if top_doc and top_doc.get("total", 0) > 0
            else "N/A"
        )

        embed = create_embed(title=f"📊 Invite Stats — {interaction.guild.name}")
        embed.add_field(name="👥 Total Joins Tracked", value=f"**{total_joins}**", inline=True)
        embed.add_field(name="🚪 Total Leaves", value=f"**{total_leaves}**", inline=True)
        embed.add_field(name="✅ Net Active", value=f"**{net_active}**", inline=True)
        embed.add_field(name="🏆 Top Inviter", value=top_line, inline=False)
        embed.add_field(name="👤 Unique Inviters", value=f"**{total_inviters}**", inline=True)

        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        await interaction.followup.send(embed=embed)

    @app_commands.command(name="inviteleaderboard", description="Show the top inviters in this server")
    async def inviteleaderboard(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        top = list(db.invites.find({"guild_id": guild_id}).sort("total", -1).limit(10))

        if not top:
            await interaction.response.send_message("❌ No invite data for this server yet.", ephemeral=True)
            return

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, doc in enumerate(top):
            prefix = medals[i] if i < 3 else f"**#{i + 1}**"
            lines.append(f"{prefix} <@{doc['user_id']}> — **{doc['total']}** invite(s)")

        embed = create_embed(
            title="📊 Invite Leaderboard",
            description="\n".join(lines),
        )

        await interaction.response.send_message(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    # MESSAGE TRACKING LISTENER
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Track messages for giveaway message requirements."""
        if message.author.bot:
            return

        if not isinstance(message.channel, discord.TextChannel):
            return

        if not db.is_connected or db.giveaways is None:
            return

        guild_id = str(message.guild.id)
        user_id = str(message.author.id)

        active = db.giveaways.find({
            "guild_id": guild_id,
            "ended": {"$ne": True},
            "message_requirement": {"$ne": None},
        })

        for giveaway in active:
            gw_id = str(giveaway["_id"])
            gw_msg_id = int(giveaway["message_id"])

            if message.id > gw_msg_id:
                self.message_counts[gw_id][user_id] += 1


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawayCog(bot))
