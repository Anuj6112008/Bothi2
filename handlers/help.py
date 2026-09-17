from telebot import TeleBot
from telebot.types import CallbackQuery
from handlers.middleware import guard
from utils import messages, keyboards
from utils.helpers import safe_edit
from database import get_setting


def register(bot: TeleBot):
    @bot.callback_query_handler(func=lambda c: c.data == "menu_help")
    def cb_help(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = messages.help_text()
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "menu_premium")
    def cb_premium(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = messages.premium_packs_text()
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.premium_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "menu_developer")
    def cb_dev(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = messages.developer_text()
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.premium_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "menu_refer")
    def cb_refer(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        try:
            me = bot.get_me()
            bot_username = me.username or "bot"
        except Exception:
            bot_username = "bot"
        link = f"https://t.me/{bot_username}?start=ref_{user.telegram_id}"
        text = messages.referral_text(user, bot_username)
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.refer_keyboard(link),
        )
