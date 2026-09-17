from database import get_db, ForceJoinChannel, get_setting
from types import SimpleNamespace
import telebot

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
    """
    if not is_force_join_enabled():
        return True, []

    channels = get_enabled_channels()
    if not channels:
        return True, []

    missing = []
    for ch in channels:
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
            if status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            # If we cannot verify (private without bot admin, etc.) treat as not joined
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
