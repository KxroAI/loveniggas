"""
Music Cog — Neroniel Bot
Components v2 controller · PIL banner · aiosqlite persistence
Commands: play, pause, resume, skip, stop, loop, queue, volume,
          autoplay, current/nowplaying  +  music setup/reset/settings
"""

import asyncio
import datetime
import io
import os
import re
import sys
import traceback

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    import urllib.request as _urllib_req
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

import aiosqlite

# ── Config ────────────────────────────────────────────────────────────────────

_LAVALINK_URI  = os.getenv("LAVALINK_URI",      "https://lavalink.jirayu.net:443")
_LAVALINK_PASS = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

_DEFAULT_BANNER = (
    "https://media.discordapp.net/attachments/1229366361826918405"
    "/1357196877023547492/images_21.jpg"
    "?ex=67ef5396&is=67ee0216&hm=065303d8f2472468d5a0a4813839aadbd08fb10d"
    "556739ef9907bece29f4c034&"
)

_DB_PATH = "db/music.db"
_URL_RE  = re.compile(r"^https?://", re.IGNORECASE)

# ── Time helpers ──────────────────────────────────────────────────────────────

def _fmt_ms(ms: int) -> str:
    try:
        s = int(ms) // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        parts = []
        if d: parts.append(f"{d}D")
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if s: parts.append(f"{s}s")
        return " ".join(parts) or "0s"
    except Exception:
        return "???"


def _trunc(text: str, limit: int = 60) -> str:
    if not text:
        return "Unknown"
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


# ── PIL banner (Neroniel's create_simple_music_banner, adapted) ────────────────

def _create_music_banner(
    thumbnail_url: str,
    title: str,
    author: str,
    duration_ms: int,
    position_ms: int,
) -> "io.BytesIO | None":
    if not _PIL_OK:
        return None
    try:
        width, height = 1200, 300

        def _load(url: str) -> "Image.Image":
            try:
                req = _urllib_req.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with _urllib_req.urlopen(req, timeout=8) as r:
                    return Image.open(io.BytesIO(r.read())).convert("RGBA")
            except Exception:
                return Image.new("RGBA", (200, 200), (50, 50, 50, 255))

        def _fit(drawer, text: str, font, max_w: int) -> str:
            text = text or "Unknown"
            if drawer.textlength(text, font=font) <= max_w:
                return text
            while len(text) > 1 and drawer.textlength(f"{text}...", font=font) > max_w:
                text = text[:-1]
            return f"{text}..."

        raw = _load(thumbnail_url or _DEFAULT_BANNER)
        bg  = raw.resize((width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=25))
        ov  = Image.new("RGBA", (width, height), (0, 0, 0, 200))
        canvas = Image.alpha_composite(bg, ov)
        draw   = ImageDraw.Draw(canvas)

        art_size = 200
        ax, ay = 50, 50
        art  = raw.resize((art_size, art_size), Image.LANCZOS)
        mask = Image.new("L", (art_size, art_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, art_size, art_size], radius=15, fill=255)
        canvas.paste(art, (ax, ay), mask=mask)

        try:
            f_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            f_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            f_time   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except Exception:
            f_title = f_artist = f_time = ImageFont.load_default()

        info_x  = ax + art_size + 40
        max_tw  = width - info_x - 50
        draw.text((info_x, 60),  _fit(draw, title,  f_title,  max_tw), fill=(255, 255, 255, 255), font=f_title)
        draw.text((info_x, 110), _fit(draw, author, f_artist, max_tw), fill=(180, 180, 180, 255), font=f_artist)

        bx, by, bw, bh = info_x, 160, max_tw, 12
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6, fill=(255, 255, 255, 40))
        ratio = max(0.0, min(1.0, position_ms / duration_ms if duration_ms > 0 else 0.0))
        pw = int(bw * ratio)
        if pw > 0:
            draw.rounded_rectangle([bx, by, bx + pw, by + bh], radius=6, fill=(255, 255, 255, 255))

        cur = _fmt_ms(max(position_ms, 0))
        tot = _fmt_ms(max(duration_ms, 0))
        draw.text((bx, by + 22), cur, fill=(200, 200, 200, 255), font=f_time)
        tw = int(draw.textlength(tot, font=f_time))
        draw.text((bx + bw - tw, by + 22), tot, fill=(200, 200, 200, 255), font=f_time)

        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        return buf
    except Exception:
        print(f"[Music] Banner generation error:\n{traceback.format_exc()}")
        return None


# ── aiosqlite helpers ─────────────────────────────────────────────────────────

async def _db_init():
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS music_settings (
                guild_id    TEXT PRIMARY KEY,
                channel_id  TEXT,
                message_id  TEXT,
                default_volume INTEGER DEFAULT 80
            )
        """)
        await db.commit()


async def _db_get(guild_id: int) -> dict:
    async with aiosqlite.connect(_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM music_settings WHERE guild_id = ?", (str(guild_id),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {}


async def _db_upsert(guild_id: int, **kwargs):
    async with aiosqlite.connect(_DB_PATH) as db:
        existing = await db.execute(
            "SELECT guild_id FROM music_settings WHERE guild_id = ?", (str(guild_id),)
        )
        row = await existing.fetchone()
        if row:
            if kwargs:
                sets = ", ".join(f"{k} = ?" for k in kwargs)
                await db.execute(
                    f"UPDATE music_settings SET {sets} WHERE guild_id = ?",
                    (*kwargs.values(), str(guild_id)),
                )
        else:
            kwargs["guild_id"] = str(guild_id)
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            await db.execute(
                f"INSERT INTO music_settings ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )
        await db.commit()


async def _db_delete(guild_id: int):
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute("DELETE FROM music_settings WHERE guild_id = ?", (str(guild_id),))
        await db.commit()


# ── Components v2 Controller View ─────────────────────────────────────────────

class MusicControllerView(discord.ui.LayoutView):

    def __init__(
        self,
        cog: "MusicCog",
        guild: discord.Guild,
        player: "wavelink.Player | None",
        artwork_media: str,
        interactive: bool = True,
    ) -> None:
        super().__init__(timeout=None if interactive else 180)
        self.cog          = cog
        self.guild        = guild
        self.player       = player
        self.interactive  = interactive and player is not None
        self.artwork_media = artwork_media
        self._build()

    def _build(self) -> None:
        container = discord.ui.Container()
        container.add_item(discord.ui.TextDisplay("# 🎵 Music"))

        if self.player and self.player.current:
            t      = self.player.current
            status = "Paused" if self.player.paused else "Playing"
            pos    = max(0, getattr(self.player, "position", 0))
            container.add_item(discord.ui.TextDisplay(
                f"## {_trunc(t.title, 64)}"
            ))
            container.add_item(discord.ui.TextDisplay(
                f"-# {_trunc(t.author, 56)} · {status} · "
                f"`{_fmt_ms(pos)} / {_fmt_ms(t.length)}`"
            ))
        else:
            container.add_item(discord.ui.TextDisplay("## Nothing is playing"))
            container.add_item(discord.ui.TextDisplay(
                "-# Drop a song name in the music channel or use `/play` to start."
            ))

        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=self.artwork_media, description="Music artwork")
        container.add_item(gallery)

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            self.cog._build_queue_summary(self.player)
        ))
        container.add_item(discord.ui.Separator())

        # ── Control row ────────────────────────────────────────────────────
        controls = discord.ui.ActionRow()

        pause_btn = discord.ui.Button(
            label="Resume" if (self.player and self.player.paused) else "Pause",
            style=(
                discord.ButtonStyle.success
                if (self.player and self.player.paused)
                else discord.ButtonStyle.secondary
            ),
            disabled=not self.interactive,
        )
        skip_btn = discord.ui.Button(
            label="⏭ Skip",
            style=discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )
        stop_btn = discord.ui.Button(
            label="⏹ Stop",
            style=discord.ButtonStyle.danger,
            disabled=not self.interactive,
        )

        if self.interactive:
            pause_btn.callback = self.cog.pause_resume_button_callback
            skip_btn.callback  = self.cog.skip_button_callback
            stop_btn.callback  = self.cog.stop_button_callback

        controls.add_item(pause_btn)
        controls.add_item(skip_btn)
        controls.add_item(stop_btn)
        container.add_item(controls)

        # ── Utility row ────────────────────────────────────────────────────
        utils = discord.ui.ActionRow()

        ap_on   = self.player and self.player.autoplay != wavelink.AutoPlayMode.disabled
        loop_on = self.player and self.player.queue.mode == wavelink.QueueMode.loop

        ap_btn = discord.ui.Button(
            label=f"Autoplay {'On' if ap_on else 'Off'}",
            style=discord.ButtonStyle.success if ap_on else discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )
        loop_btn = discord.ui.Button(
            label=f"Loop {'On' if loop_on else 'Off'}",
            style=discord.ButtonStyle.success if loop_on else discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )
        vol_btn = discord.ui.Button(
            label=f"🔊 Volume {self.player.volume}%" if self.player else "🔊 Volume",
            style=discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )

        if self.interactive:
            ap_btn.callback   = self.cog.autoplay_toggle_callback
            loop_btn.callback = self.cog.loop_toggle_callback
            vol_btn.callback  = self.cog.set_volume_button_callback

        utils.add_item(ap_btn)
        utils.add_item(loop_btn)
        utils.add_item(vol_btn)
        container.add_item(utils)

        self.add_item(container)


# ── Main Cog ──────────────────────────────────────────────────────────────────

class MusicCog(commands.Cog, name="Music"):
    """Music powered by Lavalink with Neroniel Components v2 UI."""

    CONTROLLER_COOLDOWN_SECONDS = 1.5

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id (str) → {channel_id, message_id, default_volume}
        self._music_data: dict[str, dict] = {}
        # guild_id (str) → discord.Message  (when no setup channel)
        self._manual_controller: dict[str, discord.Message] = {}
        # guild_id (int) → datetime  (button rate-limit)
        self._controller_cooldown: dict[int, datetime.datetime] = {}

    # ── Startup ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        await _db_init()
        # Load all music settings into memory cache
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM music_settings") as cur:
                async for row in cur:
                    self._music_data[row["guild_id"]] = dict(row)

        # Connect to Lavalink
        try:
            wavelink.Pool.get_node()
            return
        except wavelink.exceptions.InvalidNodeException:
            pass
        try:
            node = wavelink.Node(
                identifier="Neroniel-Node",
                uri=_LAVALINK_URI,
                password=_LAVALINK_PASS,
            )
            await wavelink.Pool.connect(nodes=[node], client=self.bot, cache_capacity=None)
            print(f"[Music] ✅ Connected to Lavalink node: {_LAVALINK_URI}")
        except Exception:
            print(f"[Music] ⚠ Lavalink connection failed:\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload):
        print(f"[Music] Node '{payload.node.identifier}' is ready (resumed={payload.resumed}).")

    # ── Track events ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player = payload.player
        if not player or not getattr(player, "guild", None):
            return
        await self.send_music_controls(player.guild, update_attachments=True)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        try:
            player = payload.player
            guild  = getattr(player, "guild", None)
            if not player or not guild:
                return

            if player.autoplay != wavelink.AutoPlayMode.disabled:
                for _ in range(5):
                    if player.current:
                        break
                    await asyncio.sleep(1)
                if guild.voice_client:
                    return await self.send_music_controls(guild, update_attachments=True)
                return

            if player.queue.is_empty and not player.queue.mode == wavelink.QueueMode.loop:
                if player.current:
                    return
                await player.disconnect()
                await self.send_music_controls(guild, end=True)
            else:
                try:
                    next_track = player.queue.get()
                except wavelink.exceptions.QueueEmpty:
                    await player.disconnect()
                    await self.send_music_controls(guild, end=True)
                    return
                await player.play(next_track)
                await self.send_music_controls(guild, update_attachments=True)
        except Exception:
            print(f"[Music] Track end error:\n{traceback.format_exc()}")

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        try:
            guild = getattr(player, "guild", None)
            if guild:
                await self.send_music_controls(guild, end=True)
            await player.disconnect()
            if guild:
                print(f"[Music] Disconnected from {guild.name} (inactive).")
        except Exception:
            pass

    # ── Queue text helper ─────────────────────────────────────────────────────

    def _build_queue_summary(self, player: "wavelink.Player | None") -> str:
        if not player or not player.current:
            return "**Queue**\n-# No active session right now."
        lines = [
            "**Queue**",
            f"**Now** — `{_trunc(player.current.title, 52)}`",
        ]
        items = list(player.queue)
        if items:
            for i, track in enumerate(items[:3], 1):
                lines.append(
                    f"**Next {i}** — `{_trunc(track.title, 44)}` — `{_fmt_ms(track.length)}`"
                )
            if len(items) > 3:
                lines.append(f"-# +{len(items) - 3} more waiting")
        else:
            lines.append("-# Queue is empty")
        return "\n".join(lines)

    # ── Controller channel resolution ─────────────────────────────────────────

    async def _resolve_controller(
        self, guild: discord.Guild, command_channel=None
    ) -> tuple:
        """Returns (target_channel, controller_message, music_data)."""
        music_data = self._music_data.get(str(guild.id), {})
        controller_message = self._manual_controller.get(str(guild.id))
        target_channel = command_channel

        chan_id = music_data.get("channel_id")
        if chan_id:
            ch = guild.get_channel(int(chan_id))
            if ch:
                target_channel = ch
                msg_id = music_data.get("message_id")
                if msg_id:
                    try:
                        controller_message = await ch.fetch_message(int(msg_id))
                    except Exception:
                        controller_message = None

        return target_channel, controller_message, music_data

    # ── send_music_controls ───────────────────────────────────────────────────

    async def send_music_controls(
        self,
        guild: discord.Guild,
        update_attachments: bool = False,
        end: bool = False,
        command_channel=None,
    ):
        try:
            target_channel, controller_message, music_data = await self._resolve_controller(
                guild, command_channel
            )
            vc: "wavelink.Player | None" = guild.voice_client

            # ── Idle / ended ───────────────────────────────────────────────
            if end or not vc or not vc.current:
                idle_view = MusicControllerView(
                    cog=self, guild=guild, player=None,
                    artwork_media=_DEFAULT_BANNER, interactive=False,
                )
                if controller_message:
                    try:
                        await controller_message.edit(view=idle_view, attachments=[])
                    except (discord.NotFound, discord.HTTPException):
                        controller_message = None
                elif target_channel:
                    controller_message = await target_channel.send(view=idle_view)

                if controller_message:
                    if music_data.get("channel_id"):
                        await _db_upsert(guild.id, message_id=str(controller_message.id))
                        self._music_data.setdefault(str(guild.id), {})["message_id"] = str(controller_message.id)
                    else:
                        self._manual_controller[str(guild.id)] = controller_message
                return

            # ── Active ─────────────────────────────────────────────────────
            file        = None
            artwork_url = vc.current.artwork or _DEFAULT_BANNER

            if update_attachments or controller_message is None:
                buf = _create_music_banner(
                    thumbnail_url=artwork_url,
                    title=vc.current.title,
                    author=vc.current.author,
                    duration_ms=vc.current.length,
                    position_ms=max(0, getattr(vc, "position", 0)),
                )
                if buf:
                    file        = discord.File(buf, filename="music_controller.png")
                    artwork_url = "attachment://music_controller.png"

            view = MusicControllerView(
                cog=self, guild=guild, player=vc,
                artwork_media=artwork_url, interactive=True,
            )

            if not target_channel:
                if controller_message:
                    target_channel = controller_message.channel
                else:
                    print(f"[Music] No target channel for {guild.name}")
                    return

            if controller_message:
                edit_kw: dict = {"view": view}
                if file:
                    edit_kw["attachments"] = [file]
                try:
                    await controller_message.edit(**edit_kw)
                except (discord.NotFound, discord.HTTPException):
                    controller_message = None

            if not controller_message:
                send_kw: dict = {"view": view}
                if file:
                    send_kw["file"] = file
                controller_message = await target_channel.send(**send_kw)

            if music_data.get("channel_id"):
                await _db_upsert(guild.id, message_id=str(controller_message.id))
                self._music_data.setdefault(str(guild.id), {})["message_id"] = str(controller_message.id)
            else:
                self._manual_controller[str(guild.id)] = controller_message

        except Exception:
            print(f"[Music] Controller error:\n{traceback.format_exc()}")

    # ── Button interaction validator ──────────────────────────────────────────

    async def _validate_controller_interaction(
        self, interaction: discord.Interaction
    ) -> "wavelink.Player | None":
        vc: "wavelink.Player | None" = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(
                embed=discord.Embed(description="The player is offline right now.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None
        if not interaction.user.voice:
            await interaction.response.send_message(
                embed=discord.Embed(description="Join a voice channel to use the controller.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None
        if vc.channel != interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=discord.Embed(description="You need to be in the same voice channel.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None

        last = self._controller_cooldown.get(interaction.guild.id)
        if last and datetime.datetime.now() - last < datetime.timedelta(seconds=self.CONTROLLER_COOLDOWN_SECONDS):
            await interaction.response.send_message(
                embed=discord.Embed(description="Controller is refreshing — try again in a moment.", color=discord.Color.orange()),
                ephemeral=True, delete_after=4,
            )
            return None

        self._controller_cooldown[interaction.guild.id] = datetime.datetime.now()
        return vc

    # ── Button callbacks (cog methods, assigned in _build) ────────────────────

    async def pause_resume_button_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return
            await interaction.response.defer()
            if vc.paused:
                await vc.pause(False)
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("▶️ Playback resumed.", ephemeral=True)
            else:
                await vc.pause(True)
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("⏸ Playback paused.", ephemeral=True)
        except Exception:
            print(f"[Music] pause_resume error:\n{traceback.format_exc()}")

    async def skip_button_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return
            await interaction.response.defer()
            if vc.queue or vc.autoplay != wavelink.AutoPlayMode.disabled:
                await vc.skip(force=True)
                await interaction.followup.send("⏭ Skipped.", ephemeral=True)
            else:
                await interaction.followup.send("Nothing left in queue to skip into.", ephemeral=True)
        except Exception:
            print(f"[Music] skip error:\n{traceback.format_exc()}")

    async def stop_button_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return
            await interaction.response.defer()
            vc.queue.clear()
            await vc.stop()
            await vc.disconnect()
            await self.send_music_controls(interaction.guild, end=True)
            await interaction.followup.send("⏹ Player stopped and disconnected.", ephemeral=True)
        except Exception:
            print(f"[Music] stop error:\n{traceback.format_exc()}")

    async def loop_toggle_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return
            await interaction.response.defer()
            if vc.queue.mode == wavelink.QueueMode.loop:
                vc.queue.mode = wavelink.QueueMode.normal
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("🔁 Loop **disabled**.", ephemeral=True)
            else:
                vc.queue.mode = wavelink.QueueMode.loop
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("🔁 Loop **enabled**.", ephemeral=True)
        except Exception:
            print(f"[Music] loop error:\n{traceback.format_exc()}")

    async def autoplay_toggle_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return
            await interaction.response.defer()
            if vc.autoplay == wavelink.AutoPlayMode.disabled:
                vc.autoplay = wavelink.AutoPlayMode.enabled
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("🔀 Autoplay **enabled**.", ephemeral=True)
            else:
                vc.autoplay = wavelink.AutoPlayMode.disabled
                await self.send_music_controls(interaction.guild, update_attachments=True)
                await interaction.followup.send("🔀 Autoplay **disabled**.", ephemeral=True)
        except Exception:
            print(f"[Music] autoplay error:\n{traceback.format_exc()}")

    async def set_volume_button_callback(self, interaction: discord.Interaction):
        try:
            vc = await self._validate_controller_interaction(interaction)
            if not vc:
                return

            cog = self

            class VolumeModal(discord.ui.Modal, title="Set Volume"):
                new_volume_field = discord.ui.TextInput(
                    label="Volume (0–100)",
                    min_length=1,
                    max_length=3,
                    required=True,
                    default=str(vc.volume),
                    placeholder="Enter volume (0-100)",
                    style=discord.TextStyle.short,
                )

                async def on_submit(self_, i: discord.Interaction):
                    try:
                        iv: "wavelink.Player | None" = i.guild.voice_client
                        if not iv:
                            return await i.response.send_message(
                                embed=discord.Embed(description="The bot disconnected.", color=discord.Color.red()),
                                ephemeral=True, delete_after=8,
                            )
                        try:
                            volume = int(self_.new_volume_field.value)
                        except ValueError:
                            return await i.response.send_message(
                                embed=discord.Embed(description="Invalid volume value.", color=discord.Color.red()),
                                ephemeral=True, delete_after=8,
                            )
                        if not 0 <= volume <= 100:
                            return await i.response.send_message(
                                embed=discord.Embed(description="Volume must be between 0 and 100.", color=discord.Color.red()),
                                ephemeral=True, delete_after=8,
                            )
                        await i.response.defer()
                        await iv.set_volume(volume)
                        await cog.send_music_controls(i.guild, update_attachments=True)
                        await i.followup.send(f"🔊 Volume set to **{volume}%**.", ephemeral=True)
                    except Exception:
                        print(f"[Music] VolumeModal error:\n{traceback.format_exc()}")

            await interaction.response.send_modal(VolumeModal())
        except Exception:
            print(f"[Music] set_volume error:\n{traceback.format_exc()}")

    # ── VC connect helper ─────────────────────────────────────────────────────

    async def _ensure_connected(self, ctx: commands.Context) -> "wavelink.Player | None":
        if not ctx.author.voice:
            await ctx.reply("❌ Join a voice channel first.", delete_after=10)
            return None
        dest = ctx.author.voice.channel
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            try:
                vc = await dest.connect(cls=wavelink.Player, self_deaf=True)
                vc.inactive_timeout = 300
            except Exception:
                await ctx.reply("❌ Could not connect to your voice channel.", delete_after=10)
                return None
        else:
            if vc.channel != dest:
                if not vc.current:
                    await vc.move_to(dest)
                else:
                    await ctx.reply("❌ I'm already playing in another voice channel.", delete_after=10)
                    return None
        return vc

    # ── Search helper ─────────────────────────────────────────────────────────

    async def _search(self, query: str):
        is_url = bool(_URL_RE.match(query.strip()))
        attempts = [query] if is_url else [f"ytsearch:{query}", f"scsearch:{query}", query]
        for attempt in attempts:
            try:
                results = await wavelink.Playable.search(attempt)
                if results:
                    return results
            except Exception as exc:
                print(f"[Music] Search '{attempt}' failed: {exc}")
        return None

    # ── on_message — dedicated music channel ──────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        music_data = self._music_data.get(str(message.guild.id), {})
        chan_id = music_data.get("channel_id")
        if not chan_id or message.channel.id != int(chan_id):
            return
        await self._music_channel_play(message)

    async def _music_channel_play(self, message: discord.Message):
        try:
            try:
                await message.delete()
            except Exception:
                pass

            if not message.author.voice:
                return await message.channel.send(
                    "❌ You need to be in a voice channel.", delete_after=10
                )

            vc: "wavelink.Player | None" = message.guild.voice_client
            if not vc:
                try:
                    vc = await message.author.voice.channel.connect(
                        cls=wavelink.Player, timeout=60, self_deaf=True
                    )
                    vc.inactive_timeout = 300
                except Exception:
                    return await message.channel.send("❌ Failed to connect to voice channel.", delete_after=5)
            else:
                if vc.channel != message.author.voice.channel:
                    if not vc.current:
                        await vc.move_to(message.author.voice.channel)
                    else:
                        return await message.channel.send(
                            "❌ I'm already playing in another voice channel.", delete_after=5
                        )

            search = message.content.strip()
            if not search:
                return await message.channel.send("❌ Please provide a song name or URL.", delete_after=5)

            results = await self._search(search)
            if not results:
                return await message.channel.send("❌ No results found.", delete_after=5)

            track = results[0]
            music_data = self._music_data.get(str(message.guild.id), {})
            default_vol = int(music_data.get("default_volume") or 80)

            if not vc.current:
                await vc.play(track, volume=default_vol)
                await self.send_music_controls(message.guild, update_attachments=True)
                await message.channel.send(f"✅ Playing: **{track.title}**", delete_after=5)
            else:
                if len(vc.queue) >= 50:
                    return await message.channel.send("❌ Queue is full (50 tracks max).", delete_after=5)
                await vc.queue.put_wait(track)
                await self.send_music_controls(message.guild)
                await message.channel.send(
                    f"📋 Added to queue: **{track.title}**", delete_after=5
                )
        except Exception:
            print(f"[Music] music_channel_play error:\n{traceback.format_exc()}")

    # ── /play ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song or add it to the queue.", with_app_command=True)
    @app_commands.describe(search="Song name or URL")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, search: str):
        try:
            if ctx.interaction:
                try:
                    await ctx.defer()
                except discord.errors.NotFound:
                    return

            # If a dedicated music channel is configured, redirect there
            music_data = self._music_data.get(str(ctx.guild.id), {})
            chan_id = music_data.get("channel_id")
            if chan_id:
                ch = ctx.guild.get_channel(int(chan_id))
                if ch and ctx.channel.id != int(chan_id):
                    return await ctx.reply(
                        embed=discord.Embed(
                            description=f"🎵 Send song names directly in <#{chan_id}> to play music.\nUse `/music reset` to remove the setup.",
                            color=discord.Color.red(),
                        )
                    )

            vc = await self._ensure_connected(ctx)
            if not vc:
                return

            results = await self._search(search)
            if not results:
                return await ctx.reply("❌ No results found. Try a different search term.", delete_after=10)

            default_vol = int(music_data.get("default_volume") or 80)

            if isinstance(results, wavelink.Playlist):
                tracks = results.tracks
                await vc.queue.put_wait(tracks)
                await ctx.reply(f"📋 Added playlist **{results.name}** ({len(tracks)} tracks) to the queue.")
                if not vc.current:
                    await vc.play(vc.queue.get(), volume=default_vol)
                await self.send_music_controls(ctx.guild, update_attachments=True, command_channel=ctx.channel)
            else:
                track = results[0]
                if not vc.current:
                    await vc.play(track, volume=default_vol)
                    await ctx.reply(f"▶️ Now playing **{_trunc(track.title)}**.")
                    await self.send_music_controls(ctx.guild, update_attachments=True, command_channel=ctx.channel)
                else:
                    if len(vc.queue) >= 50:
                        return await ctx.reply("❌ Queue is full (50 tracks max).", delete_after=10)
                    await vc.queue.put_wait(track)
                    await ctx.reply(f"📋 Added **{_trunc(track.title)}** to the queue (position {len(vc.queue)}).")
                    await self.send_music_controls(ctx.guild, command_channel=ctx.channel)
        except Exception:
            print(f"[Music] play error:\n{traceback.format_exc()}")

    # ── /pause ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="pause", description="Pause the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if vc.paused:
            return await ctx.reply("⏸ Already paused.", delete_after=8)
        await vc.pause(True)
        await self.send_music_controls(ctx.guild)
        await ctx.reply("⏸ Paused.")

    # ── /resume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="resume", description="Resume the paused track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if not vc.paused:
            return await ctx.reply("▶️ Already playing.", delete_after=8)
        await vc.pause(False)
        await self.send_music_controls(ctx.guild)
        await ctx.reply("▶️ Resumed.")

    # ── /skip ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="skip", description="Skip the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if not vc.playing and not vc.paused:
            return await ctx.reply("❌ No track is currently playing.", delete_after=10)
        await vc.stop()
        await ctx.reply("⏭ Skipped.")

    # ── /loop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="loop", description="Toggle loop mode.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def loop(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            await ctx.reply("✅ Looping **disabled**.")
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            await ctx.reply("✅ Looping **enabled**.")
        await self.send_music_controls(ctx.guild)

    # ── /autoplay ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="autoplay", description="Toggle autoplay mode.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def autoplay(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if vc.autoplay == wavelink.AutoPlayMode.disabled:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            await ctx.reply("✅ Autoplay **enabled**.")
        else:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            await ctx.reply("✅ Autoplay **disabled**.")
        await self.send_music_controls(ctx.guild)

    # ── /stop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="stop", description="Stop the player and disconnect.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            # Try forcefully disconnecting if somehow stuck
            if ctx.guild.me.voice:
                try:
                    await ctx.guild.me.move_to(None)
                    return await ctx.reply("✅ Disconnected.", delete_after=10)
                except Exception:
                    pass
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        vc.queue.clear()
        await vc.stop()
        await vc.disconnect()
        await self.send_music_controls(ctx.guild, end=True)
        await ctx.reply("⏹ Player stopped and disconnected.", delete_after=10)

    # ── /current (/nowplaying) ────────────────────────────────────────────────

    @commands.hybrid_command(name="current", aliases=["nowplaying", "np"], description="Show the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def current(self, ctx: commands.Context):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ No track is currently playing.", delete_after=10)
        await ctx.reply(
            f"{'⏸️' if vc.paused else '▶️'} **{vc.current.title}** by `{vc.current.author}` "
            f"— `{_fmt_ms(max(0, getattr(vc, 'position', 0)))} / {_fmt_ms(vc.current.length)}`"
        )

    # ── /volume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="volume", aliases=["vol", "v"], description="Get or set the volume.", with_app_command=True)
    @app_commands.describe(volume="Volume (0-100), leave blank to check current")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, volume: int = None):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc:
            return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        if volume is None:
            return await ctx.reply(f"🔊 Current volume: **{vc.volume}%**")
        if not 0 <= volume <= 100:
            return await ctx.reply("❌ Volume must be between 0 and 100.", delete_after=10)
        await vc.set_volume(volume)
        filled = volume // 10
        bar = "█" * filled + "░" * (10 - filled)
        await ctx.reply(f"🔊 Volume set to **{volume}%**\n`{bar}`")
        await self.send_music_controls(ctx.guild, update_attachments=True)

    # ── /queue ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="queue", aliases=["q", "tracks"], description="Show the queue.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def queue(self, ctx: commands.Context):
        try:
            if ctx.interaction:
                try:
                    await ctx.defer()
                except discord.errors.NotFound:
                    return

            vc: "wavelink.Player | None" = ctx.guild.voice_client
            if not vc:
                return await ctx.reply("❌ The bot is not connected to any voice channel.", delete_after=10)

            async def build_embed():
                embed = discord.Embed(title="🎵 Track Queue", description="", color=discord.Color.dark_theme())
                if vc.current:
                    title = _trunc(vc.current.title, 50)
                    icon  = "⏸️" if vc.paused else "▶️"
                    embed.description += f"**{icon} 1. {title}** — `{_fmt_ms(vc.current.length)}`\n"
                for i, track in enumerate(vc.queue, start=2):
                    embed.description += f"**🎵 {i}. {_trunc(track.title, 50)}** — `{_fmt_ms(track.length)}`\n"
                if not vc.current and vc.queue.is_empty:
                    embed.description = "Queue is empty."
                return embed

            timeout_time = 60
            cancelled = False

            async def build_view(disabled=False):
                nonlocal timeout_time
                timeout_time = 60
                view = discord.ui.View()
                options = []
                for i, track in enumerate(vc.queue):
                    options.append(discord.SelectOption(
                        label=_trunc(track.title, 50),
                        value=str(i),
                        description=f"Length: {_fmt_ms(track.length)}",
                        emoji="🎵",
                    ))
                if options:
                    sel = discord.ui.Select(
                        placeholder="Select a track to remove from queue",
                        options=options[:25],
                    )

                    async def sel_callback(interaction: discord.Interaction):
                        if interaction.user.id != ctx.author.id:
                            return await interaction.response.send_message(
                                "❌ You can't use this.", ephemeral=True, delete_after=5
                            )
                        await interaction.response.defer()
                        idx = int(interaction.data["values"][0])
                        if idx < len(list(vc.queue)):
                            vc.queue.delete(idx)
                        await msg.edit(embed=await build_embed(), view=await build_view())

                    sel.callback = sel_callback
                    if not disabled:
                        view.add_item(sel)
                return view

            msg = await ctx.send(embed=await build_embed(), view=await build_view())

            while not cancelled:
                timeout_time -= 1
                if timeout_time <= 0:
                    try:
                        await msg.edit(view=await build_view(disabled=True))
                    except Exception:
                        pass
                    break
                await asyncio.sleep(1)

        except Exception:
            print(f"[Music] queue error:\n{traceback.format_exc()}")

    # ── /seek ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="seek", description="Seek to a position in the current track (seconds).", with_app_command=True)
    @app_commands.describe(seconds="Position in seconds")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def seek(self, ctx: commands.Context, seconds: int):
        if ctx.interaction:
            try:
                await ctx.defer()
            except discord.errors.NotFound:
                return
        vc: "wavelink.Player | None" = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ No track is currently playing.", delete_after=10)
        if not ctx.author.voice or vc.channel != ctx.author.voice.channel:
            return await ctx.reply("❌ You need to be in the same voice channel.", delete_after=10)
        ms = seconds * 1000
        if not 0 <= ms <= vc.current.length:
            return await ctx.reply(f"❌ Seek position must be between 0 and {_fmt_ms(vc.current.length)}.", delete_after=10)
        await vc.seek(ms)
        await ctx.reply(f"⏩ Seeked to **{_fmt_ms(ms)}**.")
        await self.send_music_controls(ctx.guild, update_attachments=True)

    # ── /music group ──────────────────────────────────────────────────────────

    @commands.hybrid_group(name="music", description="Music configuration commands.", with_app_command=True, invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_cmd(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🎵 Music Config",
            description=(
                "**`/music setup`** — Create a dedicated music channel\n"
                "**`/music reset`** — Remove the dedicated music channel\n"
                "**`/music settings`** — View and edit music settings"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.send(embed=embed)

    @music_cmd.command(name="setup", description="Create a dedicated music channel.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_setup(self, ctx: commands.Context):
        try:
            if ctx.interaction:
                try:
                    await ctx.defer(ephemeral=True)
                except discord.errors.NotFound:
                    return

            music_data = self._music_data.get(str(ctx.guild.id), {})
            if music_data.get("channel_id"):
                return await ctx.reply(
                    embed=discord.Embed(
                        description=f"❌ A music channel already exists: <#{music_data['channel_id']}>\nUse `/music reset` to remove it first.",
                        color=discord.Color.red(),
                    ).set_footer(text="Use /music reset to reset the music channel."),
                    delete_after=15,
                )

            wait_msg = await ctx.send("⏳ Creating the music channel...")
            try:
                ch = await ctx.guild.create_text_channel(name="🎸-music-channel")
            except Exception:
                return await wait_msg.edit(content="❌ Failed to create the music channel.")

            await _db_upsert(ctx.guild.id, channel_id=str(ch.id), message_id=None, default_volume=80)
            self._music_data[str(ctx.guild.id)] = {
                "guild_id": str(ctx.guild.id),
                "channel_id": str(ch.id),
                "message_id": None,
                "default_volume": 80,
            }
            await wait_msg.edit(content=f"✅ Music channel created: <#{ch.id}>")
            await self.send_music_controls(ctx.guild, end=True)

        except Exception:
            print(f"[Music] music_setup error:\n{traceback.format_exc()}")

    @music_cmd.command(name="reset", description="Remove the dedicated music channel.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_reset(self, ctx: commands.Context):
        try:
            if ctx.interaction:
                try:
                    await ctx.defer(ephemeral=True)
                except discord.errors.NotFound:
                    return

            music_data = self._music_data.get(str(ctx.guild.id), {})
            if not music_data.get("channel_id"):
                return await ctx.reply(
                    embed=discord.Embed(
                        description="❌ No dedicated music channel is set.\nUse `/music setup` to create one.",
                        color=discord.Color.red(),
                    ),
                    delete_after=10,
                )

            wait_msg = await ctx.send("⏳ Removing the music channel...")
            ch = ctx.guild.get_channel(int(music_data["channel_id"]))
            if ch:
                try:
                    await ch.delete()
                except Exception:
                    pass

            await _db_upsert(ctx.guild.id, channel_id=None, message_id=None)
            self._music_data.pop(str(ctx.guild.id), None)
            self._manual_controller.pop(str(ctx.guild.id), None)
            await wait_msg.edit(content="✅ Music channel removed.")

        except Exception:
            print(f"[Music] music_reset error:\n{traceback.format_exc()}")

    @music_cmd.command(name="settings", description="View and edit music settings.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_settings(self, ctx: commands.Context):
        try:
            if ctx.interaction:
                try:
                    await ctx.defer(ephemeral=True)
                except discord.errors.NotFound:
                    return

            # Ensure a DB row exists for this guild
            if str(ctx.guild.id) not in self._music_data:
                await _db_upsert(ctx.guild.id, default_volume=80)
                self._music_data[str(ctx.guild.id)] = {
                    "guild_id": str(ctx.guild.id), "channel_id": None,
                    "message_id": None, "default_volume": 80,
                }

            async def build_embed():
                data = self._music_data.get(str(ctx.guild.id), {})
                embed = discord.Embed(
                    title="🎵 Music Settings",
                    description="Configure music settings for this server.",
                    color=discord.Color.green(),
                )
                embed.add_field(
                    name="Default Volume",
                    value=f"`{data.get('default_volume') or 80}%`",
                    inline=True,
                )
                embed.add_field(
                    name="Music Channel",
                    value=(f"<#{data['channel_id']}>" if data.get("channel_id") else "`Not set`"),
                    inline=True,
                )
                embed.set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
                if ctx.guild.icon:
                    embed.set_thumbnail(url=ctx.guild.icon.url)
                return embed

            timeout_time = 200
            cancelled = False

            async def build_view(disabled=False):
                nonlocal timeout_time
                timeout_time = 200
                view = discord.ui.View(timeout=200)

                vol_btn = discord.ui.Button(
                    label="Set Default Volume",
                    style=discord.ButtonStyle.primary,
                    emoji="🔊",
                    row=0,
                )
                cancel_btn = discord.ui.Button(
                    label="Cancel",
                    style=discord.ButtonStyle.secondary,
                    emoji="❌",
                    row=0,
                )

                data = self._music_data.get(str(ctx.guild.id), {})
                default_values = []
                if data.get("channel_id"):
                    ch = ctx.guild.get_channel(int(data["channel_id"]))
                    if ch:
                        default_values = [ch]

                chan_select = discord.ui.ChannelSelect(
                    placeholder="Select dedicated music channel (optional)",
                    min_values=0,
                    max_values=1,
                    row=1,
                    channel_types=[discord.ChannelType.text],
                    default_values=default_values,
                )

                async def vol_btn_callback(interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
                    cur_vol = str(self._music_data.get(str(ctx.guild.id), {}).get("default_volume") or 80)

                    class VolumeModal(discord.ui.Modal, title="Set Default Volume"):
                        new_vol = discord.ui.TextInput(
                            label="Default Volume (0–100)",
                            placeholder="80",
                            required=True,
                            max_length=3,
                            default=cur_vol,
                            style=discord.TextStyle.short,
                        )

                        async def on_submit(self_, i: discord.Interaction):
                            try:
                                v = int(self_.new_vol.value)
                            except ValueError:
                                return await i.response.send_message("❌ Invalid number.", ephemeral=True, delete_after=5)
                            if not 0 <= v <= 100:
                                return await i.response.send_message("❌ Must be 0–100.", ephemeral=True, delete_after=5)
                            await i.response.defer()
                            await _db_upsert(ctx.guild.id, default_volume=v)
                            self._music_data.setdefault(str(ctx.guild.id), {})["default_volume"] = v
                            await msg.edit(embed=await build_embed(), view=await build_view())

                    await interaction.response.send_modal(VolumeModal())

                async def cancel_callback(interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        return await interaction.response.send_message("❌ Not your button.", ephemeral=True)
                    nonlocal cancelled
                    cancelled = True
                    await interaction.response.defer()
                    await msg.edit(embed=await build_embed(), view=await build_view(disabled=True))

                async def chan_select_callback(interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        return await interaction.response.send_message("❌ Not your select.", ephemeral=True)
                    await interaction.response.defer()
                    values = interaction.data.get("values", [])
                    chan_id = values[0] if values else None
                    await _db_upsert(ctx.guild.id, channel_id=chan_id, message_id=None)
                    self._music_data.setdefault(str(ctx.guild.id), {})["channel_id"] = chan_id
                    self._music_data[str(ctx.guild.id)]["message_id"] = None
                    await msg.edit(embed=await build_embed(), view=await build_view())

                vol_btn.callback    = vol_btn_callback
                cancel_btn.callback = cancel_callback
                chan_select.callback = chan_select_callback

                view.add_item(vol_btn)
                view.add_item(cancel_btn)
                view.add_item(chan_select)

                if disabled:
                    for item in view.children:
                        item.disabled = True

                return view

            msg = await ctx.send(embed=await build_embed(), view=await build_view())

            while not cancelled:
                timeout_time -= 1
                if timeout_time <= 0:
                    try:
                        await msg.edit(embed=await build_embed(), view=await build_view(disabled=True))
                    except Exception:
                        pass
                    break
                await asyncio.sleep(1)

        except Exception:
            print(f"[Music] music_settings error:\n{traceback.format_exc()}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
