"""
Social Media Commands Cog
Handles TikTok download, Instagram preview, and other social features.
"""

import os
import re
import tempfile
import discord
import pyktok as pyk
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
        self.editsnipe_cache: dict[int, dict] = {}
    
    # ══════════════════════════════════════════════════════════════════════════
    # TIKTOK
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="tiktok", description="Download and share a TikTok video directly in Discord")
    @app_commands.describe(link="The TikTok Video URL to Convert", spoiler="Should the video be sent as a spoiler?")
    async def tiktok(self, interaction: discord.Interaction, link: str, spoiler: bool = False):
        await interaction.response.defer(ephemeral=False)

        original_dir = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.chdir(tmpdir)
                pyk.save_tiktok(link, save_video=True)

                video_files = [
                    os.path.join(root, f)
                    for root, _, files in os.walk(tmpdir)
                    for f in files if f.lower().endswith(".mp4")
                ]

                if not video_files:
                    await interaction.followup.send("❌ Failed to find TikTok video after download.")
                    return

                video_path = video_files[0]
                filename = os.path.basename(video_path)
                if spoiler:
                    filename = f"SPOILER_{filename}"

                await interaction.followup.send(
                    file=discord.File(fp=video_path, filename=filename),
                    ephemeral=False,
                )
        except Exception as e:
            await interaction.followup.send(f"❌ An error occurred while processing the video: {e}")
            print(f"[ERROR] {e}")
        finally:
            os.chdir(original_dir)
    
    # ══════════════════════════════════════════════════════════════════════════
    # INSTAGRAM
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="instagram", description="Convert an Instagram post/reel into an embeddable preview link")
    @app_commands.describe(link="Instagram post or reel URL", spoiler="Should the video be sent as a spoiler?")
    async def instagram(self, interaction: discord.Interaction, link: str, spoiler: bool = False):
        match = re.search(r"instagram\.com/(p|reel)/([^/]+)/", link)
        if not match:
            await interaction.response.send_message("❌ Invalid Instagram post or reel link.", ephemeral=False)
            return

        short_code = match.group(2)
        instagramez_link = f"https://instagramez.com/p/{short_code}"

        message = f"[EmbedEZ]({instagramez_link})"
        if spoiler:
            message = f"||{message}||"
        await interaction.response.send_message(message, ephemeral=False)
    
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
            "author": str(message.author),
            "content": message.content,
            "timestamp": message.created_at,
            "attachments": [a.url for a in message.attachments],
        }

    @app_commands.command(name="snipe", description="Show the last deleted message in this channel")
    async def snipe(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.snipe_cache:
            await interaction.response.send_message(
                "❌ There are no recently deleted messages in this channel.",
                ephemeral=True,
            )
            return

        msg_data = self.snipe_cache[channel_id]
        author = msg_data["author"]
        content = msg_data["content"] or "[No text content]"
        attachments = msg_data["attachments"]

        embed = discord.Embed(
            description=content,
            color=discord.Color.red(),
            timestamp=msg_data["timestamp"],
        )
        embed.set_author(name=author)
        embed.set_footer(text="Neroniel | Deleted at:")

        if attachments:
            embed.add_field(
                name="Attachments",
                value="\n".join([f"[Link]({url})" for url in attachments]),
                inline=False,
            )

        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ══════════════════════════════════════════════════════════════════════════
    # EDITSNIPE
    # ══════════════════════════════════════════════════════════════════════════

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """Cache edited messages for editsnipe."""
        if before.author.bot:
            return
        if before.content == after.content:
            return

        self.editsnipe_cache[before.channel.id] = {
            "author": str(before.author),
            "before": before.content,
            "after": after.content,
            "timestamp": before.created_at,
        }

    @app_commands.command(name="editsnipe", description="Show the last edited message in this channel")
    async def editsnipe(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if channel_id not in self.editsnipe_cache:
            await interaction.response.send_message(
                "❌ There are no recently edited messages in this channel.",
                ephemeral=True,
            )
            return

        msg_data = self.editsnipe_cache[channel_id]

        embed = discord.Embed(
            color=discord.Color.orange(),
            timestamp=msg_data["timestamp"],
        )
        embed.set_author(name=msg_data["author"])
        embed.add_field(name="Before", value=msg_data["before"] or "[No text content]", inline=False)
        embed.add_field(name="After",  value=msg_data["after"]  or "[No text content]", inline=False)
        embed.set_footer(text="Neroniel | Edited at:")

        await interaction.response.send_message(embed=embed, ephemeral=False)

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
