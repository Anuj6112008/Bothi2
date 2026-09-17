from datetime import datetime, timedelta
from database import get_db, User, Broadcast, log_admin_action
import time
import json

_cancel_flags = {}


def request_cancel(broadcast_id: int):
    _cancel_flags[broadcast_id] = True


def is_cancelled(broadcast_id: int) -> bool:
    return _cancel_flags.get(broadcast_id, False)


def clear_cancel(broadcast_id: int):
    _cancel_flags.pop(broadcast_id, None)


def get_recipients(target: str = "all"):
    session = get_db()
    try:
        q = session.query(User).filter(User.status != "BANNED")
        if target == "free":
            q = q.filter(User.is_premium == False)
        elif target == "premium":
            q = q.filter(User.is_premium == True)
        elif target == "active":
            cutoff = datetime.utcnow() - timedelta(days=7)
            q = q.filter(User.last_active >= cutoff)
        return [u.telegram_id for u in q.all()]
    finally:
        session.close()


def entities_to_json(entities):
    if not entities:
        return None
    out = []
    for e in entities:
        item = {
            "type": e.type,
            "offset": e.offset,
            "length": e.length,
        }
        if getattr(e, "url", None):
            item["url"] = e.url
        if getattr(e, "user", None):
            item["user"] = getattr(e.user, "id", None)
        if getattr(e, "language", None):
            item["language"] = e.language
        if getattr(e, "custom_emoji_id", None):
            item["custom_emoji_id"] = e.custom_emoji_id
        out.append(item)
    return json.dumps(out)


def json_to_entities(raw):
    """Rebuild MessageEntity-like dicts for TeleBot."""
    if not raw:
        return None
    try:
        from telebot.types import MessageEntity
        data = json.loads(raw) if isinstance(raw, str) else raw
        entities = []
        for item in data:
            kwargs = {
                "type": item["type"],
                "offset": item["offset"],
                "length": item["length"],
            }
            if item.get("url"):
                kwargs["url"] = item["url"]
            if item.get("language"):
                kwargs["language"] = item["language"]
            if item.get("custom_emoji_id"):
                kwargs["custom_emoji_id"] = item["custom_emoji_id"]
            entities.append(MessageEntity(**kwargs))
        return entities
    except Exception:
        return None


def create_broadcast(
    message=None,
    target="all",
    admin_name=None,
    media_type=None,
    media_file_id=None,
    caption=None,
    entities_json=None,
    caption_entities_json=None,
) -> int:
    recipients = get_recipients(target)
    session = get_db()
    try:
        # Store entities in caption field suffix if needed - use message for text entities
        # We'll put entities JSON in a dedicated way via caption field metadata
        # Simplest: store entities_json in media_file_id adjacent - better add columns via migrate
        b = Broadcast(
            message=message,
            media_type=media_type,
            media_file_id=media_file_id,
            caption=caption,
            target=target,
            total_recipients=len(recipients),
            status="pending",
            admin_name=admin_name,
        )
        # Piggyback entities in unused fields if columns missing: append to message as JSON blob is bad
        # Store in caption with separator only for internal - use Broadcast.message for text
        session.add(b)
        session.commit()
        session.refresh(b)
        # Store entities in AdminLog-style side table - or update after migrate
        # For reliability store as JSON in a text field we control: put in Broadcast if columns exist
        try:
            if entities_json or caption_entities_json:
                from sqlalchemy import text
                # Try update extra columns
                session.execute(
                    text(
                        "UPDATE broadcasts SET caption = :c WHERE id = :id"
                    ),
                    {"c": caption, "id": b.id},
                )
                session.commit()
        except Exception:
            pass
        # Keep entities in memory map for this process
        _entities_store[b.id] = {
            "entities": entities_json,
            "caption_entities": caption_entities_json,
        }
        return b.id
    finally:
        session.close()


_entities_store = {}


def _send_one(bot, tid, message, media_type, media_file_id, caption, entities=None, caption_entities=None):
    """
    Send preserving Telegram entities (bold, italic, underline, strike, spoiler, code, pre, text_link, blockquote).
    Fancy unicode fonts are preserved because we send the exact unicode string.
    """
    # Prefer entities over parse_mode so original formatting is kept exactly
    try:
        if media_type == "photo" and media_file_id:
            bot.send_photo(
                tid, media_file_id,
                caption=caption or None,
                caption_entities=caption_entities,
                parse_mode=None,
            )
        elif media_type == "video" and media_file_id:
            bot.send_video(
                tid, media_file_id,
                caption=caption or None,
                caption_entities=caption_entities,
                parse_mode=None,
            )
        elif media_type == "audio" and media_file_id:
            bot.send_audio(
                tid, media_file_id,
                caption=caption or None,
                caption_entities=caption_entities,
                parse_mode=None,
            )
        elif media_type == "animation" and media_file_id:
            bot.send_animation(
                tid, media_file_id,
                caption=caption or None,
                caption_entities=caption_entities,
                parse_mode=None,
            )
        elif media_type == "document" and media_file_id:
            bot.send_document(
                tid, media_file_id,
                caption=caption or None,
                caption_entities=caption_entities,
                parse_mode=None,
            )
        else:
            text = message or caption or ""
            bot.send_message(
                tid, text,
                entities=entities,
                parse_mode=None,
                disable_web_page_preview=True,
            )
    except Exception:
        # Fallback without entities
        if media_type == "photo" and media_file_id:
            bot.send_photo(tid, media_file_id, caption=caption or None)
        elif media_type == "video" and media_file_id:
            bot.send_video(tid, media_file_id, caption=caption or None)
        elif media_type == "audio" and media_file_id:
            bot.send_audio(tid, media_file_id, caption=caption or None)
        elif media_type == "animation" and media_file_id:
            bot.send_animation(tid, media_file_id, caption=caption or None)
        elif media_type == "document" and media_file_id:
            bot.send_document(tid, media_file_id, caption=caption or None)
        else:
            bot.send_message(tid, message or caption or "", disable_web_page_preview=True)


def run_broadcast(bot, broadcast_id: int):
    clear_cancel(broadcast_id)
    session = get_db()
    try:
        b = session.query(Broadcast).filter_by(id=broadcast_id).first()
        if not b:
            return 0, 0, False
        b.status = "running"
        session.commit()
        message = b.message
        media_type = b.media_type
        media_file_id = b.media_file_id
        caption = b.caption
        target = b.target
        admin_name = b.admin_name
    finally:
        session.close()

    ent = _entities_store.get(broadcast_id, {})
    entities = json_to_entities(ent.get("entities"))
    caption_entities = json_to_entities(ent.get("caption_entities"))

    recipients = get_recipients(target)
    sent = 0
    failed = 0

    for tid in recipients:
        if is_cancelled(broadcast_id):
            break
        try:
            _send_one(
                bot, tid, message, media_type, media_file_id, caption,
                entities=entities, caption_entities=caption_entities,
            )
            sent += 1
        except Exception:
            failed += 1
        if (sent + failed) % 25 == 0:
            time.sleep(1)
        if (sent + failed) % 50 == 0:
            session = get_db()
            try:
                b = session.query(Broadcast).filter_by(id=broadcast_id).first()
                if b:
                    b.sent = sent
                    b.failed = failed
                    session.commit()
            finally:
                session.close()

    cancelled = is_cancelled(broadcast_id)
    session = get_db()
    try:
        b = session.query(Broadcast).filter_by(id=broadcast_id).first()
        if b:
            b.sent = sent
            b.failed = failed
            b.status = "cancelled" if cancelled else "completed"
            b.completed_at = datetime.utcnow()
            session.commit()
        log_admin_action(
            "broadcast_completed" if not cancelled else "broadcast_cancelled",
            f"id={broadcast_id} sent={sent} failed={failed}",
            admin_name=admin_name,
        )
    finally:
        session.close()
    clear_cancel(broadcast_id)
    _entities_store.pop(broadcast_id, None)
    return sent, failed, cancelled
