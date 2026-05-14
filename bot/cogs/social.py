"""
Social Media Commands Cog
Handles TikTok download, Instagram preview, and other social features.
"""

import re
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta

from ..config import PH_TIMEZONE
from ..database import db
from ..utils import create_embed, parse_duration


class SocialCog(commands.Cog):
    """Social media and miscellaneous commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.snipe_cache: dict[int, dict] = {}
    
    # ══════════════════════════════════════════════════════════════════════════
    # TIKTOK
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="tiktok", description="Download a TikTok video")
    @app_commands.describe(link="TikTok video URL", spoiler="Mark as spoiler?")
    async def tiktok(self, interaction: discord.Interaction, link: str, spoiler: bool = False):
        # Convert to embeddable link
        if "tiktok.com" not in link:
            await interaction.response.send_message("❌ Invalid TikTok URL.", ephemeral=True)
            return
        
        # Try to convert to vxtiktok for embedding
        embed_link = link.replace("tiktok.com", "vxtiktok.com")
        
        embed = create_embed(
            description=f"🎵 **TikTok Video**\n[Watch Video]({embed_link})"
        )
        
        if spoiler:
            embed.description = f"||{embed.description}||"
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # INSTAGRAM
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="instagram", description="Convert Instagram to embeddable link")
    @app_commands.describe(link="Instagram post/reel URL")
    async def instagram(self, interaction: discord.Interaction, link: str):
        if "instagram.com" not in link:
            await interaction.response.send_message("❌ Invalid Instagram URL.", ephemeral=True)
            return
        
        # Convert to ddinstagram for embedding
        embed_link = link.replace("instagram.com", "ddinstagram.com")
        
        embed = create_embed(
            description=f"📸 **Instagram Post**\n[View Post]({embed_link})"
        )
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # POLL
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="poll", description="Create a timed poll")
    @app_commands.describe(
        question="The poll question",
        duration="Poll duration (e.g., 5m, 1h)",
    )
    async def poll(self, interaction: discord.Interaction, question: str, duration: str):
        try:
            seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message("❌ Invalid duration.", ephemeral=True)
            return
        
        end_time = datetime.now(PH_TIMEZONE) + timedelta(seconds=seconds)
        end_unix = int(end_time.timestamp())
        
        embed = create_embed(
            title="📊 Poll",
            description=f"**{question}**\n\nEnds: <t:{end_unix}:R>",
        )
        embed.add_field(name="👍", value="Yes", inline=True)
        embed.add_field(name="👎", value="No", inline=True)
        
        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
    
    # ══════════════════════════════════════════════════════════════════════════
    # REMIND ME
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="remindme", description="Set a reminder")
    @app_commands.describe(
        duration="When to remind (e.g., 5m, 1h, 1d)",
        note="What to remind you about",
    )
    async def remindme(self, interaction: discord.Interaction, duration: str, note: str):
        try:
            seconds = parse_duration(duration)
        except ValueError:
            await interaction.response.send_message("❌ Invalid duration.", ephemeral=True)
            return
        
        if not db.is_connected or db.reminders is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
        
        reminder_time = datetime.now(PH_TIMEZONE) + timedelta(seconds=seconds)
        
        db.reminders.insert_one({
            "user_id": interaction.user.id,
            "guild_id": interaction.guild.id,
            "channel_id": interaction.channel.id,
            "note": note,
            "reminder_time": reminder_time,
        })
        
        unix_time = int(reminder_time.timestamp())
        
        embed = create_embed(
            title="⏰ Reminder Set!",
            description=f"I'll remind you: **{note}**\n\nAt: <t:{unix_time}:f> (<t:{unix_time}:R>)",
            color=discord.Color.green(),
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # ══════════════════════════════════════════════════════════════════════════
    # SNIPE
    # ══════════════════════════════════════════════════════════════════════════
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """Cache deleted messages for snipe."""
        if message.author.bot:
            return
        
        self.snipe_cache[message.channel.id] = {
            "content": message.content,
            "author": message.author,
            "attachments": [a.url for a in message.attachments],
            "deleted_at": datetime.now(PH_TIMEZONE),
        }
    
    @app_commands.command(name="snipe", description="Recover the last deleted message")
    async def snipe(self, interaction: discord.Interaction):
        cached = self.snipe_cache.get(interaction.channel.id)
        
        if not cached:
            await interaction.response.send_message("❌ Nothing to snipe.", ephemeral=True)
            return
        
        embed = create_embed()
        embed.set_author(
            name=str(cached["author"]),
            icon_url=cached["author"].display_avatar.url,
        )
        embed.description = cached["content"] or "*No text content*"
        
        if cached["attachments"]:
            embed.add_field(
                name="Attachments",
                value="\n".join(cached["attachments"][:5]),
                inline=False,
            )
        
        deleted_unix = int(cached["deleted_at"].timestamp())
        embed.set_footer(text=f"Deleted at <t:{deleted_unix}:f>")
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # DONATE (FUN COMMAND)
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="donate", description="Playfully 'donate' Robux to a user (cosmetic)")
    @app_commands.describe(user="The user to donate to", amount="Amount of Robux")
    async def donate(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❗ Enter a positive amount.", ephemeral=True)
            return
        
        embed = create_embed(
            title="💸 Donation Sent!",
            description=f"{interaction.user.mention} donated **{amount:,} Robux** to {user.mention}!",
            color=discord.Color.green(),
        )
        embed.set_footer(text="(This is just for fun - no actual Robux were transferred)")
        
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SocialCog(bot))
