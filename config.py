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
