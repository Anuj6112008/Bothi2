from telebot import TeleBot
from telebot.types import Message, CallbackQuery
from handlers.middleware import guard
from services.user_service import get_or_create_user, complete_pending_referral
from services.force_join import is_force_join_enabled
from utils import messages, keyboards
from utils.helpers import safe_reply, safe_edit, extract_user
import re


def _parse_referral(text: str):
    if not text:
        return None
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    m = re.match(r"^(?:ref[_-])?(\d+)$", payload, re.I)
    if m:
        return int(m.group(1))
    return None


def notify_referrer(bot: TeleBot, referral_event: dict):
    if not referral_event:
        return
    rid = referral_event["referrer_id"]
    reward = referral_event["reward"]
    count = referral_event.get("new_count", 1)
    bonus = referral_event.get("bonus_checks", reward)
    try:
        bot.send_message(
            rid,
            f"🎉 *New referral!*\n\n"
            f"1 referral added.\n"
            f"+*{reward}* checks credited to your account.\n\n"
            f"Total referrals: *{count}*\n"
            f"Bonus checks balance: *{bonus}*",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"Could not notify referrer {rid}: {e}")


def register(bot: TeleBot):
    @bot.message_handler(commands=["start"])
    def cmd_start(message: Message):
        tid, username, first_name, last_name = extract_user(message)
        referred_by = _parse_referral(message.text or "")

        user, is_new, _ = get_or_create_user(
            tid, username, first_name, last_name, referred_by=referred_by
        )

        ok, user = guard(bot, message, user=user)
        if not ok:
            # Force join / ban / maintenance — referral NOT credited yet
            return

        # User passed all gates (force join off OR already joined)
        event = complete_pending_referral(tid)
        if event:
            notify_referrer(bot, event)

        extra = ""
        if is_new and referred_by:
            extra = "\n\n✅ You joined via a referral link!"

        text = messages.welcome_text() + extra
        safe_reply(
            bot, message, text,
            parse_mode="Markdown",
            reply_markup=keyboards.main_menu_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "menu_main")
    def cb_main(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = messages.welcome_text()
        safe_edit(
            bot,
            call.message.chat.id,
            call.message.message_id,
            text,
            parse_mode="Markdown",
            reply_markup=keyboards.main_menu_keyboard(),
        )
