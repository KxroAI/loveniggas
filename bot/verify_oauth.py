"""
Verify OAuth Blueprint
Handles Discord OAuth2 callback for the verify system.
Scopes: identify + guilds.join

Flow:
  1. User clicks Verify button in Discord
  2. Bot sends ephemeral message with a link to /verify/start?state=X
  3. /verify/start redirects to Discord OAuth2 (identify + guilds.join)
  4. User authorizes → Discord redirects to /verify/callback?code=X&state=X
  5. Callback exchanges code → access_token, then:
       - PUT /guilds/{join_gid}/members/{user_id}  for each configured guild
       - PUT /guilds/{home_gid}/members/{user_id}/roles/{role_id}  if role configured
  6. Returns a styled success/error HTML page
"""

import os
import json
import time
import secrets as _secrets
import urllib.parse
import urllib.request
import urllib.error
import asyncio
import aiosqlite

from flask import Blueprint, redirect, request

verify_oauth_bp = Blueprint("verify_oauth", __name__, url_prefix="/verify")

# ── Shared state store (cog writes, blueprint reads) ─────────────────────────
_verify_states: dict[str, dict] = {}   # state → {guild_id, user_id, expires}

DISCORD_API = "https://discord.com/api/v10"
OAUTH_URL   = "https://discord.com/api/oauth2/authorize"
TOKEN_URL   = "https://discord.com/api/oauth2/token"


# ── Public helpers called from the cog ───────────────────────────────────────

def register_state(state: str, guild_id: int, user_id: int, ttl: int = 300) -> None:
    now = time.time()
    _verify_states[state] = {"guild_id": guild_id, "user_id": user_id, "expires": now + ttl}
    # Prune stale entries
    stale = [k for k, v in list(_verify_states.items()) if v["expires"] < now]
    for k in stale:
        _verify_states.pop(k, None)


def make_oauth_url(state: str) -> str | None:
    """Build the Discord OAuth2 authorization URL. Returns None if CLIENT_ID not set."""
    client_id = os.getenv("DISCORD_CLIENT_ID")
    if not client_id:
        return None
    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  _callback_uri(),
        "response_type": "code",
        "scope":         "identify guilds.join",
        "state":         state,
        "prompt":        "none",
    })
    return f"{OAUTH_URL}?{params}"


def web_base_url() -> str:
    """Return the public base URL of this Flask server."""
    for key in ("VERIFY_BASE_URL", "DASHBOARD_BASE_URL"):
        v = os.getenv(key, "").rstrip("/")
        if v:
            return v
    dev = os.getenv("REPLIT_DEV_DOMAIN")
    if dev:
        return f"https://{dev}"
    port = os.getenv("WEB_PORT", "5000")
    return f"http://localhost:{port}"


# ── Internal helpers ──────────────────────────────────────────────────────────

def _callback_uri() -> str:
    return f"{web_base_url()}/verify/callback"


def _consume_state(state: str) -> dict | None:
    data = _verify_states.pop(state, None)
    if data and data["expires"] > time.time():
        return data
    return None


def _exchange_code(code: str) -> tuple[str | None, str | None]:
    """Exchange an auth code for an access token. Returns (token, error_msg)."""
    client_id     = os.getenv("DISCORD_CLIENT_ID")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, "DISCORD_CLIENT_ID or DISCORD_CLIENT_SECRET is not set."
    body = urllib.parse.urlencode({
        "client_id":     client_id,
        "client_secret": client_secret,
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  _callback_uri(),
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("access_token")
            if not token:
                return None, f"No access_token in response: {data}"
            return token, None
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")
        return None, f"Discord HTTP {e.code}: {body_txt}"
    except Exception as exc:
        return None, str(exc)


def _bot_put(endpoint: str, payload: dict | None = None) -> tuple[int, str]:
    """Make an authenticated Bot PUT request. Returns (status, body)."""
    token = os.getenv("DISCORD_TOKEN")
    data  = json.dumps(payload or {}).encode() if payload is not None else b""
    req   = urllib.request.Request(
        f"{DISCORD_API}{endpoint}",
        data=data,
        headers={
            "Authorization":  f"Bot {token}",
            "Content-Type":   "application/json",
            "X-Audit-Log-Reason": "Neroniel Verify System",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as exc:
        return 0, str(exc)


def _load_settings_sync(guild_id: int) -> dict | None:
    """Synchronously read verify settings from SQLite (Flask is sync)."""
    async def _fetch():
        async with aiosqlite.connect("verify.db") as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM verify_settings WHERE guild_id = ?", (guild_id,)
            ) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_fetch())
        loop.close()
        return result
    except Exception:
        return None


# ── Routes ────────────────────────────────────────────────────────────────────

@verify_oauth_bp.route("/callback")
def callback():
    # Discord error redirect
    error = request.args.get("error")
    if error:
        desc = request.args.get("error_description", error)
        return _page("Authorization Cancelled",
                     "You cancelled the authorization. Click the Verify button in Discord to try again.",
                     success=False)

    code  = request.args.get("code",  "")
    state = request.args.get("state", "")

    if not code:
        return _page("No Code", "No authorization code received from Discord.", success=False)

    state_data = _consume_state(state)
    if not state_data:
        return _page("Link Expired",
                     "This verification link has expired or already been used.\n\nClick the Verify button in Discord to get a fresh link.",
                     success=False)

    guild_id = state_data["guild_id"]
    user_id  = state_data["user_id"]

    # Exchange code → access token
    access_token, err = _exchange_code(code)
    if not access_token:
        return _page("Authorization Failed", f"Could not get your access token.\n{err}", success=False)

    # Load settings
    settings = _load_settings_sync(guild_id)
    if not settings:
        return _page("Not Configured", "This server's verify system is not set up.", success=False)

    results  = []
    errors   = []

    # ── Auto-join servers ──────────────────────────────────────────────────
    join_raw = settings.get("join_guild_ids") or ""
    join_ids = [x.strip() for x in join_raw.split(",") if x.strip()]

    for jgid in join_ids:
        status, body = _bot_put(
            f"/guilds/{jgid}/members/{user_id}",
            {"access_token": access_token},
        )
        if status in (200, 201):
            results.append("✅ Joined server successfully")
        elif status == 204:
            results.append("✅ Already a member of the server")
        else:
            try:
                msg = json.loads(body).get("message", body)
            except Exception:
                msg = body
            errors.append(f"⚠️ Could not join server ({jgid}): {msg}")

    # ── Assign role (optional) ─────────────────────────────────────────────
    role_id = settings.get("role_id")
    if role_id:
        status, body = _bot_put(
            f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
        )
        if status == 204:
            results.append("✅ Verified role assigned")
        else:
            try:
                msg = json.loads(body).get("message", body)
            except Exception:
                msg = body
            errors.append(f"⚠️ Could not assign role: {msg}")

    # ── Response page ──────────────────────────────────────────────────────
    if errors and not results:
        detail = "\n".join(errors)
        return _page("Verification Incomplete", detail, success=False)

    all_lines = results + errors
    detail = "\n".join(all_lines)
    return _page("You're Verified! 🎉",
                 f"You can now close this tab and head back to Discord.\n\n{detail}",
                 success=True)


# ── HTML page helper ──────────────────────────────────────────────────────────

def _page(title: str, message: str, success: bool = True) -> str:
    accent = "#57F287" if success else "#ED4245"
    icon   = "🎉" if success else "⚠️"
    safe_msg = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{title} — Neroniel Verify</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #1e1f22; color: #dbdee1;
      font-family: 'Segoe UI', Arial, sans-serif;
      min-height: 100vh; display: flex;
      align-items: center; justify-content: center; padding: 24px;
    }}
    .card {{
      background: #2b2d31; border-radius: 18px;
      padding: 52px 44px; text-align: center;
      max-width: 480px; width: 100%;
      border: 1px solid #3a3d44;
      box-shadow: 0 12px 40px rgba(0,0,0,.45);
    }}
    .icon {{ font-size: 3.5rem; margin-bottom: 18px; }}
    h1 {{ font-size: 1.65rem; font-weight: 800; color: {accent}; margin-bottom: 14px; }}
    .msg {{ color: #949ba4; font-size: .925rem; line-height: 1.7; }}
    .close-btn {{
      display: inline-block; margin-top: 30px;
      padding: 11px 32px; background: #5865f2; color: #fff;
      border-radius: 9px; font-weight: 700; font-size: .95rem;
      cursor: pointer; border: none; transition: opacity .15s;
    }}
    .close-btn:hover {{ opacity: .82; }}
    .brand {{ margin-top: 28px; font-size: .75rem; color: #4e5058; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p class="msg">{safe_msg}</p>
    <button class="close-btn" onclick="window.close()">Close Tab</button>
    <p class="brand">Powered by Neroniel</p>
  </div>
</body>
</html>"""
