from database import get_setting
from services.user_service import is_premium, remaining_credits
import config


def welcome_text():
    return get_setting("welcome_message") or "Welcome to Temp Mail Checker."


def help_text():
    return get_setting("help_message") or "Help"


def maintenance_text():
    return get_setting("maintenance_message") or "🛠️ Bot is under maintenance."


def ban_text():
    dev = get_setting("developer_username", "PyAnuj")
    return (
        "🚫 *You have been banned from this bot*\n\n"
        "for violating the rules.\n\n"
        "Kindly contact admin for unban.\n"
        f"Contact: @{dev.lstrip('@')}"
    )


def limit_reached_text():
    dev = get_setting("developer_username", "PyAnuj")
    return (
        "⚠️ *No Checks Remaining*\n\n"
        "You've used all free daily checks and bonus checks.\n\n"
        f"Buy more checks or unlimited access — contact @{dev.lstrip('@')}.\n\n"
        "Or invite friends with 🎁 *Refer & Earn* to get free checks."
    )


def not_enough_credits_text(remaining, requested):
    return (
        f"⚠️ *Not Enough Credits*\n\n"
        f"You have only *{remaining}* checks remaining.\n"
        f"Your request contains *{requested}* emails.\n\n"
        f"Please send {remaining} or fewer emails, buy more checks, or use Refer & Earn."
    )


def usage_text(user):
    daily_rem, bonus, total, unlimited = remaining_credits(user)
    limit = int(get_setting("daily_free_limit", 40))
    used = user.daily_usage or 0
    if unlimited:
        account = "💎 PREMIUM (Unlimited)"
        daily_line = "Daily free limit: Unlimited"
        bonus_line = f"Bonus / Paid checks: {bonus}"
        rem_line = "Checks remaining: Unlimited"
    else:
        account = "FREE"
        daily_line = f"Today free used: {used} / {limit} (left {daily_rem})"
        bonus_line = f"Bonus / Paid checks: {bonus}"
        rem_line = f"Total remaining: {total}"

    return (
        "📊 *YOUR STATISTICS*\n\n"
        f"{daily_line}\n"
        f"{bonus_line}\n"
        f"{rem_line}\n\n"
        f"Lifetime checks done: {user.total_checks or 0}\n"
        f"Available found: {user.available_count or 0}\n"
        f"Taken: {user.taken_count or 0}\n"
        f"Referrals: {user.referral_count or 0}\n\n"
        f"Account: {account}"
    )


def single_result_text(result):
    status_map = {
        "available": "✅ AVAILABLE",
        "taken": "❌ TAKEN",
        "invalid": "❌ INVALID",
        "wrong_domain": "❌ WRONG DOMAIN",
        "timeout": "⏱️ TIMEOUT",
        "error": "⚠️ ERROR",
        "retry": "🔄 RETRY",
    }
    status = status_map.get(result.get("status"), result.get("message", "Unknown"))
    return (
        "📊 *CHECK RESULT*\n\n"
        f"Email:\n`{result.get('email', '')}`\n\n"
        f"Status:\n{status}"
    )


def bulk_result_text(results):
    available = [r for r in results if r.get("status") == "available"]
    taken = [r for r in results if r.get("status") == "taken"]
    errors = [r for r in results if r.get("status") not in ("available", "taken")]
    lines = [
        "📊 *BULK CHECK RESULTS*\n",
        f"Total: {len(results)}",
        f"Available: {len(available)}",
        f"Taken: {len(taken)}",
        f"Errors: {len(errors)}\n",
    ]
    if available:
        lines.append("*✅ AVAILABLE:*")
        for r in available:
            lines.append(r["message"])
        lines.append("")
    if taken:
        lines.append("*❌ TAKEN:*")
        for r in taken:
            lines.append(r["message"])
        lines.append("")
    if errors:
        lines.append("*⚠️ OTHER:*")
        for r in errors:
            lines.append(r["message"])
    return "\n".join(lines)


def developer_text():
    dev = get_setting("developer_username", "PyAnuj")
    return (
        "👨‍💻 *Developer*\n\n"
        "This bot is developed and maintained by:\n"
        f"@{dev.lstrip('@')}\n\n"
        f"For checks / premium / support, contact @{dev.lstrip('@')}."
    )


def force_join_text(channels):
    names = ", ".join(ch.name for ch in channels) if channels else "required channels"
    return (
        "⚠️ *JOIN REQUIRED*\n\n"
        "To use this bot, please join all required channels.\n\n"
        f"Channels: {names}"
    )


def premium_packs_text():
    dev = get_setting("developer_username", "PyAnuj")
    lines = [
        "💎 *BUY CHECKS / PREMIUM*\n",
        "Choose a pack and contact the developer to purchase.\n",
    ]
    for p in config.CHECK_PACKS:
        lines.append(f"• *{p['checks']:,} Checks* — {p['price']}")
    lines.append(f"• *Unlimited ({config.UNLIMITED_DAYS} Days)* — {config.UNLIMITED_PRICE}")
    lines.append("")
    lines.append(f"To purchase, contact: @{dev.lstrip('@')}")
    lines.append("")
    lines.append("_After payment, admin will credit checks to your account._")
    return "\n".join(lines)


def referral_text(user, bot_username):
    reward = int(get_setting("referral_reward", 5))
    link = f"https://t.me/{bot_username}?start=ref_{user.telegram_id}"
    return (
        "🎁 *REFER & EARN*\n\n"
        f"Invite friends and get *{reward} bonus checks* for each new user who joins with your link.\n\n"
        f"Your referrals: *{user.referral_count or 0}*\n"
        f"Your bonus checks: *{user.bonus_checks or 0}*\n\n"
        f"*Your link:*\n`{link}`\n\n"
        "Share this link with friends!"
    )
