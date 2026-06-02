# Neroniel Discord Bot

A feature-rich Discord bot with AI, Roblox tools, giveaways, moderation, antinuke, automod, and more.

## Tech Stack
- **Language**: Python 3.12
- **Discord Library**: discord.py 2.7.1
- **Database**: MongoDB (cloud, via `pymongo`) + SQLite (local, via `aiosqlite`)
- **Web Server**: Flask (keepalive + Roblox captcha solver dashboard)
- **Music**: wavelink + Lavalink (yt-dlp, ffmpeg)
- **Entry point**: `run.py` → `bot/main.py`

## Project Structure
- `bot/` — Core bot code (main.py, config.py, database.py, cogs/, dashboard.py)
- `antinuke/` — Antinuke event listeners (symlinked into bot/antinuke/)
- `automod/` — Automod event listeners (symlinked into bot/automod/)
- `db/` — SQLite database files
- `run.py` — Runner script

## Running
```
python run.py
```
Flask server runs on `0.0.0.0:5000`. Discord bot connects automatically.

## Required Secrets
- `DISCORD_TOKEN` — Discord bot token
- `MONGO_URI` — MongoDB connection string
- `BOT_OWNER_ID` — (optional) Discord user ID of bot owner
- `ROBLOX_COOKIE` / `ROBLOX_COOKIE2` — (optional) Roblox account cookies
- `DASHBOARD_SECRET` / `FLASK_SECRET_KEY` — (optional) Flask session secret

## User Preferences
- Keep the antinuke and automod directories symlinked into bot/ so they load as bot.antinuke and bot.automod
