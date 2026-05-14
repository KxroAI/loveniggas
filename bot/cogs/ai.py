"""
AI Commands Cog
Handles AI chat functionality with conversation history.
"""

import os
import asyncio
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from collections import defaultdict

from ..config import PH_TIMEZONE, BOT_NAME
from ..database import db
from ..utils import create_embed, get_language_instruction


class AICog(commands.Cog):
    """AI Assistant commands using Llama 3."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rate_limits: dict[int, list] = defaultdict(list)
        self.conversations: dict[int, list] = defaultdict(list)
        self.last_message_id: dict[tuple, int] = {}
        self.ai_threads: dict[int, int] = {}
    
    # ══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _check_rate_limit(self, user_id: int) -> bool:
        """Check if user is rate limited. Returns True if limited."""
        current_time = asyncio.get_event_loop().time()
        
        # Clean old entries
        self.rate_limits[user_id] = [
            t for t in self.rate_limits[user_id] 
            if current_time - t <= 60
        ]
        
        self.rate_limits[user_id].append(current_time)
        return len(self.rate_limits[user_id]) > 5
    
    async def _get_ai_response(self, prompt: str, history: list) -> str:
        """Call the AI API and get a response."""
        lang_instruction = get_language_instruction(prompt)
        system_prompt = f"You are a helpful and friendly AI assistant named {BOT_NAME} AI. {lang_instruction}"
        
        # Build full prompt with history
        full_prompt = system_prompt + "\n"
        for msg in history[-5:]:
            full_prompt += f"User: {msg['user']}\nAssistant: {msg['assistant']}\n"
        full_prompt += f"User: {prompt}\nAssistant:"
        
        headers = {
            "Authorization": f"Bearer {os.getenv('TOGETHER_API_KEY')}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": "meta-llama/Llama-3-70b-chat-hf",
            "prompt": full_prompt,
            "max_tokens": 2048,
            "temperature": 0.7,
        }
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(
                "https://api.together.xyz/v1/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise Exception(f"API error {response.status}: {text}")
                
                data = await response.json()
                
        if "error" in data:
            raise Exception(data["error"]["message"])
        
        return data["choices"][0]["text"].strip()
    
    def _load_history(self, user_id: int) -> list:
        """Load conversation history from DB if not in memory."""
        if self.conversations[user_id]:
            return self.conversations[user_id][-5:]
        
        if not db.is_connected or db.conversations is None:
            return []
        
        docs = db.conversations.find({"user_id": user_id}).sort("timestamp", -1).limit(5)
        
        for doc in docs:
            self.conversations[user_id].append({
                "user": doc["prompt"],
                "assistant": doc["response"],
            })
        
        self.conversations[user_id].reverse()
        return self.conversations[user_id][-5:]
    
    def _save_conversation(self, user_id: int, prompt: str, response: str):
        """Save conversation to memory and DB."""
        self.conversations[user_id].append({
            "user": prompt,
            "assistant": response,
        })
        
        if db.is_connected and db.conversations is not None:
            db.conversations.insert_one({
                "user_id": user_id,
                "prompt": prompt,
                "response": response,
                "timestamp": datetime.now(PH_TIMEZONE),
            })
    
    # ══════════════════════════════════════════════════════════════════════════
    # COMMANDS
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="ask", description="Chat with an AI assistant using Llama 3")
    @app_commands.describe(prompt="What would you like to ask?")
    async def ask(self, interaction: discord.Interaction, prompt: str):
        user_id = interaction.user.id
        channel_id = interaction.channel.id
        
        await interaction.response.defer()
        
        # Check rate limit
        if self._check_rate_limit(user_id):
            await interaction.followup.send("⏳ You're being rate-limited. Please wait a minute.")
            return
        
        async with interaction.channel.typing():
            try:
                # Creator override
                if prompt.strip().lower() in [
                    "who made you", "who created you", 
                    "who created this bot", "who made this bot"
                ]:
                    embed = create_embed(description="I was created by **Neroniel**.")
                    msg = await interaction.followup.send(embed=embed)
                    self.last_message_id[(user_id, channel_id)] = msg.id
                    return
                
                # Load history and get response
                history = self._load_history(user_id)
                ai_response = await self._get_ai_response(prompt, history)
                
                # Send response
                embed = create_embed(description=ai_response)
                msg = await interaction.followup.send(embed=embed, wait=True)
                
                # Create thread on first message
                if isinstance(interaction.channel, discord.TextChannel):
                    if self.last_message_id.get((user_id, channel_id)) is None:
                        try:
                            fetched_msg = await interaction.channel.fetch_message(msg.id)
                            thread = await fetched_msg.create_thread(
                                name=f"AI • {interaction.user.display_name}",
                                auto_archive_duration=60,
                            )
                            self.ai_threads[thread.id] = user_id
                            await thread.send(
                                "🗨️ This conversation will continue here. Others can join too!\n"
                                "💡 **Just type your next question here** — no need to use `/ask` again!"
                            )
                        except Exception as e:
                            print(f"[!] Thread creation failed: {e}")
                
                # Save state
                self.last_message_id[(user_id, channel_id)] = msg.id
                self._save_conversation(user_id, prompt, ai_response)
                
            except Exception as e:
                await interaction.followup.send(f"❌ Error: {str(e)}")
                print(f"[EXCEPTION] /ask: {e}")
    
    @app_commands.command(name="clearhistory", description="Clear your AI conversation history")
    async def clearhistory(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # Clear in-memory history
        if user_id in self.conversations:
            self.conversations[user_id].clear()
        
        # Clear from MongoDB
        if db.is_connected and db.conversations is not None:
            result = db.conversations.delete_many({"user_id": user_id})
            print(f"[INFO] Deleted {result.deleted_count} history entries for user {user_id}")
        
        # Clear last message IDs
        keys_to_remove = [k for k in self.last_message_id if k[0] == user_id]
        for k in keys_to_remove:
            del self.last_message_id[k]
        
        await interaction.response.send_message(
            "✅ Your AI conversation history has been cleared!", 
            ephemeral=True
        )
    
    # ══════════════════════════════════════════════════════════════════════════
    # THREAD FOLLOW-UP HANDLER
    # ══════════════════════════════════════════════════════════════════════════
    
    async def handle_thread_message(self, message: discord.Message):
        """Handle messages in AI threads."""
        if message.channel.id not in self.ai_threads:
            return
        
        user_id = self.ai_threads[message.channel.id]
        prompt = message.content.strip()
        
        if not prompt:
            return
        
        # Check rate limit
        if self._check_rate_limit(user_id):
            await message.channel.send("⏳ You're being rate-limited. Please wait a minute.")
            return
        
        async with message.channel.typing():
            try:
                # Creator override
                if prompt.lower() in [
                    "who made you", "who created you",
                    "who created this bot", "who made this bot"
                ]:
                    embed = create_embed(description="I was created by **Neroniel**.")
                    await message.channel.send(embed=embed)
                    return
                
                # Get response
                history = self._load_history(user_id)
                ai_response = await self._get_ai_response(prompt, history)
                
                # Send and save
                embed = create_embed(description=ai_response)
                await message.channel.send(embed=embed)
                self._save_conversation(user_id, prompt, ai_response)
                
            except Exception as e:
                await message.channel.send(f"❌ Error: {str(e)}")
                print(f"[EXCEPTION] AI follow-up: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AICog(bot))
