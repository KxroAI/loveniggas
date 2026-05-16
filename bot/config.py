"""
Bot Configuration
Central configuration file for all constants, emojis, and settings.
"""

import os
from dotenv import load_dotenv
import pytz

load_dotenv()

# ══════════════════════════════════════════════════════════════════════════════
# TIMEZONE
# ══════════════════════════════════════════════════════════════════════════════
PH_TIMEZONE = pytz.timezone("Asia/Manila")

# ══════════════════════════════════════════════════════════════════════════════
# BOT SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
BOT_PREFIX = "!"
BOT_NAME = "Neroniel"
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
LOG_CHANNEL_ID = 1492164409240457446

# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM EMOJIS
# ══════════════════════════════════════════════════════════════════════════════
class Emojis:
    ROBUX = "<:robux:1438835687741853709>"
    PHP = "<:PHP:1438894048222908416>"
    VERIFIED = "<:RobloxVerified:1400310297184702564>"
    UNVERIFIED = "<:Unverified:1446796507931082906>"
    PREMIUM = "<:RobloxPlus:1499454821642666084>"

# ══════════════════════════════════════════════════════════════════════════════
# ROBLOX GROUP IDS
# ══════════════════════════════════════════════════════════════════════════════
ROBLOX_GROUPS = {
    "1cy": {"id": 5838002, "cookie_env": "ROBLOX_COOKIE", "label": "1cy"},
    "mc": {"id": 1081179215, "cookie_env": "ROBLOX_COOKIE2", "label": "Modded Corporations"},
    "sb": {"id": 35341321, "cookie_env": "ROBLOX_COOKIE2", "label": "Sheboyngo"},
    "bsm": {"id": 42939987, "cookie_env": "ROBLOX_COOKIE2", "label": "Brazilian Spyder Market"},
    "mpg": {"id": 365820076, "cookie_env": "ROBLOX_COOKIE2", "label": "MPG Studios"},
    "cd": {"id": 7411911, "cookie_env": "ROBLOX_COOKIE2", "label": "Content Deleted"},
    "neroniel": {"id": 11136234, "cookie_env": "ROBLOX_COOKIE", "label": "Neroniel"},
}

ALL_GROUP_IDS = [5838002, 1081179215, 35341321, 42939987, 365820076, 7411911, 11136234]

# ══════════════════════════════════════════════════════════════════════════════
# CITIES FOR WEATHER
# ══════════════════════════════════════════════════════════════════════════════
PHILIPPINE_CITIES = [
    "Manila", "Quezon City", "Caloocan", "Las Piñas", "Makati", "Malabon",
    "Navotas", "Paranaque", "Pasay", "Muntinlupa", "Taguig", "Valenzuela",
    "Marikina", "Pasig", "San Juan", "Cavite", "Cebu", "Davao", "Iloilo",
    "Baguio", "Zamboanga", "Angeles", "Bacolod", "Batangas", "Cagayan de Oro",
    "Cebu City", "Davao City", "General Santos", "Iligan", "Kalibo",
    "Lapu-Lapu City", "Lucena", "Mandaue", "Olongapo", "Ormoc", "Oroquieta",
    "Ozamiz", "Palawan", "Puerto Princesa", "Roxas City", "San Pablo", "Silay",
]

GLOBAL_CAPITALS = [
    "Washington D.C.", "London", "Paris", "Berlin", "Rome", "Moscow",
    "Beijing", "Tokyo", "Seoul", "New Delhi", "Islamabad", "Canberra",
    "Ottawa", "Brasilia", "Cairo", "Nairobi", "Pretoria", "Kuala Lumpur",
    "Jakarta", "Bangkok", "Hanoi", "Athens", "Vienna", "Stockholm", "Oslo",
    "Copenhagen", "Helsinki", "Dublin", "Warsaw", "Prague", "Madrid",
    "Amsterdam", "Brussels", "Bern", "Wellington", "Santiago", "Buenos Aires",
    "Abu Dhabi", "Doha", "Riyadh", "Kuwait City", "Muscat", "Manama",
    "Shanghai", "Sydney", "Melbourne",
]

# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT INFO
# ══════════════════════════════════════════════════════════════════════════════
PAYMENT_INFO = {
    "Gcash": {
        "title": "Gcash Payment",
        "description": "Account Initials: M R G.\nAccount Number: `09550333612`",
        "image": "https://raw.githubusercontent.com/KxroAI/whatupmyniggga/c52d0cb1f626fd55d24a6181fd3821c9dd9f1455/IMG_2868.jpeg",
    },
    "PayMaya": {
        "title": "PayMaya Payment",
        "description": "Account Initials: N G.\nAccount Number: `09550333612`",
        "image": "https://raw.githubusercontent.com/KxroAI/whatupmyniggga/refs/heads/main/IMG_2869.jpeg",
    },
    "GoTyme": {
        "title": "GoTyme Payment",
        "description": "Account Initials: N G.\nAccount Number: HIDDEN",
        "image": "https://raw.githubusercontent.com/KxroAI/whatupmyniggga/refs/heads/main/IMG_2870.jpeg",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# ROBLOX ASSET TYPE MAP
# ══════════════════════════════════════════════════════════════════════════════
ASSET_TYPE_MAP = {
    1: "Image",
    2: "T-Shirt",
    3: "Audio",
    4: "Mesh",
    5: "Lua",
    6: "HTML",
    7: "Text",
    8: "Hat",
    9: "Place",
    10: "Model",
    11: "Shirt",
    12: "Pants",
    13: "Decal",
    16: "Avatar",
    17: "Head",
    18: "Face",
    19: "Gear",
    21: "Badge",
    22: "Group Emblem",
    24: "Animation",
    25: "Arms",
    26: "Legs",
    27: "Torso",
    28: "Right Arm",
    29: "Left Arm",
    30: "Left Leg",
    31: "Right Leg",
    32: "Package",
    33: "YouTubeVideo",
    34: "Pass",
    35: "App",
    37: "Code",
    38: "Plugin",
    39: "SolidModel",
    40: "MeshPart",
    41: "Hair Accessory",
    42: "Face Accessory",
    43: "Neck Accessory",
    44: "Shoulder Accessory",
    45: "Front Accessory",
    46: "Back Accessory",
    47: "Waist Accessory",
    48: "Climb Animation",
    49: "Death Animation",
    50: "Fall Animation",
    51: "Idle Animation",
    52: "Jump Animation",
    53: "Run Animation",
    54: "Swim Animation",
    55: "Walk Animation",
    56: "Pose Animation",
    59: "LocalizationTableManifest",
    60: "LocalizationTableTranslation",
    61: "Emote Animation",
    62: "Video",
    63: "TexturePack",
    64: "T-Shirt Accessory",
    65: "Shirt Accessory",
    66: "Pants Accessory",
    67: "Jacket Accessory",
    68: "Sweater Accessory",
    69: "Shorts Accessory",
    70: "Left Shoe Accessory",
    71: "Right Shoe Accessory",
    72: "Dress Skirt Accessory",
    73: "Font Family",
    74: "Font Face",
    75: "MeshHiddenSurfaceRemoval"
}
