"""Shared business rules: who can edit what, and staleness for metrics."""
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import config
from .models import ActionItem, AuditLog, STAFF_ROLES, Task


def can_edit_task(user, task: Task) -> bool:
    """Tasks are a personal to-do list — only the owner may edit, note, or
    delete it, regardless of role. Everyone else can still see it on the
    dashboard for visibility, but can't touch it."""
    if user is None:
        return False
    return user.id == task.owner_id


def can_edit_action_item(user, item: ActionItem) -> bool:
    """The requester, the assignee, or a manager/admin may edit or reassign it."""
    if user is None:
        return False
    if user.role in STAFF_ROLES:
        return True
    return user.id in (item.requested_by_id, item.assignee_id)


def is_stale(updated_at: datetime, weeks: int = config.STALE_WEEKS) -> bool:
    """True if an open item hasn't been touched (edited or noted) in `weeks`."""
    return datetime.utcnow() - updated_at > timedelta(weeks=weeks)


def age_weeks(created_at: datetime) -> float:
    return (datetime.utcnow() - created_at).days / 7.0


def most_active_user(db: Session) -> dict | None:
    """All-time #1 on the audit-log activity leaderboard — shown as a small
    "hall of fame" badge on the login screen to nudge adoption. Ties break
    alphabetically by email for deterministic results. Returns None if there's
    no audit activity yet (e.g. a brand-new deployment)."""
    row = (
        db.query(AuditLog.user_email, func.count(AuditLog.id).label("cnt"))
        .filter(AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .order_by(func.count(AuditLog.id).desc(), AuditLog.user_email.asc())
        .first()
    )
    if not row or not row.cnt:
        return None
    return {"email": row.user_email, "count": row.cnt}
