"""
Conversion Commands Cog
Handles Robux/PHP conversion and currency conversion commands.
"""

import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

from ..config import PH_TIMEZONE, BOT_OWNER_ID, Emojis
from ..database import db
from ..utils import create_embed, format_php, get_current_rates


class ConversionCog(commands.Cog):
    """Robux/PHP conversion commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ══════════════════════════════════════════════════════════════════════════
    # HELPER METHODS
    # ══════════════════════════════════════════════════════════════════════════
    
    def _create_conversion_embed(
        self,
        amount: float,
        result: float,
        is_robux_to_php: bool,
        note: str = None,
    ) -> discord.Embed:
        """Create a standardized conversion embed."""
        embed = create_embed()
        
        if is_robux_to_php:
            embed.add_field(name="Amount:", value=f"{Emojis.ROBUX} {int(amount):,}", inline=False)
            embed.add_field(name="Payment:", value=f"{Emojis.PHP} {format_php(result)}", inline=False)
        else:
            embed.add_field(name="Payment:", value=f"{Emojis.PHP} {format_php(amount)}", inline=False)
            embed.add_field(name="Amount:", value=f"{Emojis.ROBUX} {int(result):,}", inline=False)
        
        if note:
            embed.add_field(name="Note:", value=note, inline=False)
        
        return embed
    
    # ══════════════════════════════════════════════════════════════════════════
    # PAYOUT COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="payout", description="Convert between Robux and PHP using the Payout rate")
    @app_commands.describe(conversion_type="Choose conversion direction", amount="Amount to convert")
    @app_commands.choices(conversion_type=[
        app_commands.Choice(name="Robux to PHP", value="robux_to_php"),
        app_commands.Choice(name="PHP to Robux", value="php_to_robux"),
    ])
    async def payout(
        self, 
        interaction: discord.Interaction, 
        conversion_type: app_commands.Choice[str], 
        amount: float
    ):
        if amount <= 0:
            await interaction.response.send_message("❗ Amount must be greater than zero.", ephemeral=True)
            return

        rates = get_current_rates(str(interaction.guild.id))
        rate = rates["payout"]
        if rate is None:
            await interaction.response.send_message("❌ Payout rate not set. An admin can set it with `/setrate`.", ephemeral=True)
            return

        is_robux_to_php = conversion_type.value == "robux_to_php"
        result = amount * (rate / 1000) if is_robux_to_php else (amount / rate) * 1000

        note = (
            "To be eligible for a payout, you must be a member of the group for at least 14 days. "
            "You can view the Group Link by typing `/roblox group` in the chat."
        )

        embed = self._create_conversion_embed(amount, result, is_robux_to_php, note)
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # GIFT COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="gift", description="Convert Robux ↔ PHP using the InGame Gift rate")
    @app_commands.describe(conversion_type="Choose conversion direction", amount="Amount to convert")
    @app_commands.choices(conversion_type=[
        app_commands.Choice(name="Robux to PHP", value="robux_to_php"),
        app_commands.Choice(name="PHP to Robux", value="php_to_robux"),
    ])
    async def gift(
        self, 
        interaction: discord.Interaction, 
        conversion_type: app_commands.Choice[str], 
        amount: float
    ):
        if amount <= 0:
            await interaction.response.send_message("❗ Amount must be greater than zero.", ephemeral=True)
            return

        rates = get_current_rates(str(interaction.guild.id))
        rate = rates["gift"]
        if rate is None:
            await interaction.response.send_message("❌ Gift rate not set. An admin can set it with `/setrate`.", ephemeral=True)
            return

        is_robux_to_php = conversion_type.value == "robux_to_php"
        result = amount * (rate / 1000) if is_robux_to_php else (amount / rate) * 1000

        embed = self._create_conversion_embed(amount, result, is_robux_to_php)
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # NCT COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="nct", description="Convert Robux ↔ PHP using the Not Covered Tax rate")
    @app_commands.describe(conversion_type="Choose conversion direction", amount="Amount to convert")
    @app_commands.choices(conversion_type=[
        app_commands.Choice(name="Robux to PHP", value="robux_to_php"),
        app_commands.Choice(name="PHP to Robux", value="php_to_robux"),
    ])
    async def nct(
        self, 
        interaction: discord.Interaction, 
        conversion_type: app_commands.Choice[str], 
        amount: float
    ):
        if amount <= 0:
            await interaction.response.send_message("❗ Amount must be greater than zero.", ephemeral=True)
            return

        rates = get_current_rates(str(interaction.guild.id))
        rate = rates["nct"]
        if rate is None:
            await interaction.response.send_message("❌ NCT rate not set. An admin can set it with `/setrate`.", ephemeral=True)
            return

        is_robux_to_php = conversion_type.value == "robux_to_php"
        result = amount * (rate / 1000) if is_robux_to_php else (amount / rate) * 1000

        note = (
            "To proceed with this transaction, you must own the required Gamepass and have Regional Pricing disabled. "
            "You may view the Gamepass details by typing `/roblox gamepass` in the chat."
        )

        embed = self._create_conversion_embed(amount, result, is_robux_to_php, note)
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # CT COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="ct", description="Convert Robux ↔ PHP using the Covered Tax rate")
    @app_commands.describe(conversion_type="Choose conversion direction", amount="Amount to convert")
    @app_commands.choices(conversion_type=[
        app_commands.Choice(name="Robux to PHP", value="robux_to_php"),
        app_commands.Choice(name="PHP to Robux", value="php_to_robux"),
    ])
    async def ct(
        self, 
        interaction: discord.Interaction, 
        conversion_type: app_commands.Choice[str], 
        amount: float
    ):
        if amount <= 0:
            await interaction.response.send_message("❗ Amount must be greater than zero.", ephemeral=True)
            return

        rates = get_current_rates(str(interaction.guild.id))
        rate = rates["ct"]
        if rate is None:
            await interaction.response.send_message("❌ CT rate not set. An admin can set it with `/setrate`.", ephemeral=True)
            return

        is_robux_to_php = conversion_type.value == "robux_to_php"
        result = amount * (rate / 1000) if is_robux_to_php else (amount / rate) * 1000

        note = (
            "To proceed with this transaction, you must own the required Gamepass and have Regional Pricing disabled. "
            "You may view the Gamepass details by typing `/roblox gamepass` in the chat."
        )

        embed = self._create_conversion_embed(amount, result, is_robux_to_php, note)
        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # ALL RATES COMMAND
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="allrates", description="Compare PHP/Robux values across all 4 conversion rates")
    @app_commands.describe(conversion_type="Choose conversion direction", amount="Amount to convert")
    @app_commands.choices(conversion_type=[
        app_commands.Choice(name="Robux to PHP", value="robux_to_php"),
        app_commands.Choice(name="PHP to Robux", value="php_to_robux"),
    ])
    async def allrates(
        self, 
        interaction: discord.Interaction, 
        conversion_type: app_commands.Choice[str], 
        amount: float
    ):
        if amount <= 0:
            await interaction.response.send_message("❗ Amount must be greater than zero.", ephemeral=True)
            return
        
        rates = get_current_rates(str(interaction.guild.id))

        any_set = any(v is not None for v in rates.values())
        if not any_set:
            await interaction.response.send_message("❌ No rates set for this server. An admin can set them with `/setrate`.", ephemeral=True)
            return

        embed = create_embed(title="All Conversion Rates")

        rate_types = [
            ("Payout Rate", rates["payout"]),
            ("Gift Rate",   rates["gift"]),
            ("NCT Rate",    rates["nct"]),
            ("CT Rate",     rates["ct"]),
        ]

        if conversion_type.value == "robux_to_php":
            robux = int(amount)
            embed.description = f"{Emojis.ROBUX} {robux:,} → PHP equivalent across all rates:"
            for label, rate in rate_types:
                val = f"{Emojis.PHP} {format_php((rate / 1000) * robux)}" if rate is not None else "Not Set"
                embed.add_field(name=f"• {label}", value=val, inline=False)
        else:
            php = amount
            embed.description = f"{Emojis.PHP} {format_php(php)} → Robux equivalent across all rates:"
            for label, rate in rate_types:
                val = f"{Emojis.ROBUX} {int((php / rate) * 1000):,}" if rate is not None else "Not Set"
                embed.add_field(name=f"• {label}", value=val, inline=False)

        await interaction.response.send_message(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # SET/RESET RATE COMMANDS
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="setrate", description="Update server-specific conversion rates (Admin only)")
    @app_commands.describe(
        payout_rate="PHP per 1000 Robux for Payout",
        gift_rate="PHP per 1000 Robux for Gift",
        nct_rate="PHP per 1000 Robux for NCT",
        ct_rate="PHP per 1000 Robux for CT",
    )
    async def setrate(
        self,
        interaction: discord.Interaction,
        payout_rate: float = None,
        gift_rate: float = None,
        nct_rate: float = None,
        ct_rate: float = None,
    ):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You must be an administrator.", ephemeral=True)
            return

        if not db.is_connected:
            await interaction.followup.send("❌ Database not connected.", ephemeral=True)
            return

        if all(v is None for v in [payout_rate, gift_rate, nct_rate, ct_rate]):
            await interaction.followup.send("❗ Provide at least one rate to update. Tip: use `/roblox rate` instead.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)

        # Fetch global minimums (set via /roblox rate by bot owner)
        global_doc = db.rates.find_one({"guild_id": "__global__"}) or {}
        mins = {
            "payout_rate": global_doc.get("payout_min"),
            "gift_rate":   global_doc.get("gift_min"),
            "nct_rate":    global_doc.get("nct_min"),
            "ct_rate":     global_doc.get("ct_min"),
        }

        update_fields: dict = {"guild_id": guild_id, "updated_at": datetime.now(PH_TIMEZONE)}
        errors = []

        for label, val, key in [
            ("Payout", payout_rate, "payout_rate"),
            ("Gift",   gift_rate,   "gift_rate"),
            ("NCT",    nct_rate,    "nct_rate"),
            ("CT",     ct_rate,     "ct_rate"),
        ]:
            if val is None:
                continue
            if val <= 0:
                errors.append(f"❗ {label} rate must be greater than 0.")
                continue
            floor = mins.get(key)
            if floor is not None and val < floor:
                errors.append(f"❗ {label} rate **₱{val:.2f}** is below the minimum **₱{floor:.2f}** set by `/roblox rate`.")
                continue
            update_fields[key] = val

        if errors:
            await interaction.followup.send("\n".join(errors), ephemeral=True)
            return

        db.rates.update_one({"guild_id": guild_id}, {"$set": update_fields}, upsert=True)

        embed = create_embed(title="✅ Rates Updated", color=discord.Color.green())
        if payout_rate is not None and "payout_rate" in update_fields:
            embed.add_field(name="• Payout Rate", value=f"₱{payout_rate:.2f} / 1,000 Robux", inline=False)
        if gift_rate is not None and "gift_rate" in update_fields:
            embed.add_field(name="• Gift Rate",   value=f"₱{gift_rate:.2f} / 1,000 Robux", inline=False)
        if nct_rate is not None and "nct_rate" in update_fields:
            embed.add_field(name="• NCT Rate",    value=f"₱{nct_rate:.2f} / 1,000 Robux", inline=False)
        if ct_rate is not None and "ct_rate" in update_fields:
            embed.add_field(name="• CT Rate",     value=f"₱{ct_rate:.2f} / 1,000 Robux", inline=False)

        if not embed.fields:
            await interaction.followup.send("⚠️ No rates were updated (all values were below the minimums).", ephemeral=True)
            return

        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="resetrate", description="Clear saved rates for this server (Admin only)")
    @app_commands.describe(
        payout="Clear Payout rate",
        gift="Clear Gift rate",
        nct="Clear NCT rate",
        ct="Clear CT rate",
    )
    async def resetrate(
        self,
        interaction: discord.Interaction,
        payout: bool = False,
        gift: bool = False,
        nct: bool = False,
        ct: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send("❌ You must be an administrator.", ephemeral=True)
            return

        if not any([payout, gift, nct, ct]):
            await interaction.followup.send("❗ Select at least one rate to clear.", ephemeral=True)
            return

        if not db.is_connected:
            await interaction.followup.send("❌ Database not connected.", ephemeral=True)
            return

        guild_id = str(interaction.guild.id)
        unset_fields = {}
        cleared = []

        if payout:
            unset_fields["payout_rate"] = ""
            cleared.append("Payout")
        if gift:
            unset_fields["gift_rate"] = ""
            cleared.append("Gift")
        if nct:
            unset_fields["nct_rate"] = ""
            cleared.append("NCT")
        if ct:
            unset_fields["ct_rate"] = ""
            cleared.append("CT")

        db.rates.update_one({"guild_id": guild_id}, {"$unset": unset_fields})

        embed = create_embed(
            title="✅ Rates Cleared",
            description=f"Cleared: **{', '.join(cleared)}**\nConversion commands will show \"Not Set\" until rates are updated via `/roblox rate`.",
            color=discord.Color.orange(),
        )

        await interaction.followup.send(embed=embed)
    
    # ══════════════════════════════════════════════════════════════════════════
    # CURRENCY CONVERSION
    # ══════════════════════════════════════════════════════════════════════════
    
    @app_commands.command(name="convertcurrency", description="Convert between real-world currencies")
    @app_commands.describe(
        amount="Amount to convert",
        from_currency="Currency to convert from (e.g., USD)",
        to_currency="Currency to convert to (e.g., PHP)",
    )
    async def convertcurrency(
        self, 
        interaction: discord.Interaction, 
        amount: float,
        from_currency: str, 
        to_currency: str
    ):
        api_key = os.getenv("CURRENCY_API_KEY")
        
        if not api_key:
            await interaction.response.send_message("❌ Currency API key missing.", ephemeral=True)
            return
        
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        try:
            url = f"https://api.currencyapi.com/v3/latest?apikey={api_key}&currencies={to_currency}&base_currency={from_currency}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    data = await response.json()
            
            if "error" in data:
                await interaction.response.send_message(f"❌ API Error: {data['error']['message']}")
                return
            
            if "data" not in data or to_currency not in data["data"]:
                await interaction.response.send_message("❌ Invalid currency code.")
                return
            
            rate = data["data"][to_currency]["value"]
            result = amount * rate
            
            embed = create_embed(title="💱 Currency Conversion")
            embed.add_field(name="📥 Input", value=f"{amount} {from_currency}", inline=False)
            embed.add_field(name="📉 Rate", value=f"1 {from_currency} = {rate:.4f} {to_currency}", inline=False)
            embed.add_field(name="📤 Result", value=f"≈ **{result:.2f} {to_currency}**", inline=False)
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {str(e)}")
    
    @convertcurrency.autocomplete("from_currency")
    @convertcurrency.autocomplete("to_currency")
    async def currency_autocomplete(self, interaction: discord.Interaction, current: str):
        currencies = [
            "USD - US Dollar", "EUR - Euro", "JPY - Japanese Yen",
            "GBP - British Pound", "PHP - Philippine Peso", "AUD - Australian Dollar",
            "CAD - Canadian Dollar", "CHF - Swiss Franc", "CNY - Chinese Yuan",
            "KRW - South Korean Won", "SGD - Singapore Dollar", "INR - Indian Rupee",
            "BRL - Brazilian Real", "RUB - Russian Ruble", "ZAR - South African Rand",
            "MXN - Mexican Peso", "TRY - Turkish Lira", "AED - UAE Dirham",
            "SAR - Saudi Riyal", "THB - Thai Baht", "MYR - Malaysian Ringgit",
            "IDR - Indonesian Rupiah", "PLN - Polish Zloty", "SEK - Swedish Krona",
            "NZD - New Zealand Dollar", "HKD - Hong Kong Dollar", "ARS - Argentine Peso",
            "CLP - Chilean Peso", "EGP - Egyptian Pound",
        ]
        filtered = [c for c in currencies if current.lower() in c.lower()]
        return [app_commands.Choice(name=c, value=c.split(" ")[0]) for c in filtered[:25]]

    # ══════════════════════════════════════════════════════════════════════════
    # FORCE RESET ALL RATES (OWNER ONLY)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="forceresetallrates", description="Wipe ALL saved rate data from every server (Owner only)")
    async def forceresetallrates(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return

        if not db.is_connected:
            await interaction.response.send_message("❌ Database not connected.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            # Fetch global minimums to reset servers back to
            global_doc = db.rates.find_one({"guild_id": "__global__"}) or {}
            reset_fields = {"updated_at": datetime.now(PH_TIMEZONE)}
            unset_fields = {}

            for rate_key, min_key in [
                ("payout_rate", "payout_min"),
                ("gift_rate",   "gift_min"),
                ("nct_rate",    "nct_min"),
                ("ct_rate",     "ct_min"),
            ]:
                if min_key in global_doc:
                    reset_fields[rate_key] = global_doc[min_key]
                else:
                    unset_fields[rate_key] = ""

            update_op = {"$set": reset_fields}
            if unset_fields:
                update_op["$unset"] = unset_fields

            result = db.rates.update_many({"guild_id": {"$ne": "__global__"}}, update_op)

            has_mins = any(k in global_doc for k in ["payout_min", "gift_min", "nct_min", "ct_min"])
            detail = (
                "Active rates have been **reset to the global minimums** set by `/roblox rate`."
                if has_mins else
                "No global minimums found — active rates have been **cleared** (will show \"Not Set\")."
            )
            await interaction.followup.send(
                f"✅ Reset active rates for **{result.modified_count}** server(s).\n{detail}",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)

    # ══════════════════════════════════════════════════════════════════════════
    # VIEW RATES (OWNER ONLY)
    # ══════════════════════════════════════════════════════════════════════════

    @app_commands.command(name="viewrates", description="Display all custom conversion rates saved across servers (Owner only)")
    async def viewrates(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return

        if not db.is_connected:
            await interaction.response.send_message("❌ Database not connected.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            all_rate_docs = list(db.rates.find())
            if not all_rate_docs:
                await interaction.followup.send("📭 No rate data found in the database.", ephemeral=True)
                return

            robux_emoji = "<:robux:1438835687741853709>"
            php_emoji = "<:PHP:1438894048222908416>"
            robux_formatted = "1,000"

            global_doc = next((d for d in all_rate_docs if d.get("guild_id") == "__global__"), {})
            server_docs = [d for d in all_rate_docs if d.get("guild_id") != "__global__"]

            def _fv(doc, key):
                v = doc.get(key)
                return f"{php_emoji} {format_php(v)}" if v is not None else "Not Set"

            def _fmin(key):
                v = global_doc.get(key)
                return f"{php_emoji} {format_php(v)}" if v is not None else "—"

            # Show global minimums first
            if global_doc:
                embed = create_embed(title="🌐 Global Minimum Rates (set by /roblox rate)")
                embed.add_field(name="• Payout Min", value=f"{robux_emoji} {robux_formatted} → {_fmin('payout_min')}", inline=False)
                embed.add_field(name="• Gift Min",   value=f"{robux_emoji} {robux_formatted} → {_fmin('gift_min')}",   inline=False)
                embed.add_field(name="• NCT Min",    value=f"{robux_emoji} {robux_formatted} → {_fmin('nct_min')}",    inline=False)
                embed.add_field(name="• CT Min",     value=f"{robux_emoji} {robux_formatted} → {_fmin('ct_min')}",     inline=False)
                updated_at = global_doc.get("updated_at")
                if updated_at:
                    embed.timestamp = updated_at
                    embed.set_footer(text="Last updated")
                await interaction.followup.send(embed=embed, ephemeral=True)

            # Show per-server rates
            for doc in server_docs:
                try:
                    guild = self.bot.get_guild(int(doc["guild_id"]))
                    guild_name = guild.name if guild else f"Unknown Server ({doc['guild_id']})"
                except Exception:
                    guild_name = f"Unknown Server ({doc.get('guild_id', '?')})"

                embed = create_embed(title=f"📊 {guild_name}")

                for label, rate_key, min_key in [
                    ("Payout", "payout_rate", "payout_min"),
                    ("Gift",   "gift_rate",   "gift_min"),
                    ("NCT",    "nct_rate",    "nct_min"),
                    ("CT",     "ct_rate",     "ct_min"),
                ]:
                    active = _fv(doc, rate_key)
                    floor  = _fmin(min_key)
                    embed.add_field(
                        name=f"• {label} Rate",
                        value=f"{robux_emoji} {robux_formatted} → {active}\n**Min:** {floor}",
                        inline=False,
                    )

                updated_at = doc.get("updated_at")
                if updated_at:
                    embed.timestamp = updated_at
                    embed.set_footer(text="Last updated")

                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ Error: {str(e)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ConversionCog(bot))
