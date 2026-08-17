"""Shared business rules: who can edit what, and staleness for metrics."""
from datetime import datetime, timedelta

from . import config
from .models import ActionItem, STAFF_ROLES, Task


def can_edit_task(user, task: Task) -> bool:
    """Only the task's owner, or a manager/admin, may edit or reassign it."""
    if user is None:
        return False
    if user.role in STAFF_ROLES:
        return True
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
