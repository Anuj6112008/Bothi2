from datetime import datetime, date, timedelta
from sqlalchemy import func
from database import get_db, User, CheckLog, Broadcast, ForceJoinChannel


def dashboard_stats():
    session = get_db()
    try:
        total_users = session.query(User).count()
        premium_users = session.query(User).filter(User.is_premium == True).count()
        banned_users = session.query(User).filter(User.status == "BANNED").count()
        today = date.today()
        week_ago = datetime.utcnow() - timedelta(days=7)

        active_users = (
            session.query(User)
            .filter(User.last_active >= week_ago)
            .count()
        )
        total_checks = session.query(func.coalesce(func.sum(User.total_checks), 0)).scalar() or 0
        todays_checks = (
            session.query(func.count(CheckLog.id))
            .filter(func.date(CheckLog.created_at) == today)
            .scalar()
            or 0
        )
        force_join_count = (
            session.query(ForceJoinChannel).filter_by(is_enabled=True).count()
        )
        available = session.query(func.coalesce(func.sum(User.available_count), 0)).scalar() or 0
        taken = session.query(func.coalesce(func.sum(User.taken_count), 0)).scalar() or 0

        new_today = (
            session.query(User)
            .filter(func.date(User.joined_at) == today)
            .count()
        )
        new_week = (
            session.query(User)
            .filter(User.joined_at >= week_ago)
            .count()
        )
        month_ago = datetime.utcnow() - timedelta(days=30)
        new_month = (
            session.query(User)
            .filter(User.joined_at >= month_ago)
            .count()
        )

        # daily checks last 14 days
        daily_checks = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            cnt = (
                session.query(func.count(CheckLog.id))
                .filter(func.date(CheckLog.created_at) == d)
                .scalar()
                or 0
            )
            daily_checks.append({"date": d.isoformat(), "count": cnt})

        # user growth last 14 days
        user_growth = []
        for i in range(13, -1, -1):
            d = today - timedelta(days=i)
            cnt = (
                session.query(User)
                .filter(func.date(User.joined_at) == d)
                .count()
            )
            user_growth.append({"date": d.isoformat(), "count": cnt})

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_checks": int(total_checks),
            "todays_checks": todays_checks,
            "premium_users": premium_users,
            "banned_users": banned_users,
            "force_join_channels": force_join_count,
            "available": int(available),
            "taken": int(taken),
            "new_today": new_today,
            "new_week": new_week,
            "new_month": new_month,
            "daily_checks": daily_checks,
            "user_growth": user_growth,
        }
    finally:
        session.close()


def most_active_users(limit=10):
    session = get_db()
    try:
        return (
            session.query(User)
            .order_by(User.total_checks.desc())
            .limit(limit)
            .all()
        )
    finally:
        session.close()
