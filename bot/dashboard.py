"""
Dashboard Blueprint
Flask-based web dashboard with Discord OAuth2.
Requires env vars: DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET
Optional: DASHBOARD_REDIRECT_URI (auto-detected from REPLIT_DEV_DOMAIN if not set)
"""

import os
import time as _time
import urllib.parse
import urllib.request
import json as _json
import secrets as _secrets

from flask import Blueprint, redirect, request, session, render_template_string
from datetime import datetime, timezone

# ── Server-side OAuth state store ────────────────────────────────────────────
# Keyed by state token → expiry Unix timestamp.
# Avoids relying on Flask session cookies (which can be lost on cross-site
# redirects from Discord back to Render/production hosts).
_pending_states: dict[str, float] = {}

def _register_state(state: str, ttl: int = 600) -> None:
    """Store an OAuth state with a TTL (default 10 min)."""
    _pending_states[state] = _time.time() + ttl
    # Prune expired entries on each write
    now = _time.time()
    expired = [k for k, v in list(_pending_states.items()) if v < now]
    for k in expired:
        _pending_states.pop(k, None)

def _consume_state(state: str) -> bool:
    """Return True and remove state if it's valid and unexpired."""
    if not state:
        return False
    expiry = _pending_states.pop(state, None)
    if expiry is None:
        return False
    return _time.time() < expiry

DISCORD_API = "https://discord.com/api/v10"
OAUTH_URL   = "https://discord.com/api/oauth2/authorize"
TOKEN_URL   = "https://discord.com/api/oauth2/token"
REVOKE_URL  = "https://discord.com/api/oauth2/token/revoke"
SCOPES      = "identify guilds"
ADMINISTRATOR = 0x8
MANAGE_GUILD  = 0x20

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")

# ─── helpers ─────────────────────────────────────────────────────────────────

def _redirect_uri() -> str:
    # 1) Explicit override
    custom = os.getenv("DASHBOARD_REDIRECT_URI")
    if custom:
        return custom
    # 2) DASHBOARD_BASE_URL from .env (e.g. https://mybot.replit.app)
    base = os.getenv("DASHBOARD_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}/dashboard/callback"
    # 3) Auto-detect Replit dev domain
    dev_domain = os.getenv("REPLIT_DEV_DOMAIN")
    if dev_domain:
        return f"https://{dev_domain}/dashboard/callback"
    # 4) Localhost fallback
    port = os.getenv("WEB_PORT", "5000")
    return f"http://localhost:{port}/dashboard/callback"


def _discord_get(endpoint: str, token: str):
    req = urllib.request.Request(
        f"{DISCORD_API}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read().decode())
    except Exception:
        return None


def _bot_get(endpoint: str):
    token = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
    if not token:
        return None
    req = urllib.request.Request(
        f"{DISCORD_API}{endpoint}",
        headers={"Authorization": f"Bot {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read().decode())
    except Exception:
        return None


def _exchange_code(code: str):
    client_id     = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, "DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET is not set."
    redirect = _redirect_uri()
    data = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  redirect,
        "scope":         SCOPES,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return _json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        return None, (
            f"Discord returned HTTP {e.code}. "
            f"Make sure this **exact redirect URI** is added to your Discord app's OAuth2 Redirects:\n\n"
            f"`{redirect}`\n\n"
            f"Discord error: `{body}`"
        )
    except Exception as exc:
        return None, str(exc)


def _revoke_token(token: str):
    client_id     = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    if not client_id or not client_secret:
        return
    data = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "token":         token,
    }).encode()
    req = urllib.request.Request(
        REVOKE_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def _snowflake_to_date(snowflake_id: str) -> str:
    try:
        ts = ((int(snowflake_id) >> 22) + 1420070400000) / 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%B %d, %Y")
    except Exception:
        return "Unknown"


def _get_bot_guild_ids() -> set:
    data = _bot_get("/users/@me/guilds") or []
    return {g["id"] for g in data} if isinstance(data, list) else set()


def _avatar_url(user_id: str, avatar_hash: str) -> str:
    if avatar_hash:
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
    return f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"


def _guild_icon_url(guild_id: str, icon_hash: str) -> str:
    if icon_hash:
        return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png"
    return ""


# ─── templates ───────────────────────────────────────────────────────────────

_T_BASE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{{ page_title }} — Neroniel</title>
  <style>{% raw %}
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #1e1f22; color: #dbdee1; font-family: 'Segoe UI', Arial, sans-serif; min-height: 100vh; }
    a { color: #5865f2; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .navbar { background: #111214; padding: 14px 32px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #2b2d31; }
    .brand { font-size: 1.25rem; font-weight: 700; color: #fff; letter-spacing: .5px; }
    .brand span { color: #5865f2; }
    .nav-right { display: flex; gap: 10px; align-items: center; }
    .btn { display: inline-block; padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: .875rem; font-weight: 600; border: none; transition: opacity .15s; text-align: center; }
    .btn:hover { opacity: .85; text-decoration: none; }
    .btn-primary { background: #5865f2; color: #fff; }
    .btn-danger  { background: #ed4245; color: #fff; }
    .btn-gray    { background: #4e5058; color: #dbdee1; }
    .container { max-width: 1100px; margin: 0 auto; padding: 40px 24px; }
    .page-title { font-size: 1.75rem; font-weight: 800; color: #fff; margin-bottom: 4px; }
    .page-sub   { color: #949ba4; font-size: .925rem; margin-bottom: 32px; }
    .guild-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(205px, 1fr)); gap: 16px; }
    .guild-card { background: #2b2d31; border-radius: 12px; padding: 20px; text-align: center; transition: transform .15s, box-shadow .15s; border: 1px solid #3a3d44; }
    .guild-card:hover { transform: translateY(-3px); box-shadow: 0 8px 28px rgba(0,0,0,.45); border-color: #5865f2; }
    .guild-icon { width: 72px; height: 72px; border-radius: 50%; margin-bottom: 10px; }
    .guild-initials { width: 72px; height: 72px; border-radius: 50%; margin: 0 auto 10px; background: #5865f2; display: flex; align-items: center; justify-content: center; font-size: 1.5rem; font-weight: 800; color: #fff; }
    .guild-name { font-weight: 700; color: #fff; font-size: .925rem; margin-bottom: 5px; word-break: break-word; }
    .badge { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: .75rem; font-weight: 700; margin-bottom: 12px; }
    .badge-bot   { background: rgba(88,101,242,.15); color: #5865f2; border: 1px solid rgba(88,101,242,.4); }
    .badge-nobot { background: rgba(237,66,69,.12); color: #ed4245; border: 1px solid rgba(237,66,69,.35); }
    .stat-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 28px; }
    .stat-card { background: #2b2d31; border-radius: 10px; padding: 16px 22px; flex: 1; min-width: 130px; border: 1px solid #3a3d44; }
    .stat-card .val { font-size: 1.8rem; font-weight: 800; color: #5865f2; }
    .stat-card .lbl { font-size: .78rem; color: #949ba4; margin-top: 2px; }
    .section-title { font-size: 1rem; font-weight: 700; color: #fff; margin-bottom: 12px; }
    .info-table { width: 100%; border-collapse: collapse; }
    .info-table td { padding: 9px 12px; border-bottom: 1px solid #2b2d31; font-size: .875rem; }
    .info-table td:first-child { color: #949ba4; width: 180px; }
    .card { background: #2b2d31; border-radius: 12px; padding: 22px; margin-bottom: 22px; border: 1px solid #3a3d44; }
    .alert { border-radius: 8px; padding: 13px 17px; font-size: .875rem; margin-bottom: 20px; }
    .alert-info { background: rgba(88,101,242,.12); border: 1px solid rgba(88,101,242,.4); color: #c0c3f5; }
    .login-wrap { display: flex; align-items: center; justify-content: center; min-height: 82vh; }
    .login-box { background: #2b2d31; border-radius: 16px; padding: 48px 40px; text-align: center; max-width: 420px; width: 100%; border: 1px solid #3a3d44; }
    .login-box .bot-av { width: 86px; height: 86px; border-radius: 50%; margin-bottom: 18px; }
    .login-box h1 { font-size: 1.45rem; font-weight: 800; color: #fff; margin-bottom: 8px; }
    .login-box p  { color: #949ba4; margin-bottom: 26px; font-size: .925rem; }
    .user-chip { display: flex; align-items: center; gap: 8px; font-size: .875rem; color: #fff; }
    .user-chip img { width: 30px; height: 30px; border-radius: 50%; }
    .back-link { color: #949ba4; font-size: .875rem; display: inline-block; margin-bottom: 20px; }
    .back-link:hover { color: #dbdee1; }
    .guild-banner { display: flex; align-items: center; gap: 16px; margin-bottom: 26px; }
    .guild-banner img { width: 68px; height: 68px; border-radius: 50%; }
    .guild-banner-initials { width: 68px; height: 68px; border-radius: 50%; background: #5865f2; display: flex; align-items: center; justify-content: center; font-size: 1.6rem; font-weight: 800; color: #fff; flex-shrink: 0; }
  {% endraw %}</style>
</head>
<body>"""

_T_NAV_ANON = """<nav class="navbar">
  <div class="brand">Nero<span>niel</span></div>
</nav>"""

_T_NAV_USER = """<nav class="navbar">
  <div class="brand">Nero<span>niel</span></div>
  <div class="nav-right">
    <div class="user-chip">
      <img src="{{ av_url }}" alt="av"/>
      <span>{{ username }}</span>
    </div>
    <a href="/dashboard/logout" class="btn btn-gray">Logout</a>
  </div>
</nav>"""

_T_LOGIN = _T_BASE_HEAD + _T_NAV_ANON + """
<div class="login-wrap">
  <div class="login-box">
    {% if bot_av %}
      <img class="bot-av" src="{{ bot_av }}" alt="bot"/>
    {% else %}
      <div style="font-size:3.5rem;margin-bottom:16px;">🤖</div>
    {% endif %}
    <h1>Neroniel Dashboard</h1>
    <p>Log in with your Discord account to manage your servers.</p>
    {% if has_client_id %}
      <a href="/dashboard/login" class="btn btn-primary" style="font-size:1rem;padding:12px 32px;">
        Login with Discord
      </a>
    {% else %}
      <div class="alert alert-info" style="text-align:left;">
        ⚠️ <strong>DISCORD_CLIENT_ID</strong> is not set.<br>
        Set it in your environment variables to enable OAuth login.
      </div>
    {% endif %}
  </div>
</div>
</body></html>"""

_T_GUILDS = _T_BASE_HEAD + _T_NAV_USER + """
<div class="container">
  <div class="page-title">My Servers</div>
  <div class="page-sub">Showing servers where you have Manage Server permission.</div>
  <div class="guild-grid">
    {% for g in guilds %}
    <a href="/dashboard/guild/{{ g.id }}" style="text-decoration:none;">
      <div class="guild-card">
        {% if g.icon_url %}
          <img class="guild-icon" src="{{ g.icon_url }}" alt="{{ g.name }}"/>
        {% else %}
          <div class="guild-initials">{{ g.name[0]|upper }}</div>
        {% endif %}
        <div class="guild-name">{{ g.name }}</div>
        {% if g.has_bot %}
          <span class="badge badge-bot">Bot Added</span>
        {% else %}
          <span class="badge badge-nobot">Bot Missing</span>
        {% endif %}
        <div><span class="btn btn-primary" style="font-size:.8rem;padding:6px 14px;">Manage</span></div>
      </div>
    </a>
    {% else %}
    <div style="color:#949ba4;grid-column:1/-1;padding:20px 0;">
      No servers found where you have Manage Server permission.
    </div>
    {% endfor %}
  </div>
</div>
</body></html>"""

_T_GUILD = _T_BASE_HEAD + _T_NAV_USER + """
<div class="container">
  <a href="/dashboard" class="back-link">← Back to servers</a>
  <div class="guild-banner">
    {% if icon_url %}
      <img src="{{ icon_url }}" alt="{{ guild_name }}"/>
    {% else %}
      <div class="guild-banner-initials">{{ guild_name[0]|upper }}</div>
    {% endif %}
    <div>
      <div class="page-title">{{ guild_name }}</div>
      <div class="page-sub">ID: {{ guild_id }}{% if has_bot %} &nbsp;•&nbsp; ✅ Bot is in this server{% else %} &nbsp;•&nbsp; ❌ Bot not in server{% endif %}</div>
    </div>
  </div>

  <div class="stat-row">
    <div class="stat-card"><div class="val">{{ member_count }}</div><div class="lbl">Members</div></div>
    <div class="stat-card"><div class="val">{{ boost_count }}</div><div class="lbl">Boosts</div></div>
    <div class="stat-card"><div class="val">Level {{ boost_tier }}</div><div class="lbl">Boost Level</div></div>
  </div>

  <div class="card">
    <div class="section-title">ℹ️ Server Info</div>
    <table class="info-table">
      <tr><td>Server ID</td><td>{{ guild_id }}</td></tr>
      <tr><td>Created</td><td>{{ created }}</td></tr>
      <tr><td>Verification Level</td><td>{{ verification }}</td></tr>
    </table>
  </div>

  <div class="alert alert-info">
    💡 Settings for <strong>antinuke</strong>, <strong>automod</strong>, <strong>welcomer</strong>,
    and <strong>tickets</strong> are managed via bot slash commands in your server.
    Use <code>/antinuke</code>, <code>/automod</code>, <code>/welcomer</code>, <code>/ticket</code>.
  </div>
</div>
</body></html>"""

_T_ERROR = _T_BASE_HEAD + _T_NAV_ANON + """
<div class="container">
  <div class="page-title" style="color:#ed4245;">⚠️ Error</div>
  <div class="page-sub">{{ message }}</div>
  <a href="/dashboard" class="btn btn-primary" style="margin-top:20px;">← Back to Dashboard</a>
</div>
</body></html>"""


def _err(msg: str, code: int = 400):
    return render_template_string(_T_ERROR, page_title="Error", message=msg), code


# ─── routes ──────────────────────────────────────────────────────────────────

@dashboard_bp.route("/debug")
def debug():
    redirect = _redirect_uri()
    client_id = os.getenv("DISCORD_CLIENT_ID", "NOT SET")
    return render_template_string(
        _T_BASE_HEAD + _T_NAV_ANON + """
<div class="container">
  <div class="page-title">⚙️ Dashboard Debug</div>
  <div class="page-sub">Use this info to configure your Discord application correctly.</div>
  <div class="card">
    <div class="section-title">OAuth2 Redirect URI</div>
    <p style="margin-bottom:8px;color:#949ba4;font-size:.875rem;">
      Add this <strong>exact URL</strong> to your Discord app's OAuth2 Redirects at
      <a href="https://discord.com/developers/applications" target="_blank">discord.com/developers/applications</a>
      → Your App → OAuth2 → Redirects.
    </p>
    <code style="background:#111214;padding:10px 14px;border-radius:6px;display:block;word-break:break-all;color:#5865f2;">""" + redirect + """</code>
  </div>
  <div class="card">
    <div class="section-title">Environment Check</div>
    <table class="info-table">
      <tr><td>DISCORD_CLIENT_ID</td><td>""" + ("✅ Set" if client_id != "NOT SET" else "❌ Not set") + """</td></tr>
      <tr><td>DISCORD_CLIENT_SECRET</td><td>""" + ("✅ Set" if os.getenv("DISCORD_CLIENT_SECRET") else "❌ Not set") + """</td></tr>
      <tr><td>REPLIT_DEV_DOMAIN</td><td><code>""" + (os.getenv("REPLIT_DEV_DOMAIN", "not set")) + """</code></td></tr>
      <tr><td>DASHBOARD_REDIRECT_URI</td><td><code>""" + (os.getenv("DASHBOARD_REDIRECT_URI", "not set — auto-detected")) + """</code></td></tr>
    </table>
  </div>
  <a href="/dashboard" class="btn btn-primary">← Back to Dashboard</a>
</div>
</body></html>""",
        page_title="Debug",
    )


@dashboard_bp.route("/")
def index():
    client_id = os.getenv("DISCORD_CLIENT_ID")
    user = session.get("discord_user")

    if not user:
        bot_data  = _bot_get("/users/@me") or {}
        bot_id    = bot_data.get("id", "")
        av_hash   = bot_data.get("avatar")
        bot_av    = _avatar_url(bot_id, av_hash) if bot_id else ""
        return render_template_string(
            _T_LOGIN,
            page_title="Dashboard",
            bot_av=bot_av,
            has_client_id=bool(client_id),
        )

    guilds      = session.get("discord_guilds", [])
    bot_gids    = _get_bot_guild_ids()
    user_id     = user.get("id", "")
    av_hash     = user.get("avatar")

    filtered = []
    for g in guilds:
        perms = int(g.get("permissions", 0))
        if not (perms & MANAGE_GUILD or perms & ADMINISTRATOR):
            continue
        gid = g["id"]
        filtered.append({
            "id":       gid,
            "name":     g.get("name", "Unknown"),
            "icon_url": _guild_icon_url(gid, g.get("icon")),
            "has_bot":  gid in bot_gids,
        })

    return render_template_string(
        _T_GUILDS,
        page_title="My Servers",
        guilds=filtered,
        av_url=_avatar_url(user_id, av_hash),
        username=user.get("username", "Unknown"),
    )


@dashboard_bp.route("/login")
def login():
    client_id = os.getenv("DISCORD_CLIENT_ID")
    if not client_id:
        return _err("DISCORD_CLIENT_ID is not set in environment variables.", 500)

    state = _secrets.token_urlsafe(16)
    _register_state(state)

    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  _redirect_uri(),
        "response_type": "code",
        "scope":         SCOPES,
        "state":         state,
    })
    return redirect(f"{OAUTH_URL}?{params}")


@dashboard_bp.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return _err(f"Discord denied access: {request.args.get('error_description', error)}", 400)

    code  = request.args.get("code")
    state = request.args.get("state")
    if not code:
        return _err("No authorization code received from Discord.", 400)
    if not _consume_state(state):
        return _err("Invalid OAuth state. Please try logging in again.", 400)

    token_data, exchange_err = _exchange_code(code)
    if exchange_err or not token_data or "access_token" not in token_data:
        msg = exchange_err or "Unexpected response from Discord — no access token returned."
        return _err(msg, 500)

    access_token = token_data["access_token"]
    user         = _discord_get("/users/@me", access_token)
    guilds       = _discord_get("/users/@me/guilds", access_token) or []

    _revoke_token(access_token)

    session["discord_user"]   = user
    session["discord_guilds"] = guilds

    return redirect("/dashboard")


@dashboard_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/dashboard")


@dashboard_bp.route("/guild/<guild_id>")
def guild_page(guild_id: str):
    user = session.get("discord_user")
    if not user:
        return redirect("/dashboard")

    guilds     = session.get("discord_guilds", [])
    guild_info = next((g for g in guilds if g["id"] == guild_id), None)
    if not guild_info:
        return _err("Server not found or you don't have access.", 404)

    perms = int(guild_info.get("permissions", 0))
    if not (perms & MANAGE_GUILD or perms & ADMINISTRATOR):
        return _err("You need Manage Server permission to view this page.", 403)

    bot_gids = _get_bot_guild_ids()
    has_bot  = guild_id in bot_gids

    bot_guild = {}
    if has_bot:
        bot_guild = _bot_get(f"/guilds/{guild_id}?with_counts=true") or {}

    name         = guild_info.get("name", "Unknown")
    icon_url     = _guild_icon_url(guild_id, guild_info.get("icon"))
    member_count = bot_guild.get("approximate_member_count", "—")
    boost_count  = bot_guild.get("premium_subscription_count", 0)
    boost_tier   = bot_guild.get("premium_tier", 0)
    verification = str(bot_guild.get("verification_level", "—"))
    created      = _snowflake_to_date(guild_id)

    user_id  = user.get("id", "")
    av_hash  = user.get("avatar")

    return render_template_string(
        _T_GUILD,
        page_title=name,
        guild_name=name,
        guild_id=guild_id,
        icon_url=icon_url,
        has_bot=has_bot,
        member_count=member_count,
        boost_count=boost_count,
        boost_tier=boost_tier,
        verification=verification,
        created=created,
        av_url=_avatar_url(user_id, av_hash),
        username=user.get("username", "Unknown"),
    )
