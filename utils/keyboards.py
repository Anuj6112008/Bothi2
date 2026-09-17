from telebot import types
from database import get_setting
from services.force_join import get_enabled_channels


def main_menu_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔍 Check Email", callback_data="menu_check"),
        types.InlineKeyboardButton("📚 Bulk Checker", callback_data="menu_bulk"),
    )
    kb.add(
        types.InlineKeyboardButton("📊 My Usage", callback_data="menu_usage"),
        types.InlineKeyboardButton("🎁 Refer & Earn", callback_data="menu_refer"),
    )
    kb.add(
        types.InlineKeyboardButton("💎 Buy Checks", callback_data="menu_premium"),
        types.InlineKeyboardButton("📖 Help", callback_data="menu_help"),
    )
    kb.add(types.InlineKeyboardButton("👨‍💻 Developer", callback_data="menu_developer"))
    return kb


def back_to_menu_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"))
    return kb


def result_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🔄 Check Again", callback_data="menu_check"),
        types.InlineKeyboardButton("📊 My Usage", callback_data="menu_usage"),
    )
    kb.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"))
    return kb


def premium_keyboard():
    dev = get_setting("developer_username", "PyAnuj")
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton(
            "💬 Contact @PyAnuj",
            url=f"https://t.me/{dev.lstrip('@')}",
        )
    )
    kb.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"))
    return kb


def force_join_keyboard(channels):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for ch in channels:
        text = f"📢 Join {ch.name}"
        url = None
        if ch.invite_link:
            url = ch.invite_link
        elif ch.username:
            url = f"https://t.me/{ch.username.lstrip('@')}"
        if url:
            kb.add(types.InlineKeyboardButton(text, url=url))
        else:
            kb.add(types.InlineKeyboardButton(text, callback_data="fj_noop"))
    kb.add(types.InlineKeyboardButton("✅ I've Joined", callback_data="fj_verify"))
    return kb


def cancel_keyboard():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("❌ Cancel", callback_data="menu_main"))
    return kb


def refer_keyboard(link):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={link}&text=Check%20temp%20mails%20with%20this%20bot!"))
    kb.add(types.InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"))
    return kb
