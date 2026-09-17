# Temp Mail Checker Pro

Telegram bot for temp-mail availability checks with full in-bot Admin Panel.

**Developer:** [@PyAnuj](https://t.me/PyAnuj)

## Features

- Single & bulk email checks (hi2.in / telegmail.com)
- Daily free limit + **bonus/paid checks**
- **Refer & Earn** (configurable checks per referral)
- Buy checks packs + Unlimited 30 days (contact @PyAnuj)
- Force Join, ban/unban, maintenance
- Broadcast: text (any font), photo, video, audio, GIF + **cancel mid-broadcast**
- Admin: `/admin` → give checks by user ID, settings, logs

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# Set BOT_TOKEN and ADMIN_TELEGRAM_IDS
python main.py
```

DB auto-creates at `data/bot.db`.

## Admin

`/admin` → Dashboard, Users (ban/unban/premium), **Give Checks**, Broadcast, Force Join, Settings (referral reward, limits), Logs.

### Give checks
- Admin → Give Checks → `USER_ID AMOUNT`
- Or open user → Give Checks

### Referral
Users → Refer & Earn → share link. Reward set in Admin → Settings.

### Pricing (shown in bot)
100 / 300 / 500 / 1000 / 2500 / 5000 checks + Unlimited 30d — contact @PyAnuj

Developer: **@PyAnuj**
