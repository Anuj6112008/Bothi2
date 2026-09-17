from telebot import TeleBot
from telebot.types import CallbackQuery
from handlers.middleware import guard
from utils import messages, keyboards
from utils.helpers import safe_edit


def register(bot: TeleBot):
    @bot.callback_query_handler(func=lambda c: c.data == "menu_usage")
    def cb_usage(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        text = messages.usage_text(user)
        safe_edit(
            bot,
            call.message.chat.id,
            call.message.message_id,
            text,
            parse_mode="Markdown",
            reply_markup=keyboards.back_to_menu_keyboard(),
        )
