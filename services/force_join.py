from database import get_db, ForceJoinChannel, get_setting
from types import SimpleNamespace
import threading
import time
import telebot

# ---- Membership cache -------------------------------------------------
# guard() runs on EVERY message/callback; without a cache that's a
# getChatMember Telegram API call per channel per update -> rate limits.
# Results (joined AND not-joined) are cached for FORCE_JOIN_CACHE_TTL.
import config

_CACHE_TTL = getattr(config, "FORCE_JOIN_CACHE_TTL", 300)
_cache_lock = threading.Lock()
_cache = {}          # (user_id, channel_row_id) -> (ok: bool, ts: float)
_version = 0          # bumped whenever channels change -> invalidates all


def invalidate_user(user_id: int):
    """Drop cached results for one user (used by the Verify button)."""
    with _cache_lock:
        for key in [k for k in _cache if k[0] == user_id]:
            _cache.pop(key, None)


def invalidate_all():
    """Drop every cached result (channel added/removed/toggled)."""
    global _version
    with _cache_lock:
        _version += 1
        _cache.clear()


def _cache_get(user_id, ch_id, version):
    with _cache_lock:
        hit = _cache.get((user_id, ch_id, version))
    if not hit:
        return None
    ok, ts = hit
    if time.time() - ts > _CACHE_TTL:
        return None
    return ok


def _cache_put(user_id, ch_id, version, ok):
    with _cache_lock:
        _cache[(user_id, ch_id, version)] = (ok, time.time())
        # simple bound so memory can't grow forever
        if len(_cache) > 50000:
            _cache.clear()


def _plain_ch(ch):
    if ch is None:
        return None
    return SimpleNamespace(
        id=ch.id, name=ch.name, username=ch.username, channel_id=ch.channel_id,
        invite_link=ch.invite_link, channel_type=ch.channel_type, is_enabled=ch.is_enabled,
        created_at=getattr(ch, "created_at", None),
    )



def get_enabled_channels():
    session = get_db()
    try:
        rows = (
            session.query(ForceJoinChannel)
            .filter_by(is_enabled=True)
            .order_by(ForceJoinChannel.id)
            .all()
        )
        return [_plain_ch(r) for r in rows]
    finally:
        session.close()


def is_force_join_enabled() -> bool:
    return bool(get_setting("force_join_enabled", True))


def check_membership(bot: telebot.TeleBot, user_id: int) -> tuple[bool, list]:
    """
    Returns (all_joined, missing_channels).
    missing_channels is list of ForceJoinChannel objects still not joined.
    Uses a short-lived cache to avoid hammering the Telegram API.
    """
    if not is_force_join_enabled():
        return True, []

    channels = get_enabled_channels()
    if not channels:
        return True, []

    missing = []
    ver = _version
    for ch in channels:
        cached = _cache_get(user_id, ch.id, ver)
        if cached is True:
            continue
        if cached is False:
            missing.append(ch)
            continue

        chat_id = None
        if ch.channel_id:
            try:
                chat_id = int(ch.channel_id)
            except (TypeError, ValueError):
                chat_id = ch.channel_id
        elif ch.username:
            chat_id = f"@{ch.username.lstrip('@')}"
        else:
            missing.append(ch)
            continue

        try:
            member = bot.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", "")
            joined = status not in ("left", "kicked")
        except Exception:
            # If we cannot verify (private without bot admin, etc.) treat as
            # not joined – but don't cache failures (could be a 429 blip).
            missing.append(ch)
            continue

        _cache_put(user_id, ch.id, ver, joined)
        if not joined:
            missing.append(ch)

    return len(missing) == 0, missing


def add_channel(name, username=None, channel_id=None, invite_link=None, channel_type="public", is_enabled=True):
    session = get_db()
    try:
        ch = ForceJoinChannel(
            name=name,
            username=(username or "").lstrip("@") or None,
            channel_id=str(channel_id) if channel_id else None,
            invite_link=invite_link,
            channel_type=channel_type or "public",
            is_enabled=bool(is_enabled),
        )
        session.add(ch)
        session.commit()
        invalidate_all()
        return ch.id
    finally:
        session.close()


def update_channel(ch_id, **kwargs):
    session = get_db()
    try:
        ch = session.query(ForceJoinChannel).filter_by(id=ch_id).first()
        if not ch:
            return False
        for k, v in kwargs.items():
            if hasattr(ch, k):
                if k == "username" and v:
                    v = str(v).lstrip("@")
                setattr(ch, k, v)
        session.commit()
        invalidate_all()
        return True
    finally:
        session.close()


def delete_channel(ch_id):
    session = get_db()
    try:
        ch = session.query(ForceJoinChannel).filter_by(id=ch_id).first()
        if not ch:
            return False
        session.delete(ch)
        session.commit()
        invalidate_all()
        return True
    finally:
        session.close()


def list_channels():
    session = get_db()
    try:
        rows = session.query(ForceJoinChannel).order_by(ForceJoinChannel.id).all()
        return [_plain_ch(r) for r in rows]
    finally:
        session.close()
