from datetime import datetime, date
from types import SimpleNamespace
from database import get_db, User, CheckLog, log_admin_action, get_setting
import config

_USER_ATTRS = (
    "id", "telegram_id", "username", "first_name", "last_name",
    "status", "is_premium", "premium_expires", "ban_reason",
    "daily_usage", "daily_usage_date", "bonus_checks",
    "referred_by", "referral_count", "referral_credited",
    "total_checks", "available_count", "taken_count", "error_count",
    "joined_at", "last_active", "is_admin",
)


def _to_plain(user):
    if user is None:
        return None
    data = {}
    for attr in _USER_ATTRS:
        try:
            data[attr] = getattr(user, attr, None)
        except Exception:
            data[attr] = None
    # default for older rows
    if data.get("referral_credited") is None:
        data["referral_credited"] = False
    return SimpleNamespace(**data)


def get_or_create_user(telegram_id, username=None, first_name=None, last_name=None, referred_by=None):
    """
    Returns (plain_user, is_new, None).
    Referral is NOT credited here — only stored as referred_by.
    Credit happens after force-join verify via complete_pending_referral().
    """
    telegram_id = int(telegram_id)
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if user:
            user.username = username or user.username
            user.first_name = first_name or user.first_name
            user.last_name = last_name or user.last_name
            user.last_active = datetime.utcnow()
            user.ensure_daily_reset()
            if telegram_id in config.ADMIN_TELEGRAM_IDS:
                user.is_admin = True
                if (user.status or "").upper() != "BANNED":
                    user.status = "ADMIN"
            session.commit()
            return _to_plain(user), False, None

        is_admin = telegram_id in config.ADMIN_TELEGRAM_IDS
        ref = None
        if referred_by is not None:
            try:
                ref_id = int(referred_by)
                if ref_id > 0 and ref_id != telegram_id:
                    # only store if referrer exists
                    exists = session.query(User).filter_by(telegram_id=ref_id).first()
                    if exists:
                        ref = ref_id
            except (TypeError, ValueError):
                ref = None

        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            status="ADMIN" if is_admin else "FREE",
            is_admin=is_admin,
            joined_at=datetime.utcnow(),
            last_active=datetime.utcnow(),
            daily_usage_date=date.today(),
            bonus_checks=0,
            referred_by=ref,
            referral_count=0,
            referral_credited=False,
        )
        session.add(user)
        session.commit()
        log_admin_action(
            "user_joined",
            f"New user {telegram_id} pending_ref={ref}",
            user_telegram_id=telegram_id,
        )
        return _to_plain(user), True, None
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def complete_pending_referral(telegram_id):
    """
    Call after user passes force-join (or if force-join is off, on first successful start).
    Credits referrer once. Returns referral_event dict or None.
    """
    telegram_id = int(telegram_id)
    reward = int(get_setting("referral_reward", 5))
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            return None
        if getattr(user, "referral_credited", False):
            return None
        ref = user.referred_by
        if not ref:
            user.referral_credited = True
            session.commit()
            return None

        referrer = session.query(User).filter_by(telegram_id=int(ref)).first()
        if not referrer or (referrer.status or "").upper() == "BANNED":
            user.referral_credited = True
            session.commit()
            return None

        referrer.bonus_checks = (referrer.bonus_checks or 0) + reward
        referrer.referral_count = (referrer.referral_count or 0) + 1
        user.referral_credited = True
        session.commit()

        event = {
            "referrer_id": int(ref),
            "reward": reward,
            "new_count": referrer.referral_count,
            "bonus_checks": referrer.bonus_checks,
        }
        log_admin_action(
            "referral_reward",
            f"+{reward} to {ref} for inviting {telegram_id}",
            user_telegram_id=int(ref),
        )
        return event
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_user(telegram_id):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if user:
            user.ensure_daily_reset()
            session.commit()
            return _to_plain(user)
        return None
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def is_banned(user):
    if user is None:
        return False
    return (getattr(user, "status", None) or "").upper() == "BANNED"


def is_premium(user):
    if not user or not getattr(user, "is_premium", False):
        return False
    exp = getattr(user, "premium_expires", None)
    if exp and exp < datetime.utcnow():
        session = get_db()
        try:
            u = session.query(User).filter_by(telegram_id=user.telegram_id).first()
            if u:
                u.is_premium = False
                u.status = "FREE"
                u.premium_expires = None
                session.commit()
            user.is_premium = False
            user.status = "FREE"
            user.premium_expires = None
        finally:
            session.close()
        return False
    return True


def is_admin_user(user):
    if user is None:
        return False
    if getattr(user, "is_admin", False):
        return True
    if getattr(user, "telegram_id", None) in config.ADMIN_TELEGRAM_IDS:
        return True
    return False


def remaining_credits(user):
    if is_premium(user):
        return 0, getattr(user, "bonus_checks", 0) or 0, 999999, True
    limit = int(get_setting("daily_free_limit", 40))
    used = getattr(user, "daily_usage", 0) or 0
    daily_rem = max(0, limit - used)
    bonus = getattr(user, "bonus_checks", 0) or 0
    return daily_rem, bonus, daily_rem + bonus, False


def can_check(user, count=1):
    if is_banned(user):
        return False, "banned"
    # Premium = unlimited. Everyone else (including admin accounts) uses free+bonus pool.
    daily_rem, bonus, total, unlimited = remaining_credits(user)
    if unlimited:
        return True, "premium"
    if total < count:
        return False, f"limit:{total}"
    return True, "ok"


def consume_checks(user, results):
    session = get_db()
    try:
        u = session.query(User).filter_by(telegram_id=int(user.telegram_id)).first()
        if not u:
            return
        u.ensure_daily_reset()
        count = len(results)
        # Only active PREMIUM (unlimited) skips free/bonus deduction.
        # FREE users (and admins without premium) always consume credits.
        is_unlim = bool(u.is_premium)
        if is_unlim and u.premium_expires and u.premium_expires < datetime.utcnow():
            u.is_premium = False
            u.status = "FREE"
            u.premium_expires = None
            is_unlim = False
        if not is_unlim:
            limit = int(get_setting("daily_free_limit", 40))
            used = int(u.daily_usage or 0)
            daily_rem = max(0, limit - used)
            from_daily = min(count, daily_rem)
            from_bonus = count - from_daily
            u.daily_usage = used + from_daily
            if from_bonus > 0:
                u.bonus_checks = max(0, int(u.bonus_checks or 0) - from_bonus)
        u.total_checks = int(u.total_checks or 0) + count
        for r in results:
            status = r.get("status")
            if status == "available":
                u.available_count = (u.available_count or 0) + 1
            elif status == "taken":
                u.taken_count = (u.taken_count or 0) + 1
            else:
                u.error_count = (u.error_count or 0) + 1
            session.add(CheckLog(
                user_id=u.id,
                email=(r.get("email") or "")[:320],
                result=status or "error",
            ))
        u.last_active = datetime.utcnow()
        session.commit()
        user.daily_usage = u.daily_usage
        user.bonus_checks = u.bonus_checks
        user.total_checks = u.total_checks
        user.available_count = u.available_count
        user.taken_count = u.taken_count
        user.error_count = u.error_count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def add_bonus_checks(telegram_id, amount, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.bonus_checks = (user.bonus_checks or 0) + int(amount)
        session.commit()
        log_admin_action("checks_granted", f"+{amount}", admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def ban_user(telegram_id, reason=None, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.status = "BANNED"
        user.ban_reason = reason
        session.commit()
        log_admin_action("user_banned", reason, admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def unban_user(telegram_id, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.status = "PREMIUM" if user.is_premium else "FREE"
        user.ban_reason = None
        session.commit()
        log_admin_action("user_unbanned", None, admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def set_premium(telegram_id, expires=None, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.is_premium = True
        user.status = "PREMIUM"
        user.premium_expires = expires
        session.commit()
        log_admin_action("premium_granted", f"expires={expires}", admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def remove_premium(telegram_id, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.is_premium = False
        user.premium_expires = None
        if (user.status or "").upper() != "BANNED":
            user.status = "FREE"
        session.commit()
        log_admin_action("premium_removed", None, admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def reset_daily_usage(telegram_id, admin_name=None):
    session = get_db()
    try:
        user = session.query(User).filter_by(telegram_id=int(telegram_id)).first()
        if not user:
            return False
        user.daily_usage = 0
        user.daily_usage_date = date.today()
        session.commit()
        log_admin_action("daily_reset", None, admin_name, int(telegram_id))
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def list_users(offset=0, limit=10, status_filter=None, search=None):
    session = get_db()
    try:
        q = session.query(User)
        if status_filter == "premium":
            q = q.filter(User.is_premium == True)
        elif status_filter == "banned":
            q = q.filter(User.status == "BANNED")
        elif status_filter == "free":
            q = q.filter(User.is_premium == False, User.status != "BANNED")
        if search:
            if str(search).isdigit():
                q = q.filter(
                    (User.telegram_id == int(search))
                    | (User.username.ilike(f"%{search}%"))
                    | (User.first_name.ilike(f"%{search}%"))
                )
            else:
                q = q.filter(
                    (User.username.ilike(f"%{search}%"))
                    | (User.first_name.ilike(f"%{search}%"))
                )
        total = q.count()
        items = q.order_by(User.joined_at.desc()).offset(offset).limit(limit).all()
        return [_to_plain(u) for u in items], total
    finally:
        session.close()
