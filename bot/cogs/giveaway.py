"""
Giveaway Commands Cog
Handles giveaway creation, management, and entry tracking.
"""

import re
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
# GIVEAWAY VIEW
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
        
        # Check if already entered
        if user_id in giveaway.get("entries", []):
            # Allow leaving
            db.giveaways.update_one(
                {"_id": self.giveaway_id},
                {"$pull": {"entries": user_id}}
            )
            
            # Update footer
            giveaway = db.giveaways.find_one({"_id": self.giveaway_id})
            await self._update_embed(interaction, giveaway)
            await interaction.response.send_message("❌ You left the giveaway.", ephemeral=True)
            return
        
        # Check role requirements
        if self.required_roles:
            member_roles = [r.id for r in interaction.user.roles]
            if not any(r in member_roles for r in self.required_roles):
                role_mentions = ", ".join(f"<@&{r}>" for r in self.required_roles)
                await interaction.response.send_message(
                    f"❌ You need one of these roles: {role_mentions}",
                    ephemeral=True,
                )
                return
        
        # Check message requirement
        if self.message_requirement and self.cog:
            gw_id = str(self.giveaway_id)
            msg_count = self.cog.message_counts.get(gw_id, {}).get(user_id, 0)
            if msg_count < self.message_requirement:
                await interaction.response.send_message(
                    f"❌ You need {self.message_requirement} messages to enter. You have {msg_count}.",
                    ephemeral=True,
                )
                return
        
        # Check invite requirement
        if self.invite_requirement and self.cog:
            gw_id = str(self.giveaway_id)
            invite_count = self.cog.invite_counts.get(gw_id, {}).get(user_id, 0)
            if invite_count < self.invite_requirement:
                await interaction.response.send_message(
                    f"❌ You need {self.invite_requirement} invites. You have {invite_count}.",
                    ephemeral=True,
                )
                return
        
        # Add entry
        db.giveaways.update_one(
            {"_id": self.giveaway_id},
            {"$addToSet": {"entries": user_id}}
        )
        
        # Update embed
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
            embed.add_field(name="Required Roles", value=roles, inline=False)
        
        if giveaway.get("message_requirement"):
            embed.add_field(
                name="Message Requirement",
                value=f"{giveaway['message_requirement']} message(s)",
                inline=False,
            )
        
        if giveaway.get("invite_requirement"):
            embed.add_field(
                name="Invite Requirement",
                value=f"{giveaway['invite_requirement']} invite(s)",
                inline=False,
            )
        
        embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
        embed.set_footer(text=f"Entries {entry_count} | ID: {giveaway['_id']}")
        embed.timestamp = datetime.now(PH_TIMEZONE)
        
        try:
            await interaction.message.edit(embed=embed)
        except Exception:
            pass


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
        """Snapshot the current invite use-counts for a guild."""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.Cog.listener()
    async def on_ready(self):
        """Cache invites for all guilds on startup."""
        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Cache invites when the bot joins a new guild."""
        await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Add a new invite to the cache."""
        if invite.guild:
            self.invite_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Remove a deleted invite from the cache."""
        if invite.guild:
            self.invite_cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Detect which invite was used and credit the inviter."""
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
        """Subtract from the inviter's count when an invited member leaves."""
        if not db.is_connected or db.invites is None:
            return

        guild_id = str(member.guild.id)
        user_id = str(member.id)

        doc = db.invites.find_one(
            {"guild_id": guild_id, "invited_users": user_id}
        )
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
        
        # Cleanup tracking
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
        
        # Build final embed
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
        
        embed.add_field(name="Hosted by", value=f"<@{giveaway['host_id']}>", inline=False)
        embed.set_footer(text=f"Entries {len(entries)} | ID: {giveaway_id}")
        embed.timestamp = datetime.now(PH_TIMEZONE)
        
        await message.edit(embed=embed, view=None)
        
        if entries:
            await message.reply(f"🏆 **Winner(s)**: {winner_mentions}")
    
    async def schedule_end(self, giveaway_id: ObjectId, delay: float):
        """Schedule a giveaway to end after delay seconds."""
        await asyncio.sleep(delay)
        await self.end_giveaway(giveaway_id)
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMMANDS
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="giveaway", description="Start a timed giveaway")
    @app_commands.describe(
        prize="The prize for the giveaway",
        duration="Duration (e.g., 30s, 10m, 2h, 1d)",
        winner_count="Number of winners",
        required_roles="Mention roles required to enter (optional)",
        message_requirement="Min messages to enter (optional)",
        invite_requirement="Min invites to enter (optional)",
    )
    async def giveaway(
        self,
        interaction: discord.Interaction,
        prize: str,
        duration: str,
        winner_count: int,
        required_roles: str = None,
        message_requirement: int = None,
        invite_requirement: int = None,
    ):
        if not has_manage_guild(interaction, BOT_OWNER_ID):
            await interaction.response.send_message(
                "❌ You need **Manage Server** permission.",
                ephemeral=True,
            )
            return
        
        try:
            total_seconds = parse_duration(duration)
            if total_seconds <= 0 or winner_count <= 0:
                raise ValueError()
        except Exception:
            await interaction.response.send_message(
                "❌ Invalid duration or winner count.",
                ephemeral=True,
            )
            return
        
        # Parse roles
        required_role_ids = []
        if required_roles:
            required_role_ids = [int(rid) for rid in re.findall(r'<@&(\d+)>', required_roles)]
        
        # Calculate end time
        end_time_ph = datetime.now(PH_TIMEZONE) + timedelta(seconds=total_seconds)
        end_time_utc = end_time_ph.astimezone(pytz.UTC)
        end_unix = int(end_time_ph.timestamp())
        
        # Build embed
        embed = discord.Embed(title=f"**🎁 {prize}**", color=discord.Color.gold())
        embed.add_field(name="⏰ Ends", value=f"<t:{end_unix}:f> (<t:{end_unix}:R>)", inline=False)
        embed.add_field(name="🏆 Winners", value=str(winner_count), inline=False)
        
        if required_role_ids:
            roles = ", ".join(f"<@&{r}>" for r in required_role_ids)
            embed.add_field(name="Required Roles", value=roles, inline=False)
        
        if message_requirement:
            embed.add_field(name="Message Requirement", value=f"{message_requirement} message(s)", inline=False)
        
        if invite_requirement:
            embed.add_field(name="Invite Requirement", value=f"{invite_requirement} invite(s)", inline=False)
        
        embed.add_field(name="Hosted by", value=interaction.user.mention, inline=False)
        embed.set_footer(text="Entries 0 | ID: Loading...")
        embed.timestamp = datetime.now(PH_TIMEZONE)
        
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        
        # Save to DB
        giveaway_data = {
            "guild_id": str(interaction.guild.id),
            "channel_id": str(interaction.channel.id),
            "message_id": str(msg.id),
            "host_id": str(interaction.user.id),
            "prize": prize,
            "end_time": end_time_utc,
            "winner_count": winner_count,
            "required_roles": required_role_ids,
            "message_requirement": message_requirement,
            "invite_requirement": invite_requirement,
            "entries": [],
            "ended": False,
            "created_at": datetime.now(PH_TIMEZONE),
        }
        
        if not db.is_connected:
            await interaction.followup.send("❌ Database error.", ephemeral=True)
            return
        
        result = db.giveaways.insert_one(giveaway_data)
        giveaway_id = result.inserted_id
        
        # Update footer
        embed.set_footer(text=f"Entries 0 | ID: {giveaway_id}")
        
        # Create view
        view = GiveawayEntryView(
            giveaway_id=giveaway_id,
            host_id=str(interaction.user.id),
            prize=prize,
            end_time=end_time_ph,
            winner_count=winner_count,
            required_roles=required_role_ids,
            message_requirement=message_requirement,
            invite_requirement=invite_requirement,
            cog=self,
        )
        
        await msg.edit(embed=embed, view=view)
        
        # Schedule end
        asyncio.create_task(self.schedule_end(giveaway_id, total_seconds))
    
    @app_commands.command(name="giveawayend", description="Force-end a giveaway early")
    @app_commands.describe(id="The giveaway ID (from footer)")
    async def giveawayend(self, interaction: discord.Interaction, id: str):
        if not has_manage_guild(interaction, BOT_OWNER_ID):
            await interaction.response.send_message("❌ You need **Manage Server** permission.", ephemeral=True)
            return
        
        if not db.is_connected:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
        
        try:
            giveaway_id = ObjectId(id)
        except Exception:
            await interaction.response.send_message("❌ Invalid giveaway ID.", ephemeral=True)
            return
        
        giveaway = db.giveaways.find_one({"_id": giveaway_id})
        
        if not giveaway:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return
        
        if giveaway.get("ended"):
            await interaction.response.send_message("❌ Already ended.", ephemeral=True)
            return
        
        if str(giveaway["guild_id"]) != str(interaction.guild.id):
            await interaction.response.send_message("❌ Not from this server.", ephemeral=True)
            return
        
        await self.end_giveaway(giveaway_id)
        await interaction.response.send_message("✅ Giveaway ended!")
    
    @app_commands.command(name="giveawayreroll", description="Pick new winners for an ended giveaway")
    @app_commands.describe(id="The giveaway ID (from footer)")
    async def giveawayreroll(self, interaction: discord.Interaction, id: str):
        if not has_manage_guild(interaction, BOT_OWNER_ID):
            await interaction.response.send_message("❌ You need **Manage Server** permission.", ephemeral=True)
            return
        
        if not db.is_connected:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
        
        try:
            giveaway_id = ObjectId(id)
        except Exception:
            await interaction.response.send_message("❌ Invalid giveaway ID.", ephemeral=True)
            return
        
        giveaway = db.giveaways.find_one({"_id": giveaway_id})
        
        if not giveaway:
            await interaction.response.send_message("❌ Giveaway not found.", ephemeral=True)
            return
        
        if not giveaway.get("ended"):
            await interaction.response.send_message("❌ Giveaway hasn't ended yet.", ephemeral=True)
            return
        
        entries = giveaway.get("entries", [])
        
        if not entries:
            await interaction.response.send_message("❌ No entries to reroll.", ephemeral=True)
            return
        
        winner_count = giveaway.get("winner_count", 1)
        new_winners = random.sample(entries, min(len(entries), winner_count))
        winner_mentions = ", ".join(f"<@{w}>" for w in new_winners)
        
        guild = self.bot.get_guild(int(giveaway["guild_id"]))
        channel = guild.get_channel(int(giveaway["channel_id"])) if guild else None
        
        if not channel:
            await interaction.response.send_message("❌ Channel not found.", ephemeral=True)
            return
        
        try:
            original = await channel.fetch_message(int(giveaway["message_id"]))
            await original.reply(
                f"🔄 **Giveaway Re-Rolled!**\n🏆 **New Winner(s) for `{giveaway['prize']}`**: {winner_mentions}"
            )
            await interaction.response.send_message("✅ Re-rolled successfully!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
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
        """Track messages for giveaway requirements."""
        if message.author.bot:
            return
        
        if not isinstance(message.channel, discord.TextChannel):
            return
        
        if not db.is_connected or db.giveaways is None:
            return
        
        guild_id = str(message.guild.id)
        user_id = str(message.author.id)
        
        # Find active giveaways with message requirement
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
