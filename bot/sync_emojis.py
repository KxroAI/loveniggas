"""
Emoji Sync — adapted from Reo-Bot's sync_emojis.py
On startup (when SYNC_EMOJIS=True), scans the bot codebase for all custom
emoji references, uploads any missing ones to Discord Application Emojis,
and auto-fixes stale IDs directly in the source files.
"""

import os
import re
import base64
import requests
from dotenv import load_dotenv

load_dotenv()

# Directories to scan for emoji references
_BOT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SCAN_DIRS = [_BOT_ROOT]
_SCAN_EXT  = ".py"


def _fetch_emoji_image(emoji_id: str, animated: bool) -> bytes | None:
    for ext in (("gif" if animated else "webp"), "png"):
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.content
            if r.status_code in (301, 302):
                loc = r.headers.get("Location")
                if loc:
                    r2 = requests.get(loc, timeout=10)
                    if r2.status_code == 200:
                        return r2.content
        except Exception:
            pass
    return None


def _collect_py_files():
    for scan_dir in _SCAN_DIRS:
        for root, _, files in os.walk(scan_dir):
            for fname in files:
                if fname.endswith(_SCAN_EXT):
                    yield os.path.join(root, fname)


def run_sync():
    """
    Run the emoji sync sequence.
    Safe to call at startup (synchronous / blocking).
    """
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("[EmojiSync] ✖ No DISCORD_TOKEN found — skipping.")
        return

    # ── collect all emoji refs from every .py file ──────────────────────────
    all_matches: set[tuple[str, str, str]] = set()
    file_contents: dict[str, str] = {}

    for path in _collect_py_files():
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            file_contents[path] = content
            found = re.findall(r"<(a?):(\w+):(\d+)>", content)
            all_matches.update(found)
        except Exception:
            pass

    if not all_matches:
        print("[EmojiSync] ◈ No custom emoji references found — nothing to sync.")
        return

    headers = {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
    }

    # ── get bot application ID ───────────────────────────────────────────────
    r = requests.get("https://discord.com/api/v10/users/@me", headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"[EmojiSync] ✖ Failed to fetch bot info [HTTP {r.status_code}]")
        return
    app_id = r.json().get("id")

    # ── fetch existing application emojis ────────────────────────────────────
    r = requests.get(
        f"https://discord.com/api/v10/applications/{app_id}/emojis",
        headers=headers,
        timeout=10,
    )
    if r.status_code != 200:
        print(f"[EmojiSync] ✖ Failed to fetch application emojis [HTTP {r.status_code}]")
        return

    raw = r.json()
    app_emojis: list[dict] = raw.get("items", []) if isinstance(raw, dict) else raw

    print(
        f"[EmojiSync] ★ Starting sync — "
        f"{len(all_matches)} template(s) found | "
        f"{len(app_emojis)} app emoji(s) on Discord"
    )

    # ── build ID-replacement map (old_str → new_str) ─────────────────────────
    replacements: dict[str, str] = {}
    skipped = uploaded = fixed = failed = 0

    for animated_str, name, old_id in all_matches:
        animated = animated_str == "a"
        # match by ID first, then by name
        existing = next((e for e in app_emojis if e["id"] == old_id), None) or \
                   next((e for e in app_emojis if e["name"] == name), None)

        if existing:
            new_id = existing["id"]
            if old_id != new_id:
                old_str = f"<{animated_str}:{name}:{old_id}>"
                new_str = f"<{animated_str}:{existing['name']}:{new_id}>"
                replacements[old_str] = new_str
                fixed += 1
                print(f"[EmojiSync] ↻ Auto-fixing ID: {name} → {new_id}")
            else:
                skipped += 1
            continue

        # not found on Discord — upload it
        print(f"[EmojiSync] ↑ Uploading: {name} (not found on Discord)")
        image_data = _fetch_emoji_image(old_id, animated)
        if not image_data:
            print(f"[EmojiSync] ✖ Could not download image for: {name} [ID: {old_id}]")
            failed += 1
            continue

        mime = "image/gif" if animated else "image/webp"
        b64  = base64.b64encode(image_data).decode("utf-8")
        payload = {"name": name, "image": f"data:{mime};base64,{b64}"}

        r2 = requests.post(
            f"https://discord.com/api/v10/applications/{app_id}/emojis",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if r2.status_code in (200, 201):
            new_emoji = r2.json()
            new_id    = new_emoji["id"]
            old_str   = f"<{animated_str}:{name}:{old_id}>"
            new_str   = f"<{animated_str}:{new_emoji['name']}:{new_id}>"
            replacements[old_str] = new_str
            app_emojis.append(new_emoji)
            uploaded += 1
            print(f"[EmojiSync] ✔ Uploaded: {name} [new ID: {new_id}]")
        else:
            print(f"[EmojiSync] ✖ Discord rejected: {name} → {r2.text}")
            failed += 1

    # ── patch source files with updated IDs ─────────────────────────────────
    if replacements:
        for path, content in file_contents.items():
            new_content = content
            for old_str, new_str in replacements.items():
                new_content = new_content.replace(old_str, new_str)
            if new_content != content:
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    print(f"[EmojiSync] ✔ Patched: {os.path.relpath(path, _BOT_ROOT)}")
                except Exception as e:
                    print(f"[EmojiSync] ✖ Could not patch {path}: {e}")

    # ── summary ──────────────────────────────────────────────────────────────
    parts = []
    if skipped:  parts.append(f"{skipped} already in sync")
    if fixed:    parts.append(f"{fixed} ID(s) fixed")
    if uploaded: parts.append(f"{uploaded} newly uploaded")
    if failed:   parts.append(f"{failed} failed")

    print(f"[EmojiSync] ★ Done — {' | '.join(parts) if parts else 'nothing changed'}")
