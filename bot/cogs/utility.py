"""
Utility Commands Cog
General utility commands like userinfo, serverinfo, weather, etc.
"""

import os
import aiohttp
import discord
import psutil
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime
from enum import Enum

from ..config import (
    PH_TIMEZONE, BOT_OWNER_ID,
    PHILIPPINE_CITIES, GLOBAL_CAPITALS, PAYMENT_INFO,
)
from ..utils import create_embed, create_error_embed


# ══════════════════════════════════════════════════════════════════════════════
# COMMAND PAGINATOR VIEW
# ══════════════════════════════════════════════════════════════════════════════

class CommandPaginator(ui.View):
    """Paginated view for command list."""
    
    def __init__(self, embeds: list[discord.Embed], timeout: int = 180):
        super().__init__(timeout=timeout)
        self.embeds = embeds
        self.current_page = 0
        self._update_buttons()
    
    def _update_buttons(self):
        for child in self.children:
            if isinstance(child, ui.Button):
                if child.custom_id == "prev_page":
                    child.disabled = self.current_page == 0
                elif child.custom_id == "next_page":
                    child.disabled = self.current_page == len(self.embeds) - 1
    
    @ui.button(label="◀️ Previous", style=discord.ButtonStyle.gray, custom_id="prev_page")
    async def previous_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = max(0, self.current_page - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    @ui.button(label="Next ▶️", style=discord.ButtonStyle.gray, custom_id="next_page")
    async def next_page(self, interaction: discord.Interaction, button: ui.Button):
        self.current_page = min(len(self.embeds) - 1, self.current_page + 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT METHOD ENUM
# ══════════════════════════════════════════════════════════════════════════════

class PaymentMethod(str, Enum):
    GCASH = "Gcash"
    PAYMAYA = "PayMaya"
    GOTYME = "GoTyme"


# ══════════════════════════════════════════════════════════════════════════════
# UTILITY COG
# ══════════════════════════════════════════════════════════════════════════════

class UtilityCog(commands.Cog):
    """General utility commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.start_time = datetime.now(PH_TIMEZONE)
        self.bot.command_count = 0
    
    # ══════════════════════════════════════════════════════════════════════════
    # USER & SERVER INFO
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="userinfo", description="Display detailed information about a user")
    @app_commands.describe(user="The user to get info for (optional, defaults to you)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user
        
        created_unix = int(user.created_at.timestamp())
        user_url = f"https://discordapp.com/users/{user.id}"
        
        embed = create_embed(title=f"{user.display_name} (@{user.name})", url=user_url)
        
        desc_lines = [
            f"{user.mention}", f"{user.name}", f"ID: {user.id}", "",
            "**Account Creation**", f"<t:{created_unix}:f> (<t:{created_unix}:R>)"
        ]
        
        if isinstance(user, discord.Member):
            if user.joined_at:
                joined_unix = int(user.joined_at.timestamp())
                desc_lines.extend(["", "**Joined Server**", f"<t:{joined_unix}:f> (<t:{joined_unix}:R>)"])
            
            if user.premium_since:
                boost_unix = int(user.premium_since.timestamp())
                desc_lines.extend(["", "**Server Booster**", f"<t:{boost_unix}:f> (<t:{boost_unix}:R>)"])
        
        embed.description = "\n".join(desc_lines)
        embed.set_thumbnail(url=user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="serverinfo", description="Display detailed information about this server")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        
        if not guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
            return
        
        created_unix = int(guild.created_at.timestamp())
        owner = guild.owner or await self.bot.fetch_user(guild.owner_id)
        
        embed = create_embed(
            title=guild.name,
            url=f"https://discord.com/channels/{guild.id}",
        )
        
        embed.description = (
            f"ID: {guild.id}\n"
            f"{owner} ({owner.mention})\n\n"
            f"**Server Creation**\n<t:{created_unix}:f> (<t:{created_unix}:R>)\n\n"
            f"**Member Count**\n{guild.member_count}\n\n"
            f"**Server Boost**\n{guild.premium_subscription_count} (Level {guild.premium_tier})\n\n"
            f"**Server Info**\n"
            f"- Text Channels: {len(guild.text_channels)}\n"
            f"- Voice Channels: {len(guild.voice_channels)}\n"
            f"- Categories: {len(guild.categories)}\n"
            f"- Roles: {len(guild.roles) - 1}\n"
            f"- Emojis: {len(guild.emojis)}"
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # AVATAR & BANNER
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="avatar", description="Display a user's profile picture")
    @app_commands.describe(user="The user whose avatar you want to see")
    async def avatar(self, interaction: discord.Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user
        
        embed = create_embed(title=f"{user}'s Avatar")
        embed.set_image(url=user.display_avatar.url)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="banner", description="Display a user's banner")
    @app_commands.describe(user="The user whose banner you want to see")
    async def banner(self, interaction: discord.Interaction, user: discord.User = None):
        if user is None:
            user = interaction.user
        
        try:
            fetched_user = await self.bot.fetch_user(user.id)
        except discord.NotFound:
            await interaction.response.send_message("❌ User not found.", ephemeral=True)
            return
        
        banner_url = fetched_user.banner.url if fetched_user.banner else None
        
        embed = create_embed()
        
        if banner_url:
            embed.set_image(url=banner_url)
        else:
            embed.description = f"**{user.mention} has no banner.**"
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # WEATHER
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="weather", description="Get live weather data")
    @app_commands.describe(city="City name", unit="Temperature unit (default is Celsius)")
    @app_commands.choices(unit=[
        app_commands.Choice(name="Celsius (°C)", value="c"),
        app_commands.Choice(name="Fahrenheit (°F)", value="f"),
    ])
    async def weather(self, interaction: discord.Interaction, city: str, unit: str = "c"):
        api_key = os.getenv("WEATHER_API_KEY")
        
        if not api_key:
            await interaction.response.send_message("❌ Weather API key is missing.", ephemeral=True)
            return
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(
                    f"http://api.weatherapi.com/v1/current.json?key={api_key}&q={city}"
                ) as response:
                    data = await response.json()
            
            if "error" in data:
                await interaction.response.send_message("❌ City not found.", ephemeral=True)
                return
            
            current = data["current"]
            location = data["location"]
            
            temp = current["temp_c"] if unit == "c" else current["temp_f"]
            feels_like = current["feelslike_c"] if unit == "c" else current["feelslike_f"]
            unit_label = "°C" if unit == "c" else "°F"
            
            embed = create_embed(title=f"🌤️ Weather in {location['name']}, {location['region']}, {location['country']}")
            embed.add_field(name="🌡️ Temperature", value=f"{temp}{unit_label}", inline=True)
            embed.add_field(name="🧯 Feels Like", value=f"{feels_like}{unit_label}", inline=True)
            embed.add_field(name="💧 Humidity", value=f"{current['humidity']}%", inline=True)
            embed.add_field(name="🌬️ Wind Speed", value=f"{current['wind_kph']} km/h", inline=True)
            embed.add_field(name="📝 Condition", value=current["condition"]["text"], inline=False)
            embed.set_thumbnail(url=f"https:{current['condition']['icon']}")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)
    
    @weather.autocomplete("city")
    async def city_autocomplete(self, interaction: discord.Interaction, current: str):
        all_cities = PHILIPPINE_CITIES + GLOBAL_CAPITALS
        filtered = [c for c in all_cities if current.lower() in c.lower()]
        return [app_commands.Choice(name=c, value=c) for c in filtered[:25]]
    
    # ══════════════════════════════════════════════════════════════════════════
    # CALCULATOR
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="calculator", description="Perform basic math operations")
    @app_commands.describe(num1="First number", operation="Operation", num2="Second number")
    @app_commands.choices(operation=[
        app_commands.Choice(name="Add (+)", value="add"),
        app_commands.Choice(name="Subtract (-)", value="subtract"),
        app_commands.Choice(name="Multiply (×)", value="multiply"),
        app_commands.Choice(name="Divide (÷)", value="divide"),
    ])
    async def calculator(
        self, 
        interaction: discord.Interaction, 
        num1: float, 
        operation: app_commands.Choice[str], 
        num2: float
    ):
        try:
            if operation.value == "add":
                result, symbol = num1 + num2, "+"
            elif operation.value == "subtract":
                result, symbol = num1 - num2, "-"
            elif operation.value == "multiply":
                result, symbol = num1 * num2, "*"
            elif operation.value == "divide":
                if num2 == 0:
                    await interaction.response.send_message("❌ Cannot divide by zero.", ephemeral=True)
                    return
                result, symbol = num1 / num2, "/"
            
            await interaction.response.send_message(f"🔢 `{num1} {symbol} {num2} = {result}`")
            
        except Exception as e:
            await interaction.response.send_message(f"⚠️ Error: {str(e)}")
    
    # ══════════════════════════════════════════════════════════════════════════
    # PAYMENT
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="payment", description="Show payment instructions")
    @app_commands.describe(method="Choose a payment method")
    @app_commands.choices(method=[
        app_commands.Choice(name="Gcash", value="Gcash"),
        app_commands.Choice(name="PayMaya", value="PayMaya"),
        app_commands.Choice(name="GoTyme", value="GoTyme"),
    ])
    async def payment(self, interaction: discord.Interaction, method: app_commands.Choice[str]):
        info = PAYMENT_INFO[method.value]
        
        embed = create_embed(title=info["title"], description=info["description"])
        
        if info["image"]:
            embed.set_image(url=info["image"])
        
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # STATUS & INVITE
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="status", description="Show bot stats including uptime and system resources")
    async def status(self, interaction: discord.Interaction):
        # System stats
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
        ram = psutil.virtual_memory()
        
        # Uptime
        uptime = datetime.now(PH_TIMEZONE) - self.bot.start_time
        days = uptime.days
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        embed = create_embed()
        embed.add_field(
            name="⌖ __Operating System__",
            value=(
                f"**CPU:** {cpu_percent:.1f}% ({cpu_count} Core @ {int(cpu_freq)}MHz)\n"
                f"**RAM:** {ram.percent:.1f}% ({ram.used / (1024**3):.2f}GB/{ram.total / (1024**3):.2f}GB)"
            ),
            inline=False,
        )
        embed.add_field(
            name="⌖ __Bot Info__",
            value=(
                f"**Servers:** {len(self.bot.guilds):,}\n"
                f"**Members:** {sum(g.member_count for g in self.bot.guilds):,}\n"
                f"**Uptime:** {days}d {hours}h {minutes}m {seconds}s\n"
                f"**Commands ran:** {self.bot.command_count:,}"
            ),
            inline=False,
        )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name="invite", description="Get the invite link for the bot")
    async def invite(self, interaction: discord.Interaction):
        embed = create_embed(
            title="🔗 Invite N Bot",
            description="Click [here](https://discord.com/oauth2/authorize?client_id=1358242947790803084&permissions=8&integration_type=0&scope=bot%20applications.commands) to invite the bot to your server!",
        )
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # MEXC CRYPTO
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="mexc", description="View top cryptocurrencies by 24h trading volume on MEXC exchange")
    async def mexc(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.mexc.com/api/v3/ticker/24hr",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        await interaction.followup.send("❌ Failed to fetch MEXC data.", ephemeral=True)
                        return
                    data = await resp.json()

            usdt_pairs = [
                t for t in data
                if str(t.get("symbol", "")).endswith("USDT") and float(t.get("quoteVolume", 0)) > 0
            ]
            top = sorted(usdt_pairs, key=lambda t: float(t.get("quoteVolume", 0)), reverse=True)[:10]

            embed = create_embed(title="📊 MEXC — Top 10 by 24h Volume")
            embed.description = "Showing top USDT pairs sorted by 24h trading volume.\n\u200b"

            for i, ticker in enumerate(top, 1):
                symbol = ticker["symbol"].replace("USDT", "")
                last_price = float(ticker.get("lastPrice", 0))
                change = float(ticker.get("priceChangePercent", 0))
                volume = float(ticker.get("quoteVolume", 0))

                change_icon = "🟢" if change >= 0 else "🔴"
                change_str = f"{'+' if change >= 0 else ''}{change:.2f}%"

                embed.add_field(
                    name=f"#{i} {symbol}/USDT",
                    value=(
                        f"**Price:** ${last_price:,.4f}\n"
                        f"**24h:** {change_icon} {change_str}\n"
                        f"**Volume:** ${volume:,.0f}"
                    ),
                    inline=True,
                )

            embed.set_footer(text="Powered by MEXC API • Neroniel")

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ Error fetching MEXC data: {str(e)}", ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    # COMMAND LIST
    # ══════════════════════════════════════════════════════════════════════════

    def _build_help_embeds(self) -> list[discord.Embed]:
        categories = {
            "🤖 AI Assistant": [
                "`/ask <prompt>` – Chat with Llama 3 AI",
                "`/clearhistory` – Clear your AI conversation history",
            ],
            "🧱 Roblox Tools": [
                "`/roblox group` – Display Roblox group info",
                "`/roblox profile <user>` – View a player's profile",
                "`/roblox game <id>` – Get game info",
                "`/roblox stocks` – Check Robux balances",
                "`/roblox rate` – Set Roblox group rates (Admin)",
            ],
            "💱 Currency & Conversion": [
                "`/payout <type> <amount>` – Convert Robux ↔ PHP (Payout rate)",
                "`/gift <type> <amount>` – Convert Robux ↔ PHP (Gift rate)",
                "`/nct <type> <amount>` – Convert Robux ↔ PHP (NCT rate)",
                "`/ct <type> <amount>` – Convert Robux ↔ PHP (CT rate)",
                "`/allrates <type> <amount>` – Compare all 4 rates at once",
                "`/setrate` – Update server conversion rates (Admin)",
                "`/resetrate` – Clear saved rates for this server (Admin)",
                "`/convertcurrency <amount> <from> <to>` – Convert real-world currencies",
            ],
            "🛠️ Utility": [
                "`/userinfo [user]` – View Discord account details",
                "`/serverinfo` – Display server stats",
                "`/avatar [user]` – View profile picture",
                "`/banner [user]` – View profile banner",
                "`/weather <city>` – Get live weather data",
                "`/calculator <num1> <op> <num2>` – Basic math",
                "`/payment <method>` – Show payment instructions",
                "`/mexc` – Top 10 cryptos by 24h volume on MEXC",
                "`/status` – Bot health & uptime",
                "`/invite` – Get the bot invite link",
            ],
            "📢 Giveaways": [
                "`/giveaway <prize> <duration> <winners>` – Start a giveaway",
                "`/giveawayend <id>` – End a giveaway early",
                "`/giveawayreroll <id>` – Pick new winners",
            ],
            "📨 Invites": [
                "`/invites [user]` – Check how many members someone has invited",
                "`/invitehistory [user]` – Paginated timestamped log of invited members",
                "`/invitestats` – Server-wide joins, leaves, and net active invite summary",
                "`/inviteleaderboard` – Top 10 inviters in this server",
                "`/adjustinvites <user> <amount>` – Add or remove invites (Admin)",
                "`/resetinvites <user>` – Reset a user's invite count (Admin)",
            ],
            "📱 Social": [
                "`/tiktok <link>` – Convert TikTok link for embedding",
                "`/instagram <link>` – Convert Instagram link for embedding",
                "`/poll <question> <duration>` – Create a timed poll",
                "`/remindme <duration> <note>` – Set a personal reminder",
                "`/snipe` – Recover the last deleted message",
                "`/donate <user> <amount>` – Playfully donate Robux (cosmetic)",
            ],
            "🔧 Admin": [
                "`/purge <amount>` – Bulk-delete messages",
                "`/announcement` – Create a server announcement",
                "`/say <message>` – Make the bot send a message",
                "`/dm <user> <message>` – DM a user (Owner)",
                "`/dmall <message>` – DM all members (Owner)",
                "`/createinvite` – Generate invites for all servers (Owner)",
            ],
        }
        return [
            create_embed(title=title, description="\n".join(cmds))
            for title, cmds in categories.items()
        ]

    @app_commands.command(name="listallcommands", description="Display all available commands")
    async def listallcommands(self, interaction: discord.Interaction):
        embeds = self._build_help_embeds()
        view = CommandPaginator(embeds)
        await interaction.response.send_message(embed=embeds[0], view=view)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        embeds = self._build_help_embeds()
        view = CommandPaginator(embeds)
        await ctx.send(embed=embeds[0], view=view)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        stripped = message.content.strip()
        mentioned_only = (
            stripped == self.bot.user.mention
            or stripped == f"<@!{self.bot.user.id}>"
        )
        if mentioned_only:
            embeds = self._build_help_embeds()
            view = CommandPaginator(embeds)
            await message.channel.send(embed=embeds[0], view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(UtilityCog(bot))
