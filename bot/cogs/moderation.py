"""
Moderation Commands Cog
Slash commands: warn, ban, unban, kick, mute, unmute, lock, unlock, hide, unhide.
"""

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

SUCCESS = "<:check:1408031262312108102>"
FAIL = "<:cross:1408031235057385564>"


class ModerationCog(commands.Cog, name="Moderation"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── WARN ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="warn", description="Warn a member")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if member == interaction.user:
            return await interaction.response.send_message(f"{FAIL} You cannot warn yourself.", ephemeral=True)
        if member.id == interaction.guild.owner_id:
            return await interaction.response.send_message(f"{FAIL} You cannot warn the server owner.", ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id and interaction.user.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} You cannot warn someone with an equal or higher role.", ephemeral=True)

        try:
            await member.send(
                f"You have been warned in **{interaction.guild.name}** by **{interaction.user}**.\n"
                f"Reason: {reason or 'No reason provided'}"
            )
        except discord.Forbidden:
            pass

        await interaction.response.send_message(
            f"{SUCCESS} {member.mention} has been warned. Reason: {reason or 'No reason provided'}"
        )

    # ── BAN ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="Member to ban", reason="Reason for the ban")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if member == interaction.user:
            return await interaction.response.send_message(f"{FAIL} You cannot ban yourself.", ephemeral=True)
        if member.id == interaction.guild.owner_id:
            return await interaction.response.send_message(f"{FAIL} You cannot ban the server owner.", ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id and interaction.user.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} You cannot ban someone with an equal or higher role.", ephemeral=True)
        if interaction.guild.me.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} My role is not high enough to ban that member.", ephemeral=True)

        try:
            await member.ban(reason=reason or f"Action by {interaction.user}")
            await interaction.response.send_message(
                f"{SUCCESS} {member.mention} has been banned. Reason: {reason or 'No reason provided'}"
            )
        except Exception as e:
            await interaction.response.send_message(f"{FAIL} Failed to ban: {e}", ephemeral=True)

    # ── UNBAN ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="unban", description="Unban a user by their ID")
    @app_commands.describe(user_id="The Discord user ID to unban", reason="Reason for unbanning")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = None):
        try:
            uid = int(user_id)
        except ValueError:
            return await interaction.response.send_message(f"{FAIL} Invalid user ID — must be a number.", ephemeral=True)

        await interaction.response.defer()
        try:
            banned_entry = await interaction.guild.fetch_ban(discord.Object(id=uid))
            await interaction.guild.unban(banned_entry.user, reason=reason or f"Action by {interaction.user}")
            await interaction.followup.send(
                f"{SUCCESS} **{banned_entry.user}** has been unbanned. Reason: {reason or 'No reason provided'}"
            )
        except discord.NotFound:
            await interaction.followup.send(f"{FAIL} That user is not banned.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"{FAIL} Failed to unban: {e}", ephemeral=True)

    # ── KICK ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="Member to kick", reason="Reason for the kick")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if member == interaction.user:
            return await interaction.response.send_message(f"{FAIL} You cannot kick yourself.", ephemeral=True)
        if member.id == interaction.guild.owner_id:
            return await interaction.response.send_message(f"{FAIL} You cannot kick the server owner.", ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id and interaction.user.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} You cannot kick someone with an equal or higher role.", ephemeral=True)
        if interaction.guild.me.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} My role is not high enough to kick that member.", ephemeral=True)

        try:
            await member.kick(reason=reason or f"Action by {interaction.user}")
            await interaction.response.send_message(
                f"{SUCCESS} {member.mention} has been kicked. Reason: {reason or 'No reason provided'}"
            )
        except Exception as e:
            await interaction.response.send_message(f"{FAIL} Failed to kick: {e}", ephemeral=True)

    # ── MUTE (timeout) ────────────────────────────────────────────────────────

    @app_commands.command(name="mute", description="Timeout a member (28 days)")
    @app_commands.describe(member="Member to mute", reason="Reason for the mute")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mute(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if member == interaction.user:
            return await interaction.response.send_message(f"{FAIL} You cannot mute yourself.", ephemeral=True)
        if member.id == interaction.guild.owner_id:
            return await interaction.response.send_message(f"{FAIL} You cannot mute the server owner.", ephemeral=True)
        if interaction.user.id != interaction.guild.owner_id and interaction.user.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} You cannot mute someone with an equal or higher role.", ephemeral=True)
        if interaction.guild.me.top_role <= member.top_role:
            return await interaction.response.send_message(f"{FAIL} My role is not high enough to mute that member.", ephemeral=True)
        if member.timed_out_until and member.timed_out_until > discord.utils.utcnow():
            return await interaction.response.send_message(f"{FAIL} {member.mention} is already muted.", ephemeral=True)

        try:
            await member.timeout(timedelta(days=28), reason=reason or f"Action by {interaction.user}")
            await interaction.response.send_message(
                f"{SUCCESS} {member.mention} has been muted. Reason: {reason or 'No reason provided'}"
            )
        except Exception as e:
            await interaction.response.send_message(f"{FAIL} Failed to mute: {e}", ephemeral=True)

    # ── UNMUTE ────────────────────────────────────────────────────────────────

    @app_commands.command(name="unmute", description="Remove a member's timeout")
    @app_commands.describe(member="Member to unmute", reason="Reason for unmuting")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = None):
        if not member.timed_out_until or member.timed_out_until < discord.utils.utcnow():
            return await interaction.response.send_message(f"{FAIL} {member.mention} is not muted.", ephemeral=True)

        try:
            await member.timeout(None, reason=reason or f"Action by {interaction.user}")
            await interaction.response.send_message(
                f"{SUCCESS} {member.mention} has been unmuted. Reason: {reason or 'No reason provided'}"
            )
        except Exception as e:
            await interaction.response.send_message(f"{FAIL} Failed to unmute: {e}", ephemeral=True)

    # ── LOCK ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="lock", description="Lock the current channel (block @everyone from sending)")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def lock(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages is False:
            return await interaction.response.send_message(f"{FAIL} Channel is already locked.", ephemeral=True)

        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"{SUCCESS} Channel locked by {interaction.user.mention}.")

    # ── UNLOCK ────────────────────────────────────────────────────────────────

    @app_commands.command(name="unlock", description="Unlock the current channel")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unlock(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        if overwrite.send_messages is None or overwrite.send_messages is True:
            return await interaction.response.send_message(f"{FAIL} Channel is not locked.", ephemeral=True)

        overwrite.send_messages = True
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"{SUCCESS} Channel unlocked by {interaction.user.mention}.")

    # ── HIDE ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="hide", description="Hide the current channel from @everyone")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def hide(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        if overwrite.view_channel is False:
            return await interaction.response.send_message(f"{FAIL} Channel is already hidden.", ephemeral=True)

        overwrite.view_channel = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"{SUCCESS} Channel hidden by {interaction.user.mention}.")

    # ── UNHIDE ────────────────────────────────────────────────────────────────

    @app_commands.command(name="unhide", description="Unhide the current channel for @everyone")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def unhide(self, interaction: discord.Interaction):
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        if overwrite.view_channel is None or overwrite.view_channel is True:
            return await interaction.response.send_message(f"{FAIL} Channel is not hidden.", ephemeral=True)

        overwrite.view_channel = True
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message(f"{SUCCESS} Channel unhidden by {interaction.user.mention}.")


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
