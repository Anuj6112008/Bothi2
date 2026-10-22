from telebot import TeleBot
from telebot.types import Message, CallbackQuery
from handlers.middleware import guard
from services.checker import check_single_email, check_bulk_emails, parse_emails
from services import insta_queue
from services.user_service import can_check, consume_checks, remaining_credits
from services import check_queue
from database import get_setting
from utils import messages, keyboards
from utils.helpers import live_progress_edit, safe_edit, safe_reply
import threading
import time
import requests
import io

_awaiting = {}  # telegram_id -> "single" | "bulk" | "insta"


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

    @bot.callback_query_handler(func=lambda c: c.data == "menu_insta")
    def cb_insta(call: CallbackQuery):
        ok, user = guard(bot, call)
        if not ok:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _awaiting[user.telegram_id] = "insta"
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            messages.insta_prompt_text(), parse_mode="Markdown",
            reply_markup=keyboards.cancel_keyboard(),
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
        except Exception:
            try:
                print(f"[checker] file download failed for doc {doc.file_id}")
            except Exception:
                pass
            safe_reply(
                bot, message,
                "⚠️ Could not read that file. Please try re-uploading it.",
                reply_markup=keyboards.main_menu_keyboard(),
            )
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

        if mode == "insta":
            _awaiting.pop(user.telegram_id, None)
            _run_insta(bot, message, user, emails[0])
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

    queued = check_queue.position()
    status_msg = safe_reply(bot, message, "⏳ Checking...")
    mid = status_msg.message_id if status_msg else None
    chat_id = message.chat.id
    started = time.time()

    # Race guard + LIVE progress (same proven pattern as _run_insta). The
    # check starts IMMEDIATELY — no blocking intro animation stealing 1.8s.
    # A spinner thread keeps the message honest (queue pos + elapsed) until
    # the result lands; every edit is serialised by edit_lock so the RESULT
    # is always the LAST edit on this message (no more 5-10s freeze).
    result_ready = threading.Event()
    edit_lock = threading.Lock()

    def _finish(text, reply_markup=None):
        result_ready.set()
        with edit_lock:
            safe_edit(bot, chat_id, mid, text, parse_mode="Markdown",
                      reply_markup=reply_markup)

    def work():
        try:
            result = check_single_email(email)
            consume_checks(user, [result])
            _finish(messages.single_result_text(result),
                    keyboards.result_keyboard())
        except Exception:
            try:
                print(f"[checker] single work error for {email}")
            except Exception:
                pass
            _finish("⚠️ Something went wrong — please try again.\n💳 *0 credits were charged.*",
                    keyboards.main_menu_keyboard())

    def _spin():
        base = "⏳ Checking..."
        while not result_ready.wait(1.1):
            with edit_lock:
                if result_ready.is_set():
                    return
                # re-read live queue depth so the number stays truthful
                pos = check_queue.position()
                live_progress_edit(bot, chat_id, mid, base, started,
                                   queue_pos=pos)

    threading.Thread(target=work, daemon=True).start()
    if mid:
        threading.Thread(target=_spin, daemon=True).start()


def _run_insta(bot, message, user, email):
    """Instagram check: 1 credit only on a definitive answer."""
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

    status_msg = safe_reply(bot, message, "🔎 Checking Instagram...")
    mid = status_msg.message_id if status_msg else None
    chat_id = message.chat.id
    started = time.time()

    # Race guard + LIVE progress. The check starts immediately (no blocking
    # intro); a spinner thread keeps the message honest (elapsed seconds,
    # honest bar) until the result lands. Every edit is serialised by
    # edit_lock and done() only edits after setting result_ready -> the
    # RESULT is always the LAST edit on this message.
    result_ready = threading.Event()    # result edit is about to land
    edit_lock = threading.Lock()

    def _finish(text, reply_markup=None):
        result_ready.set()
        with edit_lock:
            safe_edit(bot, chat_id, mid, text, parse_mode="Markdown",
                      reply_markup=reply_markup)

    def done(result):
        try:
            consume_checks(user, [result])
            text = messages.insta_result_text(result)
        except Exception:
            text = None
        if text is None:
            try:
                print(f"[checker] insta work error for {email}")
            except Exception:
                pass
            _finish("⚠️ Something went wrong — please try again.\n💳 *0 credits were charged.*",
                    keyboards.main_menu_keyboard())
        else:
            _finish(text, keyboards.insta_result_keyboard())

    # bounded queue instead of one thread per user: workers + backlog cap
    if not insta_queue.submit(email, done):
        _finish("⏳ The Instagram checker is busy right now — please try again "
                "in a minute.\n\n💳 *0 credits used* — nothing was charged.",
                keyboards.main_menu_keyboard())
        return

    def _spin():
        base = "🔎 Checking Instagram..."
        while not result_ready.wait(1.1):
            with edit_lock:
                if result_ready.is_set():
                    return
                live_progress_edit(bot, chat_id, mid, base, started)

    if mid:
        threading.Thread(target=_spin, daemon=True).start()


def _run_bulk(bot, message, user, emails):
    count = len(emails)
    status_msg = safe_reply(
        bot, message, f"⏳ Bulk check started ({count} emails)..."
    )
    mid = status_msg.message_id if status_msg else None
    chat_id = message.chat.id
    started = time.time()

    def work():
        try:
            # Live progress: users used to stare at one status message for
            # the WHOLE batch (minutes when slow) and assumed it was stuck.
            # Edit at most every ~4s so Telegram never rate-limits us.
            state = {"last": 0.0}

            def on_progress(done, total):
                if done >= total:
                    return                       # final text replaces this
                now = time.time()
                if now - state["last"] < 4:
                    return
                state["last"] = now
                filled = done * 10 // total
                safe_edit(
                    bot, chat_id, mid,
                    f"⏳ Bulk check in progress: {done}/{total} checked · "
                    f"{int(now - started)}s\n"
                    f"{'▓' * filled}{'░' * (10 - filled)}",
                )

            results = check_bulk_emails(emails, on_progress=on_progress)
            consume_checks(user, results)
            text = messages.bulk_result_text(
                results,
                billed=getattr(user, "_billed_checks", None),
                failed=getattr(user, "_failed_checks", None),
            )
            if len(text) > 4000:
                text = text[:3900] + "\n\n... (truncated)"
            safe_edit(
                bot, chat_id, mid, text,
                parse_mode="Markdown",
                reply_markup=keyboards.result_keyboard(),
            )
        except Exception:
            try:
                print(f"[checker] bulk work error ({count} emails)")
            except Exception:
                pass
            safe_edit(
                bot, chat_id, mid,
                "⚠️ Something went wrong — please try again.\n💳 *Failed checks were not charged.*",
                parse_mode="Markdown",
                reply_markup=keyboards.main_menu_keyboard(),
            )

    threading.Thread(target=work, daemon=True).start()
