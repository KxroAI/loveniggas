"""
Admin Commands Cog
Owner and administrator only commands, plus sticky pin management.
"""

import asyncio
import time
import uuid
import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime
from typing import Optional

from ..config import PH_TIMEZONE, BOT_OWNER_ID
from ..database import db
from ..utils import create_embed


# ══════════════════════════════════════════════════════════════════════════════
# ANNOUNCEMENT MODAL
# ══════════════════════════════════════════════════════════════════════════════

class AnnouncementModal(ui.Modal, title="Create Announcement"):
    """Modal for creating announcements."""
    
    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.collected_data = {}
        
        self.title_input = ui.TextInput(
            label="Title (optional)",
            default="ANNOUNCEMENT",
            required=False,
            max_length=256,
        )
        self.message_input = ui.TextInput(
            label="Message (required)",
            placeholder="Your announcement message...",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
        )
        self.codeblock_input = ui.TextInput(
            label="Use Code Block? (Yes/No)",
            default="No",
            required=True,
            placeholder="Type 'Yes' or 'No'",
        )
        
        self.add_item(self.title_input)
        self.add_item(self.message_input)
        self.add_item(self.codeblock_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        title = self.title_input.value.strip() or "ANNOUNCEMENT"
        message = self.message_input.value.strip()
        use_codeblock = self.codeblock_input.value.strip().lower() in ("yes", "y", "true", "1")
        
        description = f"```\n{message}\n```" if use_codeblock else message
        embed = create_embed(title=title, description=description)
        
        view = AnnouncementConfirmView(
            author=interaction.user,
            title=title,
            message=message,
            use_codeblock=use_codeblock,
        )
        
        await interaction.response.send_message(
            "📋 **Preview:**",
            embed=embed,
            view=view,
            ephemeral=True,
        )


class AnnouncementConfirmView(ui.View):
    """Confirmation view for announcements."""
    
    def __init__(self, author: discord.User, title: str, message: str, use_codeblock: bool):
        super().__init__(timeout=180)
        self.author = author
        self.title = title
        self.message = message
        self.use_codeblock = use_codeblock
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user == self.author
    
    @ui.button(label="Send", style=discord.ButtonStyle.green)
    async def send(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message(
            "Please select a channel:",
            view=ChannelSelectView(
                author=self.author,
                title=self.title,
                message=self.message,
                use_codeblock=self.use_codeblock,
            ),
            ephemeral=True,
        )
    
    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        embed = create_embed(title="❌ Announcement cancelled.")
        await interaction.response.edit_message(embed=embed, view=None)


class ChannelSelectView(ui.View):
    """Channel selection for announcements."""
    
    def __init__(self, author: discord.User, title: str, message: str, use_codeblock: bool):
        super().__init__(timeout=180)
        self.author = author
        self.title = title
        self.message = message
        self.use_codeblock = use_codeblock
    
    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select a channel...",
    )
    async def select_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        if interaction.user != self.author:
            await interaction.response.send_message("❌ Not your menu.", ephemeral=True)
            return
        
        try:
            channel = await interaction.guild.fetch_channel(select.values[0].id)
        except Exception:
            await interaction.response.send_message("❌ Channel not accessible.", ephemeral=True)
            return
        
        description = f"```\n{self.message}\n```" if self.use_codeblock else self.message
        embed = create_embed(title=self.title, description=description)
        
        try:
            await channel.send(embed=embed)
            await interaction.response.edit_message(
                content="✅ Announcement sent!",
                embed=None,
                view=None,
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ No permission to send there.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — DATA MODEL
# ══════════════════════════════════════════════════════════════════════════════

class StickyPin:
    def __init__(self, pin_id: str, guild_id: int, creator_id: int):
        self.pin_id: str = pin_id
        self.guild_id: int = guild_id
        self.creator_id: int = creator_id
        self.pin_type: str = "text"
        self.content: str = ""
        self.embed_title: str = ""
        self.embed_description: str = ""
        self.embed_footer: str = ""
        self.embed_color: int = 0x7289DA
        self.channels: list[int] = []
        self.buttons: list[dict] = []
        self.delay: int = 3

    def build_view(self) -> Optional[discord.ui.View]:
        if not self.buttons:
            return None
        v = discord.ui.View(timeout=None)
        for btn in self.buttons:
            v.add_item(discord.ui.Button(
                style=discord.ButtonStyle.link,
                label=btn["label"],
                url=btn["url"],
            ))
        return v

    def build_embed(self) -> discord.Embed:
        e = discord.Embed(
            title=self.embed_title or None,
            description=self.embed_description or None,
            color=self.embed_color,
        )
        e.set_footer(text=self.embed_footer.strip() if self.embed_footer else "📌 Sticky Pin")
        return e


# guild_id -> list[StickyPin]
_pins: dict[int, list[StickyPin]] = {}
# f"{channel_id}:{pin_id}" -> last sticky message id
_last_msg: dict[str, int] = {}
# channel_id -> pending asyncio Task
_pending: dict[int, asyncio.Task] = {}
# f"{channel_id}:{pin_id}" -> monotonic timestamp of last post
_last_post_ts: dict[str, float] = {}


def _get_pins_for_channel(channel_id: int, guild_id: int) -> list[StickyPin]:
    return [p for p in _pins.get(guild_id, []) if channel_id in p.channels]


def _short_id(pin_id: str) -> str:
    return pin_id[:8]


def _fmt_channels(channel_ids: list[int]) -> str:
    return ", ".join(f"<#{cid}>" for cid in channel_ids) if channel_ids else "*(none)*"


def _parse_color(raw: str) -> int:
    try:
        return int(raw.strip().lstrip("#"), 16)
    except ValueError:
        return 0x7289DA


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — WIZARD STATE
# ══════════════════════════════════════════════════════════════════════════════

class WizardState:
    def __init__(self, guild_id: int, creator_id: int, edit_pin: StickyPin = None):
        self.guild_id = guild_id
        self.creator_id = creator_id
        self._cog = None
        if edit_pin:
            self.pin_id = edit_pin.pin_id
            self.pin_type = edit_pin.pin_type
            self.content = edit_pin.content
            self.embed_title = edit_pin.embed_title
            self.embed_description = edit_pin.embed_description
            self.embed_footer = edit_pin.embed_footer
            self.embed_color = edit_pin.embed_color
            self.channels = list(edit_pin.channels)
            self.buttons = list(edit_pin.buttons)
            self.delay = edit_pin.delay
        else:
            self.pin_id = str(uuid.uuid4())
            self.pin_type = "text"
            self.content = ""
            self.embed_title = ""
            self.embed_description = ""
            self.embed_footer = ""
            self.embed_color = 0x7289DA
            self.channels = []
            self.buttons = []
            self.delay = 3


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — MAIN MENU
# ══════════════════════════════════════════════════════════════════════════════

def _main_menu_embed() -> discord.Embed:
    e = discord.Embed(
        title="📌 Sticky Pins",
        description="Keep a message pinned at the bottom of any channel.\nChoose an action below to get started.",
        color=0x7289DA,
    )
    e.add_field(name="✨ Create a new Pin", value="Set up a new pin message", inline=False)
    e.add_field(name="✏️ Edit a Pin", value="Modify an existing pin message", inline=False)
    e.add_field(name="🗑️ Delete Pins", value="Remove pin messages from channels", inline=False)
    e.add_field(name="📋 List Pins", value="View all pin messages in server", inline=False)
    e.set_footer(text="What would you like to do?")
    return e


class MainMenuView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog
        select = ui.Select(
            placeholder="What would you like to do?",
            options=[
                discord.SelectOption(label="Create a new Pin", description="Set up a new pin message", value="create", emoji="✨"),
                discord.SelectOption(label="Edit a Pin", description="Modify an existing pin message", value="edit", emoji="✏️"),
                discord.SelectOption(label="Delete Pins", description="Remove pin messages from channels", value="delete", emoji="🗑️"),
                discord.SelectOption(label="List Pins", description="View all pin messages in server", value="list", emoji="📋"),
            ],
            min_values=1,
            max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def _on_select(self, interaction: discord.Interaction):
        choice = interaction.data["values"][0]
        guild_id = interaction.guild.id

        if choice == "create":
            state = WizardState(guild_id, interaction.user.id)
            state._cog = self.cog
            await interaction.response.edit_message(embed=_step1_embed(), view=Step1TypeView(state))

        elif choice == "edit":
            pins = _pins.get(guild_id, [])
            if not pins:
                await interaction.response.send_message("❌ No sticky pins found. Create one first!", ephemeral=True)
                return
            await interaction.response.edit_message(
                embed=discord.Embed(title="✏️ Edit a Pin", description="Select which pin you want to edit.", color=0x7289DA),
                view=EditSelectView(pins, self.cog),
            )

        elif choice == "delete":
            pins = _pins.get(guild_id, [])
            if not pins:
                await interaction.response.send_message("❌ No sticky pins found.", ephemeral=True)
                return
            await interaction.response.edit_message(
                embed=discord.Embed(title="🗑️ Delete a Pin", description="Select which pin you want to delete.", color=0xED4245),
                view=DeleteSelectView(pins, self.cog),
            )

        elif choice == "list":
            pins = _pins.get(guild_id, [])
            if not pins:
                await interaction.response.edit_message(
                    embed=discord.Embed(title="📋 No Sticky Pins", description="This server has no sticky pins yet.\nSelect **✨ Create a new Pin** to make one!", color=0x7289DA),
                    view=BackToMenuView(self.cog),
                )
                return
            await interaction.response.edit_message(embed=_list_embed(pins), view=BackToMenuView(self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class BackToMenuView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @ui.button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — STEP 1: TYPE
# ══════════════════════════════════════════════════════════════════════════════

def _step1_embed() -> discord.Embed:
    e = discord.Embed(
        title="📌 Create Sticky Pin — Step 1 of 5",
        description=(
            "**Choose Message Type**\n\n"
            "📝 **Text** — A plain text message that stays pinned.\n"
            "🎨 **Embed** — A rich embed with title, description, footer, and color.\n\n"
            "*Both types support optional interactive URL buttons.*"
        ),
        color=0x7289DA,
    )
    e.set_footer(text="Step 1 / 5 • Type Selection")
    return e


class TextContentModal(ui.Modal, title="📝 Text Sticky Content"):
    content = ui.TextInput(label="Message Content", placeholder="Enter the text that will stay pinned...", style=discord.TextStyle.paragraph, max_length=2000, required=True)

    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        if state.pin_type == "text" and state.content:
            self.content.default = state.content

    async def on_submit(self, interaction: discord.Interaction):
        self.state.pin_type = "text"
        self.state.content = self.content.value.strip()
        await interaction.response.edit_message(embed=_step2_embed(), view=Step2ChannelView(self.state))


class EmbedContentModal(ui.Modal, title="🎨 Create Embed"):
    title_input = ui.TextInput(label="Title", placeholder="Enter an embed title...", required=True, max_length=256)
    description = ui.TextInput(label="Description", placeholder="Enter the embed body text...", style=discord.TextStyle.paragraph, max_length=4000, required=True)
    footer = ui.TextInput(label="Footer", placeholder="Footer text (optional)", required=False, max_length=2048)
    color = ui.TextInput(label="Color (hex code, e.g. #FF0000)", placeholder="#7289DA", default="#7289DA", required=False, max_length=9)

    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        if state.pin_type == "embed":
            if state.embed_title:
                self.title_input.default = state.embed_title
            if state.embed_description:
                self.description.default = state.embed_description
            if state.embed_footer:
                self.footer.default = state.embed_footer
            self.color.default = f"#{state.embed_color:06X}"

    async def on_submit(self, interaction: discord.Interaction):
        self.state.pin_type = "embed"
        self.state.embed_title = self.title_input.value.strip()
        self.state.embed_description = self.description.value.strip()
        self.state.embed_footer = self.footer.value.strip()
        self.state.embed_color = _parse_color(self.color.value)
        await interaction.response.edit_message(embed=_step2_embed(), view=Step2ChannelView(self.state))


class Step1TypeView(ui.View):
    def __init__(self, state: WizardState, from_edit: bool = False):
        super().__init__(timeout=300)
        self.state = state
        select = ui.Select(
            placeholder="Select message type",
            options=[
                discord.SelectOption(label="Text", description="A plain text message that stays pinned", value="text", emoji="📝"),
                discord.SelectOption(label="Embed", description="Rich embed with title, description, footer & color", value="embed", emoji="🎨"),
            ],
            min_values=1, max_values=1, row=0,
        )
        select.callback = self._on_select
        self.add_item(select)
        back_btn = ui.Button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.data["values"][0] == "text":
            await interaction.response.send_modal(TextContentModal(self.state))
        else:
            await interaction.response.send_modal(EmbedContentModal(self.state))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(getattr(self.state, "_cog", None)))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — STEP 2: CHANNELS
# ══════════════════════════════════════════════════════════════════════════════

def _step2_embed() -> discord.Embed:
    e = discord.Embed(
        title="📌 Create Sticky Pin — Step 2 of 5",
        description="**Select Channels**\nChoose which channels this sticky pin will appear in.\nYou can select multiple channels at once.\n\n*The sticky will always stay at the bottom of each selected channel.*",
        color=0x7289DA,
    )
    e.set_footer(text="Step 2 / 5 • Channel Selection")
    return e


class Step2ChannelView(ui.View):
    def __init__(self, state: WizardState):
        super().__init__(timeout=300)
        self.state = state

    @ui.select(cls=ui.ChannelSelect, placeholder="Select one or more channels...", min_values=1, max_values=25, channel_types=[discord.ChannelType.text, discord.ChannelType.news])
    async def channel_select(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        self.state.channels = [ch.id for ch in select.values]
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3ButtonsView(self.state))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step1_embed(), view=Step1TypeView(self.state))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — STEP 3: BUTTONS
# ══════════════════════════════════════════════════════════════════════════════

def _step3_embed(state: WizardState) -> discord.Embed:
    btn_list = "\n".join(f"• **{b['label']}** → {b['url']}" for b in state.buttons) if state.buttons else "*No buttons added yet.*"
    e = discord.Embed(
        title="📌 Create Sticky Pin — Step 3 of 5",
        description=f"**Add Interactive Buttons** *(optional)*\nAdd up to 5 clickable URL buttons. Skip if not needed.\n\n**Channels:** {_fmt_channels(state.channels)}\n\n**Buttons Added:**\n{btn_list}",
        color=0x7289DA,
    )
    e.set_footer(text="Step 3 / 5 • Buttons (optional)")
    return e


class AddButtonModal(ui.Modal, title="➕ Add a Button"):
    label = ui.TextInput(label="Button Label", placeholder="e.g. Join Server", max_length=80, required=True)
    url = ui.TextInput(label="URL", placeholder="https://example.com", max_length=512, required=True)

    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            await interaction.response.send_message("❌ URL must start with `http://` or `https://`.", ephemeral=True)
            return
        self.state.buttons.append({"label": self.label.value.strip(), "url": url})
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3ButtonsView(self.state))


class Step3ButtonsView(ui.View):
    def __init__(self, state: WizardState):
        super().__init__(timeout=300)
        self.state = state
        select = ui.Select(
            placeholder="Button actions (optional)",
            options=[
                discord.SelectOption(label="Add Button", description="Add a clickable URL button to the sticky", value="add", emoji="➕"),
                discord.SelectOption(label="Clear All Buttons", description="Remove all added buttons", value="clear", emoji="🗑️"),
            ],
            min_values=1, max_values=1, row=0,
        )
        select.callback = self._on_select
        self.add_item(select)
        back_btn = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)
        next_btn = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        next_btn.callback = self._next
        self.add_item(next_btn)

    async def _on_select(self, interaction: discord.Interaction):
        if interaction.data["values"][0] == "add":
            if len(self.state.buttons) >= 5:
                await interaction.response.send_message("❌ Maximum of 5 buttons allowed.", ephemeral=True)
                return
            await interaction.response.send_modal(AddButtonModal(self.state))
        else:
            self.state.buttons.clear()
            await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3ButtonsView(self.state))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step2_embed(), view=Step2ChannelView(self.state))

    async def _next(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step4_embed(self.state.delay), view=Step4DelayView(self.state))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — STEP 4: DELAY
# ══════════════════════════════════════════════════════════════════════════════

def _step4_embed(selected: int = 3) -> discord.Embed:
    e = discord.Embed(
        title="📌 Create Sticky Pin — Step 4 of 5",
        description=f"**Set Re-pin Delay**\nHow many seconds to wait after a new message before re-pinning?\n\n*A short delay groups rapid messages together and reduces API usage.*\n\n**Currently selected:** `{selected}s`",
        color=0x7289DA,
    )
    e.set_footer(text="Step 4 / 5 • Delay Setting")
    return e


class Step4DelayView(ui.View):
    def __init__(self, state: WizardState):
        super().__init__(timeout=300)
        self.state = state
        select = ui.Select(
            placeholder="Select re-pin delay",
            options=[
                discord.SelectOption(label="1 second",  description="Re-pin almost instantly after each message", value="1",  emoji="⚡", default=(state.delay == 1)),
                discord.SelectOption(label="3 seconds", description="Short wait — good for active channels",      value="3",  emoji="🕐", default=(state.delay == 3)),
                discord.SelectOption(label="5 seconds", description="Balanced delay for most channels",           value="5",  emoji="🕑", default=(state.delay == 5)),
                discord.SelectOption(label="10 seconds", description="Calm channels or lower API usage",          value="10", emoji="🕒", default=(state.delay == 10)),
                discord.SelectOption(label="15 seconds", description="Slowest — best for low-traffic channels",  value="15", emoji="🕓", default=(state.delay == 15)),
            ],
            min_values=1, max_values=1, row=0,
        )
        select.callback = self._on_select
        self.add_item(select)
        back_btn = ui.Button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)
        next_btn = ui.Button(label="Next ▶️", style=discord.ButtonStyle.primary, row=1)
        next_btn.callback = self._next
        self.add_item(next_btn)

    async def _on_select(self, interaction: discord.Interaction):
        self.state.delay = int(interaction.data["values"][0])
        await interaction.response.edit_message(embed=_step4_embed(self.state.delay), view=Step4DelayView(self.state))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3ButtonsView(self.state))

    async def _next(self, interaction: discord.Interaction):
        cog = getattr(self.state, "_cog", None)
        await interaction.response.edit_message(embed=_step5_embed(self.state), view=Step5PreviewView(self.state, cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — STEP 5: PREVIEW & SAVE
# ══════════════════════════════════════════════════════════════════════════════

def _step5_embed(state: WizardState) -> discord.Embed:
    btn_str = "\n".join(f"• **{b['label']}** → {b['url']}" for b in state.buttons) if state.buttons else "*None*"
    if state.pin_type == "embed":
        preview = (
            f"**Title:** {state.embed_title or '*(none)*'}\n"
            f"**Description:**\n> {state.embed_description[:200]}{'...' if len(state.embed_description) > 200 else ''}\n"
            f"**Footer:** {state.embed_footer or '*(none)*'}\n"
            f"**Color:** #{state.embed_color:06X}"
        )
        type_label = "🎨 Embed"
    else:
        preview = f"> {state.content[:300]}{'...' if len(state.content) > 300 else ''}"
        type_label = "📝 Text"

    e = discord.Embed(
        title="📌 Create Sticky Pin — Step 5 of 5",
        description=(
            f"**Preview & Save**\nReview your sticky pin before saving.\n\n"
            f"**Type:** {type_label}\n**Channels:** {_fmt_channels(state.channels)}\n"
            f"**Delay:** {state.delay}s | **Buttons:** {len(state.buttons)}\n\n"
            f"**Content Preview:**\n{preview}\n\n**Buttons:**\n{btn_str}"
        ),
        color=0x57F287,
    )
    e.set_footer(text="Step 5 / 5 • Preview & Save")
    return e


class Step5PreviewView(ui.View):
    def __init__(self, state: WizardState, cog=None):
        super().__init__(timeout=300)
        self.state = state
        self.cog = cog or getattr(state, "_cog", None)

    @ui.button(label="✅ Save Pin", style=discord.ButtonStyle.success, row=0)
    async def save_pin(self, interaction: discord.Interaction, _: ui.Button):
        guild_id = self.state.guild_id
        pins = _pins.setdefault(guild_id, [])
        existing = next((p for p in pins if p.pin_id == self.state.pin_id), None)

        if existing:
            existing.pin_type = self.state.pin_type
            existing.content = self.state.content
            existing.embed_title = self.state.embed_title
            existing.embed_description = self.state.embed_description
            existing.embed_footer = self.state.embed_footer
            existing.embed_color = self.state.embed_color
            existing.channels = self.state.channels
            existing.buttons = self.state.buttons
            existing.delay = self.state.delay
            pin = existing
        else:
            pin = StickyPin(self.state.pin_id, guild_id, self.state.creator_id)
            pin.pin_type = self.state.pin_type
            pin.content = self.state.content
            pin.embed_title = self.state.embed_title
            pin.embed_description = self.state.embed_description
            pin.embed_footer = self.state.embed_footer
            pin.embed_color = self.state.embed_color
            pin.channels = self.state.channels
            pin.buttons = self.state.buttons
            pin.delay = self.state.delay
            pins.append(pin)

        saved_embed = discord.Embed(
            title="✅ Sticky Pin Saved!",
            description=(
                f"Your sticky pin is now active.\n\n"
                f"**ID:** `{_short_id(pin.pin_id)}`\n"
                f"**Type:** {'📝 Text' if pin.pin_type == 'text' else '🎨 Embed'}\n"
                f"**Channels:** {_fmt_channels(pin.channels)}\n"
                f"**Delay:** {pin.delay}s | **Buttons:** {len(pin.buttons)}\n\n"
                f"The sticky will appear at the bottom of each selected channel after new messages are sent."
            ),
            color=0x57F287,
        )
        saved_embed.set_footer(text=f"Pin ID: {_short_id(pin.pin_id)} • /stickypin → List Pins to manage")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=saved_embed, view=self)

        if self.cog:
            for cid in pin.channels:
                channel = interaction.guild.get_channel(cid)
                if channel:
                    asyncio.create_task(self.cog._post_sticky(channel, pin))

    @ui.button(label="✏️ Edit Content", style=discord.ButtonStyle.secondary, row=0)
    async def edit_content(self, interaction: discord.Interaction, _: ui.Button):
        if self.state.pin_type == "text":
            await interaction.response.send_modal(TextContentModal(self.state))
        else:
            await interaction.response.send_modal(EmbedContentModal(self.state))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step4_embed(self.state.delay), view=Step4DelayView(self.state))

    @ui.button(label="🏠 Main Menu", style=discord.ButtonStyle.secondary, row=1)
    async def main_menu(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — EDIT & DELETE FLOWS
# ══════════════════════════════════════════════════════════════════════════════

class EditSelectView(ui.View):
    def __init__(self, pins: list[StickyPin], cog):
        super().__init__(timeout=300)
        self.cog = cog
        self._pins = pins
        select = ui.Select(
            placeholder="Select a pin to edit...",
            options=[discord.SelectOption(label=f"[{_short_id(p.pin_id)}] {p.pin_type.title()}", description=f"{len(p.channels)} channel(s) | {p.delay}s delay", value=p.pin_id, emoji="📌") for p in pins[:25]],
            min_values=1, max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)
        back_btn = ui.Button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, interaction: discord.Interaction):
        pin = next((p for p in self._pins if p.pin_id == interaction.data["values"][0]), None)
        if not pin:
            await interaction.response.send_message("❌ Pin not found.", ephemeral=True)
            return
        state = WizardState(interaction.guild.id, interaction.user.id, edit_pin=pin)
        state._cog = self.cog
        await interaction.response.edit_message(embed=_step1_embed(), view=Step1TypeView(state, from_edit=True))

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class DeleteSelectView(ui.View):
    def __init__(self, pins: list[StickyPin], cog):
        super().__init__(timeout=300)
        self.cog = cog
        self._pins = pins
        select = ui.Select(
            placeholder="Select a pin to delete...",
            options=[discord.SelectOption(label=f"[{_short_id(p.pin_id)}] {p.pin_type.title()}", description=f"{len(p.channels)} channel(s) | {p.delay}s delay", value=p.pin_id, emoji="📌") for p in pins[:25]],
            min_values=1, max_values=1,
        )
        select.callback = self._on_select
        self.add_item(select)
        back_btn = ui.Button(label="↩️ Back to Menu", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, interaction: discord.Interaction):
        pin_id = interaction.data["values"][0]
        pin = next((p for p in self._pins if p.pin_id == pin_id), None)
        if not pin:
            await interaction.response.send_message("❌ Pin not found.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🗑️ Confirm Delete",
                description=f"Are you sure you want to delete pin `{_short_id(pin_id)}`?\n\n**Type:** {'📝 Text' if pin.pin_type == 'text' else '🎨 Embed'}\n**Channels:** {_fmt_channels(pin.channels)}\n**Delay:** {pin.delay}s",
                color=0xFEE75C,
            ),
            view=DeleteConfirmView(pin_id, interaction.guild.id, self.cog),
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=_main_menu_embed(), view=MainMenuView(self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class DeleteConfirmView(ui.View):
    def __init__(self, pin_id: str, guild_id: int, cog):
        super().__init__(timeout=60)
        self.pin_id = pin_id
        self.guild_id = guild_id
        self.cog = cog

    @ui.button(label="🗑️ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: ui.Button):
        pins = _pins.get(self.guild_id, [])
        pin = next((p for p in pins if p.pin_id == self.pin_id), None)
        if pin:
            for cid in pin.channels:
                task = _pending.pop(cid, None)
                if task and not task.done():
                    task.cancel()
            _pins[self.guild_id] = [p for p in pins if p.pin_id != self.pin_id]
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="✅ Pin Deleted", description=f"Sticky pin `{_short_id(self.pin_id)}` has been removed.", color=0x57F287),
            view=BackToMenuView(self.cog),
        )

    @ui.button(label="↩️ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="🗑️ Delete a Pin", description="Select which pin you want to delete.", color=0xED4245),
            view=DeleteSelectView(_pins.get(self.guild_id, []), self.cog),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# STICKY PIN — LIST EMBED
# ══════════════════════════════════════════════════════════════════════════════

def _list_embed(pins: list[StickyPin]) -> discord.Embed:
    e = discord.Embed(title=f"📋 Sticky Pins ({len(pins)} total)", color=0x7289DA)
    for pin in pins[:25]:
        channels_str = ", ".join(f"<#{cid}>" for cid in pin.channels[:5])
        if len(pin.channels) > 5:
            channels_str += f" (+{len(pin.channels) - 5} more)"
        e.add_field(
            name=f"[{_short_id(pin.pin_id)}] {'📝 Text' if pin.pin_type == 'text' else '🎨 Embed'}",
            value=f"**Channels:** {channels_str or '*(none)*'}\n**Delay:** {pin.delay}s | **Buttons:** {len(pin.buttons)}",
            inline=False,
        )
    e.set_footer(text="Use /stickypin → Delete Pins to remove a pin")
    return e


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN COG
# ══════════════════════════════════════════════════════════════════════════════

class AdminCog(commands.Cog):
    """Admin and owner-only commands, plus sticky pin management."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    # ── DM COMMANDS (OWNER ONLY) ──────────────────────────────────────────────
    
    @app_commands.command(name="dm", description="Send a DM to a user (Owner only)")
    @app_commands.describe(user="The user to message", message="The message to send")
    async def dm(self, interaction: discord.Interaction, user: discord.User, message: str):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        try:
            await user.send(message)
            await interaction.response.send_message(f"✅ Sent DM to {user}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ Can't DM {user}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
    
    @app_commands.command(name="dmall", description="Send DM to all members (Owner only)")
    @app_commands.describe(message="The message to send", all_servers="Send to all servers? (Default: current server only)")
    @app_commands.choices(all_servers=[
        app_commands.Choice(name="YES", value="all"),
        app_commands.Choice(name="NO", value="server"),
    ])
    async def dmall(self, interaction: discord.Interaction, message: str, all_servers: app_commands.Choice[str] = None):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        scope = "server" if all_servers is None else all_servers.value
        await interaction.response.defer(ephemeral=True)
        success = 0
        fail = 0
        guilds = [interaction.guild] if scope == "server" else self.bot.guilds
        for guild in guilds:
            if not guild:
                continue
            if not guild.chunked:
                try:
                    await guild.chunk()
                except Exception:
                    continue
            for member in guild.members:
                if member.bot:
                    continue
                try:
                    await member.send(message)
                    success += 1
                except Exception:
                    fail += 1
                await asyncio.sleep(1.5)
        await interaction.followup.send(f"✅ Sent to **{success}** members. ❌ Failed: **{fail}**")
    
    # ── PURGE ─────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="purge", description="Bulk-delete messages (Admin)")
    @app_commands.describe(amount="Number of messages to delete")
    async def purge(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❗ Enter a positive number.", ephemeral=True)
            return
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.id == BOT_OWNER_ID):
            await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"✅ Deleted **{len(deleted)}** messages.", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ No permission.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
    
    # ── ANNOUNCEMENT ──────────────────────────────────────────────────────────
    
    @app_commands.command(name="announcement", description="Create an announcement (Admin)")
    async def announcement(self, interaction: discord.Interaction):
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.id == BOT_OWNER_ID):
            await interaction.response.send_message("❌ You need Manage Messages permission.", ephemeral=True)
            return
        await interaction.response.send_modal(AnnouncementModal(self.bot))
    
    # ── SAY ───────────────────────────────────────────────────────────────────
    
    @app_commands.command(name="say", description="Make the bot say something")
    @app_commands.describe(message="The message to send")
    async def say(self, interaction: discord.Interaction, message: str):
        if "@everyone" in message or "@here" in message:
            await interaction.response.send_message("❌ Cannot mention everyone/here.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Sending...", ephemeral=True)
        await interaction.channel.send(message)
    
    # ── CREATE INVITE (OWNER ONLY) ────────────────────────────────────────────
    
    @app_commands.command(name="createinvite", description="Generate invites for all servers (Owner only)")
    async def createinvite(self, interaction: discord.Interaction):
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Owner only.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        invites = []
        for guild in self.bot.guilds:
            try:
                channel = next((ch for ch in guild.text_channels if ch.permissions_for(guild.me).create_instant_invite), None)
                if channel:
                    invite = await channel.create_invite(max_age=1800, reason="Owner request")
                    invites.append(f"**{guild.name}** (`{guild.id}`): {invite.url}")
                else:
                    invites.append(f"**{guild.name}**: ❌ No suitable channel")
            except discord.Forbidden:
                invites.append(f"**{guild.name}**: ❌ No permission")
            except Exception as e:
                invites.append(f"**{guild.name}**: ❌ {e}")
            await asyncio.sleep(0.5)
        full_message = "\n".join(invites)
        if len(full_message) > 1900:
            chunks = [full_message[i:i+1900] for i in range(0, len(full_message), 1900)]
            await interaction.followup.send(chunks[0], ephemeral=True)
            for chunk in chunks[1:]:
                await interaction.followup.send(chunk, ephemeral=True)
        else:
            await interaction.followup.send(full_message, ephemeral=True)

    # ── INVITE MANAGEMENT (ADMIN) ─────────────────────────────────────────────

    @app_commands.command(name="adjustinvites", description="Add or remove invites from a user's count (Admin)")
    @app_commands.describe(user="The user to adjust", amount="Positive to add, negative to remove")
    async def adjustinvites(self, interaction: discord.Interaction, user: discord.User, amount: int):
        if not (interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
            return
        if amount == 0:
            await interaction.response.send_message("❗ Amount cannot be zero.", ephemeral=True)
            return
        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
        guild_id = str(interaction.guild.id)
        user_id = str(user.id)
        db.invites.update_one({"guild_id": guild_id, "user_id": user_id}, {"$inc": {"total": amount}}, upsert=True)
        doc = db.invites.find_one({"guild_id": guild_id, "user_id": user_id})
        new_total = max(doc.get("total", 0), 0) if doc else 0
        if new_total < 0:
            db.invites.update_one({"guild_id": guild_id, "user_id": user_id}, {"$set": {"total": 0}})
            new_total = 0
        action = f"+{amount}" if amount > 0 else str(amount)
        embed = create_embed(title="✅ Invites Adjusted", description=f"**User:** {user.mention}\n**Change:** {action}\n**New Total:** {new_total} invite(s)", color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resetinvites", description="Reset a user's invite count to zero (Admin)")
    @app_commands.describe(user="The user whose invite count to reset")
    async def resetinvites(self, interaction: discord.Interaction, user: discord.User):
        if not (interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
            await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
            return
        if not db.is_connected or db.invites is None:
            await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)
            return
        db.invites.update_one({"guild_id": str(interaction.guild.id), "user_id": str(user.id)}, {"$set": {"total": 0, "invited_users": []}}, upsert=True)
        embed = create_embed(title="✅ Invites Reset", description=f"{user.mention}'s invite count has been reset to **0**.", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed)

    # ── STICKY PIN ────────────────────────────────────────────────────────────

    @app_commands.command(name="stickypin", description="Create and manage sticky pins in your server")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def stickypin(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_main_menu_embed(), view=MainMenuView(self), ephemeral=True)

    @stickypin.error
    async def stickypin_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need the **Manage Messages** permission to use sticky pins.", ephemeral=True)

    # ── STICKY PIN: MESSAGE LISTENER ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        active_pins = _get_pins_for_channel(message.channel.id, message.guild.id)
        if not active_pins:
            return
        existing = _pending.pop(message.channel.id, None)
        if existing and not existing.done():
            existing.cancel()
        delay = min(p.delay for p in active_pins)
        task = asyncio.create_task(self._delayed_repost(message.channel, active_pins, delay))
        _pending[message.channel.id] = task

    async def _delayed_repost(self, channel: discord.TextChannel, pins: list[StickyPin], delay: int):
        try:
            await asyncio.sleep(delay)
            for pin in pins:
                await self._post_sticky(channel, pin)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[StickyPin] _delayed_repost error: {e}")
        finally:
            _pending.pop(channel.id, None)

    async def _post_sticky(self, channel: discord.TextChannel, pin: StickyPin):
        key = f"{channel.id}:{pin.pin_id}"
        now = time.monotonic()
        if now - _last_post_ts.get(key, 0) < max(pin.delay - 0.5, 0.5):
            return
        _last_post_ts[key] = now
        old_msg_id = _last_msg.get(key)
        if old_msg_id:
            try:
                await (await channel.fetch_message(old_msg_id)).delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            _last_msg.pop(key, None)
        try:
            view = pin.build_view()
            sent = await channel.send(embed=pin.build_embed(), view=view) if pin.pin_type == "embed" else await channel.send(content=pin.content, view=view)
            _last_msg[key] = sent.id
        except discord.Forbidden:
            print(f"[StickyPin] No send permission in #{channel.name}")
        except discord.HTTPException as e:
            print(f"[StickyPin] HTTP error: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
