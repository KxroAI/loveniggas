"""
Neroniel Discord Bot - Main Entry Point
A feature-rich Discord bot with AI, Roblox tools, giveaways, and more.

Author: Neroniel
Version: 2.0.0
"""

import os
import asyncio
import aiohttp
import pytz
import discord
from discord.ext import commands, tasks
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template_string
import threading

from .config import PH_TIMEZONE, BOT_PREFIX, LOG_CHANNEL_ID
from .database import db
from .utils import create_embed

# Load environment variables
load_dotenv()


# ══════════════════════════════════════════════════════════════════════════════
# FLASK KEEPALIVE SERVER
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

_CHALLENGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Roblox Challenge — Neroniel Bot</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #1a1a2e; color: #e0e0e0;
      font-family: 'Segoe UI', Arial, sans-serif;
      display: flex; flex-direction: column;
      align-items: center; justify-content: center;
      min-height: 100vh; padding: 24px; text-align: center;
    }
    h1 { color: #7289da; font-size: 1.8rem; margin-bottom: 8px; }
    p  { color: #aaa; margin-bottom: 24px; font-size: 0.95rem; }
    #widget-container { margin: 0 auto 24px; }
    #status { font-size: 1.05rem; min-height: 28px; margin-top: 12px; }
    .ok  { color: #43b581; } .err { color: #f04747; }
    .spinner {
      width: 44px; height: 44px; margin: 18px auto;
      border: 4px solid #333; border-top-color: #7289da;
      border-radius: 50%; animation: spin 0.75s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <h1>🤖 Roblox Login Challenge</h1>
  <p id="desc">Please wait…</p>
  <div id="widget-container"></div>
  <div id="spinner" class="spinner" style="display:none"></div>
  <div id="status"></div>

  <script>
    var SESSION    = "{{ session_id }}";
    var CHAL_TYPE  = "{{ challenge_type }}";
    var POW_SID    = "{{ pow_sid }}";
    var POW_CID    = "{{ pow_cid }}";

    function st(msg, cls) {
      var el = document.getElementById("status");
      el.textContent = msg; el.className = cls || "";
    }
    function spin(on) {
      document.getElementById("spinner").style.display = on ? "block" : "none";
    }

    /* ── CAPTCHA ─────────────────────────────────────────────────────────── */
    if (CHAL_TYPE === "captcha") {
      document.getElementById("desc").textContent =
        "Solve the challenge below to continue your Roblox login.";

      function onEnforcementReady(enforcement) {
        enforcement.setConfig({
          selector: "#widget-container",
          onCompleted: function(r) {
            st("⏳ Submitting…");
            fetch("/captcha/submit", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({session: SESSION, token: r.token})
            })
            .then(function(res) { return res.json(); })
            .then(function(d) {
              d.ok ? st("✅ Done! You can close this tab.", "ok")
                   : st("❌ " + (d.error || "Unknown error"), "err");
            })
            .catch(function(e) { st("❌ Network error: " + e, "err"); });
          },
          onError: function(code) { st("❌ Captcha error: " + code, "err"); }
        });
      }
    }

    /* ── PROOF-OF-WORK ───────────────────────────────────────────────────── */
    if (CHAL_TYPE === "proofofwork") {
      document.getElementById("desc").textContent =
        "Solving Roblox proof-of-work challenge automatically — please keep this tab open.";
      spin(true);

      async function run() {
        st("⏳ Fetching challenge…");
        var res = await fetch(
          "/captcha/pow-challenge?sessionId=" + encodeURIComponent(POW_SID) +
          "&challengeId=" + encodeURIComponent(POW_CID)
        );
        var body = await res.text();
        if (!res.ok) {
          // getChallenge unavailable — Roblox may have issued a transparent PoW
          // (renderNativeChallenge: false). Try submitting nonce "0" directly.
          st("⚙️ Challenge API unavailable — attempting transparent solve…");
          var sub = await fetch("/captcha/submit", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              session: SESSION, type: "proofofwork",
              nonce: "0", pow_sid: POW_SID, pow_cid: POW_CID
            })
          });
          var d = await sub.json();
          spin(false);
          d.ok ? st("✅ Login complete! You can close this tab.", "ok")
               : st("❌ " + (d.error || "Transparent solve failed — check bot logs."), "err");
          return;
        }
        var puzzle    = JSON.parse(body);
        var artifacts = puzzle.artifacts || puzzle;
        var prefix    = artifacts.prefix || artifacts.anchor || puzzle.prefix || puzzle.anchor || "";
        var target    = artifacts.target || puzzle.target || "";
        if (!prefix || !target) {
          st("❌ Unexpected puzzle shape: " + body, "err");
          spin(false); return;
        }

        st("⚙️ Solving (target: " + target + ")…");
        var enc = new TextEncoder();
        var nonce = 0;
        while (true) {
          var hash = await crypto.subtle.digest("SHA-256", enc.encode(prefix + nonce));
          var hex  = Array.from(new Uint8Array(hash))
                       .map(function(b){ return b.toString(16).padStart(2,"0"); }).join("");
          if (hex.startsWith(target)) break;
          nonce++;
          if (nonce % 50000 === 0) {
            st("⚙️ Solving… " + nonce + " attempts (target: " + target + ")");
            await new Promise(function(r){ setTimeout(r, 0); });
          }
        }
        st("✅ Solved in " + nonce + " attempts — submitting…");

        var sub = await fetch("/captcha/submit", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            session: SESSION, type: "proofofwork",
            nonce: String(nonce), pow_sid: POW_SID, pow_cid: POW_CID
          })
        });
        var d = await sub.json();
        spin(false);
        d.ok ? st("✅ Login complete! You can close this tab.", "ok")
             : st("❌ " + (d.error || "Unknown error"), "err");
      }

      run().catch(function(e) { spin(false); st("❌ " + e, "err"); });
    }
  </script>

  {% if challenge_type == "captcha" %}
  <script src="https://roblox-api.arkoselabs.com/v2/476068BF-9607-4799-B53D-966BE98E2B81/api.js"
          data-callback="onEnforcementReady" async defer></script>
  {% endif %}
</body>
</html>"""


@app.route("/")
def home():
    return "Bot is alive!"


@app.route("/captcha")
def captcha_page():
    from .captcha_store import session_exists
    session_id = request.args.get("session", "")
    if not session_id or not session_exists(session_id):
        return "Invalid or expired session.", 400
    challenge_type = request.args.get("type", "captcha")
    pow_sid = request.args.get("pow_sid", "")
    pow_cid = request.args.get("pow_cid", "")
    return render_template_string(
        _CHALLENGE_HTML,
        session_id=session_id,
        challenge_type=challenge_type,
        pow_sid=pow_sid,
        pow_cid=pow_cid,
    )


@app.route("/captcha/submit", methods=["POST"])
def captcha_submit():
    import json as _json, base64 as _b64
    import urllib.request as _urllib
    from .captcha_store import resolve_session

    data = request.get_json(silent=True) or {}
    session_id   = data.get("session", "")
    submit_type  = data.get("type", "captcha")

    if not session_id:
        return jsonify({"ok": False, "error": "Missing session"}), 400

    if submit_type == "proofofwork":
        nonce   = data.get("nonce", "")
        pow_sid = data.get("pow_sid", "")
        pow_cid = data.get("pow_cid", "")
        if not all([nonce, pow_sid, pow_cid]):
            return jsonify({"ok": False, "error": "Missing nonce/pow_sid/pow_cid"}), 400

        def _post(url, payload):
            body = _json.dumps(payload).encode()
            req  = _urllib.Request(url, data=body,
                                   headers={"Content-Type": "application/json"})
            try:
                with _urllib.urlopen(req, timeout=15) as r:
                    return r.status, r.read().decode()
            except Exception as exc:
                return 0, str(exc)

        status, raw = _post(
            "https://apis.roblox.com/proof-of-work-challenge/v1/solve",
            {"sessionId": pow_sid, "solution": nonce},
        )
        print(f"[PoW/submit] solve HTTP {status}: {raw}")
        if status != 200:
            return jsonify({"ok": False, "error": f"Roblox solve failed ({status}): {raw}"}), 502

        redemption_token = _json.loads(raw).get("redemptionToken", "")
        meta_str = _json.dumps({"redemptionToken": redemption_token, "sessionId": pow_sid})
        meta_b64 = _b64.b64encode(meta_str.encode()).decode()

        status2, raw2 = _post(
            "https://apis.roblox.com/challenge/v1/continue",
            {"challengeId": pow_cid, "challengeType": "proofofwork",
             "challengeMetadata": meta_b64},
        )
        print(f"[PoW/submit] challenge/continue HTTP {status2}: {raw2}")

        if resolve_session(session_id, meta_b64):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Session not found or expired"}), 404

    else:
        token = data.get("token", "")
        if not token:
            return jsonify({"ok": False, "error": "Missing token"}), 400
        if resolve_session(session_id, token):
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Session not found or already resolved"}), 404


@app.route("/captcha/pow-challenge")
def pow_challenge_proxy():
    """Server-side proxy for Roblox getChallenge — bypasses browser CORS.
    Tries POST with JSON body (Roblox SDK style) then GET fallback,
    for both pow_sid and pow_cid until one returns 200.
    """
    import urllib.request as _req
    import urllib.error as _uerr
    import json as _json

    pow_sid = request.args.get("sessionId", "")
    pow_cid = request.args.get("challengeId", "")
    if not pow_sid and not pow_cid:
        return jsonify({"error": "Missing sessionId"}), 400

    base_url = "https://apis.roblox.com/proof-of-work-challenge/v1/getChallenge"
    hdrs_base = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Origin": "https://www.roblox.com",
        "Referer": "https://www.roblox.com/",
    }

    def _try(sid):
        attempts = [
            # POST with JSON body (SDK style)
            _req.Request(base_url,
                         data=_json.dumps({"sessionId": sid}).encode(),
                         headers=hdrs_base, method="POST"),
            # GET with query param (fallback)
            _req.Request(f"{base_url}?sessionId={sid}",
                         headers={k: v for k, v in hdrs_base.items()
                                  if k != "Content-Type"}),
        ]
        for req in attempts:
            method = req.get_method()
            try:
                with _req.urlopen(req, timeout=15) as r:
                    raw = r.read()
                    print(f"[PoW/proxy] {method} getChallenge({sid!r}) HTTP 200")
                    return 200, raw
            except _uerr.HTTPError as e:
                raw = e.read().decode(errors="replace")
                print(f"[PoW/proxy] {method} getChallenge({sid!r}) HTTP {e.code}: {raw}")
                if e.code != 404:
                    return e.code, raw.encode()
            except Exception as exc:
                print(f"[PoW/proxy] {method} getChallenge({sid!r}) error: {exc}")
        return 404, b'{"error":"not found"}'

    for sid in filter(None, [pow_sid, pow_cid]):
        status, body = _try(sid)
        if status == 200:
            return app.response_class(body, status=200, mimetype="application/json")

    return app.response_class(body, status=404, mimetype="application/json")


_SOLVER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Roblox Captcha Solver — Neroniel</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0f0f1a;
      color: #e0e0e0;
      font-family: 'Segoe UI', Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 32px 16px;
      gap: 24px;
    }
    .card {
      background: #1a1a2e;
      border: 1px solid #2a2a45;
      border-radius: 16px;
      padding: 32px 28px;
      width: 100%;
      max-width: 480px;
      text-align: center;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
    }
    h1 {
      font-size: 1.6rem;
      color: #7289da;
      margin-bottom: 6px;
      letter-spacing: -0.3px;
    }
    .subtitle {
      color: #888;
      font-size: 0.88rem;
      margin-bottom: 28px;
    }
    #widget-container { margin: 0 auto 20px; min-height: 60px; }
    #status {
      font-size: 0.95rem;
      min-height: 22px;
      margin-bottom: 16px;
      transition: color 0.2s;
    }
    .ok  { color: #43b581; }
    .err { color: #f04747; }
    .info { color: #aaa; }

    #token-box {
      display: none;
      background: #111127;
      border: 1px solid #2a2a45;
      border-radius: 10px;
      padding: 16px;
      margin-top: 16px;
      text-align: left;
    }
    #token-box label {
      font-size: 0.78rem;
      color: #7289da;
      text-transform: uppercase;
      letter-spacing: 0.8px;
      display: block;
      margin-bottom: 8px;
    }
    #token-text {
      width: 100%;
      background: #0f0f1a;
      border: 1px solid #2a2a45;
      border-radius: 6px;
      color: #c5c5e8;
      font-family: 'Courier New', monospace;
      font-size: 0.75rem;
      padding: 10px;
      resize: none;
      height: 90px;
      word-break: break-all;
    }
    #copy-btn {
      margin-top: 10px;
      width: 100%;
      padding: 10px;
      background: #7289da;
      color: #fff;
      border: none;
      border-radius: 8px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      transition: background 0.15s;
    }
    #copy-btn:hover { background: #5f73c7; }
    #copy-btn:active { background: #4e62b8; }
    #copy-feedback {
      font-size: 0.82rem;
      color: #43b581;
      margin-top: 6px;
      min-height: 18px;
    }

    .reset-btn {
      margin-top: 20px;
      background: none;
      border: 1px solid #2a2a45;
      color: #888;
      padding: 8px 18px;
      border-radius: 8px;
      font-size: 0.82rem;
      cursor: pointer;
      transition: border-color 0.15s, color 0.15s;
    }
    .reset-btn:hover { border-color: #7289da; color: #7289da; }

    .badge {
      font-size: 0.72rem;
      color: #555;
      margin-top: 4px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>🔐 Roblox Captcha Solver</h1>
    <p class="subtitle">Solve the challenge below, then copy your token.</p>

    <div id="widget-container"></div>
    <div id="status" class="info">Loading challenge…</div>

    <div id="token-box">
      <label>Captcha Token</label>
      <textarea id="token-text" readonly></textarea>
      <button id="copy-btn" onclick="copyToken()">📋 Copy Token</button>
      <div id="copy-feedback"></div>
    </div>

    <button class="reset-btn" onclick="location.reload()">↺ Solve Again</button>
    <p class="badge">Neroniel Bot • Manual Solver</p>
  </div>

  <script>
    function st(msg, cls) {
      var el = document.getElementById("status");
      el.textContent = msg;
      el.className = cls || "";
    }

    function showToken(token) {
      document.getElementById("token-text").value = token;
      document.getElementById("token-box").style.display = "block";
      st("✅ Captcha solved! Copy the token below.", "ok");
    }

    function copyToken() {
      var ta = document.getElementById("token-text");
      ta.select();
      ta.setSelectionRange(0, 99999);
      try {
        navigator.clipboard.writeText(ta.value).then(function() {
          document.getElementById("copy-feedback").textContent = "✅ Copied to clipboard!";
          setTimeout(function() {
            document.getElementById("copy-feedback").textContent = "";
          }, 2500);
        }).catch(function() {
          document.execCommand("copy");
          document.getElementById("copy-feedback").textContent = "✅ Copied!";
        });
      } catch(e) {
        document.execCommand("copy");
        document.getElementById("copy-feedback").textContent = "✅ Copied!";
      }
    }

    var SESSION = "{{ session_id }}";

    function onEnforcementReady(enforcement) {
      st("Solve the challenge to continue.", "info");
      enforcement.setConfig({
        selector: "#widget-container",
        onCompleted: function(r) {
          if (SESSION) {
            st("⏳ Submitting to bot…", "info");
            fetch("/captcha/submit", {
              method: "POST",
              headers: {"Content-Type": "application/json"},
              body: JSON.stringify({session: SESSION, token: r.token})
            })
            .then(function(res) { return res.json(); })
            .then(function(d) {
              if (d.ok) {
                showToken(r.token);
                st("✅ Solved & sent to bot! You can close this tab.", "ok");
              } else {
                showToken(r.token);
                st("⚠️ Bot submit failed: " + (d.error || "Unknown") + " — token copied above.", "err");
              }
            })
            .catch(function(e) {
              showToken(r.token);
              st("⚠️ Network error — token shown above, copy it manually.", "err");
            });
          } else {
            showToken(r.token);
          }
        },
        onError: function(code) {
          st("❌ Challenge error: " + code, "err");
        },
        onReady: function() {
          st("Ready — solve the challenge above.", "info");
        }
      });
    }
  </script>

  <script src="https://roblox-api.arkoselabs.com/v2/476068BF-9607-4799-B53D-966BE98E2B81/api.js"
          data-callback="onEnforcementReady" async defer></script>
</body>
</html>"""


@app.route("/solver")
def solver_page():
    from .captcha_store import session_exists
    session_id = request.args.get("session", "")
    if session_id and not session_exists(session_id):
        session_id = ""
    return render_template_string(_SOLVER_HTML, session_id=session_id)


def run_server():
    app.run(host="0.0.0.0", port=5000)


# ══════════════════════════════════════════════════════════════════════════════
# BOT CLASS
# ══════════════════════════════════════════════════════════════════════════════

class NeronielBot(commands.Bot):
    """Custom bot class with extended functionality."""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        
        super().__init__(
            command_prefix=BOT_PREFIX,
            intents=intents,
            help_command=None,
        )
        
        self.start_time = datetime.now(PH_TIMEZONE)
        self.command_count = 0
    
    async def setup_hook(self):
        """Called when the bot is starting up."""
        # Connect to database
        db.connect()
        
        # Load all cogs
        cogs = [
            "bot.cogs.log",
            "bot.cogs.ai",
            "bot.cogs.utility",
            "bot.cogs.conversion",
            "bot.cogs.roblox",
            "bot.cogs.giveaway",
            "bot.cogs.admin",
            "bot.cogs.social",
        ]
        
        for cog in cogs:
            try:
                await self.load_extension(cog)
                print(f"✅ Loaded: {cog}")
            except Exception as e:
                print(f"❌ Failed to load {cog}: {e}")
        
        # Start background tasks
        if db.is_connected and db.reminders is not None:
            self.check_reminders.start()
    
    async def on_ready(self):
        """Called when the bot is ready."""
        print(f"{'═' * 50}")
        print(f"  Bot Online: {self.user}")
        print(f"  Servers: {len(self.guilds)}")
        print(f"  Users: {sum(g.member_count for g in self.guilds):,}")
        print(f"{'═' * 50}")
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            print(f"✅ Synced {len(synced)} commands")
        except Exception as e:
            print(f"❌ Failed to sync commands: {e}")
        
        # Restore giveaways
        await self._restore_giveaways()
        
        # Start status loop
        asyncio.create_task(self._status_loop())
    
    async def _restore_giveaways(self):
        """Restore active giveaways after restart."""
        if not db.is_connected or db.giveaways is None:
            return
        
        from bson import ObjectId
        
        giveaway_cog = self.get_cog("GiveawayCog")
        if not giveaway_cog:
            return
        
        active = db.giveaways.find({"ended": {"$ne": True}})
        
        for gw in active:
            end_time = gw["end_time"]
            
            if end_time.tzinfo is None:
                end_time = pytz.UTC.localize(end_time)
            else:
                end_time = end_time.astimezone(pytz.UTC)
            
            now_utc = datetime.now(pytz.UTC)
            
            if end_time <= now_utc:
                asyncio.create_task(giveaway_cog.end_giveaway(gw["_id"]))
            else:
                delay = (end_time - now_utc).total_seconds()
                asyncio.create_task(giveaway_cog.schedule_end(gw["_id"], delay))
        
        print("✅ Giveaways restored")
    
    async def _status_loop(self):
        """Update bot status with group member count."""
        group_id = os.getenv("GROUP_ID")
        if not group_id:
            return
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                        f"https://groups.roblox.com/v1/groups/{group_id}"
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            count = data.get("memberCount", 0)
                            await self.change_presence(
                                status=discord.Status.dnd,
                                activity=discord.Activity(
                                    type=discord.ActivityType.watching,
                                    name=f"1cy | {count:,} Members",
                                ),
                            )
                except Exception as e:
                    print(f"[STATUS] Error: {e}")
                
                await asyncio.sleep(60)
    
    @tasks.loop(seconds=60)
    async def check_reminders(self):
        """Check and send due reminders."""
        if not db.is_connected or db.reminders is None:
            return
        
        try:
            now = datetime.now(PH_TIMEZONE)
            expired = db.reminders.find({"reminder_time": {"$lte": now}})
            
            for reminder in expired:
                user = self.get_user(reminder["user_id"])
                if not user:
                    try:
                        user = await self.fetch_user(reminder["user_id"])
                    except Exception:
                        continue
                
                guild = self.get_guild(reminder["guild_id"])
                if not guild:
                    continue
                
                channel = guild.get_channel(reminder["channel_id"])
                if not channel:
                    continue
                
                try:
                    await channel.send(f"🔔 {user.mention}, reminder: {reminder['note']}")
                except discord.Forbidden:
                    pass
                
                db.reminders.delete_one({"_id": reminder["_id"]})
                
        except Exception as e:
            print(f"[REMINDERS] Error: {e}")
    
    async def on_message(self, message: discord.Message):
        """Handle messages for AI threads and giveaway tracking."""
        if message.author.bot:
            return
        
        # Handle AI thread follow-ups
        ai_cog = self.get_cog("AICog")
        if ai_cog and isinstance(message.channel, discord.Thread):
            if message.channel.id in ai_cog.ai_threads:
                await ai_cog.handle_thread_message(message)
                return
        
        # Process commands
        await self.process_commands(message)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for the bot."""
    # Start keepalive server
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Create and run bot
    bot = NeronielBot()
    
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("❌ DISCORD_TOKEN not found!")
        return
    
    bot.run(token)


if __name__ == "__main__":
    main()
