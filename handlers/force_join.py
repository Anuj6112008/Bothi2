from telebot import TeleBot
from telebot.types import CallbackQuery
from services.force_join import check_membership
from services.user_service import complete_pending_referral
from handlers.middleware import ensure_user
from handlers.start import notify_referrer
from utils import messages, keyboards
from utils.helpers import safe_edit


def register(bot: TeleBot):
    @bot.callback_query_handler(func=lambda c: c.data == "fj_verify")
    def cb_verify(call: CallbackQuery):
        user = ensure_user(call)
        try:
            bot.answer_callback_query(call.id, "Verifying...")
        except Exception:
            pass
        ok, missing = check_membership(bot, user.telegram_id)
        if ok:
            # Credit referral ONLY after all channels joined
            event = complete_pending_referral(user.telegram_id)
            if event:
                notify_referrer(bot, event)

            text = "✅ *Verification successful!*\n\n" + messages.welcome_text()
            safe_edit(
                bot,
                call.message.chat.id,
                call.message.message_id,
                text,
                parse_mode="Markdown",
                reply_markup=keyboards.main_menu_keyboard(),
            )
        else:
            text = (
                "❌ You haven't joined all required channels yet.\n\n"
                + messages.force_join_text(missing)
            )
            safe_edit(
                bot,
                call.message.chat.id,
                call.message.message_id,
                text,
                parse_mode="Markdown",
                reply_markup=keyboards.force_join_keyboard(missing),
            )

    @bot.callback_query_handler(func=lambda c: c.data == "fj_noop")
    def cb_noop(call: CallbackQuery):
        try:
            bot.answer_callback_query(call.id, "Please use the join link.", show_alert=True)
        except Exception:
            pass
