"""
Music Cog — wavelink 3.x / Lavalink
Commands: play, pause, resume, skip, stop, loop, queue, volume, autoplay, nowplaying
          music setup / reset / settings (admin)
"""

import asyncio
import datetime
import os
import traceback

import discord
import wavelink
from discord.ext import commands
from discord import app_commands


# ── Lavalink node config (override via env vars) ─────────────────────────────
_LAVALINK_URI = os.getenv("LAVALINK_URI", "https://lavalink.jirayu.net:443")
_LAVALINK_PASS = os.getenv("LAVALINK_PASSWORD", "youshallnotpass")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_ms(ms: int) -> str:
    """Format milliseconds into a human-readable duration string."""
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


def _vc_checks(ctx_or_interaction, vc: wavelink.Player | None) -> str | None:
    """
    Returns an error string if the interaction/context fails basic VC checks,
    or None if everything is fine.
    Works for both commands.Context and discord.Interaction.
    """
    if isinstance(ctx_or_interaction, discord.Interaction):
        author = ctx_or_interaction.user
    else:
        author = ctx_or_interaction.author

    if not vc:
        return "❌ I'm not connected to any voice channel."
    if not author.voice:
        return "❌ You need to be in a voice channel."
    if vc.channel != author.voice.channel:
        return "❌ You need to be in the **same** voice channel as me."
    return None


# ── Controller View ───────────────────────────────────────────────────────────

class MusicControllerView(discord.ui.View):
    """Persistent button row shown with the now-playing message."""

    def __init__(self, cog: "MusicCog"):
        super().__init__(timeout=None)
        self.cog = cog

    # ── Pause / Resume ────────────────────────────────────────────────────────

    @discord.ui.button(label="⏸ Pause", style=discord.ButtonStyle.secondary, custom_id="mc_pause")
    async def pause_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player | None = interaction.guild.voice_client
        err = _vc_checks(interaction, vc)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        if vc.paused:
            await vc.pause(False)
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            await vc.pause(True)
            await interaction.response.send_message("⏸ Paused.", ephemeral=True)
        await self.cog._update_controller(interaction.guild)

    # ── Skip ──────────────────────────────────────────────────────────────────

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.secondary, custom_id="mc_skip")
    async def skip_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player | None = interaction.guild.voice_client
        err = _vc_checks(interaction, vc)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        await vc.skip(force=True)
        await interaction.response.send_message("⏭ Skipped.", ephemeral=True)

    # ── Stop ──────────────────────────────────────────────────────────────────

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger, custom_id="mc_stop")
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player | None = interaction.guild.voice_client
        err = _vc_checks(interaction, vc)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        vc.queue.clear()
        await vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹ Stopped and disconnected.", ephemeral=True)
        await self.cog._clear_controller(interaction.guild)

    # ── Autoplay ──────────────────────────────────────────────────────────────

    @discord.ui.button(label="🔀 Autoplay: Off", style=discord.ButtonStyle.secondary, custom_id="mc_autoplay")
    async def autoplay_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player | None = interaction.guild.voice_client
        err = _vc_checks(interaction, vc)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        if vc.autoplay == wavelink.AutoPlayMode.disabled:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            button.label = "🔀 Autoplay: On"
            button.style = discord.ButtonStyle.success
            msg = "🔀 Autoplay **enabled**."
        else:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            button.label = "🔀 Autoplay: Off"
            button.style = discord.ButtonStyle.secondary
            msg = "🔀 Autoplay **disabled**."
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    # ── Loop ──────────────────────────────────────────────────────────────────

    @discord.ui.button(label="🔁 Loop: Off", style=discord.ButtonStyle.secondary, custom_id="mc_loop")
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc: wavelink.Player | None = interaction.guild.voice_client
        err = _vc_checks(interaction, vc)
        if err:
            return await interaction.response.send_message(err, ephemeral=True)
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            button.label = "🔁 Loop: Off"
            button.style = discord.ButtonStyle.secondary
            msg = "🔁 Loop **disabled**."
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            button.label = "🔁 Loop: On"
            button.style = discord.ButtonStyle.success
            msg = "🔁 Loop **enabled**."
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)


# ── Main Cog ──────────────────────────────────────────────────────────────────

class MusicCog(commands.Cog, name="Music"):
    """Music commands powered by Lavalink."""

    CONTROLLER_COOLDOWN = 1.5  # seconds between controller updates

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id (str) → discord.Message (the now-playing controller message)
        self._controllers: dict[str, discord.Message] = {}
        self._last_update: dict[str, datetime.datetime] = {}
        # guild_id (str) → int | None  (dedicated music channel ID)
        self._music_channels: dict[str, int] = {}
        self._view = MusicControllerView(self)

    # ── Lavalink connection ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        """Connect to Lavalink once the bot is ready (idempotent)."""
        # get_node() raises if no nodes are connected yet
        try:
            wavelink.Pool.get_node()
            return  # already connected
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

    # ── Track lifecycle events ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload):
        player: wavelink.Player = payload.player
        if not player or not player.guild:
            return
        await self._update_controller(player.guild, new_track=True)

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        player: wavelink.Player = payload.player
        if not player or not player.guild:
            return
        if player.queue.is_empty and not player.current:
            await self._clear_controller(player.guild)

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player):
        """Disconnect when the player sits idle with no music."""
        try:
            await self._clear_controller(player.guild)
            await player.disconnect()
            print(f"[Music] Disconnected from {player.guild.name} (inactive).")
        except Exception:
            pass

    # ── Controller helpers ────────────────────────────────────────────────────

    def _build_controller_embed(self, player: wavelink.Player | None) -> discord.Embed:
        if not player or not player.current:
            return discord.Embed(
                description="🎵 **Nothing is playing.** Use `/play` to start a session!",
                color=discord.Color.blurple(),
            )
        t = player.current
        status = "⏸ Paused" if player.paused else "▶️ Playing"
        loop_icon = "🔁" if player.queue.mode == wavelink.QueueMode.loop else ""
        auto_icon = "🔀" if player.autoplay != wavelink.AutoPlayMode.disabled else ""

        embed = discord.Embed(
            title=f"{status} {loop_icon}{auto_icon}",
            description=f"### [{_trunc(t.title, 64)}]({t.uri})\n**{_trunc(t.author, 48)}**",
            color=discord.Color.green() if not player.paused else discord.Color.orange(),
        )
        pos = max(0, getattr(player, "position", 0))
        embed.add_field(name="Duration", value=f"`{_fmt_ms(pos)} / {_fmt_ms(t.length)}`", inline=True)
        embed.add_field(name="Volume", value=f"`{player.volume}%`", inline=True)

        # Queue summary
        queue_list = list(player.queue)
        if queue_list:
            lines = []
            for i, track in enumerate(queue_list[:5], 1):
                lines.append(f"`{i}.` {_trunc(track.title, 44)} — `{_fmt_ms(track.length)}`")
            if len(queue_list) > 5:
                lines.append(f"*+{len(queue_list) - 5} more...*")
            embed.add_field(name="Queue", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Queue", value="*Empty*", inline=False)

        if t.artwork:
            embed.set_thumbnail(url=t.artwork)
        embed.set_footer(text="Use the buttons below to control playback.")
        return embed

    def _fresh_view(self, player: wavelink.Player | None) -> MusicControllerView:
        """Return a fresh controller view with correct button states."""
        view = MusicControllerView(self)
        if player:
            # Sync Pause button label
            pause_btn = discord.utils.get(view.children, custom_id="mc_pause")
            if pause_btn:
                if player.paused:
                    pause_btn.label = "▶️ Resume"
                    pause_btn.style = discord.ButtonStyle.success
                else:
                    pause_btn.label = "⏸ Pause"
                    pause_btn.style = discord.ButtonStyle.secondary

            # Sync Autoplay button
            ap_btn = discord.utils.get(view.children, custom_id="mc_autoplay")
            if ap_btn:
                if player.autoplay != wavelink.AutoPlayMode.disabled:
                    ap_btn.label = "🔀 Autoplay: On"
                    ap_btn.style = discord.ButtonStyle.success
                else:
                    ap_btn.label = "🔀 Autoplay: Off"
                    ap_btn.style = discord.ButtonStyle.secondary

            # Sync Loop button
            loop_btn = discord.utils.get(view.children, custom_id="mc_loop")
            if loop_btn:
                if player.queue.mode == wavelink.QueueMode.loop:
                    loop_btn.label = "🔁 Loop: On"
                    loop_btn.style = discord.ButtonStyle.success
                else:
                    loop_btn.label = "🔁 Loop: Off"
                    loop_btn.style = discord.ButtonStyle.secondary
        return view

    def _get_controller_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        chan_id = self._music_channels.get(str(guild.id))
        if chan_id:
            return guild.get_channel(chan_id)
        return None

    async def _update_controller(
        self,
        guild: discord.Guild,
        new_track: bool = False,
        command_channel: discord.abc.Messageable | None = None,
    ):
        """Send or edit the now-playing controller message."""
        try:
            now = datetime.datetime.now()
            last = self._last_update.get(str(guild.id))
            if last and not new_track and (now - last).total_seconds() < self.CONTROLLER_COOLDOWN:
                return
            self._last_update[str(guild.id)] = now

            player: wavelink.Player | None = guild.voice_client
            embed = self._build_controller_embed(player)
            view = self._fresh_view(player)

            existing: discord.Message | None = self._controllers.get(str(guild.id))
            channel = self._get_controller_channel(guild) or command_channel

            if existing:
                try:
                    await existing.edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    self._controllers.pop(str(guild.id), None)
                except Exception:
                    self._controllers.pop(str(guild.id), None)

            if channel:
                msg = await channel.send(embed=embed, view=view)
                self._controllers[str(guild.id)] = msg
        except Exception:
            print(f"[Music] Controller update error:\n{traceback.format_exc()}")

    async def _clear_controller(self, guild: discord.Guild):
        """Remove or update the controller to show idle state."""
        try:
            existing = self._controllers.get(str(guild.id))
            if existing:
                embed = discord.Embed(
                    description="🎵 **Session ended.** Use `/play` to start a new one!",
                    color=discord.Color.dark_grey(),
                )
                try:
                    await existing.edit(embed=embed, view=None)
                except Exception:
                    pass
            self._controllers.pop(str(guild.id), None)
        except Exception:
            pass

    # ── Shared VC join helper ─────────────────────────────────────────────────

    async def _ensure_connected(self, ctx: commands.Context) -> wavelink.Player | None:
        """Connect to the user's VC if needed; return the player or None on error."""
        if not ctx.author.voice:
            await ctx.reply("❌ Join a voice channel first.", delete_after=10)
            return None

        dest = ctx.author.voice.channel
        vc: wavelink.Player | None = ctx.guild.voice_client

        if not vc:
            try:
                vc = await dest.connect(cls=wavelink.Player, self_deaf=True)
                vc.inactive_timeout = 300  # 5 min idle
            except Exception:
                await ctx.reply("❌ Could not connect to your voice channel.", delete_after=10)
                return None
        else:
            if vc.channel != dest:
                if not vc.current:
                    await vc.move_to(dest)
                else:
                    await ctx.reply(
                        "❌ I'm already playing in another voice channel.", delete_after=10
                    )
                    return None

        # Double-check user is in same channel
        if ctx.author.voice.channel != vc.channel:
            await ctx.reply("❌ Please join my voice channel.", delete_after=10)
            return None

        return vc

    # ─────────────────────────────────────────────────────────────────────────
    # COMMANDS
    # ─────────────────────────────────────────────────────────────────────────

    # ── /play ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="play", aliases=["p"], description="Play a song or add it to the queue.")
    @app_commands.describe(search="Song name or URL")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def play(self, ctx: commands.Context, *, search: str):
        if ctx.interaction:
            await ctx.defer()

        # If there's a dedicated music channel, redirect
        setup_chan_id = self._music_channels.get(str(ctx.guild.id))
        if setup_chan_id and ctx.channel.id != setup_chan_id:
            return await ctx.reply(
                f"🎵 Please use <#{setup_chan_id}> to control music.",
                delete_after=10,
            )

        vc = await self._ensure_connected(ctx)
        if not vc:
            return

        try:
            results = await wavelink.Playable.search(search)
        except Exception:
            return await ctx.reply("❌ Search failed. The music server may be offline.", delete_after=15)

        if not results:
            return await ctx.reply("❌ No results found.", delete_after=10)

        if isinstance(results, wavelink.Playlist):
            tracks = results.tracks
            for track in tracks:
                track.extras = {"requester": ctx.author.id}
            added = len(tracks)
            await vc.queue.put_wait(tracks)  # type: ignore[arg-type]
            await ctx.reply(f"📋 Added playlist **{results.name}** ({added} tracks) to the queue.")
        else:
            track: wavelink.Playable = results[0]
            track.extras = {"requester": ctx.author.id}
            if vc.current:
                if len(vc.queue) >= 50:
                    return await ctx.reply("❌ Queue is full (50 tracks max).", delete_after=10)
                await vc.queue.put_wait(track)
                await ctx.reply(f"📋 Added **{_trunc(track.title)}** to the queue (position {len(vc.queue)}).")
                await self._update_controller(ctx.guild, command_channel=ctx.channel)
            else:
                await vc.play(track, volume=80)
                await ctx.reply(f"▶️ Now playing **{_trunc(track.title)}**.")

    # ── /pause ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="pause", description="Pause the current track.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def pause(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.paused:
            return await ctx.reply("⏸ Already paused.", delete_after=8)
        await vc.pause(True)
        await ctx.reply("⏸ Paused.")
        await self._update_controller(ctx.guild, command_channel=ctx.channel)

    # ── /resume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="resume", description="Resume the paused track.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def resume(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if not vc.paused:
            return await ctx.reply("▶️ Already playing.", delete_after=8)
        await vc.pause(False)
        await ctx.reply("▶️ Resumed.")
        await self._update_controller(ctx.guild, command_channel=ctx.channel)

    # ── /skip ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="skip", description="Skip the current track.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def skip(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if not vc.current:
            return await ctx.reply("❌ Nothing is playing.", delete_after=8)
        await vc.skip(force=True)
        await ctx.reply("⏭ Skipped.")

    # ── /stop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="stop", description="Stop music and disconnect the bot.")
    @commands.cooldown(rate=3, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def stop(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        vc.queue.clear()
        await vc.stop()
        await vc.disconnect()
        await ctx.reply("⏹ Stopped and disconnected.")
        await self._clear_controller(ctx.guild)

    # ── /loop ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="loop", description="Toggle looping the current track.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def loop(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.queue.mode == wavelink.QueueMode.loop:
            vc.queue.mode = wavelink.QueueMode.normal
            await ctx.reply("🔁 Loop **disabled**.")
        else:
            vc.queue.mode = wavelink.QueueMode.loop
            await ctx.reply("🔁 Loop **enabled**.")
        await self._update_controller(ctx.guild, command_channel=ctx.channel)

    # ── /autoplay ─────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="autoplay", description="Toggle autoplay (related tracks after queue ends).")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def autoplay(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if vc.autoplay == wavelink.AutoPlayMode.disabled:
            vc.autoplay = wavelink.AutoPlayMode.enabled
            await ctx.reply("🔀 Autoplay **enabled**.")
        else:
            vc.autoplay = wavelink.AutoPlayMode.disabled
            await ctx.reply("🔀 Autoplay **disabled**.")
        await self._update_controller(ctx.guild, command_channel=ctx.channel)

    # ── /volume ───────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="volume", aliases=["vol"], description="Get or set the player volume (0–100).")
    @app_commands.describe(level="Volume level 0–100 (omit to check current)")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def volume(self, ctx: commands.Context, level: int | None = None):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
        if err:
            return await ctx.reply(err, delete_after=10)
        if level is None:
            return await ctx.reply(f"🔊 Current volume: **{vc.volume}%**")
        if not 0 <= level <= 100:
            return await ctx.reply("❌ Volume must be between **0** and **100**.", delete_after=10)
        await vc.set_volume(level)
        await ctx.reply(f"🔊 Volume set to **{level}%**.")
        await self._update_controller(ctx.guild, command_channel=ctx.channel)

    # ── /nowplaying ───────────────────────────────────────────────────────────

    @commands.hybrid_command(name="nowplaying", aliases=["np"], description="Show the currently playing track.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def nowplaying(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ Nothing is currently playing.", delete_after=10)
        embed = self._build_controller_embed(vc)
        await ctx.reply(embed=embed)

    # ── /queue ────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="queue", aliases=["q"], description="Show the current track queue.")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def queue_cmd(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        if not vc or not vc.current:
            return await ctx.reply("❌ Nothing is playing.", delete_after=10)

        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.blurple())
        pos = max(0, getattr(vc, "position", 0))
        status = "⏸" if vc.paused else "▶️"
        embed.add_field(
            name=f"{status} Now Playing",
            value=f"[{_trunc(vc.current.title)}]({vc.current.uri})\n`{_fmt_ms(pos)} / {_fmt_ms(vc.current.length)}`",
            inline=False,
        )

        queue_items = list(vc.queue)
        if queue_items:
            lines = []
            for i, track in enumerate(queue_items[:10], 1):
                lines.append(f"`{i}.` [{_trunc(track.title, 48)}]({track.uri}) — `{_fmt_ms(track.length)}`")
            if len(queue_items) > 10:
                lines.append(f"*…and {len(queue_items) - 10} more*")
            embed.add_field(name="Up Next", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Up Next", value="*Queue is empty*", inline=False)

        modes = []
        if vc.queue.mode == wavelink.QueueMode.loop:
            modes.append("🔁 Loop On")
        if vc.autoplay != wavelink.AutoPlayMode.disabled:
            modes.append("🔀 Autoplay On")
        if modes:
            embed.set_footer(text=" · ".join(modes))

        await ctx.reply(embed=embed)

    # ── /seek ─────────────────────────────────────────────────────────────────

    @commands.hybrid_command(name="seek", description="Seek to a position in the current track.")
    @app_commands.describe(seconds="Position in seconds (e.g. 90 = 1m 30s)")
    @commands.cooldown(rate=5, per=30, type=commands.BucketType.user)
    @commands.guild_only()
    async def seek(self, ctx: commands.Context, seconds: int):
        if ctx.interaction:
            await ctx.defer()
        vc: wavelink.Player | None = ctx.guild.voice_client
        err = _vc_checks(ctx, vc)
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

    # ── /music (admin group) ──────────────────────────────────────────────────

    @commands.hybrid_group(
        name="music",
        description="Admin music configuration.",
        invoke_without_command=True,
        with_app_command=True,
    )
    @commands.guild_only()
    async def music_group(self, ctx: commands.Context):
        await ctx.reply(
            "**Music config commands:**\n"
            "`/music setup` — Designate a channel as the music control channel\n"
            "`/music reset` — Remove the dedicated music channel\n"
            "`/music settings` — View current music configuration",
            ephemeral=True,
        )

    @music_group.command(name="setup", description="Set a channel as the dedicated music channel.")
    @app_commands.describe(channel="The text channel to use for music control (leave blank to use this channel)")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_setup(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        target = channel or ctx.channel
        self._music_channels[str(ctx.guild.id)] = target.id
        await ctx.reply(
            f"✅ Music control channel set to {target.mention}.\n"
            f"All music commands must be used there, and the controller will appear in that channel.",
            ephemeral=True,
        )

    @music_group.command(name="reset", description="Remove the dedicated music channel.")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def music_reset(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer(ephemeral=True)
        if str(ctx.guild.id) in self._music_channels:
            del self._music_channels[str(ctx.guild.id)]
            await ctx.reply("✅ Dedicated music channel removed. You can use music commands anywhere now.", ephemeral=True)
        else:
            await ctx.reply("❌ No dedicated music channel is set.", ephemeral=True)

    @music_group.command(name="settings", description="View current music settings.")
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
        embed.add_field(
            name="Lavalink Node",
            value=f"`{_LAVALINK_URI}`",
            inline=True,
        )
        if vc and vc.current:
            embed.add_field(name="Now Playing", value=_trunc(vc.current.title), inline=False)
            embed.add_field(name="Volume", value=f"{vc.volume}%", inline=True)
            loop_mode = "Loop" if vc.queue.mode == wavelink.QueueMode.loop else "Normal"
            embed.add_field(name="Loop Mode", value=loop_mode, inline=True)
            auto = "On" if vc.autoplay != wavelink.AutoPlayMode.disabled else "Off"
            embed.add_field(name="Autoplay", value=auto, inline=True)
        await ctx.reply(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
