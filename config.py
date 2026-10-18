import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production-please")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")
RECAPTCHA_SITE_KEY = os.getenv(
    "RECAPTCHA_SITE_KEY",
    "6LfEUPkgAAAAAKTgbMoewQkWBEQhO2VPL4QviKct",
)
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

_raw_admins = os.getenv("ADMIN_TELEGRAM_IDS", "").strip()
ADMIN_TELEGRAM_IDS = []
if _raw_admins:
    for part in _raw_admins.split(","):
        part = part.strip()
        if part.isdigit():
            ADMIN_TELEGRAM_IDS.append(int(part))

# Check packs for display (admin sells via @PyAnuj)
CHECK_PACKS = [
    {"checks": 100, "price": "₹30"},
    {"checks": 300, "price": "₹75"},
    {"checks": 500, "price": "₹110"},
    {"checks": 1000, "price": "₹199"},
    {"checks": 2500, "price": "₹449"},
    {"checks": 5000, "price": "₹799"},
]
UNLIMITED_PRICE = "₹999"
UNLIMITED_DAYS = 30

# ---- Check pipeline tuning (rate limiter for hi2.in API) ----
# Max concurrent checks against hi2.in across ALL users combined.
CHECK_WORKERS = int(os.getenv("CHECK_WORKERS", "4"))
# Minimum global gap (seconds) between two hi2.in API calls -> max ~4 req/s.
CHECK_MIN_INTERVAL = float(os.getenv("CHECK_MIN_INTERVAL", "0.25"))
# Max jobs allowed waiting in the queue before we tell users to slow down.
CHECK_MAX_QUEUE = int(os.getenv("CHECK_MAX_QUEUE", "1500"))
# Attempts per email (1 try + auto-retries with backoff) before giving up.
CHECK_MAX_ATTEMPTS = int(os.getenv("CHECK_MAX_ATTEMPTS", "3"))
# Seconds to wait before each retry.
CHECK_RETRY_BACKOFF = tuple(
    float(x) for x in os.getenv("CHECK_RETRY_BACKOFF", "1.5,3.0").split(",") if x.strip()
)
# Recaptcha token pool (tokens are reused across checks).
TOKEN_POOL_SIZE = int(os.getenv("TOKEN_POOL_SIZE", "4"))
# hi2.in rolling 24h request quota per IP (observed ~1000/day from logs).
# Display-only, shown in admin dashboard as "API quota (24h)".
API_SOFT_QUOTA = int(os.getenv("API_SOFT_QUOTA", "1000"))
# Cooldown cap when the API keeps answering "Too many requests".
API_COOLDOWN_CAP = float(os.getenv("API_COOLDOWN_CAP", "300"))     # 5 min probes
# If the global cooldown is longer than this, reject new checks instantly
# with a polite "server busy" instead of making users wait in line.
API_FAIL_FAST_AFTER = float(os.getenv("API_FAIL_FAST_AFTER", "60"))
# ---- Budget-aware pacing (observed rolling limits from 7-day DB analysis:
#      ~500 successes / 2h  and  ~1000 successes / 24h per IP) ----
# Full speed while usage is below the soft limits; then slow to a drip so
# capacity always lasts into the evening (no more 18h dead windows).
PACE_SOFT_2H = int(os.getenv("PACE_SOFT_2H", "430"))           # of ~500
PACE_2H_INTERVAL = float(os.getenv("PACE_2H_INTERVAL", "30"))
PACE_SOFT_24H = int(os.getenv("PACE_SOFT_24H", "750"))         # of ~1000
PACE_24H_INTERVAL = float(os.getenv("PACE_24H_INTERVAL", "15"))
PACE_HARD_24H = int(os.getenv("PACE_HARD_24H", "920"))
PACE_HARD_INTERVAL = float(os.getenv("PACE_HARD_INTERVAL", "60"))
# Force-join membership cache TTL in seconds (avoids Telegram API spam).
FORCE_JOIN_CACHE_TTL = int(os.getenv("FORCE_JOIN_CACHE_TTL", "300"))

DEFAULTS = {
    "bot_name": "Temp Mail Checker",
    "welcome_message": (
        "🔍 *TEMP MAIL CHECKER*\n\n"
        "Welcome! Check availability of temporary emails on supported domains.\n\n"
        "Use the buttons below to get started."
    ),
    "help_message": (
        "📚 *HELP*\n\n"
        "*Supported domains:*\n"
        "• @hi2.in\n"
        "• @telegmail.com\n\n"
        "*Single check:* Send an email or use 🔍 Check Email\n"
        "*Bulk check:* Send multiple emails.\n\n"
        "*Daily free limit* + *bonus/paid checks* apply.\n"
        "Invite friends with 🎁 Refer & Earn to get extra checks."
    ),
    "daily_free_limit": 40,
    "bulk_limit": 30,
    "referral_reward": 5,
    "premium_message": "",
    "developer_username": "PyAnuj",
    "force_join_enabled": True,
    "maintenance_mode": False,
    "premium_cta": "💎 Get Checks / Premium",
    "maintenance_message": (
        "🛠️ *Bot Maintenance*\n\n"
        "We're currently performing maintenance.\nPlease try again later."
    ),
}
