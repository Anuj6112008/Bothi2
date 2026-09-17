#!/usr/bin/env python3
"""
Temp Mail Checker Pro – Telegram Bot
Developer: @PyAnuj
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import telebot
import config
from database import init_db

if not config.BOT_TOKEN:
    print("ERROR: BOT_TOKEN is not set. Copy .env.example to .env and fill in your token.")
    print("Also set ADMIN_TELEGRAM_IDS with your Telegram user ID(s).")
    sys.exit(1)

init_db()

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode=None)

from handlers import start, force_join, usage, help as help_handler, checker, admin

start.register(bot)
force_join.register(bot)
usage.register(bot)
help_handler.register(bot)
admin.register(bot)
checker.register(bot)

if __name__ == "__main__":
    print("=" * 50)
    print("Temp Mail Checker Pro – Bot starting...")
    print("Developer: @PyAnuj")
    print("Admin: /admin (set ADMIN_TELEGRAM_IDS in .env)")
    print("=" * 50)
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        raise
