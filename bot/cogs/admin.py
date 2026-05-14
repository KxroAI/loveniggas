"""
Admin Commands Cog
Owner and administrator only commands.
"""

import asyncio
import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime

from ..config import PH_TIMEZONE, BOT_OWNER_ID
from ..database import db
from ..utils import create_embed


# ══════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENT MODAL
# ══════════════════════════════════════════════════════════════════════════════

class AnnouncementModal(ui.Modal, title="Create Announcement"):
    """Modal for creating announcements."""
    
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.collected_data = {}
        
        self.title_input = ui.TextInput(
            label="Title (optional)",
            default="ANNOUNCEMENT",
            required=False,
            max_length=256,
        )
        self.message_input = ui.TextInput(
            label="Message (required)",
            placeholder="Your announcement message...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
        )
        self.codeblock_input = ui.TextInput(
            label="Use Code Block? (Yes/No)",
            default="No",
            required=True,
            placeholder="Type 'Yes' or 'No'",
        )
        
        self.add_item(self.title_input)
        self.add_item(self.message_input)
        self.add_item(self.codeblock_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        title = self.title_input.value.strip() or "ANNOUNCEMENT"
        message = self.message_input.value.strip()
        use_codeblock = self.codeblock_input.value.strip().lower() in ("yes", "y", "true", "1")
        
        # Show preview
        description = f"```\n{message}\n```" if use_codeblock else message
        embed = create_embed(title=title, description=description)
        
        view = AnnouncementConfirmView(
            author=interaction.user,
            title=title,
            message=message,
            use_codeblock=use_codeblock,
        )
        
        await interaction.response.send_message(
            "📋 **Preview:**",
            embed=embed,
            view=view,
            ephemeral=True,
        )


class AnnouncementConfirmView(ui.View):
    """Confirmation view for announcements."""
    
    def __init__(self, author: discord.User, title: str, message: str, use_codeblock: bool):
        super().__init__(timeout=180)
        self.author = author
        self.title = title
        self.message = message
        self.use_codeblock = use_codeblock
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.author
    
    @ui.button(label="Send", style=discord.ButtonStyle.green)
    async def send(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Please select a channel:",
            view=ChannelSelectView(
                author=self.author,
                title=self.title,
                message=self.message,
                use_codeblock=self.use_codeblock,
            ),
            ephemeral=True,
        )
    
    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(title="❌ Announcement cancelled.")
        await interaction.response.edit_message(embed=embed, view=None)


class ChannelSelectView(ui.View):
    """Channel selection for announcements."""
    
    def __init__(self, author: discord.User, title: str, message: str, use_codeblock: bool):
        super().__init__(timeout=180)
        self.author = author
        self.title = title
        self.message = message
        self.use_codeblock = use_codeblock
    
    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select a channel...",
    )
    async def select_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        if interaction.user != self.author:
            await interaction.response.send_message("❌ Not your menu.", ephemeral=True)
            return
        
        try:
            channel = await interaction.guild.fetch_channel(select.values[0].id)
        except Exception:
            await interaction.response.send_message("❌ Channel not accessible.", ephemeral=True)
            return
        
        description = f"```\n{self.message}\n```" if self.use_codeblock else self.message
        embed = create_embed(title=self.title, description=description)
        
        try:
            await channel.send(embed=embed)
            await interaction.response.edit_message(
                content="✅ Announcement sent!",
                embed=None,
                view=None,
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to send there.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN COG
# ══════════════════════════════════════════════════════════════════════════════

class AdminCog(commands.Cog):
    """Admin and owner-only commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ══════════════════════════════════════════════════════════════════════════
    # DM COMMANDS (OWNER ONLY)
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="dm", description="Send a DM to a user (Owner only)")
    @app_commands.describe(user="The user to message", message="The message to send")
    async def dm(self, interaction: discord.Interaction, user: discord.User, message: str):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        
        try:
            await user.send(message)
            await interaction.response.send_message(f"✅ Sent DM to {user}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Can't DM {user}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="dmall", description="Send DM to all members (Owner only)")
    @app_commands.describe(
        message="The message to send",
        all_servers="Send to all servers? (Default: current server only)",
    )
    @app_commands.choices(all_servers=[
        app_commands.Choice(name="YES", value="all"),
        app_commands.Choice(name="NO", value="server"),
    ])
    async def dmall(
        self, 
        interaction: discord.Interaction, 
        message: str, 
        all_servers: app_commands.Choice[str] = None
    ):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        
        scope = "server" if all_servers is None else all_servers.value
        await interaction.response.defer(ephemeral=True)
        
        success = 0
        fail = 0
        
        guilds = [interaction.guild] if scope == "server" else self.bot.guilds
        
        for guild in guilds:
            if not guild:
                continue
            
            if not guild.chunked:
                try:
                    await guild.chunk()
                except Exception:
                    continue
            
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    await member.send(message)
                    success += 1
                except Exception:
                    fail += 1
                await asyncio.sleep(1.5)  # Rate limit protection
        
        await interaction.followup.send(
            f"✅ Sent to **{success}** members. ❌ Failed: **{fail}**"
        )
    
    # ══════════════════════════════════════════════════════════════════════════
    # PURGE COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="purge", description="Bulk-delete messages (Admin)")
    @app_commands.describe(amount="Number of messages to delete")
    async def purge(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❗ Enter a positive number.", ephemeral=True)
            return
        
        has_permission = (
            interaction.user.guild_permissions.manage_messages or 
            interaction.user.id == BOT_OWNER_ID
        )
        
        if not has_permission:
            await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ Deleted **{len(deleted)}** messages.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No permission.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
    
    # ══════════════════════════════════════════════════════════════════════════
    # ANNOUNCEMENT COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="announcement", description="Create an announcement (Admin)")
    async def announcement(self, interaction: discord.Interaction):
        has_permission = (
            interaction.user.guild_permissions.manage_messages or 
            interaction.user.id == BOT_OWNER_ID
        )
        
        if not has_permission:
            await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
            return
        
        modal = AnnouncementModal(self.bot)
        await interaction.response.send_modal(modal)
    
    # ══════════════════════════════════════════════════════════════════════════
    # SAY COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="say", description="Make the bot say something")
    @app_commands.describe(message="The message to send")
    async def say(self, interaction: discord.Interaction, message: str):
        # Block @everyone/@here for safety
        if "@everyone" in message or "@here" in message:
            await interaction.response.send_message("❌ Cannot mention everyone/here.", ephemeral=True)
            return
        
        await interaction.response.send_message("✅ Sending...", ephemeral=True)
        await interaction.channel.send(message)
    
    # ══════════════════════════════════════════════════════════════════════════
    # CREATE INVITE COMMAND (OWNER ONLY)
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="createinvite", description="Generate invites for all servers (Owner only)")
    async def createinvite(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        invites = []
        for guild in self.bot.guilds:
            try:
                channel = next(
                    (ch for ch in guild.text_channels if ch.permissions_for(guild.me).create_instant_invite),
                    None,
                )
                if channel:
                    invite = await channel.create_invite(max_age=1800, reason="Owner request")
                    invites.append(f"**{guild.name}** (`{guild.id}`): {invite.url}")
                else:
                    invites.append(f"**{guild.name}**: ❌ No suitable channel")
            except discord.Forbidden:
                invites.append(f"**{guild.name}**: ❌ No permission")
            except Exception as e:
                invites.append(f"**{guild.name}**: ❌ {e}")
            await asyncio.sleep(0.5)
        
        # Split if too long
        full_message = "\n".join(invites)
        if len(full_message) > 1900:
            chunks = [full_message[i:i+1900] for i in range(0, len(full_message), 1900)]
            await interaction.followup.send(chunks[0], ephemeral=True)
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.followup.send(full_message, ephemeral=True)


    # ══════════════════════════════════════════════════════════════════════════
    # INVITE MANAGEMENT (ADMIN)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="adjustinvites", description="Add or remove invites from a user's count (Admin)")
    @app_commands.describe(user="The user to adjust", amount="Positive to add, negative to remove")
    async def adjustinvites(self, interaction: discord.Interaction, user: discord.User, amount: int):
        has_permission = (
            interaction.user.guild_permissions.administrator or
            interaction.user.id == BOT_OWNER_ID
        )
        if not has_permission:
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
            return

        if amount == 0:
            await interaction.response.send_message("❗ Amount cannot be zero.", ephemeral=True)
            return

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        user_id = str(user.id)

        db.invites.update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$inc": {"total": amount}},
            upsert=True,
        )

        doc = db.invites.find_one({"guild_id": guild_id, "user_id": user_id})
        new_total = max(doc.get("total", 0), 0) if doc else 0

        if new_total < 0:
            db.invites.update_one(
                {"guild_id": guild_id, "user_id": user_id},
                {"$set": {"total": 0}},
            )
            new_total = 0

        action = f"+{amount}" if amount > 0 else str(amount)
        embed = create_embed(
            title="✅ Invites Adjusted",
            description=(
                f"**User:** {user.mention}\n"
                f"**Change:** {action}\n"
                f"**New Total:** {new_total} invite(s)"
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resetinvites", description="Reset a user's invite count to zero (Admin)")
    @app_commands.describe(user="The user whose invite count to reset")
    async def resetinvites(self, interaction: discord.Interaction, user: discord.User):
        has_permission = (
            interaction.user.guild_permissions.administrator or
            interaction.user.id == BOT_OWNER_ID
        )
        if not has_permission:
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
            return

        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        user_id = str(user.id)

        db.invites.update_one(
            {"guild_id": guild_id, "user_id": user_id},
            {"$set": {"total": 0, "invited_users": []}},
            upsert=True,
        )

        embed = create_embed(
            title="✅ Invites Reset",
            description=f"{user.mention}'s invite count has been reset to **0**.",
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
