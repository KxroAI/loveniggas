"""
Utility Functions
Helper functions used throughout the bot.
"""

import re
import discord
from datetime import datetime
from typing import Optional
from langdetect import detect, LangDetectException

from .config import PH_TIMEZONE, Emojis
from .database import db


# ══════════════════════════════════════════════════════════════════════════════
# FORMATTING UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def format_php(value: float) -> str:
    """Format PHP value with commas, removing unnecessary decimals."""
    rounded = round(value, 2)
    
    if rounded.is_integer():
        return f"{int(rounded):,}"
    
    whole_part = int(rounded)
    frac_part = rounded - whole_part
    frac_str = f"{frac_part:.2f}".split('.')[1].rstrip('0')
    
    return f"{whole_part:,}.{frac_str}" if frac_str else f"{whole_part:,}"


def format_number(n: float) -> str:
    """Format number cleanly, removing trailing .0 or .0000."""
    if isinstance(n, float) and n.is_integer():
        return f"{int(n):,}"
    return f"{n:,.4f}".rstrip('0').rstrip('.')


def clean_text_for_match(text: str) -> str:
    """Keep only alphanumeric and spaces, then lowercase."""
    return re.sub(r'[^a-z0-9\s]', '', text.lower())


# ══════════════════════════════════════════════════════════════════════════════
# DURATION PARSING
# ══════════════════════════════════════════════════════════════════════════════

def parse_duration(duration_str: str) -> int:
    """
    Parse duration string to seconds.
    Supports: 30s, 10m, 2h, 1d
    """
    duration_str = duration_str.strip().lower()
    
    match = re.match(r'^(\d+)([smhd])$', duration_str)
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")
    
    value = int(match.group(1))
    unit = match.group(2)
    
    multipliers = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}
    return value * multipliers[unit]


# ══════════════════════════════════════════════════════════════════════════════
# LANGUAGE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

LANGUAGE_INSTRUCTIONS = {
    "tl": "Please respond in Tagalog.",
    "es": "Por favor responde en español.",
    "fr": "Veuillez répondre en français.",
    "ja": "日本語で答えてください。",
    "ko": "한국어로 답변해 주세요.",
    "zh": "请用中文回答。",
    "ru": "Пожалуйста, отвечайте на русском языке。",
    "ar": "من فضلك أجب بالعربية。",
    "vi": "Vui lòng trả lời bằng tiếng Việt.",
    "th": "กรุณาตอบเป็นภาษาไทย",
    "id": "Silakan jawab dalam bahasa Indonesia",
}


def get_language_instruction(text: str) -> str:
    """Detect language and return appropriate instruction."""
    try:
        detected = detect(text)
        return LANGUAGE_INSTRUCTIONS.get(detected, "")
    except LangDetectException:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# RATES MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def get_current_rates(guild_id: str) -> dict:
    """
    Get conversion rates for a guild from DB.
    Priority: server active rate → global minimum (set via /roblox rate) → None.
    """
    empty = {"payout": None, "gift": None, "nct": None, "ct": None}

    if not db.is_connected or db.rates is None:
        return empty

    server_doc = db.rates.find_one({"guild_id": str(guild_id)}) or {}
    global_doc = db.rates.find_one({"guild_id": "__global__"}) or {}

    def _resolve(rate_key, min_key):
        return server_doc.get(rate_key) or global_doc.get(min_key) or None

    return {
        "payout": _resolve("payout_rate", "payout_min"),
        "gift":   _resolve("gift_rate",   "gift_min"),
        "nct":    _resolve("nct_rate",    "nct_min"),
        "ct":     _resolve("ct_rate",     "ct_min"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# EMBED HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def create_embed(
    title: Optional[str] = None,
    description: Optional[str] = None,
    color: discord.Color = None,
    url: Optional[str] = None,
) -> discord.Embed:
    """Create a standard embed with consistent styling."""
    if color is None:
        color = discord.Color.from_rgb(0, 0, 0)
    
    embed = discord.Embed(title=title, description=description, color=color, url=url)
    embed.set_footer(text="Neroniel")
    embed.timestamp = datetime.now(PH_TIMEZONE)
    
    return embed


def create_error_embed(message: str) -> discord.Embed:
    """Create an error embed."""
    return create_embed(
        title="❌ Error",
        description=message,
        color=discord.Color.red(),
    )


def create_success_embed(message: str) -> discord.Embed:
    """Create a success embed."""
    return create_embed(
        title="✅ Success",
        description=message,
        color=discord.Color.green(),
    )


# ══════════════════════════════════════════════════════════════════════════════
# PERMISSION CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def is_admin_or_owner(interaction: discord.Interaction, owner_id: int) -> bool:
    """Check if user is admin or bot owner."""
    if interaction.user.id == owner_id:
        return True
    if interaction.user.guild_permissions.administrator:
        return True
    return False


def has_manage_guild(interaction: discord.Interaction, owner_id: int) -> bool:
    """Check if user has manage guild permission or is bot owner."""
    if interaction.user.id == owner_id:
        return True
    if interaction.user.guild_permissions.manage_guild:
        return True
    return False
