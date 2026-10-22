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
# ---- Egress proxy pool (hi2.in limits per client IP; proxies spread load,
#      so a throttled VPS IP no longer blocks every user) ----
PROXY_ENABLED = os.getenv("PROXY_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")
PROXY_FILE = os.getenv("PROXY_FILE", "data/proxies.txt")
PROXY_SOFT_2H = int(os.getenv("PROXY_SOFT_2H", "50"))       # per-proxy successes / 2h
PROXY_HARD_24H = int(os.getenv("PROXY_HARD_24H", "200"))    # per-proxy successes / 24h
PROXY_MAX_FAILS = int(os.getenv("PROXY_MAX_FAILS", "3"))    # net fails -> quarantine
PROXY_QUARANTINE = float(os.getenv("PROXY_QUARANTINE", "600"))
PROXY_SCALE_CAP = int(os.getenv("PROXY_SCALE_CAP", "5"))    # global pacing scale cap
# ---- Auto refresher: keeps the pool stocked WITHOUT any manual work ----
# Trigger: usable proxies drop below REFILL_AT  OR  last sweep older than
# SWEEP_HOURS -> fetch fresh lists from the source repos, probe them live,
# write up to TARGET alive proxies into PROXY_FILE and hot-reload.
PROXY_TARGET = int(os.getenv("PROXY_TARGET", "1000"))        # desired pool size
PROXY_REFILL_AT = int(os.getenv("PROXY_REFILL_AT", "200"))   # auto-sweep below this many usable
PROXY_SWEEP_HOURS = float(os.getenv("PROXY_SWEEP_HOURS", "6"))
PROXY_SWEEP_EVERY = float(os.getenv("PROXY_SWEEP_EVERY", "300"))   # trigger check cadence (s)
PROXY_PROBE_WORKERS = int(os.getenv("PROXY_PROBE_WORKERS", "50"))
PROXY_PROBE_DEADLINE = float(os.getenv("PROXY_PROBE_DEADLINE", "3600"))  # max sweep seconds
# (tag, url): tag = scheme for entries that arrive as bare ip:port
PROXY_SOURCES = (
    ("http",   "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt"),
    ("http",   "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt"),
    ("socks4", "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt"),
    ("socks5", "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt"),
    ("http",   "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
    ("socks4", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS.txt"),
    ("socks4", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4.txt"),
    ("socks5", "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5.txt"),
    ("http",   "https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt"),
    ("http",   "https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt"),
    ("socks4", "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt"),
    ("http",   "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all"),
    ("socks4", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&timeout=5000&country=all"),
    ("socks5", "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&timeout=5000&country=all"),
    # --- added 2026-10-19 (verified 200 + proxy lines) to push alive pool
    #     toward PROXY_TARGET=1000; unverified extras are harmless (skipped).
    ("http",   "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt"),
    ("http",   "https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt"),
    ("socks4", "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt"),
    ("http",   "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"),
    ("http",   "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt"),
    ("socks4", "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt"),
    ("socks5", "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt"),
)
PROXY_SOURCES_EXTRA = [u.strip() for u in os.getenv("PROXY_SOURCES_EXTRA", "").split(",") if u.strip()]
# Manual big finds (proxiech.py run on the laptop) live here: every sweep
# re-validates them from the VPS too, so they keep refreshing themselves.
PROXY_SEED_FILE = os.getenv("PROXY_SEED_FILE", "data/seed_proxies.txt")
# ---- Instagram lookup (CAA/bloks account-recovery search) ----
# Instagram is hostile to datacenter IPs: on the VPS every check should leave
# through a residential-looking proxy. Direct is only the last-resort fallback
# (works from laptop/home IPs, often challenged from the VPS).
INSTA_PROXY_FIRST = os.getenv("INSTA_PROXY_FIRST", "1").strip().lower() not in ("0", "false", "no", "")
INSTA_MAX_ATTEMPTS = int(os.getenv("INSTA_MAX_ATTEMPTS", "4"))   # proxies to try per check
INSTA_TIMEOUT = float(os.getenv("INSTA_TIMEOUT", "20"))          # read timeout (s)
INSTA_MIN_INTERVAL = float(os.getenv("INSTA_MIN_INTERVAL", "1.5"))  # global pacing (s)
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
