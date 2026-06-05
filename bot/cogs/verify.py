"""
Verify System Cog
Single /verify command — wizard-style setup (like stickypin).

Posts a persistent Verify panel. When a member clicks the button:
  • If "auto-join servers" is configured → sends an OAuth2 link (identify + guilds.join)
    The Flask callback auto-joins the servers and assigns the role.
  • If only a role is configured (no auto-join) → assigns the role directly, no OAuth needed.
  • Role is always optional.

Uses aiosqlite for settings storage + shared in-memory state with verify_oauth.py.
"""

import secrets as _secrets
import aiosqlite
import discord
from discord import app_commands, ui
from discord.ext import commands
from datetime import datetime, timezone

from ..utils import create_embed, create_error_embed

DB_PATH = "verify.db"

# ══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════════════

async def _init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS verify_settings (
                guild_id        INTEGER PRIMARY KEY,
                channel_id      INTEGER,
                role_id         INTEGER,
                message_id      INTEGER,
                embed_title     TEXT    DEFAULT 'Verification',
                embed_desc      TEXT    DEFAULT 'Click the button below to verify yourself and gain access to the server.',
                embed_color     INTEGER DEFAULT 5793266,
                button_label    TEXT    DEFAULT '✅  Verify',
                join_guild_ids  TEXT    DEFAULT ''
            )
        """)
        # Migration: add join_guild_ids if it didn't exist yet
        try:
            await db.execute("ALTER TABLE verify_settings ADD COLUMN join_guild_ids TEXT DEFAULT ''")
        except Exception:
            pass
        # Migration: drop old server_invites column gracefully (SQLite ignores unknown columns)
        await db.commit()


async def _get_settings(guild_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM verify_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _save_settings(guild_id: int, **kwargs):
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await (
            await db.execute(
                "SELECT guild_id FROM verify_settings WHERE guild_id = ?", (guild_id,)
            )
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            await db.execute(
                f"UPDATE verify_settings SET {sets} WHERE guild_id = ?",
                (*kwargs.values(), guild_id),
            )
        else:
            kwargs["guild_id"] = guild_id
            cols  = ", ".join(kwargs.keys())
            marks = ", ".join("?" for _ in kwargs)
            await db.execute(
                f"INSERT INTO verify_settings ({cols}) VALUES ({marks})",
                tuple(kwargs.values()),
            )
        await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD STATE
# ══════════════════════════════════════════════════════════════════════════════

class WizardState:
    def __init__(self, guild_id: int, existing: dict | None = None):
        self.guild_id      = guild_id
        self.channel_id    = existing["channel_id"]    if existing else None
        self.role_id       = existing.get("role_id")   if existing else None   # optional
        self.message_id    = existing.get("message_id") if existing else None
        self.embed_title   = existing["embed_title"]   if existing else "Verification"
        self.embed_desc    = existing["embed_desc"]    if existing else "Click the button below to verify yourself and gain access to the server."
        self.embed_color   = existing["embed_color"]   if existing else 0x5865F2
        self.button_label  = existing["button_label"]  if existing else "✅  Verify"
        raw = (existing.get("join_guild_ids") or "") if existing else ""
        self.join_guild_ids: list[str] = [x.strip() for x in raw.split(",") if x.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENT VERIFY BUTTON
# ══════════════════════════════════════════════════════════════════════════════

class VerifyPanelView(ui.View):
    """Live verify panel — persistent across bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(
        label="✅  Verify",
        style=discord.ButtonStyle.success,
        custom_id="verify_panel_btn",
    )
    async def verify_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild  = interaction.guild
        member = interaction.user

        if not guild:
            return await interaction.followup.send("❌ This only works inside a server.", ephemeral=True)

        settings = await _get_settings(guild.id)
        if not settings or not settings.get("channel_id"):
            return await interaction.followup.send(
                "❌ The verify system is not configured. Ask an admin to run `/verify`.",
                ephemeral=True,
            )

        join_raw  = settings.get("join_guild_ids") or ""
        join_ids  = [x.strip() for x in join_raw.split(",") if x.strip()]
        role_id   = settings.get("role_id")

        if not join_ids and not role_id:
            return await interaction.followup.send(
                "❌ Verify system has no role or servers configured. Ask an admin to reconfigure.",
                ephemeral=True,
            )

        # ── Path A: OAuth flow needed (auto-join servers configured) ────────
        if join_ids:
            # Import here to avoid circular; the blueprint is already loaded
            from ..verify_oauth import register_state, make_oauth_url, web_base_url
            import os

            if not os.getenv("DISCORD_CLIENT_ID"):
                return await interaction.followup.send(
                    "❌ `DISCORD_CLIENT_ID` is not set. The server admin needs to configure it for auto-join to work.",
                    ephemeral=True,
                )

            state = _secrets.token_urlsafe(20)
            register_state(state, guild.id, member.id)
            oauth_url = make_oauth_url(state)
            if not oauth_url:
                return await interaction.followup.send(
                    "❌ Could not build OAuth URL. Make sure `DISCORD_CLIENT_ID` is set.", ephemeral=True
                )

            embed = discord.Embed(
                title="🔐 Authorization Required",
                description=(
                    "To verify you, the bot needs your permission to:\n\n"
                    "• **Know who you are** (username & avatar)\n"
                    "• **Join servers for you** (auto-join configured servers)\n\n"
                    "Click the button below to authorize. "
                    "You'll be redirected to Discord's official authorization page."
                ),
                color=0x5865F2,
            )
            embed.set_footer(text="This link expires in 5 minutes.")

            view = ui.View(timeout=None)
            view.add_item(
                ui.Button(
                    label="🔐  Authorize to Verify",
                    style=discord.ButtonStyle.link,
                    url=oauth_url,
                )
            )
            return await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        # ── Path B: Direct role assignment (no auto-join needed) ────────────
        role = guild.get_role(role_id)
        if not role:
            return await interaction.followup.send(
                "❌ The configured role no longer exists. Ask an admin to reconfigure with `/verify`.",
                ephemeral=True,
            )

        if role in member.roles:
            return await interaction.followup.send(
                f"✅ You already have the **{role.name}** role!", ephemeral=True
            )

        try:
            await member.add_roles(role, reason="Verified via /verify panel")
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ I don't have permission to assign that role. My role must be above the verified role.",
                ephemeral=True,
            )

        await interaction.followup.send(
            f"✅ You've been verified and received the **{role.name}** role!", ephemeral=True
        )


# ══════════════════════════════════════════════════════════════════════════════
# EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _main_menu_embed(settings: dict | None) -> discord.Embed:
    if settings and settings.get("channel_id"):
        join_ids = [x.strip() for x in (settings.get("join_guild_ids") or "").split(",") if x.strip()]
        role_str = f"<@&{settings['role_id']}>" if settings.get("role_id") else "*None (optional)*"
        status = (
            f"**Channel:** <#{settings['channel_id']}>\n"
            f"**Verified Role:** {role_str}\n"
            f"**Button:** {settings.get('button_label', '✅  Verify')}\n"
            f"**Auto-Join Servers:** {len(join_ids)} configured"
        )
        desc  = f"✅ **Verify panel is active.**\n\n{status}\n\nUse **🔧 Setup / Edit** to change settings."
        color = 0x57F287
    else:
        desc  = (
            "No verify panel is active yet.\n\n"
            "Click **🔧 Setup** to create one:\n"
            "• Pick a channel & optional role\n"
            "• Customize the embed\n"
            "• Optionally add server IDs to auto-join users into\n"
            "  *(requires Discord OAuth — users click Authorize instead of Verify)*"
        )
        color = 0x5865F2

    e = discord.Embed(title="✅ Verify System", description=desc, color=color)
    e.set_footer(text="/verify • Neroniel")
    return e


def _step1_embed() -> discord.Embed:
    return discord.Embed(
        title="✅ Setup Verify — Step 1 of 4",
        description=(
            "**Choose the channel** where the verify panel will be posted.\n\n"
            "Members will click the Verify button in this channel."
        ),
        color=0x5865F2,
    ).set_footer(text="Step 1 / 4 • Channel")


def _step2_embed(channel_id: int) -> discord.Embed:
    return discord.Embed(
        title="✅ Setup Verify — Step 2 of 4",
        description=(
            f"**Channel:** <#{channel_id}>\n\n"
            "**Choose a role** to give members when they verify.\n\n"
            "⚙️ **Role is optional** — skip this step if you only need auto-join."
        ),
        color=0x5865F2,
    ).set_footer(text="Step 2 / 4 • Role (optional)")


def _step3_embed(state: WizardState) -> discord.Embed:
    role_str  = f"<@&{state.role_id}>" if state.role_id else "*None*"
    join_str  = ", ".join(f"`{g}`" for g in state.join_guild_ids) if state.join_guild_ids else "*None*"
    return discord.Embed(
        title="✅ Setup Verify — Step 3 of 4",
        description=(
            f"**Channel:** <#{state.channel_id}>\n"
            f"**Role:** {role_str}\n\n"
            "Customize the panel embed and configure which servers to **auto-join** users into after they authorize.\n\n"
            f"**Embed title:** {state.embed_title}\n"
            f"**Button label:** {state.button_label}\n"
            f"**Auto-join server IDs:** {join_str}"
        ),
        color=0x5865F2,
    ).set_footer(text="Step 3 / 4 • Customize")


def _step4_embed(state: WizardState) -> discord.Embed:
    role_str  = f"<@&{state.role_id}>" if state.role_id else "*None (no role will be assigned)*"
    join_str  = "\n".join(f"• `{g}`" for g in state.join_guild_ids) or "*None — users click Verify directly (no OAuth)*"
    return discord.Embed(
        title="✅ Setup Verify — Step 4 of 4",
        description=(
            "**Preview & Deploy**\n\n"
            f"**Channel:** <#{state.channel_id}>\n"
            f"**Role:** {role_str}\n"
            f"**Button:** {state.button_label}\n\n"
            f"**Auto-Join Servers (guild IDs):**\n{join_str}\n\n"
            "Click **🚀 Deploy** to post the panel."
        ),
        color=0x57F287,
    ).set_footer(text="Step 4 / 4 • Preview & Deploy")


def _build_panel_embed(state: WizardState) -> discord.Embed:
    e = discord.Embed(
        title=state.embed_title,
        description=state.embed_desc,
        color=state.embed_color,
    )
    e.set_footer(text="Neroniel • Click the button below to verify")
    return e


# ══════════════════════════════════════════════════════════════════════════════
# MODALS
# ══════════════════════════════════════════════════════════════════════════════

class EmbedCustomizeModal(ui.Modal, title="Customize Verify Embed"):
    embed_title  = ui.TextInput(label="Embed Title",       max_length=200, required=True)
    embed_desc   = ui.TextInput(label="Embed Description", style=discord.TextStyle.paragraph, max_length=1800, required=True)
    embed_color  = ui.TextInput(label="Embed Color (hex, e.g. 5865F2)",   max_length=7,  required=True)
    button_label = ui.TextInput(label="Button Label",      max_length=60,  required=True)

    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.embed_title.default  = state.embed_title
        self.embed_desc.default   = state.embed_desc
        self.embed_color.default  = f"{state.embed_color:06X}"
        self.button_label.default = state.button_label

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.embed_color.value.lstrip("#"), 16)
        except ValueError:
            color = 0x5865F2
        self.state.embed_title  = self.embed_title.value.strip()
        self.state.embed_desc   = self.embed_desc.value.strip()
        self.state.embed_color  = color
        self.state.button_label = self.button_label.value.strip() or "✅  Verify"
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state))


class AutoJoinModal(ui.Modal, title="Auto-Join Servers (guilds.join OAuth)"):
    guild_ids = ui.TextInput(
        label="Server (Guild) IDs — one per line, up to 5",
        style=discord.TextStyle.paragraph,
        placeholder=(
            "123456789012345678\n"
            "987654321098765432\n\n"
            "Leave blank to disable auto-join.\n"
            "The bot must already be in each server."
        ),
        required=False,
        max_length=500,
    )

    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.guild_ids.default = "\n".join(state.join_guild_ids)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.guild_ids.value or ""
        ids = [x.strip() for x in raw.splitlines() if x.strip().isdigit()][:5]
        self.state.join_guild_ids = ids
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state))


# ══════════════════════════════════════════════════════════════════════════════
# WIZARD VIEWS
# ══════════════════════════════════════════════════════════════════════════════

class MainMenuView(ui.View):
    def __init__(self, cog, settings: dict | None):
        super().__init__(timeout=300)
        self.cog      = cog
        self.settings = settings
        if not (settings and settings.get("channel_id")):
            self.remove_panel.disabled = True

    @ui.button(label="🔧 Setup / Edit", style=discord.ButtonStyle.primary, row=0)
    async def setup(self, interaction: discord.Interaction, _: ui.Button):
        state = WizardState(interaction.guild.id, self.settings)
        await interaction.response.edit_message(embed=_step1_embed(), view=Step1ChannelView(state, self.cog))

    @ui.button(label="🗑️ Remove Panel", style=discord.ButtonStyle.danger, row=0)
    async def remove_panel(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🗑️ Remove Verify Panel",
                description="This will delete the posted panel message and clear all configuration.",
                color=0xED4245,
            ),
            view=RemoveConfirmView(self.cog, self.settings),
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class RemoveConfirmView(ui.View):
    def __init__(self, cog, settings: dict | None):
        super().__init__(timeout=60)
        self.cog      = cog
        self.settings = settings

    @ui.button(label="✅ Yes, Remove", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: ui.Button):
        if self.settings:
            ch_id  = self.settings.get("channel_id")
            msg_id = self.settings.get("message_id")
            if ch_id and msg_id:
                ch = interaction.guild.get_channel(ch_id)
                if ch:
                    try:
                        msg = await ch.fetch_message(msg_id)
                        await msg.delete()
                    except Exception:
                        pass
            await _save_settings(interaction.guild.id, channel_id=None, role_id=None, message_id=None, join_guild_ids="")
        await interaction.response.edit_message(
            embed=discord.Embed(title="✅ Removed", description="Verify panel removed.", color=0x57F287),
            view=None,
        )

    @ui.button(label="↩️ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_main_menu_embed(self.settings), view=MainMenuView(self.cog, self.settings))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Step 1: Channel ──────────────────────────────────────────────────────────

class Step1ChannelView(ui.View):
    def __init__(self, state: WizardState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog
        sel = ui.ChannelSelect(placeholder="Select the verify panel channel…", channel_types=[discord.ChannelType.text])
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        self.state.channel_id = interaction.data["values"][0]
        await interaction.response.edit_message(embed=_step2_embed(int(self.state.channel_id)), view=Step2RoleView(self.state, self.cog))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        settings = await _get_settings(interaction.guild.id)
        await interaction.response.edit_message(embed=_main_menu_embed(settings), view=MainMenuView(self.cog, settings))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Step 2: Role (optional) ──────────────────────────────────────────────────

class Step2RoleView(ui.View):
    def __init__(self, state: WizardState, cog):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog
        sel = ui.RoleSelect(placeholder="Select the verified role… (optional)")
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction):
        self.state.role_id = int(interaction.data["values"][0])
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state, self.cog))

    @ui.button(label="⏭️ Skip (No Role)", style=discord.ButtonStyle.secondary, row=1)
    async def skip(self, interaction: discord.Interaction, _: ui.Button):
        self.state.role_id = None
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state, self.cog))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step1_embed(), view=Step1ChannelView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Step 3: Customize ────────────────────────────────────────────────────────

class Step3CustomizeView(ui.View):
    def __init__(self, state: WizardState, cog=None):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog

    @ui.button(label="🎨 Edit Embed & Button", style=discord.ButtonStyle.primary, row=0)
    async def edit_embed(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(EmbedCustomizeModal(self.state))

    @ui.button(label="🖥️ Auto-Join Servers", style=discord.ButtonStyle.secondary, row=0)
    async def auto_join(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.send_modal(AutoJoinModal(self.state))

    @ui.button(label="▶️ Next → Preview", style=discord.ButtonStyle.success, row=1)
    async def next_step(self, interaction: discord.Interaction, _: ui.Button):
        if not self.state.role_id and not self.state.join_guild_ids:
            await interaction.response.send_message(
                "⚠️ You must configure at least a **role** or at least one **auto-join server** before deploying.",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(embed=_step4_embed(self.state), view=Step4PreviewView(self.state, self.cog))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step2_embed(int(self.state.channel_id)), view=Step2RoleView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Step 4: Preview & Deploy ─────────────────────────────────────────────────

class Step4PreviewView(ui.View):
    def __init__(self, state: WizardState, cog=None):
        super().__init__(timeout=300)
        self.state = state
        self.cog   = cog

    @ui.button(label="🚀 Deploy Panel", style=discord.ButtonStyle.success, row=0)
    async def deploy(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.defer()
        guild   = interaction.guild
        state   = self.state
        channel = guild.get_channel(int(state.channel_id))
        if not channel:
            await interaction.followup.send("❌ Channel not found.", ephemeral=True)
            return

        panel_embed = _build_panel_embed(state)

        # Build panel view with correct button label
        panel_view = VerifyPanelView()
        for item in panel_view.children:
            if isinstance(item, ui.Button) and item.custom_id == "verify_panel_btn":
                item.label = state.button_label

        # Delete previous panel
        old = await _get_settings(guild.id)
        if old and old.get("message_id"):
            old_ch = guild.get_channel(old.get("channel_id") or 0)
            if old_ch:
                try:
                    old_msg = await old_ch.fetch_message(old["message_id"])
                    await old_msg.delete()
                except Exception:
                    pass

        try:
            panel_msg = await channel.send(embed=panel_embed, view=panel_view)
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to send messages in that channel.", ephemeral=True)
            return

        await _save_settings(
            guild.id,
            channel_id     = int(state.channel_id),
            role_id        = state.role_id,
            message_id     = panel_msg.id,
            embed_title    = state.embed_title,
            embed_desc     = state.embed_desc,
            embed_color    = state.embed_color,
            button_label   = state.button_label,
            join_guild_ids = ",".join(state.join_guild_ids),
        )

        # OAuth info blurb
        if state.join_guild_ids:
            from ..verify_oauth import web_base_url
            redirect_uri = f"{web_base_url()}/verify/callback"
            note = (
                f"\n\n**OAuth Redirect URI** (add this to your Discord app's OAuth2 Redirects):\n"
                f"`{redirect_uri}`\n\n"
                "Also make sure `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` are set as secrets."
            )
        else:
            note = ""

        for item in self.children:
            item.disabled = True

        done = discord.Embed(
            title="🚀 Verify Panel Deployed!",
            description=(
                f"Panel is live in {channel.mention}.\n\n"
                f"**Role:** {'<@&' + str(state.role_id) + '>' if state.role_id else '*None*'}\n"
                f"**Button:** {state.button_label}\n"
                f"**Auto-Join Servers:** {len(state.join_guild_ids)} configured"
                f"{note}"
            ),
            color=0x57F287,
        )
        done.set_footer(text="Use /verify to edit or remove this panel anytime.")
        await interaction.edit_original_response(embed=done, view=self)

    @ui.button(label="✏️ Edit", style=discord.ButtonStyle.secondary, row=0)
    async def edit(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state, self.cog))

    @ui.button(label="↩️ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, _: ui.Button):
        await interaction.response.edit_message(embed=_step3_embed(self.state), view=Step3CustomizeView(self.state, self.cog))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
# COG
# ══════════════════════════════════════════════════════════════════════════════

class VerifyCog(commands.Cog):
    """Single /verify command with wizard setup + persistent verify panel."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await _init_db()
        self.bot.add_view(VerifyPanelView())  # re-register persistent view on restart

    @app_commands.command(name="verify", description="Set up or manage the server's verification panel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_cmd(self, interaction: discord.Interaction):
        settings = await _get_settings(interaction.guild.id)
        await interaction.response.send_message(
            embed=_main_menu_embed(settings),
            view=MainMenuView(self, settings),
            ephemeral=True,
        )

    @verify_cmd.error
    async def verify_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ You need **Manage Server** permission.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifyCog(bot))
