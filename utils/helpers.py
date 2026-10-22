import time
from telebot import TeleBot
from telebot.types import Message, CallbackQuery


def animate_loading(bot: TeleBot, chat_id: int, message_id: int = None, frames=None, delay=0.6):
    """Lightweight progress animation by editing the same message."""
    if frames is None:
        frames = [
            "⏳ Checking...\n▓░░░░░░░░░",
            "⏳ Checking...\n▓▓▓▓░░░░░░",
            "⏳ Checking...\n▓▓▓▓▓▓▓▓▓▓",
        ]
    mid = message_id
    for frame in frames:
        try:
            if mid is None:
                msg = bot.send_message(chat_id, frame)
                mid = msg.message_id
            else:
                bot.edit_message_text(frame, chat_id, mid)
        except Exception:
            pass
        time.sleep(delay)
    return mid


def live_progress_edit(bot: TeleBot, chat_id: int, message_id: int, base: str,
                       started: float, queue_pos: int = 0, filled: int = None):
    """
    ONE accurate loading frame — no misleading full bar, no freeze.

    Shows real queue position while waiting, then an elapsed-seconds counter
    with a slow "honest" stepped bar (fills toward ~30s then holds). The bar
    never claims 100% before a result exists, so the message is truthful and
    never looks stuck. Returns the text it rendered.
    """
    elapsed = max(0.0, time.time() - started)
    if queue_pos and queue_pos > 0:
        line2 = f"Queued #{queue_pos} · {int(elapsed)}s"
        frac = 0.1
    else:
        line2 = f"{int(elapsed)}s elapsed"
        # honest bar: ~10 cells over 30s, then hold at 10 (still "working")
        frac = min(1.0, elapsed / 30.0)
    if filled is None:
        filled = int(round(frac * 10))
    bar = "▓" * filled + "░" * (10 - filled)
    text = f"{base}\n{bar}\n⏳ {line2}"
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception:
        # progress ticker only: NEVER fall back to a fresh send_message here
        # (an edit flood would otherwise spam the chat with new messages)
        pass
    return text


def safe_edit(bot: TeleBot, chat_id: int, message_id: int, text: str, **kwargs):
    try:
        bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except Exception:
        try:
            bot.send_message(chat_id, text, **kwargs)
        except Exception:
            pass


def safe_reply(bot: TeleBot, message: Message, text: str, **kwargs):
    try:
        return bot.reply_to(message, text, **kwargs)
    except Exception:
        try:
            return bot.send_message(message.chat.id, text, **kwargs)
        except Exception:
            return None


def extract_user(message_or_call):
    if isinstance(message_or_call, CallbackQuery):
        u = message_or_call.from_user
    else:
        u = message_or_call.from_user
    return u.id, u.username, u.first_name, getattr(u, "last_name", None)
