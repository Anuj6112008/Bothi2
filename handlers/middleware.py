from telebot import TeleBot
from telebot.types import Message, CallbackQuery
from services.user_service import get_or_create_user, is_banned, is_admin_user
from services.force_join import check_membership, is_force_join_enabled
from database import get_setting
from utils import messages, keyboards
from utils.helpers import extract_user, safe_reply, safe_edit


def ensure_user(message_or_call):
    tid, username, first_name, last_name = extract_user(message_or_call)
    user, _, _ = get_or_create_user(tid, username, first_name, last_name)
    return user


def guard(bot: TeleBot, message_or_call, user=None, skip_force_join=False):
    if user is None:
        user = ensure_user(message_or_call)

    is_cb = isinstance(message_or_call, CallbackQuery)
    chat_id = message_or_call.message.chat.id if is_cb else message_or_call.chat.id

    if is_banned(user) and not is_admin_user(user):
        text = messages.ban_text()
        if is_cb:
            try:
                bot.answer_callback_query(message_or_call.id, "Banned", show_alert=True)
            except Exception:
                pass
            try:
                safe_edit(bot, chat_id, message_or_call.message.message_id, text, parse_mode="Markdown")
            except Exception:
                bot.send_message(chat_id, text, parse_mode="Markdown")
        else:
            safe_reply(bot, message_or_call, text, parse_mode="Markdown")
        return False, user

    maint = get_setting("maintenance_mode", False)
    if maint in (True, "true", "True", "1", "yes", "on"):
        if not is_admin_user(user):
            text = messages.maintenance_text()
            if is_cb:
                try:
                    bot.answer_callback_query(message_or_call.id, "Maintenance", show_alert=True)
                except Exception:
                    pass
                try:
                    safe_edit(bot, chat_id, message_or_call.message.message_id, text, parse_mode="Markdown")
                except Exception:
                    bot.send_message(chat_id, text, parse_mode="Markdown")
            else:
                safe_reply(bot, message_or_call, text, parse_mode="Markdown")
            return False, user

    if not skip_force_join and is_force_join_enabled() and not is_admin_user(user):
        ok, missing = check_membership(bot, user.telegram_id)
        if not ok:
            text = messages.force_join_text(missing)
            kb = keyboards.force_join_keyboard(missing)
            if is_cb:
                try:
                    bot.answer_callback_query(message_or_call.id)
                except Exception:
                    pass
                try:
                    safe_edit(
                        bot, chat_id, message_or_call.message.message_id,
                        text, parse_mode="Markdown", reply_markup=kb,
                    )
                except Exception:
                    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=kb)
            else:
                safe_reply(bot, message_or_call, text, parse_mode="Markdown", reply_markup=kb)
            return False, user

    return True, user
