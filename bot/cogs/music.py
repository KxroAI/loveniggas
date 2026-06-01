"""
Music Cog — wavelink 3.x / Lavalink
Components v2 controller (LayoutView + Container + MediaGallery)
PIL-generated banner image
Commands: play, pause, resume, skip, stop, loop, queue, volume,
          autoplay, nowplaying, seek  +  music setup/reset/settings
"""

import asyncio
import datetime
import io
import os
import re
import traceback

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# ── Config ────────────────────────────────────────────────────────────────────

_LAVALINK_URI  = os.getenv("LAVALINK_URI",      "https://lavalink.jirayu.net:443")
_LAVALINK_PASS = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")

_DEFAULT_BANNER = (
    "https://media.discordapp.net/attachments/1229366361826918405"
    "/1357196877023547492/images_21.jpg"
    "?ex=67ef5396&is=67ee0216&hm=065303d8f2472468d5a0a4813839aadbd08fb10d"
    "556739ef9907bece29f4c034&"
)

_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_ms(ms: int) -> str:
    try:
        s = int(ms) // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
    except Exception:
        return "???"


def _trunc(text: str, limit: int = 60) -> str:
    if not text:
        return "Unknown"
    return text if len(text) <= limit else f"{text[:limit - 3]}..."


# ── PIL banner generator (adapted from reference bot) ─────────────────────────

def _create_music_banner(
    thumbnail_url: str,
    title: str,
    author: str,
    duration_ms: int,
    position_ms: int,
) -> io.BytesIO | None:
    """
    Generates a 1200×300 music banner image and returns it as a BytesIO.
    Falls back to None if PIL is unavailable or something goes wrong.
    """
    if not _PIL_OK:
        return None
    try:
        import urllib.request as _urllib

        width, height = 1200, 300

        def _load(url: str) -> Image.Image:
            try:
                req = _urllib.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with _urllib.urlopen(req, timeout=8) as r:
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

        raw   = _load(thumbnail_url or _DEFAULT_BANNER)
        bg    = raw.resize((width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(radius=20))
        over  = Image.new("RGBA", (width, height), (0, 0, 0, 180))
        canvas = Image.alpha_composite(bg, over)
        draw  = ImageDraw.Draw(canvas)

        # Thumbnail
        art_size = 200
        ax, ay   = 50, 50
        art = raw.resize((art_size, art_size), Image.LANCZOS)
        mask = Image.new("L", (art_size, art_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, art_size, art_size], radius=15, fill=255)
        canvas.paste(art, (ax, ay), mask=mask)

        # Fonts
        try:
            f_title  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            f_artist = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
            f_time   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        except Exception:
            f_title = f_artist = f_time = ImageFont.load_default()

        info_x   = ax + art_size + 40
        max_tw   = width - info_x - 50
        draw.text((info_x, 60),  _fit(draw, title,  f_title,  max_tw), fill=(255, 255, 255, 255), font=f_title)
        draw.text((info_x, 110), _fit(draw, author, f_artist, max_tw), fill=(180, 180, 180, 255), font=f_artist)

        # Progress bar
        bx, by, bw, bh = info_x, 160, max_tw, 12
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=6, fill=(255, 255, 255, 40))
        ratio = max(0.0, min(1.0, position_ms / duration_ms if duration_ms > 0 else 0.0))
        pw = int(bw * ratio)
        if pw > 0:
            draw.rounded_rectangle([bx, by, bx + pw, by + bh], radius=6, fill=(255, 255, 255, 255))

        cur  = _fmt_ms(max(position_ms, 0))
        tot  = _fmt_ms(max(duration_ms, 0))
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


# ── Components v2 Controller View ─────────────────────────────────────────────

class MusicControllerView(discord.ui.LayoutView):
    """Components v2 music controller using Container + MediaGallery."""

    def __init__(
        self,
        cog: "MusicCog",
        guild: discord.Guild,
        player: wavelink.Player | None,
        artwork_url: str,
        interactive: bool = True,
    ) -> None:
        super().__init__(timeout=None if interactive else 180)
        self.cog        = cog
        self.guild      = guild
        self.player     = player
        self.interactive = interactive and player is not None
        self.artwork_url = artwork_url
        self._build()

    def _build(self) -> None:
        container = discord.ui.Container(accent_colour=discord.Colour.blurple())

        # ── Title ──────────────────────────────────────────────────────────
        container.add_item(discord.ui.TextDisplay("# 🎵 Music"))

        # ── Now playing info ───────────────────────────────────────────────
        if self.player and self.player.current:
            t      = self.player.current
            status = "⏸ Paused" if self.player.paused else "▶️ Playing"
            pos    = max(0, getattr(self.player, "position", 0))
            loop   = "🔁" if self.player.queue.mode == wavelink.QueueMode.loop else ""
            ap     = "🔀" if self.player.autoplay != wavelink.AutoPlayMode.disabled else ""

            container.add_item(discord.ui.TextDisplay(
                f"## {_trunc(t.title, 64)}"
            ))
            container.add_item(discord.ui.TextDisplay(
                f"-# {_trunc(t.author, 48)} · {status} {loop}{ap} · "
                f"`{_fmt_ms(pos)} / {_fmt_ms(t.length)}`"
            ))
        else:
            container.add_item(discord.ui.TextDisplay("## Nothing is playing"))
            container.add_item(discord.ui.TextDisplay(
                "-# Use `/play` to start a session."
            ))

        # ── Artwork ────────────────────────────────────────────────────────
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=self.artwork_url, description="Now playing artwork")
        container.add_item(gallery)

        container.add_item(discord.ui.Separator())

        # ── Queue summary ──────────────────────────────────────────────────
        container.add_item(discord.ui.TextDisplay(
            self._queue_summary()
        ))

        container.add_item(discord.ui.Separator())

        # ── Control buttons ────────────────────────────────────────────────
        controls = discord.ui.ActionRow()

        is_paused = self.player and self.player.paused
        pause_btn = discord.ui.Button(
            label="▶️ Resume" if is_paused else "⏸ Pause",
            style=discord.ButtonStyle.success if is_paused else discord.ButtonStyle.secondary,
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
            pause_btn.callback = self._pause_callback
            skip_btn.callback  = self._skip_callback
            stop_btn.callback  = self._stop_callback

        controls.add_item(pause_btn)
        controls.add_item(skip_btn)
        controls.add_item(stop_btn)
        container.add_item(controls)

        # ── Utility buttons ────────────────────────────────────────────────
        utils = discord.ui.ActionRow()

        loop_on = self.player and self.player.queue.mode == wavelink.QueueMode.loop
        ap_on   = self.player and self.player.autoplay != wavelink.AutoPlayMode.disabled

        loop_btn = discord.ui.Button(
            label="🔁 Loop: On" if loop_on else "🔁 Loop: Off",
            style=discord.ButtonStyle.success if loop_on else discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )
        ap_btn = discord.ui.Button(
            label="🔀 Autoplay: On" if ap_on else "🔀 Autoplay: Off",
            style=discord.ButtonStyle.success if ap_on else discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )
        vol_btn = discord.ui.Button(
            label=f"🔊 Volume {self.player.volume}%" if self.player else "🔊 Volume",
            style=discord.ButtonStyle.secondary,
            disabled=not self.interactive,
        )

        if self.interactive:
            loop_btn.callback = self._loop_callback
            ap_btn.callback   = self._autoplay_callback
            vol_btn.callback  = self._volume_callback

        utils.add_item(loop_btn)
        utils.add_item(ap_btn)
        utils.add_item(vol_btn)
        container.add_item(utils)

        self.add_item(container)

    # ── Queue text helper ──────────────────────────────────────────────────

    def _queue_summary(self) -> str:
        if not self.player or not self.player.current:
            return "**Queue**\n-# No active session."
        t     = self.player.current
        lines = [
            "**Queue**",
            f"**Now** · `{_trunc(t.title, 52)}`",
        ]
        items = list(self.player.queue)
        if items:
            for i, track in enumerate(items[:3], 1):
                lines.append(f"**Next {i}** · `{_trunc(track.title, 44)}` · `{_fmt_ms(track.length)}`")
            if len(items) > 3:
                lines.append(f"-# +{len(items) - 3} more in queue")
        else:
            lines.append("-# Queue is empty")
        return "\n".join(lines)

    # ── Validation helper ──────────────────────────────────────────────────

    async def _validate(self, interaction: discord.Interaction) -> wavelink.Player | None:
        vc: wavelink.Player | None = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ The player is not running.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None
        if not interaction.user.voice:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ Join a voice channel first.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None
        if vc.channel != interaction.user.voice.channel:
            await interaction.response.send_message(
                embed=discord.Embed(description="❌ You must be in the same voice channel.", color=discord.Color.red()),
                ephemeral=True, delete_after=8,
            )
            return None
        return vc

    # ── Button callbacks ───────────────────────────────────────────────────

    async def _pause_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        await vc.pause(not vc.paused)
        state = "⏸ Paused" if vc.paused else "▶️ Resumed"
        await interaction.response.send_message(f"{state}.", ephemeral=True, delete_after=5)
        await self.cog.send_music_controls(interaction.guild)

    async def _skip_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        await vc.stop()
        await interaction.response.send_message("⏭ Skipped.", ephemeral=True, delete_after=5)

    async def _stop_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        vc.queue.clear()
        await vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹ Stopped and disconnected.", ephemeral=True, delete_after=5)
        await self.cog.send_music_controls(interaction.guild, end=True)

    async def _loop_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            msg = "🔁 Loop **disabled**."
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            msg = "🔁 Loop **enabled**."
        await interaction.response.send_message(msg, ephemeral=True, delete_after=5)
        await self.cog.send_music_controls(interaction.guild)

    async def _autoplay_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        if vc.autoplay == wavelink.AutoPlayMode.disabled:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            msg = "🔀 Autoplay **enabled**."
        else:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            msg = "🔀 Autoplay **disabled**."
        await interaction.response.send_message(msg, ephemeral=True, delete_after=5)
        await self.cog.send_music_controls(interaction.guild)

    async def _volume_callback(self, interaction: discord.Interaction):
        vc = await self._validate(interaction)
        if not vc:
            return
        cog = self.cog

        class VolumeModal(discord.ui.Modal, title="Set Volume"):
            vol_input = discord.ui.TextInput(
                label="Volume (0–100)",
                placeholder="80",
                required=True,
                max_length=3,
            )

            async def on_submit(self_, i: discord.Interaction):
                try:
                    v = int(self_.vol_input.value)
                except ValueError:
                    return await i.response.send_message("❌ Invalid number.", ephemeral=True, delete_after=5)
                if not 0 <= v <= 100:
                    return await i.response.send_message("❌ Must be 0–100.", ephemeral=True, delete_after=5)
                await vc.set_volume(v)
                await i.response.send_message(f"🔊 Volume set to **{v}%**.", ephemeral=True, delete_after=5)
                await cog.send_music_controls(i.guild)

        await interaction.response.send_modal(VolumeModal())


# ── Main Cog ──────────────────────────────────────────────────────────────────

class MusicCog(commands.Cog, name="Music"):
    """Music powered by Lavalink with Components v2 controller."""

    CONTROLLER_COOLDOWN = 2.0  # seconds

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id (str) → discord.Message
        self._controllers:   dict[str, discord.Message] = {}
        self._last_update:   dict[str, datetime.datetime] = {}
        # guild_id (str) → int (dedicated music channel)
        self._music_channels: dict[str, int] = {}

    # ── Lavalink connection ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
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
        if not player or not player.guild:
            return
        await self.send_music_controls(player.guild, update_attachments=True)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player = payload.player
        if not player or not player.guild:
            return
        if player.autoplay != wavelink.AutoPlayMode.disabled:
            for _ in range(5):
                if player.current:
                    break
                await asyncio.sleep(1)
            if player.guild.voice_client:
                return await self.send_music_controls(player.guild, update_attachments=True)
            return
        if player.queue.is_empty and not player.current:
            await player.disconnect()
            await self.send_music_controls(player.guild, end=True)
        else:
            await self.send_music_controls(player.guild, update_attachments=True)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        try:
            await self.send_music_controls(player.guild, end=True)
            await player.disconnect()
            print(f"[Music] Disconnected from {player.guild.name} (inactive).")
        except Exception:
            pass

    # ── Controller helpers ────────────────────────────────────────────────────

    def _get_controller_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cid = self._music_channels.get(str(guild.id))
        return guild.get_channel(cid) if cid else None

    async def send_music_controls(
        self,
        guild: discord.Guild,
        update_attachments: bool = False,
        end: bool = False,
        command_channel: discord.abc.Messageable | None = None,
    ):
        """Create or edit the now-playing controller message."""
        try:
            now  = datetime.datetime.now()
            last = self._last_update.get(str(guild.id))
            if (
                last
                and not end
                and not update_attachments
                and (now - last).total_seconds() < self.CONTROLLER_COOLDOWN
            ):
                return
            self._last_update[str(guild.id)] = now

            vc: wavelink.Player | None = guild.voice_client

            target_channel = self._get_controller_channel(guild) or command_channel

            # ── Idle / ended state ─────────────────────────────────────────
            if end or not vc or not vc.current:
                idle_view = MusicControllerView(
                    cog=self, guild=guild, player=None,
                    artwork_url=_DEFAULT_BANNER, interactive=False,
                )
                existing = self._controllers.get(str(guild.id))
                if existing:
                    try:
                        await existing.edit(view=idle_view, attachments=[])
                    except (discord.NotFound, discord.HTTPException):
                        self._controllers.pop(str(guild.id), None)
                elif target_channel:
                    msg = await target_channel.send(view=idle_view)
                    self._controllers[str(guild.id)] = msg
                return

            # ── Active state ───────────────────────────────────────────────
            file         = None
            artwork_url  = vc.current.artwork or _DEFAULT_BANNER

            if update_attachments or str(guild.id) not in self._controllers:
                buf = _create_music_banner(
                    thumbnail_url=artwork_url,
                    title=vc.current.title,
                    author=vc.current.author,
                    duration_ms=vc.current.length,
                    position_ms=max(0, getattr(vc, "position", 0)),
                )
                if buf:
                    file = discord.File(buf, filename="music_controller.png")
                    artwork_url = "attachment://music_controller.png"

            view = MusicControllerView(
                cog=self, guild=guild, player=vc,
                artwork_url=artwork_url, interactive=True,
            )

            if not target_channel:
                existing = self._controllers.get(str(guild.id))
                if existing:
                    target_channel = existing.channel

            existing = self._controllers.get(str(guild.id))

            if existing:
                edit_kwargs: dict = {"view": view}
                if file:
                    edit_kwargs["attachments"] = [file]
                try:
                    await existing.edit(**edit_kwargs)
                    return
                except discord.NotFound:
                    self._controllers.pop(str(guild.id), None)
                except Exception:
                    self._controllers.pop(str(guild.id), None)

            if target_channel:
                msg = await target_channel.send(
                    view=view,
                    file=file if file else discord.utils.MISSING,
                )
                self._controllers[str(guild.id)] = msg

        except Exception:
            print(f"[Music] Controller error:\n{traceback.format_exc()}")

    # ── Search helper ─────────────────────────────────────────────────────────

    async def _search(self, query: str):
        is_url = bool(_URL_RE.match(query.strip()))
        attempts = [query] if is_url else [
            f"ytsearch:{query}",
            f"scsearch:{query}",
            query,
        ]
        for attempt in attempts:
            try:
                results = await wavelink.Playable.search(attempt)
                if results:
                    return results
            except Exception as exc:
                print(f"[Music] Search '{attempt}' failed: {exc}")
        return None

    # ── VC connect helper ─────────────────────────────────────────────────────

    async def _ensure_connected(self, ctx: commands.Context) -> wavelink.Player | None:
        if not ctx.author.voice:
            await ctx.reply("❌ Join a voice channel first.", delete_after=10)
            return None
        dest = ctx.author.voice.channel
        vc: wavelink.Player | None = ctx.guild.voice_client
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
        if ctx.author.voice.channel != vc.channel:
            await ctx.reply("❌ Please join my voice channel.", delete_after=10)
            return None
        return vc

    # ── VC check helper ───────────────────────────────────────────────────────

    def _vc_error(self, ctx: commands.Context, vc: wavelink.Player | None) -> str | None:
        if not vc:
            return "❌ I'm not in a voice channel."
        if not ctx.author.voice:
            return "❌ You need to be in a voice channel."
        if vc.channel != ctx.author.voice.channel:
            return "❌ You must be in the same voice channel as me."
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # COMMANDS
    # ─────────────────────────────────────────────────────────────────────────

    # ── /play ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song or add it to the queue.", with_app_command=True)
    @app_commands.describe(search="Song name or URL")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, search: str):
        if ctx.interaction:
            await ctx.defer()

        setup_chan_id = self._music_channels.get(str(ctx.guild.id))
        if setup_chan_id and ctx.channel.id != setup_chan_id:
            return await ctx.reply(
                embed=discord.Embed(
                    description=f"🎵 Please use <#{setup_chan_id}> to control music.",
                    color=discord.Color.red(),
                ),
                delete_after=10,
            )

        vc = await self._ensure_connected(ctx)
        if not vc:
            return

        results = await self._search(search)
        if results is None:
            return await ctx.reply("❌ Search failed — the music server may be offline.", delete_after=15)
        if not results:
            return await ctx.reply("❌ No results found. Try a different search term.", delete_after=10)

        if isinstance(results, wavelink.Playlist):
            tracks = results.tracks
            for t in tracks:
                t.extras = {"requester": ctx.author.id}
            await vc.queue.put_wait(tracks)  # type: ignore[arg-type]
            await ctx.reply(f"📋 Added playlist **{results.name}** ({len(tracks)} tracks) to the queue.")
            if not vc.current:
                await vc.play(vc.queue.get(), volume=80)
            await self.send_music_controls(ctx.guild, update_attachments=True, command_channel=ctx.channel)
        else:
            track: wavelink.Playable = results[0]
            track.extras = {"requester": ctx.author.id}
            if vc.current:
                if len(vc.queue) >= 50:
                    return await ctx.reply("❌ Queue is full (50 tracks max).", delete_after=10)
                await vc.queue.put_wait(track)
                await ctx.reply(f"📋 Added **{_trunc(track.title)}** to the queue (position {len(vc.queue)}).")
                await self.send_music_controls(ctx.guild, command_channel=ctx.channel)
            else:
                await vc.play(track, volume=80)
                await ctx.reply(f"▶️ Now playing **{_trunc(track.title)}**.")

    # ── /pause ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="pause", description="Pause the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.paused:
            return await ctx.reply("⏸ Already paused.", delete_after=8)
        await vc.pause(True)
        await ctx.reply("⏸ Paused.")
        await self.send_music_controls(ctx.guild, command_channel=ctx.channel)

    # ── /resume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="resume", description="Resume the paused track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if not vc.paused:
            return await ctx.reply("▶️ Already playing.", delete_after=8)
        await vc.pause(False)
        await ctx.reply("▶️ Resumed.")
        await self.send_music_controls(ctx.guild, command_channel=ctx.channel)

    # ── /skip ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="skip", description="Skip the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if not vc.current:
            return await ctx.reply("❌ Nothing is playing.", delete_after=8)
        await vc.stop()
        await ctx.reply("⏭ Skipped.")

    # ── /stop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="stop", description="Stop music and disconnect.", with_app_command=True)
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        vc.queue.clear()
        await vc.stop()
        await vc.disconnect()
        await ctx.reply("⏹ Stopped and disconnected.")
        await self.send_music_controls(ctx.guild, end=True)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="loop", description="Toggle looping the current track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def loop(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            await ctx.reply("🔁 Loop **disabled**.")
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            await ctx.reply("🔁 Loop **enabled**.")
        await self.send_music_controls(ctx.guild, command_channel=ctx.channel)

    # ── /autoplay ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="autoplay", description="Toggle autoplay of related tracks.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def autoplay(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.autoplay == wavelink.AutoPlayMode.disabled:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            await ctx.reply("🔀 Autoplay **enabled**.")
        else:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            await ctx.reply("🔀 Autoplay **disabled**.")
        await self.send_music_controls(ctx.guild, command_channel=ctx.channel)

    # ── /volume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Get or set the player volume (0–100).", with_app_command=True)
    @app_commands.describe(level="Volume level 0–100 (omit to check current)")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, level: int | None = None):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if level is None:
            return await ctx.reply(f"🔊 Current volume: **{vc.volume}%**")
        if not 0 <= level <= 100:
            return await ctx.reply("❌ Volume must be between **0** and **100**.", delete_after=10)
        await vc.set_volume(level)
        await ctx.reply(f"🔊 Volume set to **{level}%**.")
        await self.send_music_controls(ctx.guild, command_channel=ctx.channel)

    # ── /nowplaying ───────────────────────────────────────────────────────────

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the currently playing track.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ Nothing is currently playing.", delete_after=10)
        t   = vc.current
        pos = max(0, getattr(vc, "position", 0))
        embed = discord.Embed(
            title=f"▶️ {'Paused' if vc.paused else 'Playing'}",
            description=f"### [{_trunc(t.title, 64)}]({t.uri})\n**{_trunc(t.author, 48)}**",
            color=discord.Color.orange() if vc.paused else discord.Color.green(),
        )
        embed.add_field(name="Position", value=f"`{_fmt_ms(pos)} / {_fmt_ms(t.length)}`", inline=True)
        embed.add_field(name="Volume",   value=f"`{vc.volume}%`", inline=True)
        loop = "🔁 Loop On" if vc.queue.mode == wavelink.QueueMode.loop else "Loop Off"
        ap   = "🔀 Autoplay On" if vc.autoplay != wavelink.AutoPlayMode.disabled else "Autoplay Off"
        embed.add_field(name="Modes", value=f"{loop} · {ap}", inline=False)
        if t.artwork:
            embed.set_thumbnail(url=t.artwork)
        await ctx.reply(embed=embed)

    # ── /queue ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the current track queue.", with_app_command=True)
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def queue_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ Nothing is playing.", delete_after=10)

        embed = discord.Embed(title="🎵 Track Queue", color=discord.Color.blurple())
        pos    = max(0, getattr(vc, "position", 0))
        status = "⏸" if vc.paused else "▶️"
        embed.add_field(
            name=f"{status} Now Playing",
            value=f"[{_trunc(vc.current.title)}]({vc.current.uri})\n`{_fmt_ms(pos)} / {_fmt_ms(vc.current.length)}`",
            inline=False,
        )

        items = list(vc.queue)

        # Interactive select to remove tracks
        async def make_view(disabled: bool = False) -> discord.ui.View:
            view = discord.ui.View(timeout=60)
            options = [
                discord.SelectOption(
                    label=_trunc(t.title, 50),
                    value=str(i),
                    description=f"Length: {_fmt_ms(t.length)}",
                )
                for i, t in enumerate(items[:25])
            ]
            if options:
                sel = discord.ui.Select(placeholder="Select a track to remove", options=options, disabled=disabled)

                async def sel_cb(interaction: discord.Interaction):
                    if interaction.user.id != ctx.author.id:
                        return await interaction.response.send_message("❌ Not your queue view.", ephemeral=True, delete_after=5)
                    idx = int(interaction.data["values"][0])
                    try:
                        vc.queue.delete(idx)
                        items.pop(idx)
                    except Exception:
                        pass
                    await interaction.response.defer()
                    new_embed = embed.copy()
                    new_embed.clear_fields()
                    new_embed.add_field(
                        name=f"{status} Now Playing",
                        value=f"[{_trunc(vc.current.title)}]({vc.current.uri})" if vc.current else "—",
                        inline=False,
                    )
                    if items:
                        lines = [f"`{i+1}.` {_trunc(t.title, 48)} — `{_fmt_ms(t.length)}`" for i, t in enumerate(items[:10])]
                        if len(items) > 10:
                            lines.append(f"*…and {len(items)-10} more*")
                        new_embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
                    await interaction.message.edit(embed=new_embed, view=await make_view())

                sel.callback = sel_cb
                view.add_item(sel)
            return view

        if items:
            lines = [f"`{i+1}.` [{_trunc(t.title, 48)}]({t.uri}) — `{_fmt_ms(t.length)}`" for i, t in enumerate(items[:10])]
            if len(items) > 10:
                lines.append(f"*…and {len(items)-10} more*")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="*Queue is empty*", inline=False)

        await ctx.reply(embed=embed, view=await make_view())

    # ── /seek ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="seek", description="Seek to a position in the current track.", with_app_command=True)
    @app_commands.describe(seconds="Position in seconds (e.g. 90 = 1m 30s)")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def seek(self, ctx: commands.Context, seconds: int):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = self._vc_error(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if not vc.current:
            return await ctx.reply("❌ Nothing is playing.", delete_after=10)
        ms = seconds * 1000
        if not (0 <= ms <= vc.current.length):
            return await ctx.reply(
                f"❌ Must be between 0 and {vc.current.length // 1000} seconds.", delete_after=10
            )
        await vc.seek(ms)
        await ctx.reply(f"⏩ Seeked to `{_fmt_ms(ms)}`.")
        await self.send_music_controls(ctx.guild, update_attachments=True, command_channel=ctx.channel)

    # ── /music (admin group) ──────────────────────────────────────────────────

    @commands.hybrid_group(
        name="music",
        description="Admin music configuration.",
        invoke_without_command=True,
        with_app_command=True,
    )
    @commands.guild_only()
    async def music_group(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🎵 Music Config Commands",
            description=(
                "`/music setup [channel]` — Set a dedicated music channel\n"
                "`/music reset` — Remove the dedicated music channel\n"
                "`/music settings` — View current music settings"
            ),
            color=discord.Color.green(),
        )
        await ctx.reply(embed=embed, ephemeral=True)

    @music_group.command(name="setup", description="Set a channel as the dedicated music channel.", with_app_command=True)
    @app_commands.describe(channel="Text channel for music (leave blank to use this channel)")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_setup(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        target = channel or ctx.channel
        self._music_channels[str(ctx.guild.id)] = target.id
        await ctx.reply(
            embed=discord.Embed(
                description=f"✅ Music channel set to {target.mention}.\nAll music commands must be used there.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )
        await self.send_music_controls(ctx.guild, end=True)

    @music_group.command(name="reset", description="Remove the dedicated music channel.", with_app_command=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_reset(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        removed = self._music_channels.pop(str(ctx.guild.id), None)
        if removed:
            await ctx.reply(
                embed=discord.Embed(description="✅ Dedicated music channel removed.", color=discord.Color.green()),
                ephemeral=True,
            )
        else:
            await ctx.reply(
                embed=discord.Embed(description="❌ No dedicated music channel is set.", color=discord.Color.red()),
                ephemeral=True,
            )

    @music_group.command(name="settings", description="View current music settings.", with_app_command=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_settings(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        vc: wavelink.Player | None = ctx.guild.voice_client
        chan_id = self._music_channels.get(str(ctx.guild.id))
        embed = discord.Embed(title="🎵 Music Settings", color=discord.Color.blurple())
        embed.add_field(
            name="Music Channel",
            value=f"<#{chan_id}>" if chan_id else "*Not set (any channel)*",
            inline=True,
        )
        embed.add_field(name="Lavalink Node", value=f"`{_LAVALINK_URI}`", inline=True)
        if vc:
            embed.add_field(name="Connected To", value=f"`{vc.channel.name}`", inline=True)
            if vc.current:
                embed.add_field(name="Now Playing", value=_trunc(vc.current.title), inline=False)
                embed.add_field(name="Volume", value=f"{vc.volume}%", inline=True)
                loop = "On" if vc.queue.mode == wavelink.QueueMode.loop else "Off"
                ap   = "On" if vc.autoplay != wavelink.AutoPlayMode.disabled else "Off"
                embed.add_field(name="Loop", value=loop, inline=True)
                embed.add_field(name="Autoplay", value=ap, inline=True)
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        embed.set_footer(text=f"Requested by {ctx.author}")
        await ctx.reply(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
