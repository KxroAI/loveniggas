"""
Voice Channel Control Cog
VC moderation commands: mute, unmute, deafen, undeafen, move, moveall.
"""

import discord
from discord import app_commands
from discord.ext import commands

from ..config import BOT_OWNER_ID
from ..utils import create_embed, create_error_embed


def _is_owner(ctx: commands.Context) -> bool:
    return ctx.author.id == BOT_OWNER_ID


class VCControlCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── vcmute ────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcmute", description="Server-mute a member in a voice channel")
    @app_commands.describe(member="The member to mute in voice")
    @commands.guild_only()
    async def vcmute(self, ctx: commands.Context, member: discord.Member):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.mute_members:
            return await ctx.send(
                embed=create_error_embed("You need **Mute Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        if member.voice.mute:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is already server-muted."), ephemeral=True
            )
        await member.edit(mute=True, reason=f"vcmute by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="🔇 Voice Muted",
                description=f"{member.mention} has been server-muted.",
            )
        )

    # ── vcunmute ──────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcunmute", description="Remove a member's server-mute")
    @app_commands.describe(member="The member to unmute in voice")
    @commands.guild_only()
    async def vcunmute(self, ctx: commands.Context, member: discord.Member):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.mute_members:
            return await ctx.send(
                embed=create_error_embed("You need **Mute Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        await member.edit(mute=False, reason=f"vcunmute by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="🔊 Voice Unmuted",
                description=f"{member.mention} has been server-unmuted.",
            )
        )

    # ── vcdeafen ──────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcdeafen", description="Server-deafen a member in a voice channel")
    @app_commands.describe(member="The member to deafen in voice")
    @commands.guild_only()
    async def vcdeafen(self, ctx: commands.Context, member: discord.Member):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.deafen_members:
            return await ctx.send(
                embed=create_error_embed("You need **Deafen Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        if member.voice.deaf:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is already server-deafened."), ephemeral=True
            )
        await member.edit(deafen=True, reason=f"vcdeafen by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="🔕 Voice Deafened",
                description=f"{member.mention} has been server-deafened.",
            )
        )

    # ── vcundeafen ────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcundeafen", description="Remove a member's server-deafen")
    @app_commands.describe(member="The member to undeafen in voice")
    @commands.guild_only()
    async def vcundeafen(self, ctx: commands.Context, member: discord.Member):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.deafen_members:
            return await ctx.send(
                embed=create_error_embed("You need **Deafen Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        await member.edit(deafen=False, reason=f"vcundeafen by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="🔔 Voice Undeafened",
                description=f"{member.mention} has been server-undeafened.",
            )
        )

    # ── vcmove ────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcmove", description="Move a member to another voice channel")
    @app_commands.describe(member="The member to move", channel="The destination voice channel")
    @commands.guild_only()
    async def vcmove(self, ctx: commands.Context, member: discord.Member, channel: discord.VoiceChannel):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.move_members:
            return await ctx.send(
                embed=create_error_embed("You need **Move Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        await member.move_to(channel, reason=f"vcmove by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="🚶 Member Moved",
                description=f"{member.mention} was moved to **{channel.name}**.",
            )
        )

    # ── vcmoveall ─────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vcmoveall", description="Move all members from one VC to another")
    @app_commands.describe(
        from_channel="The source voice channel",
        to_channel="The destination voice channel",
    )
    @commands.guild_only()
    async def vcmoveall(
        self,
        ctx: commands.Context,
        from_channel: discord.VoiceChannel,
        to_channel: discord.VoiceChannel,
    ):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.move_members:
            return await ctx.send(
                embed=create_error_embed("You need **Move Members** permission."), ephemeral=True
            )
        members = list(from_channel.members)
        if not members:
            return await ctx.send(
                embed=create_error_embed(f"**{from_channel.name}** has no members."), ephemeral=True
            )
        await ctx.defer()
        moved = 0
        for member in members:
            try:
                await member.move_to(to_channel, reason=f"vcmoveall by {ctx.author}")
                moved += 1
            except discord.HTTPException:
                pass
        await ctx.send(
            embed=create_embed(
                title="🚶 Members Moved",
                description=f"Moved **{moved}** member(s) from **{from_channel.name}** → **{to_channel.name}**.",
            )
        )

    # ── vckick ────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="vckick", description="Kick a member from their voice channel")
    @app_commands.describe(member="The member to kick from voice")
    @commands.guild_only()
    async def vckick(self, ctx: commands.Context, member: discord.Member):
        if not _is_owner(ctx) and not ctx.author.guild_permissions.move_members:
            return await ctx.send(
                embed=create_error_embed("You need **Move Members** permission."), ephemeral=True
            )
        if not member.voice:
            return await ctx.send(
                embed=create_error_embed(f"{member.mention} is not in a voice channel."), ephemeral=True
            )
        await member.move_to(None, reason=f"vckick by {ctx.author}")
        await ctx.send(
            embed=create_embed(
                title="👢 Kicked from VC",
                description=f"{member.mention} was kicked from the voice channel.",
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(VCControlCog(bot))
