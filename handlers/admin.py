"""In-bot Admin Panel via /admin and inline buttons."""
from datetime import datetime, timedelta
from telebot import TeleBot, types
from telebot.types import Message, CallbackQuery
from handlers.middleware import ensure_user
from services.user_service import (
    is_admin_user, ban_user, unban_user, set_premium, remove_premium,
    reset_daily_usage, list_users, get_user, add_bonus_checks,
)
from services.force_join import list_channels, add_channel, update_channel, delete_channel
from services.broadcast import (
    create_broadcast, run_broadcast, get_recipients, request_cancel, entities_to_json,
)
from services.statistics import dashboard_stats
from database import get_setting, set_setting, log_admin_action, get_db, AdminLog
from utils.helpers import safe_edit, safe_reply
import threading

_admin_state = {}
_bc_progress = {}


def _admin_only(bot, message_or_call):
    user = ensure_user(message_or_call)
    if not is_admin_user(user):
        is_cb = isinstance(message_or_call, CallbackQuery)
        if is_cb:
            try:
                bot.answer_callback_query(message_or_call.id, "Admin only", show_alert=True)
            except Exception:
                pass
        else:
            safe_reply(bot, message_or_call, "⛔ Admin access only.")
        return None
    return user


def admin_menu_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📊 Dashboard", callback_data="adm_dash"),
        types.InlineKeyboardButton("👥 Users", callback_data="adm_users:0"),
    )
    kb.add(
        types.InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban_prompt"),
        types.InlineKeyboardButton("✅ Unban User", callback_data="adm_unban_prompt"),
    )
    kb.add(
        types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc"),
        types.InlineKeyboardButton("🔗 Force Join", callback_data="adm_fj"),
    )
    kb.add(
        types.InlineKeyboardButton("💎 Premium", callback_data="adm_users:0:premium"),
        types.InlineKeyboardButton("🚫 Banned List", callback_data="adm_users:0:banned"),
    )
    kb.add(
        types.InlineKeyboardButton("➕ Give Checks", callback_data="adm_give"),
        types.InlineKeyboardButton("⚙️ Settings", callback_data="adm_settings"),
    )
    kb.add(
        types.InlineKeyboardButton("📜 Logs", callback_data="adm_logs"),
        types.InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main"),
    )
    return kb


def register(bot: TeleBot):
    @bot.message_handler(commands=["admin"])
    def cmd_admin(message: Message):
        user = _admin_only(bot, message)
        if not user:
            return
        _admin_state.pop(user.telegram_id, None)
        safe_reply(
            bot, message,
            f"🛠 *Admin Panel*\n\nAdmin: `{user.telegram_id}`",
            parse_mode="Markdown", reply_markup=admin_menu_kb(),
        )

    @bot.callback_query_handler(func=lambda c: c.data == "adm_home")
    def cb_home(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state.pop(user.telegram_id, None)
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            "🛠 *Admin Panel*\n\nSelect a section below.",
            parse_mode="Markdown", reply_markup=admin_menu_kb(),
        )

    # ---------- Ban / Unban prompts ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_ban_prompt")
    def cb_ban_prompt(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state[user.telegram_id] = {"mode": "ban_user"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            "🚫 *Ban User*\n\nSend the *Telegram User ID* to ban.",
            parse_mode="Markdown", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda c: c.data == "adm_unban_prompt")
    def cb_unban_prompt(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        items, total = list_users(status_filter="banned", limit=20)
        lines = [f"✅ *Unban User*\n\nBanned users ({total}):\n"]
        if not items:
            lines.append("_No banned users._")
        else:
            for u in items:
                uname = f"@{u.username}" if u.username else (u.first_name or "—")
                lines.append(f"• {uname} — `{u.telegram_id}`")
        lines.append("\nSend the *User ID* to unban.")
        _admin_state[user.telegram_id] = {"mode": "unban_user"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
        text = "\n".join(lines)[:4000]
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, parse_mode="Markdown", reply_markup=kb)

    # ---------- Dashboard ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_dash")
    def cb_dash(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        s = dashboard_stats()
        maint = get_setting("maintenance_mode", False)
        text = (
            "📊 *Dashboard*\n\n"
            f"👥 Total Users: *{s['total_users']}*\n"
            f"🟢 Active (7d): *{s['active_users']}*\n"
            f"🔍 Total Checks: *{s['total_checks']}*\n"
            f"📅 Today Checks: *{s['todays_checks']}*\n"
            f"💎 Premium: *{s['premium_users']}*\n"
            f"🚫 Banned: *{s['banned_users']}*\n"
            f"📢 Force Join channels: *{s['force_join_channels']}*\n"
            f"🛠️ Maintenance: *{'ON' if maint else 'OFF'}*\n"
            f"✅ Available: *{s['available']}* | ❌ Taken: *{s['taken']}*"
        )
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="adm_dash"))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, parse_mode="Markdown", reply_markup=kb)

    # ---------- Users ----------
    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_users:"))
    def cb_users(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        parts = call.data.split(":")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        filt = parts[2] if len(parts) > 2 and parts[2] else None
        per = 8
        items, total = list_users(offset=page * per, limit=per, status_filter=filt)
        title = {"premium": "💎 Premium", "banned": "🚫 Banned"}.get(filt, "👥 Users")
        lines = [f"*{title}* (page {page + 1}, total {total})\n"]
        kb = types.InlineKeyboardMarkup(row_width=1)
        for u in items:
            uname = f"@{u.username}" if u.username else (u.first_name or "—")
            label = f"{uname} · {u.telegram_id} · {u.status} · 🎫{u.bonus_checks or 0}"
            kb.add(types.InlineKeyboardButton(label[:64], callback_data=f"adm_user:{u.telegram_id}"))
        nav = []
        suf = f":{filt}" if filt else ""
        if page > 0:
            nav.append(types.InlineKeyboardButton("« Prev", callback_data=f"adm_users:{page-1}{suf}"))
        if (page + 1) * per < total:
            nav.append(types.InlineKeyboardButton("Next »", callback_data=f"adm_users:{page+1}{suf}"))
        if nav:
            kb.row(*nav)
        kb.add(types.InlineKeyboardButton("🔍 Search", callback_data="adm_search"))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
        if not items:
            lines.append("_No users found._")
        safe_edit(bot, call.message.chat.id, call.message.message_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "adm_search")
    def cb_search(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state[user.telegram_id] = {"mode": "search_user"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
        safe_edit(bot, call.message.chat.id, call.message.message_id,
                  "🔍 Send Telegram User ID or username.", parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_user:"))
    def cb_user_detail(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        tid = int(call.data.split(":")[1])
        target = get_user(tid)
        if not target:
            safe_edit(bot, call.message.chat.id, call.message.message_id, "User not found.", reply_markup=admin_menu_kb())
            return
        exp = target.premium_expires.strftime("%Y-%m-%d") if target.premium_expires else "—"
        text = (
            f"👤 User `{target.telegram_id}`\n\n"
            f"Username: @{target.username or '—'}\n"
            f"Name: {target.first_name or '—'}\n"
            f"Status: {target.status}\n"
            f"Premium: {'Yes' if target.is_premium else 'No'} ({exp})\n"
            f"Daily used: {target.daily_usage or 0}\n"
            f"Bonus checks: {target.bonus_checks or 0}\n"
            f"Referrals: {target.referral_count or 0}\n"
            f"Total checks done: {target.total_checks or 0}\n"
            f"Ban reason: {target.ban_reason or '—'}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        if (target.status or "").upper() == "BANNED":
            kb.add(types.InlineKeyboardButton("✅ Unban", callback_data=f"adm_unban:{tid}"))
        else:
            kb.add(types.InlineKeyboardButton("🚫 Ban", callback_data=f"adm_ban:{tid}"))
        if target.is_premium:
            kb.add(types.InlineKeyboardButton("Remove Premium", callback_data=f"adm_rmprem:{tid}"))
        else:
            kb.add(types.InlineKeyboardButton("💎 Premium 30d", callback_data=f"adm_prem:{tid}"))
        kb.add(types.InlineKeyboardButton("➕ Give Checks", callback_data=f"adm_give_user:{tid}"))
        kb.add(types.InlineKeyboardButton("🔄 Reset Daily", callback_data=f"adm_reset:{tid}"))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_users:0"))
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_ban:"))
    def cb_ban(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        tid = int(call.data.split(":")[1])
        ban_user(tid, "Banned by admin", str(user.telegram_id))
        try:
            bot.send_message(
                tid,
                "🚫 You have been banned from this bot for violating the rules.\n"
                "Kindly contact admin for unban.",
            )
        except Exception:
            pass
        try:
            bot.answer_callback_query(call.id, "Banned")
        except Exception:
            pass
        call.data = f"adm_user:{tid}"
        cb_user_detail(call)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_unban:"))
    def cb_unban(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        tid = int(call.data.split(":")[1])
        unban_user(tid, str(user.telegram_id))
        try:
            bot.send_message(
                tid,
                "✅ You have been unbanned from this bot.\n"
                "Kindly use /start command to start the mail checks.",
            )
        except Exception:
            pass
        try:
            bot.answer_callback_query(call.id, "Unbanned")
        except Exception:
            pass
        call.data = f"adm_user:{tid}"
        cb_user_detail(call)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_prem:"))
    def cb_prem(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        tid = int(call.data.split(":")[1])
        set_premium(tid, datetime.utcnow() + timedelta(days=30), str(user.telegram_id))
        try:
            bot.answer_callback_query(call.id, "Premium 30d granted")
        except Exception:
            pass
        call.data = f"adm_user:{tid}"
        cb_user_detail(call)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_rmprem:"))
    def cb_rmprem(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        tid = int(call.data.split(":")[1])
        remove_premium(tid, str(user.telegram_id))
        try:
            bot.answer_callback_query(call.id, "Premium removed")
        except Exception:
            pass
        call.data = f"adm_user:{tid}"
        cb_user_detail(call)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_reset:"))
    def cb_reset(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        tid = int(call.data.split(":")[1])
        reset_daily_usage(tid, str(user.telegram_id))
        try:
            bot.answer_callback_query(call.id, "Daily reset")
        except Exception:
            pass
        call.data = f"adm_user:{tid}"
        cb_user_detail(call)

    # ---------- Give checks ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_give")
    def cb_give(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state[user.telegram_id] = {"mode": "give_checks"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            "➕ *Give Checks*\n\nSend: `USER_ID AMOUNT`\nExample: `123456789 100`",
            parse_mode="Markdown", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_give_user:"))
    def cb_give_user(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        tid = int(call.data.split(":")[1])
        _admin_state[user.telegram_id] = {"mode": "give_checks_uid", "uid": tid}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data=f"adm_user:{tid}"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            f"➕ Send number of checks for `{tid}`",
            parse_mode="Markdown", reply_markup=kb,
        )

    # ---------- Force Join ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_fj")
    def cb_fj(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        enabled = get_setting("force_join_enabled", True)
        channels = list_channels()
        lines = [f"🔗 *Force Join*\n\nStatus: *{'Enabled' if enabled else 'Disabled'}*\n"]
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton(
            f"{'🔴 Disable' if enabled else '🟢 Enable'} Force Join",
            callback_data="adm_fj_toggle",
        ))
        for ch in channels:
            flag = "✅" if ch.is_enabled else "⏸"
            kb.add(types.InlineKeyboardButton(
                f"{flag} {ch.name}",
                callback_data=f"adm_fj_ch:{ch.id}",
            ))
        kb.add(types.InlineKeyboardButton("➕ Add Channel (forward msg)", callback_data="adm_fj_add"))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
        if not channels:
            lines.append("_No channels configured._")
        safe_edit(bot, call.message.chat.id, call.message.message_id, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "adm_fj_toggle")
    def cb_fj_toggle(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        set_setting("force_join_enabled", not bool(get_setting("force_join_enabled", True)))
        try:
            bot.answer_callback_query(call.id, "Updated")
        except Exception:
            pass
        cb_fj(call)

    @bot.callback_query_handler(func=lambda c: c.data == "adm_fj_add")
    def cb_fj_add(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state[user.telegram_id] = {"mode": "fj_forward"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_fj"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            "➕ *Add Force Join Channel*\n\n"
            "1. Add this bot as *admin* in your channel.\n"
            "2. *Forward any message* from that channel to me here.\n\n"
            "I will auto-detect channel ID, name, username and invite link.",
            parse_mode="Markdown", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_fj_ch:"))
    def cb_fj_ch(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        ch_id = int(call.data.split(":")[1])
        ch = next((c for c in list_channels() if c.id == ch_id), None)
        if not ch:
            cb_fj(call)
            return
        text = (
            f"📢 *{ch.name}*\n\n"
            f"Username: @{ch.username or '—'}\n"
            f"ID: `{ch.channel_id or '—'}`\n"
            f"Invite: {ch.invite_link or '—'}\n"
            f"Enabled: {ch.is_enabled}"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("Toggle", callback_data=f"adm_fj_en:{ch_id}"),
            types.InlineKeyboardButton("🗑 Delete", callback_data=f"adm_fj_del:{ch_id}"),
        )
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_fj"))
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_fj_en:"))
    def cb_fj_en(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        ch_id = int(call.data.split(":")[1])
        ch = next((c for c in list_channels() if c.id == ch_id), None)
        if ch:
            update_channel(ch_id, is_enabled=not ch.is_enabled)
        try:
            bot.answer_callback_query(call.id, "Updated")
        except Exception:
            pass
        call.data = f"adm_fj_ch:{ch_id}"
        cb_fj_ch(call)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_fj_del:"))
    def cb_fj_del(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        delete_channel(int(call.data.split(":")[1]))
        try:
            bot.answer_callback_query(call.id, "Deleted")
        except Exception:
            pass
        cb_fj(call)

    # ---------- Settings ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_settings")
    def cb_settings(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        limit = get_setting("daily_free_limit", 40)
        bulk = get_setting("bulk_limit", 30)
        ref = get_setting("referral_reward", 5)
        maint = bool(get_setting("maintenance_mode", False))
        fj = bool(get_setting("force_join_enabled", True))
        text = (
            "⚙️ *Settings*\n\n"
            f"Daily free limit: *{limit}*\n"
            f"Bulk limit: *{bulk}*\n"
            f"Referral reward: *{ref}* checks\n"
            f"Maintenance: *{'ON' if maint else 'OFF'}*\n"
            f"Force Join: *{'ON' if fj else 'OFF'}*"
        )
        kb = types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            types.InlineKeyboardButton("Daily −5", callback_data="adm_set:daily:-5"),
            types.InlineKeyboardButton("Daily +5", callback_data="adm_set:daily:+5"),
        )
        kb.add(
            types.InlineKeyboardButton("Bulk −5", callback_data="adm_set:bulk:-5"),
            types.InlineKeyboardButton("Bulk +5", callback_data="adm_set:bulk:+5"),
        )
        kb.add(
            types.InlineKeyboardButton("Refer −1", callback_data="adm_set:ref:-1"),
            types.InlineKeyboardButton("Refer +1", callback_data="adm_set:ref:+1"),
        )
        kb.add(types.InlineKeyboardButton(
            f"🛠️ Maintenance: {'ON' if maint else 'OFF'}",
            callback_data="adm_set:maint:toggle",
        ))
        kb.add(types.InlineKeyboardButton(
            f"Force Join: {'ON' if fj else 'OFF'}",
            callback_data="adm_set:fj:toggle",
        ))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, parse_mode="Markdown", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_set:"))
    def cb_set(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        parts = call.data.split(":")
        key, action = parts[1], parts[2]
        if key == "daily":
            set_setting("daily_free_limit", max(1, int(get_setting("daily_free_limit", 40)) + int(action)))
        elif key == "bulk":
            set_setting("bulk_limit", max(1, min(50, int(get_setting("bulk_limit", 30)) + int(action))))
        elif key == "ref":
            set_setting("referral_reward", max(0, int(get_setting("referral_reward", 5)) + int(action)))
        elif key == "maint":
            new_val = not bool(get_setting("maintenance_mode", False))
            set_setting("maintenance_mode", new_val)
            log_admin_action("maintenance_mode", str(new_val), str(user.telegram_id))
        elif key == "fj":
            set_setting("force_join_enabled", not bool(get_setting("force_join_enabled", True)))
        try:
            bot.answer_callback_query(call.id, "Saved")
        except Exception:
            pass
        cb_settings(call)

    # ---------- Logs (no Markdown to avoid parse errors) ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_logs")
    def cb_logs(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        session = get_db()
        try:
            logs = session.query(AdminLog).order_by(AdminLog.created_at.desc()).limit(20).all()
            lines = ["📜 Recent Logs\n"]
            for log in logs:
                ts = log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else ""
                detail = (log.details or "")[:80]
                lines.append(f"{ts} | {log.action} | {detail}")
            if len(logs) == 0:
                lines.append("No logs yet.")
            text = "\n".join(lines)[:4000]
        finally:
            session.close()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="adm_logs"))
        kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
        # plain text — avoid Markdown parse errors from special chars in logs
        safe_edit(bot, call.message.chat.id, call.message.message_id, text, reply_markup=kb)

    # ---------- Broadcast ----------
    @bot.callback_query_handler(func=lambda c: c.data == "adm_bc")
    def cb_bc(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        _admin_state[user.telegram_id] = {"mode": "broadcast_content"}
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            "📢 *Broadcast*\n\n"
            "Send text / photo / video / audio / GIF.\n"
            "Bold, italic, quote, links and fancy fonts are preserved.\n\n"
            "Then choose the audience.",
            parse_mode="Markdown", reply_markup=kb,
        )

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_bc_target:"))
    def cb_bc_target(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        target = call.data.split(":")[1]
        state = _admin_state.get(user.telegram_id) or {}
        if not state.get("broadcast_ready"):
            try:
                bot.answer_callback_query(call.id, "No content", show_alert=True)
            except Exception:
                pass
            return
        recipients = get_recipients(target)
        bid = create_broadcast(
            message=state.get("message"),
            target=target,
            admin_name=str(user.telegram_id),
            media_type=state.get("media_type"),
            media_file_id=state.get("media_file_id"),
            caption=state.get("caption"),
            entities_json=state.get("entities_json"),
            caption_entities_json=state.get("caption_entities_json"),
        )
        _admin_state.pop(user.telegram_id, None)
        try:
            bot.answer_callback_query(call.id, "Starting...")
        except Exception:
            pass
        cancel_kb = types.InlineKeyboardMarkup()
        cancel_kb.add(types.InlineKeyboardButton("⏹ Cancel Broadcast", callback_data=f"adm_bc_cancel:{bid}"))
        safe_edit(
            bot, call.message.chat.id, call.message.message_id,
            f"📢 Broadcasting to *{len(recipients)}* users...\nYou can cancel anytime.",
            parse_mode="Markdown", reply_markup=cancel_kb,
        )

        def work():
            sent, failed, cancelled = run_broadcast(bot, bid)
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("« Admin Home", callback_data="adm_home"))
            status = "Cancelled" if cancelled else "Completed"
            try:
                bot.edit_message_text(
                    f"{'⏹' if cancelled else '✅'} Broadcast {status}\n\nSent: {sent}\nFailed: {failed}",
                    call.message.chat.id, call.message.message_id, reply_markup=kb,
                )
            except Exception:
                try:
                    bot.send_message(call.message.chat.id, f"Broadcast {status}: sent={sent} failed={failed}", reply_markup=kb)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    @bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("adm_bc_cancel:"))
    def cb_bc_cancel(call: CallbackQuery):
        user = _admin_only(bot, call)
        if not user:
            return
        request_cancel(int(call.data.split(":")[1]))
        try:
            bot.answer_callback_query(call.id, "Cancel requested...")
        except Exception:
            pass

    # ---------- Admin input (text + media + forwarded) ----------
    @bot.message_handler(
        content_types=["text", "photo", "video", "audio", "animation", "document"],
        func=lambda m: m.from_user and m.from_user.id in _admin_state,
    )
    def admin_input(message: Message):
        user = _admin_only(bot, message)
        if not user:
            return
        state = _admin_state.get(user.telegram_id) or {}
        mode = state.get("mode")

        # Force-join: forwarded channel message
        if mode == "fj_forward":
            chat = None
            if getattr(message, "forward_from_chat", None):
                chat = message.forward_from_chat
            elif getattr(message, "forward_origin", None):
                # API 7+ 
                origin = message.forward_origin
                chat = getattr(origin, "chat", None)
            if not chat:
                safe_reply(
                    bot, message,
                    "Please *forward a message from the channel* (not copy).\n"
                    "Make sure the bot is admin in that channel.",
                    parse_mode="Markdown",
                )
                return
            _admin_state.pop(user.telegram_id, None)
            ch_id = str(chat.id)
            name = getattr(chat, "title", None) or getattr(chat, "username", None) or "Channel"
            username = getattr(chat, "username", None)
            invite = None
            try:
                # works if bot is admin with invite permission
                invite = bot.export_chat_invite_link(chat.id)
            except Exception:
                try:
                    link_obj = bot.create_chat_invite_link(chat.id, name="ForceJoin")
                    invite = getattr(link_obj, "invite_link", None)
                except Exception:
                    if username:
                        invite = f"https://t.me/{username}"
            ctype = "public" if username else "private"
            add_channel(
                name=name,
                username=username,
                channel_id=ch_id,
                invite_link=invite,
                channel_type=ctype,
                is_enabled=True,
            )
            log_admin_action("force_join_added", f"{name} {ch_id}", str(user.telegram_id))
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("🔗 Force Join", callback_data="adm_fj"))
            kb.add(types.InlineKeyboardButton("« Admin Home", callback_data="adm_home"))
            safe_reply(
                bot, message,
                f"✅ Channel added\n\nName: {name}\nID: `{ch_id}`\n"
                f"Username: @{username or '—'}\nInvite: {invite or '—'}\n\n"
                "Force Join is ready (make sure bot stays admin).",
                parse_mode="Markdown", reply_markup=kb,
            )
            return

        if mode == "ban_user":
            _admin_state.pop(user.telegram_id, None)
            text = (message.text or "").strip()
            if not text.isdigit():
                safe_reply(bot, message, "Send numeric User ID.", reply_markup=admin_menu_kb())
                return
            tid = int(text)
            # ensure user row exists
            from services.user_service import get_or_create_user
            get_or_create_user(tid)  # returns (user, is_new, ref_event)
            ban_user(tid, "Banned by admin", str(user.telegram_id))
            try:
                bot.send_message(
                    tid,
                    "🚫 You have been banned from this bot for violating the rules.\n"
                    "Kindly contact admin for unban.",
                )
            except Exception:
                pass
            safe_reply(bot, message, f"✅ User `{tid}` banned.", parse_mode="Markdown", reply_markup=admin_menu_kb())
            return

        if mode == "unban_user":
            _admin_state.pop(user.telegram_id, None)
            text = (message.text or "").strip()
            if not text.isdigit():
                safe_reply(bot, message, "Send numeric User ID.", reply_markup=admin_menu_kb())
                return
            tid = int(text)
            ok = unban_user(tid, str(user.telegram_id))
            if not ok:
                safe_reply(bot, message, "User not found.", reply_markup=admin_menu_kb())
                return
            try:
                bot.send_message(
                    tid,
                    "✅ You have been unbanned from this bot.\n"
                    "Kindly use /start command to start the mail checks.",
                )
            except Exception:
                pass
            safe_reply(bot, message, f"✅ User `{tid}` unbanned.", parse_mode="Markdown", reply_markup=admin_menu_kb())
            return

        if mode == "search_user":
            _admin_state.pop(user.telegram_id, None)
            q = (message.text or "").strip().lstrip("@")
            items, total = list_users(search=q, limit=10)
            if not items:
                safe_reply(bot, message, "No users found.", reply_markup=admin_menu_kb())
                return
            kb = types.InlineKeyboardMarkup(row_width=1)
            for u in items:
                uname = f"@{u.username}" if u.username else (u.first_name or "—")
                kb.add(types.InlineKeyboardButton(f"{uname} · {u.telegram_id}", callback_data=f"adm_user:{u.telegram_id}"))
            kb.add(types.InlineKeyboardButton("« Back", callback_data="adm_home"))
            safe_reply(bot, message, f"Found {total}:", reply_markup=kb)
            return

        if mode == "give_checks":
            _admin_state.pop(user.telegram_id, None)
            parts = (message.text or "").strip().split()
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1].lstrip("-").isdigit():
                safe_reply(bot, message, "Use: USER_ID AMOUNT", reply_markup=admin_menu_kb())
                return
            tid, amount = int(parts[0]), int(parts[1])
            from services.user_service import get_or_create_user
            get_or_create_user(tid)  # returns (user, is_new, ref_event)
            ok = add_bonus_checks(tid, amount, str(user.telegram_id))
            if ok:
                safe_reply(bot, message, f"✅ Gave {amount} checks to {tid}.", reply_markup=admin_menu_kb())
                try:
                    bot.send_message(tid, f"🎁 You received {amount} bonus checks!")
                except Exception:
                    pass
            else:
                safe_reply(bot, message, "Failed.", reply_markup=admin_menu_kb())
            return

        if mode == "give_checks_uid":
            uid = state.get("uid")
            _admin_state.pop(user.telegram_id, None)
            text = (message.text or "").strip()
            if not text.lstrip("-").isdigit():
                safe_reply(bot, message, "Send a number.", reply_markup=admin_menu_kb())
                return
            amount = int(text)
            ok = add_bonus_checks(uid, amount, str(user.telegram_id))
            if ok:
                safe_reply(bot, message, f"✅ Gave {amount} checks to {uid}.", reply_markup=admin_menu_kb())
                try:
                    bot.send_message(uid, f"🎁 You received {amount} bonus checks!")
                except Exception:
                    pass
            else:
                safe_reply(bot, message, "Failed.", reply_markup=admin_menu_kb())
            return

        if mode == "broadcast_content":
            media_type = None
            media_file_id = None
            caption = None
            text_msg = None
            entities_json = None
            caption_entities_json = None

            if message.content_type == "photo":
                media_type = "photo"
                media_file_id = message.photo[-1].file_id
                caption = message.caption
                caption_entities_json = entities_to_json(message.caption_entities)
            elif message.content_type == "video":
                media_type = "video"
                media_file_id = message.video.file_id
                caption = message.caption
                caption_entities_json = entities_to_json(message.caption_entities)
            elif message.content_type == "audio":
                media_type = "audio"
                media_file_id = message.audio.file_id
                caption = message.caption
                caption_entities_json = entities_to_json(message.caption_entities)
            elif message.content_type == "animation":
                media_type = "animation"
                media_file_id = message.animation.file_id
                caption = message.caption
                caption_entities_json = entities_to_json(message.caption_entities)
            elif message.content_type == "document":
                media_type = "document"
                media_file_id = message.document.file_id
                caption = message.caption
                caption_entities_json = entities_to_json(message.caption_entities)
            else:
                text_msg = message.text
                entities_json = entities_to_json(message.entities)

            _admin_state[user.telegram_id] = {
                "mode": "broadcast_target",
                "broadcast_ready": True,
                "message": text_msg,
                "media_type": media_type,
                "media_file_id": media_file_id,
                "caption": caption,
                "entities_json": entities_json,
                "caption_entities_json": caption_entities_json,
            }
            kb = types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                types.InlineKeyboardButton("All", callback_data="adm_bc_target:all"),
                types.InlineKeyboardButton("Free", callback_data="adm_bc_target:free"),
            )
            kb.add(
                types.InlineKeyboardButton("Premium", callback_data="adm_bc_target:premium"),
                types.InlineKeyboardButton("Active 7d", callback_data="adm_bc_target:active"),
            )
            kb.add(types.InlineKeyboardButton("« Cancel", callback_data="adm_home"))
            n = len(get_recipients("all"))
            safe_reply(bot, message, f"Content saved. Audience (~{n} users):", reply_markup=kb)
