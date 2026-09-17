import os
from datetime import datetime, date
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, Date,
    Text, UniqueConstraint, BigInteger
)
from sqlalchemy.orm import declarative_base, sessionmaker
import config

_BASE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_BASE, "data")
os.makedirs(_DATA_DIR, exist_ok=True)

_db_url = config.DATABASE_URL or "sqlite:///data/bot.db"
if _db_url.startswith("sqlite:///"):
    rel = _db_url.replace("sqlite:///", "", 1)
    if not os.path.isabs(rel):
        abs_path = os.path.join(_BASE, rel)
        os.makedirs(os.path.dirname(abs_path) or _DATA_DIR, exist_ok=True)
        _db_url = f"sqlite:///{abs_path}"

engine = create_engine(
    _db_url,
    connect_args={"check_same_thread": False} if "sqlite" in _db_url else {},
    pool_pre_ping=True,
)
# Plain sessionmaker — each get_db() returns an independent session
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # BigInteger for large Telegram IDs
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    status = Column(String(32), default="FREE", index=True)
    is_premium = Column(Boolean, default=False)
    premium_expires = Column(DateTime, nullable=True)
    ban_reason = Column(Text, nullable=True)
    daily_usage = Column(Integer, default=0)
    daily_usage_date = Column(Date, default=date.today)
    bonus_checks = Column(Integer, default=0)
    referred_by = Column(BigInteger, nullable=True, index=True)
    referral_count = Column(Integer, default=0)
    referral_credited = Column(Boolean, default=False)
    total_checks = Column(Integer, default=0)
    available_count = Column(Integer, default=0)
    taken_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    is_admin = Column(Boolean, default=False)

    def ensure_daily_reset(self):
        today = date.today()
        raw = self.daily_usage_date
        # SQLite may return str; normalize before compare
        if raw is None:
            stored = None
        elif isinstance(raw, date) and not isinstance(raw, datetime):
            stored = raw
        elif isinstance(raw, datetime):
            stored = raw.date()
        else:
            try:
                s = str(raw)[:10]
                stored = date.fromisoformat(s)
            except Exception:
                stored = None
        if stored != today:
            self.daily_usage = 0
            self.daily_usage_date = today


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    usage_date = Column(Date, default=date.today, index=True)
    checks_count = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_user_date"),)


class CheckLog(Base):
    __tablename__ = "checks"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    email = Column(String(320), nullable=False)
    result = Column(String(32), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ForceJoinChannel(Base):
    __tablename__ = "force_join_channels"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)
    channel_id = Column(String(64), nullable=True)
    invite_link = Column(String(512), nullable=True)
    channel_type = Column(String(32), default="public")
    is_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Broadcast(Base):
    __tablename__ = "broadcasts"
    id = Column(Integer, primary_key=True)
    message = Column(Text, nullable=True)
    media_type = Column(String(32), nullable=True)
    media_file_id = Column(String(512), nullable=True)
    caption = Column(Text, nullable=True)
    target = Column(String(64), default="all")
    total_recipients = Column(Integer, default=0)
    sent = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String(32), default="pending")
    admin_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class AdminLog(Base):
    __tablename__ = "admin_logs"
    id = Column(Integer, primary_key=True)
    action = Column(String(128), nullable=False)
    details = Column(Text, nullable=True)
    admin_name = Column(String(128), nullable=True)
    user_telegram_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate()
    session = SessionLocal()
    try:
        for key, value in config.DEFAULTS.items():
            existing = session.query(Setting).filter_by(key=key).first()
            if not existing:
                session.add(Setting(key=key, value=str(value)))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate():
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    alters = []
    if "bonus_checks" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN bonus_checks INTEGER DEFAULT 0")
    if "referred_by" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN referred_by BIGINT")
    if "referral_count" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN referral_count INTEGER DEFAULT 0")
    if "referral_credited" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN referral_credited BOOLEAN DEFAULT 0")
    if "broadcasts" in insp.get_table_names():
        bcols = {c["name"] for c in insp.get_columns("broadcasts")}
        if "media_type" not in bcols:
            alters.append("ALTER TABLE broadcasts ADD COLUMN media_type VARCHAR(32)")
        if "media_file_id" not in bcols:
            alters.append("ALTER TABLE broadcasts ADD COLUMN media_file_id VARCHAR(512)")
        if "caption" not in bcols:
            alters.append("ALTER TABLE broadcasts ADD COLUMN caption TEXT")
    with engine.connect() as conn:
        for sql in alters:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass


def get_setting(key: str, default=None):
    session = SessionLocal()
    try:
        row = session.query(Setting).filter_by(key=key).first()
        if row is None:
            return default if default is not None else config.DEFAULTS.get(key)
        val = row.value
        if key in ("daily_free_limit", "bulk_limit", "referral_reward"):
            try:
                return int(val)
            except (TypeError, ValueError):
                return config.DEFAULTS.get(key, 5 if key == "referral_reward" else 40)
        if key in ("force_join_enabled", "maintenance_mode"):
            return str(val).lower() in ("1", "true", "yes", "on")
        return val
    finally:
        session.close()


def set_setting(key: str, value):
    session = SessionLocal()
    try:
        if isinstance(value, bool):
            value = "true" if value else "false"
        row = session.query(Setting).filter_by(key=key).first()
        if row:
            row.value = str(value)
        else:
            session.add(Setting(key=key, value=str(value)))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def log_admin_action(action: str, details: str = None, admin_name: str = None, user_telegram_id: int = None):
    session = SessionLocal()
    try:
        session.add(AdminLog(
            action=action,
            details=details,
            admin_name=admin_name,
            user_telegram_id=user_telegram_id,
        ))
        session.commit()
    except Exception:
        session.rollback()
    finally:
        session.close()


def get_db():
    return SessionLocal()
