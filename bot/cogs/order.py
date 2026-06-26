"""
Order Commands Cog
Customizable order processing with setup wizard (stickypin style).
Commands: /order setup, /order premium, /order discord, /order qr, /order queue
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import commands

from ..config import BOT_OWNER_ID, PH_TIMEZONE
from ..database import db


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    return False


def _parse_color(raw: str) -> int:
    try:
        return int(raw.strip().lstrip("#"), 16)
    except Exception:
        return 0x5865F2


def _apply_ph(text: str, data: dict) -> str:
    for k, v in data.items():
        text = text.replace(f"{{{k}}}", str(v))
    return text


def _is_valid_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


ORDER_TYPE_LABELS = {
    "premium": "💎 Premium",
    "discord": "💬 Discord",
    "qr":      "📱 QR",
    "queue":   "📋 Queue",
}

PLACEHOLDERS_HINT = (
    "`{buyer}` `{item}` `{amount}` `{username}` `{email}` `{password}` `{profile}` `{order}` `{content}`"
)

_CONFIG_DEFAULTS: dict = {
    # Confirmation message
    "confirm_msg_type":     "embed",
    "confirm_content":      "",
    "confirm_embed_title":  "order confirmation 🎫",
    "confirm_embed_desc":   "⚜ buyer: **{buyer}**\n⚜ item: **{item}**\n⚜ amount: **{amount}**",
    "confirm_embed_color":  0x5865F2,
    "confirm_embed_footer": "",
    "confirm_image_url":    "",
    "confirm_ephemeral":    False,
    # Confirm buttons (trigger followup + DM)
    "confirm_buttons":      [{"label": "confirm order"}],
    # Follow-up messages
    "followup_messages":    [],
    "followup_buttons":     [],
    "followup_ephemeral":   False,
    # DM to buyer
    "dm_msg_type":          "",
    "dm_content":           "",
    "dm_embed_title":       "",
    "dm_embed_desc":        "",
    "dm_embed_color":       0x57F287,
    "dm_embed_footer":      "",
    "dm_image_url":         "",
    "dm_buttons":           [],
    "dm_failed_msg":        "⚠️ {buyer} DMs are closed — please send payment details manually.",
}


# ══════════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _load_cfg(guild_id: int, order_type: str) -> dict:
    cfg = dict(_CONFIG_DEFAULTS)
    cfg["guild_id"]   = guild_id
    cfg["order_type"] = order_type
    if not db.is_connected or db.order_configs is None:
        return cfg
    doc = db.order_configs.find_one({"guild_id": guild_id, "order_type": order_type, "_doc_type": {"$ne": "order_instance"}})
    if doc:
        doc.pop("_id", None)
        cfg.update(doc)
    return cfg


def _save_cfg(cfg: dict) -> None:
    if not db.is_connected or db.order_configs is None:
        return
    db.order_configs.update_one(
        {"guild_id": cfg["guild_id"], "order_type": cfg["order_type"], "_doc_type": {"$ne": "order_instance"}},
        {"$set": cfg},
        upsert=True,
    )


def _save_order(order_id: str, guild_id: int, order_type: str, buyer_id: int, ph: dict) -> None:
    if not db.is_connected or db.order_configs is None:
        return
    db.order_configs.update_one(
        {"_order_id": order_id},
        {"$set": {
            "_order_id":  order_id,
            "_doc_type":  "order_instance",
            "guild_id":   guild_id,
            "order_type": order_type,
            "buyer_id":   buyer_id,
            "ph":         ph,
            "confirmed":  False,
            "created_at": datetime.now(PH_TIMEZONE),
        }},
        upsert=True,
    )


def _load_order(order_id: str) -> Optional[dict]:
    if not db.is_connected or db.order_configs is None:
        return None
    return db.order_configs.find_one({"_order_id": order_id, "_doc_type": "order_instance"})


def _mark_order_confirmed(order_id: str) -> None:
    if not db.is_connected or db.order_configs is None:
        return
    db.order_configs.update_one({"_order_id": order_id}, {"$set": {"confirmed": True}})


# ══════════════════════════════════════════════════════════════════════════════
# BUILD DISCORD OBJECTS FROM CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def _build_embed(
    title: str,
    description: str,
    color: int,
    footer: str,
    image_url: str,
    ph: dict,
) -> discord.Embed:
    """Create a discord.Embed applying placeholders and optional image."""
    e = discord.Embed(
        title=_apply_ph(title, ph) or None,
        description=_apply_ph(description, ph) or None,
        color=color,
    )
    f = _apply_ph(footer, ph)
    if f:
        e.set_footer(text=f)
    img = _apply_ph(image_url, ph).strip()
    if img and _is_valid_url(img):
        e.set_image(url=img)
    return e


def _make_text_embed_with_image(content: str, image_url: str, ph: dict) -> discord.Embed:
    """For plain-text messages with an image — wrap in a minimal embed."""
    e = discord.Embed(description=_apply_ph(content, ph) or None, color=0x2b2d31)
    img = _apply_ph(image_url, ph).strip()
    if img and _is_valid_url(img):
        e.set_image(url=img)
    return e


def _build_link_view(buttons: list[dict]) -> Optional[discord.ui.View]:
    if not buttons:
        return None
    v = discord.ui.View(timeout=None)
    for b in buttons:
        v.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=b["label"], url=b["url"]))
    return v


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD STATE
# ══════════════════════════════════════════════════════════════════════════════

class SetupState:
    def __init__(self, guild_id: int, order_type: str):
        self.guild_id   = guild_id
        self.order_type = order_type
        self.cfg        = _load_cfg(guild_id, order_type)


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — MAIN MENU
# ══════════════════════════════════════════════════════════════════════════════

def _main_menu_embed() -> discord.Embed:
    e = discord.Embed(
        title="🛒 Order Setup",
        description=(
            "Configure order messages, buttons, images, and DMs for each order type.\n"
            "Choose an order type below to start configuring."
        ),
        color=0x5865F2,
    )
    e.add_field(name="💎 Premium", value="Netflix, Spotify, etc.", inline=True)
    e.add_field(name="💬 Discord", value="Discord server orders",  inline=True)
    e.add_field(name="📱 QR",      value="QR / Roblox orders",     inline=True)
    e.add_field(name="📋 Queue",   value="Queue orders",           inline=True)
    e.set_footer(text="Select an order type to configure")
    return e


class MainMenuView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        sel = ui.Select(
            placeholder="Select order type to configure…",
            options=[
                discord.SelectOption(label="Premium", value="premium", emoji="💎"),
                discord.SelectOption(label="Discord", value="discord", emoji="💬"),
                discord.SelectOption(label="QR",      value="qr",      emoji="📱"),
                discord.SelectOption(label="Queue",   value="queue",   emoji="📋"),
            ],
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        order_type = interaction.data["values"][0]
        state = SetupState(interaction.guild.id, order_type)
        await interaction.response.edit_message(embed=_step1_embed(state), view=Step1ConfirmMsgView(state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — STEP 1: CONFIRMATION MESSAGE  (type + image + ephemeral)
# ══════════════════════════════════════════════════════════════════════════════

def _step1_embed(state: SetupState) -> discord.Embed:
    cfg      = state.cfg
    label    = ORDER_TYPE_LABELS.get(state.order_type, state.order_type)
    msg_type = cfg.get("confirm_msg_type", "embed")
    image    = cfg.get("confirm_image_url", "") or "*(none)*"
    ephemeral = cfg.get("confirm_ephemeral", False)
    e = discord.Embed(
        title=f"🛒 Setup {label} — Step 1 of 5",
        description=(
            "**Confirmation Message**\n"
            "Posted in the channel when the order command is run.\n\n"
            f"**Placeholders:** {PLACEHOLDERS_HINT}\n\n"
            f"**Current type:** `{msg_type}`\n"
            f"**Image/GIF URL:** {image}\n"
            f"**Ephemeral:** {'🔒 ON (only command runner sees it)' if ephemeral else '🔓 OFF (visible to everyone)'}"
        ),
        color=0x5865F2,
    )
    e.set_footer(text="Step 1 / 5 • Confirmation Message")
    return e


# ── Modals ─────────────────────────────────────────────────────────────────────

class TextConfirmModal(ui.Modal, title="📝 Confirmation — Text Message"):
    content   = ui.TextInput(label="Message Content", placeholder="⚜ buyer: {buyer}\n⚜ item: {item}", style=discord.TextStyle.paragraph, max_length=2000, required=True)
    image_url = ui.TextInput(label="Image / GIF URL (optional)", placeholder="https://…", required=False, max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog
        if state.cfg.get("confirm_content"):
            self.content.default   = state.cfg["confirm_content"]
        if state.cfg.get("confirm_image_url"):
            self.image_url.default = state.cfg["confirm_image_url"]

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg["confirm_msg_type"]  = "text"
        self.state.cfg["confirm_content"]   = self.content.value.strip()
        self.state.cfg["confirm_image_url"] = self.image_url.value.strip()
        await interaction.response.edit_message(embed=_step1_embed(self.state), view=Step1ConfirmMsgView(self.state, self.cog))


class EmbedConfirmModal(ui.Modal, title="🎨 Confirmation — Embed Message"):
    title_in    = ui.TextInput(label="Title",                     placeholder="order confirmation 🎫",                                  max_length=256,  required=True)
    description = ui.TextInput(label="Description",               placeholder="⚜ buyer: {buyer}\n⚜ item: {item}\n⚜ amount: {amount}", style=discord.TextStyle.paragraph, max_length=4000, required=True)
    footer      = ui.TextInput(label="Footer (optional)",                                                                                required=False,  max_length=2048)
    color       = ui.TextInput(label="Color hex (e.g. #5865F2)", default="#5865F2",                                                      required=False,  max_length=9)
    image_url   = ui.TextInput(label="Image / GIF URL (optional)", placeholder="https://…",                                              required=False,  max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog
        cfg = state.cfg
        if cfg.get("confirm_embed_title"):  self.title_in.default    = cfg["confirm_embed_title"]
        if cfg.get("confirm_embed_desc"):   self.description.default = cfg["confirm_embed_desc"]
        if cfg.get("confirm_embed_footer"): self.footer.default      = cfg["confirm_embed_footer"]
        if cfg.get("confirm_image_url"):    self.image_url.default   = cfg["confirm_image_url"]
        self.color.default = f"#{cfg.get('confirm_embed_color', 0x5865F2):06X}"

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.state.cfg
        cfg["confirm_msg_type"]     = "embed"
        cfg["confirm_embed_title"]  = self.title_in.value.strip()
        cfg["confirm_embed_desc"]   = self.description.value.strip()
        cfg["confirm_embed_footer"] = self.footer.value.strip()
        cfg["confirm_embed_color"]  = _parse_color(self.color.value)
        cfg["confirm_image_url"]    = self.image_url.value.strip()
        await interaction.response.edit_message(embed=_step1_embed(self.state), view=Step1ConfirmMsgView(self.state, self.cog))


# ── Step 1 View ────────────────────────────────────────────────────────────────

class Step1ConfirmMsgView(ui.View):
    def __init__(self, state: SetupState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog

        sel = ui.Select(
            placeholder="Set message type (Text or Embed)…",
            options=[
                discord.SelectOption(label="Text",  value="text",  emoji="📝", description="Plain text + optional image"),
                discord.SelectOption(label="Embed", value="embed", emoji="🎨", description="Rich embed with image support"),
            ],
            row=0,
        )
        sel.callback = self._on_type_select
        self.add_item(sel)

        eph_label = "🔒 Ephemeral: ON" if state.cfg.get("confirm_ephemeral") else "🔓 Ephemeral: OFF"
        eph_btn = ui.Button(label=eph_label, style=discord.ButtonStyle.secondary, row=1)
        eph_btn.callback = self._toggle_ephemeral
        self.add_item(eph_btn)

        back = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

        nxt = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        nxt.callback = self._next
        self.add_item(nxt)

    async def _on_type_select(self, interaction: discord.Interaction):
        if interaction.data["values"][0] == "text":
            await interaction.response.send_modal(TextConfirmModal(self.state, self.cog))
        else:
            await interaction.response.send_modal(EmbedConfirmModal(self.state, self.cog))

    async def _toggle_ephemeral(self, interaction: discord.Interaction):
        self.state.cfg["confirm_ephemeral"] = not self.state.cfg.get("confirm_ephemeral", False)
        await interaction.response.edit_message(embed=_step1_embed(self.state), view=Step1ConfirmMsgView(self.state, self.cog))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(self.cog))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step2_embed(self.state), view=Step2ConfirmButtonsView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — STEP 2: CONFIRM BUTTONS
# ══════════════════════════════════════════════════════════════════════════════

def _step2_embed(state: SetupState) -> discord.Embed:
    btns     = state.cfg.get("confirm_buttons", [])
    btn_list = "\n".join(f"• **{b['label']}**" for b in btns) if btns else "*No buttons — at least 1 required*"
    e = discord.Embed(
        title="🛒 Setup — Step 2 of 5",
        description=(
            "**Confirm Buttons**\n"
            "Shown on the confirmation message.\n"
            "When clicked by admin/mod → triggers follow-up messages and DMs the buyer.\n\n"
            f"**Buttons ({len(btns)}/5):**\n{btn_list}"
        ),
        color=0x5865F2,
    )
    e.set_footer(text="Step 2 / 5 • Confirm Buttons")
    return e


class AddConfirmButtonModal(ui.Modal, title="➕ Add Confirm Button"):
    label = ui.TextInput(label="Button Label", placeholder="e.g. confirm order", max_length=80, required=True)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg.setdefault("confirm_buttons", [])
        self.state.cfg["confirm_buttons"].append({"label": self.label.value.strip()})
        await interaction.response.edit_message(embed=_step2_embed(self.state), view=Step2ConfirmButtonsView(self.state, self.cog))


class Step2ConfirmButtonsView(ui.View):
    def __init__(self, state: SetupState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog
        sel = ui.Select(
            placeholder="Button actions…",
            options=[
                discord.SelectOption(label="Add Button",        value="add",   emoji="➕"),
                discord.SelectOption(label="Clear All Buttons", value="clear", emoji="🗑️"),
            ],
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)
        back = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)
        nxt = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        nxt.callback = self._next
        self.add_item(nxt)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.data["values"][0] == "add":
            if len(self.state.cfg.get("confirm_buttons", [])) >= 5:
                await interaction.response.send_message("❌ Maximum 5 buttons.", ephemeral=True)
                return
            await interaction.response.send_modal(AddConfirmButtonModal(self.state, self.cog))
        else:
            self.state.cfg["confirm_buttons"] = []
            await interaction.response.edit_message(embed=_step2_embed(self.state), view=Step2ConfirmButtonsView(self.state, self.cog))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step1_embed(self.state), view=Step1ConfirmMsgView(self.state, self.cog))

    async def _next(self, interaction: discord.Interaction):
        if not self.state.cfg.get("confirm_buttons"):
            self.state.cfg["confirm_buttons"] = [{"label": "confirm order"}]
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — STEP 3: FOLLOW-UP MESSAGES  (image + ephemeral)
# ══════════════════════════════════════════════════════════════════════════════

def _step3_embed(state: SetupState) -> discord.Embed:
    msgs       = state.cfg.get("followup_messages", [])
    ephemeral  = state.cfg.get("followup_ephemeral", False)

    def _preview(m: dict) -> str:
        t   = m.get("type", "text")
        raw = m.get("embed_title") or m.get("content", "") or ""
        img = " 🖼️" if m.get("image_url") else ""
        short = raw[:55] + ("…" if len(raw) > 55 else "")
        return f"{'Embed' if t == 'embed' else 'Text'}{img}: {short}"

    msg_list = "\n".join(f"• **{i+1}.** {_preview(m)}" for i, m in enumerate(msgs)) if msgs else "*No follow-up messages yet*"
    e = discord.Embed(
        title="🛒 Setup — Step 3 of 5",
        description=(
            "**Follow-up Messages**\n"
            "Posted when a confirm button is clicked. Each can have its own image/GIF.\n"
            f"Placeholders: {PLACEHOLDERS_HINT}\n\n"
            f"**Ephemeral:** {'🔒 ON (only button-clicker sees them)' if ephemeral else '🔓 OFF (visible to everyone)'}\n\n"
            f"**Messages ({len(msgs)}/5):**\n{msg_list}"
        ),
        color=0x5865F2,
    )
    e.set_footer(text="Step 3 / 5 • Follow-up Messages")
    return e


class AddFollowupTextModal(ui.Modal, title="📝 Follow-up — Text Message"):
    content   = ui.TextInput(label="Message Content", placeholder="{buyer}\n\nWHERE TO PAY?…", style=discord.TextStyle.paragraph, max_length=2000, required=True)
    image_url = ui.TextInput(label="Image / GIF URL (optional)", placeholder="https://…", required=False, max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg.setdefault("followup_messages", [])
        self.state.cfg["followup_messages"].append({
            "type":      "text",
            "content":   self.content.value.strip(),
            "image_url": self.image_url.value.strip(),
        })
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))


class AddFollowupEmbedModal(ui.Modal, title="🎨 Follow-up — Embed Message"):
    title_in    = ui.TextInput(label="Title (optional)",           required=False, max_length=256)
    description = ui.TextInput(label="Description",                style=discord.TextStyle.paragraph, max_length=4000, required=True)
    footer      = ui.TextInput(label="Footer (optional)",          required=False, max_length=2048)
    color       = ui.TextInput(label="Color hex",                  default="#5865F2", required=False, max_length=9)
    image_url   = ui.TextInput(label="Image / GIF URL (optional)", placeholder="https://…", required=False, max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg.setdefault("followup_messages", [])
        self.state.cfg["followup_messages"].append({
            "type":         "embed",
            "content":      "",
            "embed_title":  self.title_in.value.strip(),
            "embed_desc":   self.description.value.strip(),
            "embed_footer": self.footer.value.strip(),
            "embed_color":  _parse_color(self.color.value),
            "image_url":    self.image_url.value.strip(),
        })
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))


class Step3FollowupMsgsView(ui.View):
    def __init__(self, state: SetupState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog

        sel = ui.Select(
            placeholder="Add follow-up messages…",
            options=[
                discord.SelectOption(label="Add Text Message",  value="add_text",  emoji="📝"),
                discord.SelectOption(label="Add Embed Message", value="add_embed", emoji="🎨"),
                discord.SelectOption(label="Clear All",         value="clear",     emoji="🗑️"),
            ],
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)

        eph_label = "🔒 Ephemeral: ON" if state.cfg.get("followup_ephemeral") else "🔓 Ephemeral: OFF"
        eph_btn = ui.Button(label=eph_label, style=discord.ButtonStyle.secondary, row=1)
        eph_btn.callback = self._toggle_ephemeral
        self.add_item(eph_btn)

        back = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)
        nxt = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        nxt.callback = self._next
        self.add_item(nxt)

    async def _on_select(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]
        if choice == "clear":
            self.state.cfg["followup_messages"] = []
            await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))
        elif len(self.state.cfg.get("followup_messages", [])) >= 5:
            await interaction.response.send_message("❌ Maximum 5 follow-up messages.", ephemeral=True)
        elif choice == "add_text":
            await interaction.response.send_modal(AddFollowupTextModal(self.state, self.cog))
        else:
            await interaction.response.send_modal(AddFollowupEmbedModal(self.state, self.cog))

    async def _toggle_ephemeral(self, interaction: discord.Interaction):
        self.state.cfg["followup_ephemeral"] = not self.state.cfg.get("followup_ephemeral", False)
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step2_embed(self.state), view=Step2ConfirmButtonsView(self.state, self.cog))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step4_embed(self.state), view=Step4FollowupButtonsView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — STEP 4: FOLLOW-UP URL BUTTONS
# ══════════════════════════════════════════════════════════════════════════════

def _step4_embed(state: SetupState) -> discord.Embed:
    btns     = state.cfg.get("followup_buttons", [])
    btn_list = "\n".join(f"• **{b['label']}** → {b['url']}" for b in btns) if btns else "*No follow-up buttons yet*"
    e = discord.Embed(
        title="🛒 Setup — Step 4 of 5",
        description=(
            "**Follow-up URL Buttons**\n"
            "Link buttons shown on the last follow-up message.\n"
            "Use these for payment links, etc.\n\n"
            f"**Buttons ({len(btns)}/5):**\n{btn_list}"
        ),
        color=0x5865F2,
    )
    e.set_footer(text="Step 4 / 5 • Follow-up URL Buttons")
    return e


class AddFollowupButtonModal(ui.Modal, title="➕ Add Follow-up URL Button"):
    label = ui.TextInput(label="Button Label", max_length=80,  required=True)
    url   = ui.TextInput(label="URL",           max_length=512, required=True, placeholder="https://…")

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        if not _is_valid_url(url):
            await interaction.response.send_message("❌ URL must start with http:// or https://", ephemeral=True)
            return
        self.state.cfg.setdefault("followup_buttons", [])
        self.state.cfg["followup_buttons"].append({"label": self.label.value.strip(), "url": url})
        await interaction.response.edit_message(embed=_step4_embed(self.state), view=Step4FollowupButtonsView(self.state, self.cog))


class Step4FollowupButtonsView(ui.View):
    def __init__(self, state: SetupState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog
        sel = ui.Select(
            placeholder="Add follow-up URL buttons…",
            options=[
                discord.SelectOption(label="Add URL Button",    value="add",   emoji="➕"),
                discord.SelectOption(label="Clear All Buttons", value="clear", emoji="🗑️"),
            ],
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)
        back = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)
        nxt = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        nxt.callback = self._next
        self.add_item(nxt)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.data["values"][0] == "clear":
            self.state.cfg["followup_buttons"] = []
            await interaction.response.edit_message(embed=_step4_embed(self.state), view=Step4FollowupButtonsView(self.state, self.cog))
        elif len(self.state.cfg.get("followup_buttons", [])) >= 5:
            await interaction.response.send_message("❌ Maximum 5 URL buttons.", ephemeral=True)
        else:
            await interaction.response.send_modal(AddFollowupButtonModal(self.state, self.cog))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3FollowupMsgsView(self.state, self.cog))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD — STEP 5: DM MESSAGE  (image + no ephemeral — DMs are already private)
# ══════════════════════════════════════════════════════════════════════════════

def _step5_embed(state: SetupState) -> discord.Embed:
    cfg      = state.cfg
    dm_type  = cfg.get("dm_msg_type", "")
    dm_btns  = cfg.get("dm_buttons", [])
    btn_list = "\n".join(f"• **{b['label']}** → {b['url']}" for b in dm_btns) if dm_btns else "*None*"
    image    = cfg.get("dm_image_url", "") or "*(none)*"

    if dm_type == "embed":
        preview = cfg.get("dm_embed_title", "") or "*(no title)*"
    elif dm_type == "text":
        raw = cfg.get("dm_content", "")
        preview = raw[:80] + ("…" if len(raw) > 80 else "")
    else:
        preview = "*(no DM — buyer will not be DM'd)*"

    failed_raw  = cfg.get("dm_failed_msg", "") or "*(none set)*"
    failed_prev = failed_raw[:80] + ("…" if len(failed_raw) > 80 else "")

    e = discord.Embed(
        title="🛒 Setup — Step 5 of 5",
        description=(
            "**DM Message to Buyer**\n"
            "Sent as a DM when a confirm button is clicked. DMs are private by nature.\n"
            f"Placeholders: {PLACEHOLDERS_HINT}\n\n"
            f"**Current type:** `{dm_type or 'none'}`\n"
            f"**Image/GIF URL:** {image}\n"
            f"**Preview:** {preview}\n\n"
            f"**DM Buttons ({len(dm_btns)}/5):**\n{btn_list}\n\n"
            f"**DM Failed Message** *(posted in channel if buyer DMs are closed):*\n{failed_prev}"
        ),
        color=0x5865F2,
    )
    e.set_footer(text="Step 5 / 5 • DM Message • Save when ready")
    return e


class DMTextModal(ui.Modal, title="📝 DM Message — Text"):
    content   = ui.TextInput(label="DM Content",                    style=discord.TextStyle.paragraph, max_length=2000, required=True)
    image_url = ui.TextInput(label="Image / GIF URL (optional)",    placeholder="https://…",          required=False,  max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog
        if state.cfg.get("dm_content"):    self.content.default   = state.cfg["dm_content"]
        if state.cfg.get("dm_image_url"):  self.image_url.default = state.cfg["dm_image_url"]

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg["dm_msg_type"]  = "text"
        self.state.cfg["dm_content"]   = self.content.value.strip()
        self.state.cfg["dm_image_url"] = self.image_url.value.strip()
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))


class DMEmbedModal(ui.Modal, title="🎨 DM Message — Embed"):
    title_in    = ui.TextInput(label="Title (optional)",           required=False,  max_length=256)
    description = ui.TextInput(label="Description",                style=discord.TextStyle.paragraph, max_length=4000, required=True)
    footer      = ui.TextInput(label="Footer (optional)",          required=False,  max_length=2048)
    color       = ui.TextInput(label="Color hex",                  default="#57F287", required=False, max_length=9)
    image_url   = ui.TextInput(label="Image / GIF URL (optional)", placeholder="https://…", required=False, max_length=512)

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog
        cfg = state.cfg
        if cfg.get("dm_embed_title"):  self.title_in.default    = cfg["dm_embed_title"]
        if cfg.get("dm_embed_desc"):   self.description.default = cfg["dm_embed_desc"]
        if cfg.get("dm_embed_footer"): self.footer.default      = cfg["dm_embed_footer"]
        if cfg.get("dm_image_url"):    self.image_url.default   = cfg["dm_image_url"]
        self.color.default = f"#{cfg.get('dm_embed_color', 0x57F287):06X}"

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.state.cfg
        cfg["dm_msg_type"]    = "embed"
        cfg["dm_embed_title"] = self.title_in.value.strip()
        cfg["dm_embed_desc"]  = self.description.value.strip()
        cfg["dm_embed_footer"]= self.footer.value.strip()
        cfg["dm_embed_color"] = _parse_color(self.color.value)
        cfg["dm_image_url"]   = self.image_url.value.strip()
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))


class AddDMButtonModal(ui.Modal, title="➕ Add DM URL Button"):
    label = ui.TextInput(label="Button Label", max_length=80,  required=True)
    url   = ui.TextInput(label="URL",           max_length=512, required=True, placeholder="https://…")

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        if not _is_valid_url(url):
            await interaction.response.send_message("❌ URL must start with http:// or https://", ephemeral=True)
            return
        self.state.cfg.setdefault("dm_buttons", [])
        self.state.cfg["dm_buttons"].append({"label": self.label.value.strip(), "url": url})
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))


class DMFailedModal(ui.Modal, title="⚠️ DM Failed Message"):
    message = ui.TextInput(
        label="Message (posted in channel if DMs closed)",
        placeholder="⚠️ {buyer} DMs are closed — please send payment details manually.",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=True,
    )

    def __init__(self, state: SetupState, cog):
        super().__init__()
        self.state = state
        self.cog   = cog
        if state.cfg.get("dm_failed_msg"):
            self.message.default = state.cfg["dm_failed_msg"]

    async def on_submit(self, interaction: discord.Interaction):
        self.state.cfg["dm_failed_msg"] = self.message.value.strip()
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))


class Step5DMView(ui.View):
    def __init__(self, state: SetupState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog

    @ui.select(
        placeholder="Configure DM message…",
        options=[
            discord.SelectOption(label="Set Text DM",           value="dm_text",    emoji="📝"),
            discord.SelectOption(label="Set Embed DM",          value="dm_embed",   emoji="🎨"),
            discord.SelectOption(label="Add DM URL Button",     value="add_btn",    emoji="➕"),
            discord.SelectOption(label="Clear DM Buttons",      value="clear_btn",  emoji="🗑️"),
            discord.SelectOption(label="Set DM Failed Message", value="dm_failed",  emoji="⚠️", description="Message posted if buyer DMs are closed"),
            discord.SelectOption(label="No DM (skip)",          value="skip",       emoji="⏭️"),
        ],
        row=0,
    )
    async def dm_select(self, interaction: discord.Interaction, select: ui.Select):
        choice = select.values[0]
        if choice == "dm_text":
            await interaction.response.send_modal(DMTextModal(self.state, self.cog))
        elif choice == "dm_embed":
            await interaction.response.send_modal(DMEmbedModal(self.state, self.cog))
        elif choice == "add_btn":
            if len(self.state.cfg.get("dm_buttons", [])) >= 5:
                await interaction.response.send_message("❌ Maximum 5 DM buttons.", ephemeral=True)
            else:
                await interaction.response.send_modal(AddDMButtonModal(self.state, self.cog))
        elif choice == "clear_btn":
            self.state.cfg["dm_buttons"] = []
            await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))
        elif choice == "dm_failed":
            await interaction.response.send_modal(DMFailedModal(self.state, self.cog))
        elif choice == "skip":
            self.state.cfg["dm_msg_type"] = ""
            self.state.cfg["dm_content"]  = ""
            self.state.cfg["dm_image_url"]= ""
            await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5DMView(self.state, self.cog))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step4_embed(self.state), view=Step4FollowupButtonsView(self.state, self.cog))

    @ui.button(label="✅ Save Config", style=discord.ButtonStyle.success, row=1)
    async def save_btn(self, interaction: discord.Interaction, _: ui.Button):
        _save_cfg(self.state.cfg)
        label = ORDER_TYPE_LABELS.get(self.state.order_type, self.state.order_type)
        cfg   = self.state.cfg
        e = discord.Embed(
            title="✅ Order Config Saved!",
            description=(
                f"**Order Type:** {label}\n"
                f"**Confirm Message:** {cfg.get('confirm_msg_type', 'embed').title()} "
                f"{'🖼️' if cfg.get('confirm_image_url') else ''} "
                f"{'🔒 Ephemeral' if cfg.get('confirm_ephemeral') else '🔓 Public'}\n"
                f"**Confirm Buttons:** {len(cfg.get('confirm_buttons', []))}\n"
                f"**Follow-up Messages:** {len(cfg.get('followup_messages', []))} "
                f"{'🔒 Ephemeral' if cfg.get('followup_ephemeral') else '🔓 Public'}\n"
                f"**Follow-up Buttons:** {len(cfg.get('followup_buttons', []))}\n"
                f"**DM Message:** {'Yes ✅' if cfg.get('dm_msg_type') else 'No ❌'} "
                f"{'🖼️' if cfg.get('dm_image_url') else ''}\n"
                f"**DM Buttons:** {len(cfg.get('dm_buttons', []))}\n\n"
                f"Use `/order {self.state.order_type}` to process orders!"
            ),
            color=0x57F287,
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=e, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION — SENDING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_confirm_view(order_id: str, cfg: dict) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    for i, btn_cfg in enumerate(cfg.get("confirm_buttons", [{"label": "confirm order"}])):
        v.add_item(discord.ui.Button(
            label=btn_cfg["label"],
            style=discord.ButtonStyle.secondary,
            custom_id=f"order_confirm:{order_id}:{i}",
        ))
    return v


def _make_confirm_sendable(cfg: dict, ph: dict) -> tuple[Optional[str], Optional[discord.Embed]]:
    """Return (content, embed) for the confirmation message."""
    img = cfg.get("confirm_image_url", "")
    if cfg.get("confirm_msg_type") == "embed":
        e = _build_embed(
            cfg.get("confirm_embed_title", "") or "",
            cfg.get("confirm_embed_desc",   "") or "",
            cfg.get("confirm_embed_color", 0x5865F2),
            cfg.get("confirm_embed_footer", "") or "",
            img,
            ph,
        )
        return None, e
    else:
        content = _apply_ph(cfg.get("confirm_content", "") or "", ph)
        if img and _is_valid_url(img):
            # Wrap text + image in a minimal embed (Discord can't show images in plain text)
            return None, _make_text_embed_with_image(content, img, ph)
        return (content or "\u200b"), None


async def _send_followup_msg(
    interaction: discord.Interaction,
    channel: discord.abc.Messageable,
    msg: dict,
    view: Optional[discord.ui.View],
    ph: dict,
    ephemeral: bool,
) -> None:
    """Send one follow-up message, respecting ephemeral and image settings."""
    img = msg.get("image_url", "") or ""

    if msg.get("type") == "embed":
        e = _build_embed(
            msg.get("embed_title",  "") or "",
            msg.get("embed_desc",   "") or "",
            msg.get("embed_color", 0x5865F2),
            msg.get("embed_footer", "") or "",
            img,
            ph,
        )
        if ephemeral:
            await interaction.followup.send(embed=e, view=view, ephemeral=True)
        else:
            await channel.send(embed=e, view=view)
    else:
        content = _apply_ph(msg.get("content", "") or "", ph)
        if img and _is_valid_url(img):
            e = _make_text_embed_with_image(content, img, ph)
            if ephemeral:
                await interaction.followup.send(embed=e, view=view, ephemeral=True)
            else:
                await channel.send(embed=e, view=view)
        else:
            if content:
                if ephemeral:
                    await interaction.followup.send(content=content, view=view, ephemeral=True)
                else:
                    await channel.send(content=content, view=view)


# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION — CONFIRM BUTTON HANDLER
# ══════════════════════════════════════════════════════════════════════════════

async def _do_confirm_action(interaction: discord.Interaction, order_id: str) -> None:
    """Core logic run when a confirm button is clicked."""

    # ── Permission ────────────────────────────────────────────────────────────
    if not _is_admin(interaction):
        try:
            await interaction.response.send_message("❌ Only administrators can use this button.", ephemeral=True)
        except Exception:
            pass
        return

    # ── Load order ────────────────────────────────────────────────────────────
    order_doc = _load_order(order_id)
    if not order_doc:
        try:
            await interaction.response.send_message("❌ Order data not found (bot may have restarted).", ephemeral=True)
        except Exception:
            pass
        return

    if order_doc.get("confirmed"):
        try:
            await interaction.response.send_message("⚠️ This order was already confirmed.", ephemeral=True)
        except Exception:
            pass
        return

    # ── Defer ─────────────────────────────────────────────────────────────────
    try:
        await interaction.response.defer()
    except Exception:
        pass

    # Mark confirmed immediately (prevents race / double-click)
    _mark_order_confirmed(order_id)

    # ── Disable original confirm buttons ──────────────────────────────────────
    disabled_view = discord.ui.View(timeout=None)
    try:
        for row in interaction.message.components:
            for component in row.children:
                disabled_view.add_item(discord.ui.Button(
                    label=component.label,
                    style=discord.ButtonStyle.secondary,
                    disabled=True,
                    custom_id=f"disabled_{uuid.uuid4()}",
                ))
        await interaction.message.edit(view=disabled_view)
    except Exception:
        pass

    cfg = _load_cfg(order_doc["guild_id"], order_doc["order_type"])
    ph  = order_doc.get("ph", {})
    channel        = interaction.channel
    ephemeral_fu   = cfg.get("followup_ephemeral", False)
    followup_msgs  = cfg.get("followup_messages", [])
    followup_view  = _build_link_view(cfg.get("followup_buttons", []))

    # ── Send follow-up messages ───────────────────────────────────────────────
    for i, msg in enumerate(followup_msgs):
        is_last  = i == len(followup_msgs) - 1
        view     = followup_view if (is_last and followup_view) else None
        try:
            await _send_followup_msg(interaction, channel, msg, view, ph, ephemeral_fu)
        except discord.HTTPException as exc:
            print(f"[Order] Follow-up send error: {exc}")
        await asyncio.sleep(0.3)

    # If no follow-up messages but we have buttons, post them on their own
    if not followup_msgs and followup_view:
        try:
            if ephemeral_fu:
                await interaction.followup.send(view=followup_view, ephemeral=True)
            else:
                await channel.send(view=followup_view)
        except Exception:
            pass

    # ── DM the buyer ──────────────────────────────────────────────────────────
    dm_type  = cfg.get("dm_msg_type", "")
    buyer_id = order_doc.get("buyer_id")

    if dm_type and buyer_id:
        dm_view = _build_link_view(cfg.get("dm_buttons", []))
        img     = cfg.get("dm_image_url", "") or ""
        try:
            buyer = await interaction.client.fetch_user(buyer_id)
            if dm_type == "embed":
                e = _build_embed(
                    cfg.get("dm_embed_title",  "") or "",
                    cfg.get("dm_embed_desc",   "") or "",
                    cfg.get("dm_embed_color", 0x57F287),
                    cfg.get("dm_embed_footer", "") or "",
                    img,
                    ph,
                )
                await buyer.send(embed=e, view=dm_view)
            else:
                content = _apply_ph(cfg.get("dm_content", "") or "", ph)
                if img and _is_valid_url(img):
                    e = _make_text_embed_with_image(content, img, ph)
                    await buyer.send(embed=e, view=dm_view)
                elif content:
                    await buyer.send(content=content, view=dm_view)

            try:
                await channel.send(f"✅ DM sent to {ph.get('buyer', 'the buyer')}.", delete_after=6)
            except Exception:
                pass

        except discord.Forbidden:
            failed_msg = _apply_ph(cfg.get("dm_failed_msg", "") or "⚠️ {buyer} DMs are closed — please send payment details manually.", ph)
            try:
                await channel.send(failed_msg, delete_after=10)
            except Exception:
                pass
        except discord.NotFound:
            try:
                await channel.send("⚠️ Buyer user not found.", delete_after=6)
            except Exception:
                pass
        except discord.HTTPException as exc:
            print(f"[Order] DM error: {exc}")
            try:
                await channel.send(f"⚠️ Failed to DM buyer: {exc}", delete_after=8)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# ORDER EXECUTION — POST CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

async def _post_order(interaction: discord.Interaction, cfg: dict, ph: dict, order_id: str) -> None:
    view           = _build_confirm_view(order_id, cfg)
    content, embed = _make_confirm_sendable(cfg, ph)
    ephemeral      = cfg.get("confirm_ephemeral", False)
    try:
        if embed:
            await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)
        else:
            await interaction.followup.send(content=content, view=view, ephemeral=ephemeral)
    except discord.HTTPException as exc:
        print(f"[Order] Post error: {exc}")
        try:
            await interaction.followup.send(f"❌ Failed to send order: {exc}", ephemeral=True)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class OrderCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Persistent button listener ────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        cid = interaction.data.get("custom_id", "")
        if not cid.startswith("order_confirm:"):
            return
        parts = cid.split(":")
        if len(parts) < 3:
            return
        order_id = parts[1]
        asyncio.create_task(_do_confirm_action(interaction, order_id))

    # ── Command group ─────────────────────────────────────────────────────────

    order_group = app_commands.Group(name="order", description="Order management commands (admin only)")

    @order_group.command(name="setup", description="Configure order messages, images, and buttons")
    async def order_setup(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.send_message(embed=_main_menu_embed(), view=MainMenuView(self), ephemeral=True)

    @order_group.command(name="premium", description="Send a premium account order")
    @app_commands.describe(
        email="Account email",
        password="Account password",
        profile="Profile name or slot number",
        order="Order description",
        buyer="Buyer to mention and DM",
    )
    async def order_premium(self, interaction: discord.Interaction, email: str, password: str, profile: str, order: str, buyer: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.defer()
        cfg      = _load_cfg(interaction.guild.id, "premium")
        ph       = {"buyer": buyer.mention, "email": email, "password": password, "profile": profile, "order": order, "item": order, "amount": "", "username": "", "content": ""}
        order_id = str(uuid.uuid4())
        _save_order(order_id, interaction.guild.id, "premium", buyer.id, ph)
        await _post_order(interaction, cfg, ph, order_id)

    @order_group.command(name="discord", description="Send a Discord order")
    @app_commands.describe(content="Order content or description", buyer="Buyer to mention and DM")
    async def order_discord(self, interaction: discord.Interaction, content: str, buyer: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.defer()
        cfg      = _load_cfg(interaction.guild.id, "discord")
        ph       = {"buyer": buyer.mention, "content": content, "item": content, "order": content, "amount": "", "username": "", "email": "", "password": "", "profile": ""}
        order_id = str(uuid.uuid4())
        _save_order(order_id, interaction.guild.id, "discord", buyer.id, ph)
        await _post_order(interaction, cfg, ph, order_id)

    @order_group.command(name="qr", description="Send a QR / Roblox order")
    @app_commands.describe(buyer="Buyer to mention and DM", item="Item being ordered", amount="Amount to pay (e.g. ₱500)", username="Roblox username (optional)")
    async def order_qr(self, interaction: discord.Interaction, buyer: discord.Member, item: str, amount: str, username: Optional[str] = None):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.defer()
        cfg      = _load_cfg(interaction.guild.id, "qr")
        ph       = {"buyer": buyer.mention, "item": item, "amount": amount, "username": username or "N/A", "order": item, "content": "", "email": "", "password": "", "profile": ""}
        order_id = str(uuid.uuid4())
        _save_order(order_id, interaction.guild.id, "qr", buyer.id, ph)
        await _post_order(interaction, cfg, ph, order_id)

    @order_group.command(name="queue", description="Add a buyer to the order queue")
    @app_commands.describe(buyer="Buyer to mention and DM", item="Item being ordered", amount="Amount to pay (e.g. ₱500)")
    async def order_queue(self, interaction: discord.Interaction, buyer: discord.Member, item: str, amount: str):
        if not _is_admin(interaction):
            await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
            return
        await interaction.response.defer()
        cfg      = _load_cfg(interaction.guild.id, "queue")
        ph       = {"buyer": buyer.mention, "item": item, "amount": amount, "username": "N/A", "order": item, "content": "", "email": "", "password": "", "profile": ""}
        order_id = str(uuid.uuid4())
        _save_order(order_id, interaction.guild.id, "queue", buyer.id, ph)
        await _post_order(interaction, cfg, ph, order_id)

    # ── Error handlers ────────────────────────────────────────────────────────

    async def _handle_err(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        msg = f"❌ {error}"
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                await interaction.followup.send(msg, ephemeral=True)
        except Exception:
            pass

    @order_setup.error
    async def _e0(self, i, e): await self._handle_err(i, e)

    @order_premium.error
    async def _e1(self, i, e): await self._handle_err(i, e)

    @order_discord.error
    async def _e2(self, i, e): await self._handle_err(i, e)

    @order_qr.error
    async def _e3(self, i, e): await self._handle_err(i, e)

    @order_queue.error
    async def _e4(self, i, e): await self._handle_err(i, e)


async def setup(bot: commands.Bot):
    await bot.add_cog(OrderCog(bot))
