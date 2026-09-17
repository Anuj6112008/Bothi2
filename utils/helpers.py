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
