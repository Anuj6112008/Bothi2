from telebot import TeleBot
from telebot.types import Message, CallbackQuery
from handlers.middleware import guard
from services.checker import check_single_email, check_bulk_emails, parse_emails
from services.user_service import can_check, consume_checks, remaining_credits
from database import get_setting
from utils import messages, keyboards
from utils.helpers import animate_loading, safe_edit, safe_reply
import threading
import requests
import io

_awaiting = {}  # telegram_id -> "single" | "bulk"


def register(bot: TeleBot):
    @bot.callback_query_handler(func=lambda c: c.data == "menu_check")
    def cb_check(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _awaiting[user.telegram_id] = "single"
        text = (
            "🔍 *Single Email Check*\n\n"
            "Send one email address to check.\n"
            "Supported: `@hi2.in` and `@telegmail.com`\n\n"
            "Example: `test@hi2.in`"
        )
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.cancel_keyboard(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "menu_bulk")
    def cb_bulk(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        bulk_limit = int(get_setting("bulk_limit", 30))
        _awaiting[user.telegram_id] = "bulk"
        text = (
            "📚 *Bulk Email Check*\n\n"
            f"Send up to *{bulk_limit}* emails.\n\n"
            "• Line-by-line or comma-separated text\n"
            "• Or upload a `.txt` file (one email per line)\n\n"
            "Example:\n"
            "`one@hi2.in`\n"
            "`two@telegmail.com`"
        )
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            text, parse_mode="Markdown", reply_markup=keyboards.cancel_keyboard(),
        )

    @bot.message_handler(content_types=["document"])
    def handle_document(message: Message):
        ok, user = guard(bot, message)
        if not ok:
            return

        doc = message.document
        if not doc:
            return

        fname = (doc.file_name or "").lower()
        mime = (doc.mime_type or "").lower()
        is_txt = fname.endswith(".txt") or mime in ("text/plain", "text/txt")
        if not is_txt:
            safe_reply(
                bot, message,
                "⚠️ Please upload a `.txt` file with one email per line.",
                reply_markup=keyboards.main_menu_keyboard(),
            )
            return

        try:
            file_info = bot.get_file(doc.file_id)
            file_bytes = bot.download_file(file_info.file_path)
            text_content = file_bytes.decode("utf-8", errors="ignore")
        except Exception as e:
            safe_reply(bot, message, f"⚠️ Could not read file: {e}", reply_markup=keyboards.main_menu_keyboard())
            return

        emails = parse_emails(text_content)
        if not emails:
            safe_reply(
                bot, message,
                "⚠️ No valid emails found in the file.\nPut one email per line.",
                reply_markup=keyboards.main_menu_keyboard(),
            )
            return

        _awaiting.pop(user.telegram_id, None)
        _process_bulk(bot, message, user, emails)

    @bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
    def handle_text(message: Message):
        ok, user = guard(bot, message)
        if not ok:
            return

        mode = _awaiting.get(user.telegram_id)
        text = (message.text or "").strip()
        emails = parse_emails(text)
        if not emails:
            safe_reply(
                bot, message,
                "⚠️ No valid email found. Send an address like `test@hi2.in`\n"
                "Or upload a `.txt` file for bulk.",
                parse_mode="Markdown",
                reply_markup=keyboards.main_menu_keyboard(),
            )
            return

        if len(emails) > 1 or mode == "bulk":
            _awaiting.pop(user.telegram_id, None)
            _process_bulk(bot, message, user, emails)
        else:
            _awaiting.pop(user.telegram_id, None)
            _run_single(bot, message, user, emails[0])


def _process_bulk(bot, message, user, emails):
    bulk_limit = int(get_setting("bulk_limit", 30))
    count = len(emails)

    if count > bulk_limit:
        safe_reply(
            bot, message,
            f"⚠️ Max {bulk_limit} emails allowed at once for stability!\n"
            f"Your list has {count} emails. Please send {bulk_limit} or fewer.",
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return

    allowed, reason = can_check(user, count)
    if not allowed:
        if reason == "banned":
            return
        if reason.startswith("limit:"):
            remaining = int(reason.split(":")[1])
            safe_reply(
                bot, message,
                messages.not_enough_credits_text(remaining, count),
                parse_mode="Markdown",
                reply_markup=keyboards.premium_keyboard(),
            )
            return
        if reason.startswith("limit"):
            safe_reply(
                bot, message,
                messages.limit_reached_text(),
                parse_mode="Markdown",
                reply_markup=keyboards.premium_keyboard(),
            )
            return

    _run_bulk(bot, message, user, emails)


def _run_single(bot, message, user, email):
    allowed, reason = can_check(user, 1)
    if not allowed:
        if reason == "banned":
            return
        if reason.startswith("limit"):
            safe_reply(
                bot, message,
                messages.limit_reached_text(),
                parse_mode="Markdown",
                reply_markup=keyboards.premium_keyboard(),
            )
            return

    status_msg = safe_reply(bot, message, "⏳ Checking...\n▓░░░░░░░░░")
    mid = status_msg.message_id if status_msg else None
    chat_id = message.chat.id

    def work():
        try:
            if mid:
                animate_loading(bot, chat_id, mid)
            result = check_single_email(email)
            consume_checks(user, [result])
            text = messages.single_result_text(result)
            safe_edit(
                bot, chat_id, mid, text,
                parse_mode="Markdown",
                reply_markup=keyboards.result_keyboard(),
            )
        except Exception as e:
            safe_edit(
                bot, chat_id, mid, f"⚠️ Error: {str(e)[:80]}",
                reply_markup=keyboards.main_menu_keyboard(),
            )

    threading.Thread(target=work, daemon=True).start()


def _run_bulk(bot, message, user, emails):
    count = len(emails)
    status_msg = safe_reply(
        bot, message, f"⏳ Bulk check started ({count} emails)...\n▓░░░░░░░░░"
    )
    mid = status_msg.message_id if status_msg else None
    chat_id = message.chat.id

    def work():
        try:
            if mid:
                animate_loading(bot, chat_id, mid)
            results = check_bulk_emails(emails)
            consume_checks(user, results)
            text = messages.bulk_result_text(results)
            if len(text) > 4000:
                text = text[:3900] + "\n\n... (truncated)"
            safe_edit(
                bot, chat_id, mid, text,
                parse_mode="Markdown",
                reply_markup=keyboards.result_keyboard(),
            )
        except Exception as e:
            safe_edit(
                bot, chat_id, mid, f"⚠️ Error: {str(e)[:80]}",
                reply_markup=keyboards.main_menu_keyboard(),
            )

    threading.Thread(target=work, daemon=True).start()
