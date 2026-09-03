"""Home dashboard: two sections (Tasks, Action Items), filterable by status
and by person so anyone can get laser-focused on just their own items."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status as http_status

from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    ActionItem, AuditLog, MESSAGE_BODY_MAX_LEN, Message, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task,
    User,
)
from ..web import templates

router = APIRouter()

RECENT_COMPLETED_LIMIT = 6


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=http_status.HTTP_303_SEE_OTHER)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status_filter: str = "open",
    person: str = "",
    ok: int = 1,
    msg: str = "",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    all_users = db.query(User).order_by(User.email).all()

    # "person" defaults to nothing selected (everyone); "me" is a shortcut for
    # the signed-in user's own id.
    person_id = None
    if person == "me":
        person_id = user.id
    elif person.isdigit():
        person_id = int(person)

    tasks_q = db.query(Task)
    items_q = db.query(ActionItem)

    if status_filter == "open":
        tasks_q = tasks_q.filter(Task.status == STATUS_IN_PROGRESS)
        items_q = items_q.filter(ActionItem.status == STATUS_IN_PROGRESS)
    elif status_filter == "completed":
        tasks_q = tasks_q.filter(Task.status == STATUS_COMPLETED)
        items_q = items_q.filter(ActionItem.status == STATUS_COMPLETED)
    # status_filter == "all" → no filter

    if person_id is not None:
        tasks_q = tasks_q.filter(Task.owner_id == person_id)
        items_q = items_q.filter(
            (ActionItem.assignee_id == person_id) | (ActionItem.requested_by_id == person_id)
        )

    tasks = tasks_q.order_by(Task.status, Task.updated_at.desc()).all()
    items = items_q.order_by(ActionItem.status, ActionItem.updated_at.desc()).all()

    task_rows = [
        {
            "task": t,
            "can_edit": perm.can_edit_task(user, t),
            "stale": t.status == STATUS_IN_PROGRESS and perm.is_stale(t.updated_at),
        }
        for t in tasks
    ]
    item_rows = [
        {
            "item": i,
            "can_edit": perm.can_edit_action_item(user, i),
            "stale": i.status == STATUS_IN_PROGRESS and perm.is_stale(i.updated_at),
        }
        for i in items
    ]

    open_task_count = db.query(Task).filter(Task.status == STATUS_IN_PROGRESS).count()
    open_item_count = db.query(ActionItem).filter(ActionItem.status == STATUS_IN_PROGRESS).count()

    # Each user's own message queue — only messages addressed to them.
    my_messages = (
        db.query(Message)
        .filter(Message.recipient_id == user.id)
        .order_by(Message.created_at.desc())
        .all()
    )

    # A short "what got done" list — recently completed work across the whole
    # team, for a quick accomplishment read without parsing the metrics trend
    # chart. Cheap: reuses the same completed_at column the trend chart does.
    recent_completed = [
        {"kind": "Task", "label": t.title, "who": t.owner.email, "completed_at": t.completed_at}
        for t in db.query(Task)
        .filter(Task.status == STATUS_COMPLETED, Task.completed_at.isnot(None))
        .order_by(Task.completed_at.desc())
        .limit(RECENT_COMPLETED_LIMIT)
        .all()
    ] + [
        {
            "kind": "Action Item",
            "label": i.description,
            "who": i.assignee.email,
            "completed_at": i.completed_at,
        }
        for i in db.query(ActionItem)
        .filter(ActionItem.status == STATUS_COMPLETED, ActionItem.completed_at.isnot(None))
        .order_by(ActionItem.completed_at.desc())
        .limit(RECENT_COMPLETED_LIMIT)
        .all()
    ]
    recent_completed = sorted(
        recent_completed, key=lambda row: row["completed_at"], reverse=True
    )[:RECENT_COMPLETED_LIMIT]

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "all_users": all_users,
            "task_rows": task_rows,
            "item_rows": item_rows,
            "status_sel": status_filter,
            "person_sel": person,
            "open_task_count": open_task_count,
            "open_item_count": open_item_count,
            "my_messages": my_messages,
            "message_max_len": MESSAGE_BODY_MAX_LEN,
            "recent_completed": recent_completed,
            "ok": bool(ok),
            "msg": msg,
        },
    )


@router.get("/users/{user_key}/executive", response_class=HTMLResponse)
def user_executive(
    request: Request,
    user_key: str,
    days: int = 30,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    if user_key == "me":
        target_user = user
    else:
        if not user_key.isdigit():
            raise HTTPException(status_code=404, detail="User not found")
        target_user = db.get(User, int(user_key))

    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    days = max(7, min(days, 90))
    cutoff = datetime.utcnow() - timedelta(days=days)

    tasks_opened = (
        db.query(Task)
        .filter(Task.owner_id == target_user.id, Task.created_at >= cutoff)
        .count()
    )
    tasks_closed = (
        db.query(Task)
        .filter(
            Task.owner_id == target_user.id,
            Task.status == STATUS_COMPLETED,
            Task.completed_at.isnot(None),
            Task.completed_at >= cutoff,
        )
        .count()
    )
    open_backlog = (
        db.query(Task)
        .filter(Task.owner_id == target_user.id, Task.status == STATUS_IN_PROGRESS)
        .count()
    )
    action_items_total = db.query(ActionItem).filter(ActionItem.assignee_id == target_user.id).count()
    action_items_open = (
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id, ActionItem.status == STATUS_IN_PROGRESS)
        .count()
    )
    internal_messages = (
        db.query(Message)
        .filter(Message.sender_id == target_user.id, Message.created_at >= cutoff)
        .count()
    )
    external_emails = (
        db.query(AuditLog)
        .filter(
            AuditLog.user_id == target_user.id,
            AuditLog.action.ilike("%email%"),
            AuditLog.ts >= cutoff,
        )
        .count()
    )
    overdue_count = (
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id, ActionItem.status == STATUS_IN_PROGRESS)
        .count()
    )
    closure_rate = 0.0
    work_total = max(tasks_opened + tasks_closed, 1)
    if tasks_opened + tasks_closed:
        closure_rate = round((tasks_closed / (tasks_opened + tasks_closed)) * 100, 1)

    recent_activity = []
    for task in (
        db.query(Task)
        .filter(Task.owner_id == target_user.id)
        .order_by(Task.updated_at.desc())
        .limit(6)
        .all()
    ):
        recent_activity.append(
            {
                "ts": task.updated_at,
                "kind": "Task",
                "label": task.title,
                "status": task.status,
            }
        )
    for item in (
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id)
        .order_by(ActionItem.updated_at.desc())
        .limit(6)
        .all()
    ):
        recent_activity.append(
            {
                "ts": item.updated_at,
                "kind": "Action Item",
                "label": item.description[:80],
                "status": item.status,
            }
        )
    for msg in (
        db.query(Message)
        .filter(Message.sender_id == target_user.id)
        .order_by(Message.created_at.desc())
        .limit(6)
        .all()
    ):
        recent_activity.append(
            {
                "ts": msg.created_at,
                "kind": "Internal message",
                "label": msg.body[:80],
                "status": "sent",
            }
        )
    for email in (
        db.query(AuditLog)
        .filter(AuditLog.user_id == target_user.id, AuditLog.action.ilike("%email%"))
        .order_by(AuditLog.ts.desc())
        .limit(6)
        .all()
    ):
        recent_activity.append(
            {
                "ts": email.ts,
                "kind": "External email",
                "label": email.target_label or email.action,
                "status": "sent",
            }
        )

    recent_activity = sorted(recent_activity, key=lambda row: row["ts"], reverse=True)[:10]

    trend_days = []
    day_cursor = datetime.utcnow().date() - timedelta(days=days - 1)
    for i in range(days):
        current_day = day_cursor + timedelta(days=i)
        day_start = datetime.combine(current_day, datetime.min.time())
        day_end = day_start + timedelta(days=1)
        opened = (
            db.query(Task)
            .filter(
                Task.owner_id == target_user.id,
                Task.created_at >= day_start,
                Task.created_at < day_end,
            )
            .count()
        )
        closed = (
            db.query(Task)
            .filter(
                Task.owner_id == target_user.id,
                Task.status == STATUS_COMPLETED,
                Task.completed_at.isnot(None),
                Task.completed_at >= day_start,
                Task.completed_at < day_end,
            )
            .count()
        )
        action_items = (
            db.query(ActionItem)
            .filter(
                ActionItem.assignee_id == target_user.id,
                ActionItem.created_at >= day_start,
                ActionItem.created_at < day_end,
            )
            .count()
        )
        internal_msgs = (
            db.query(Message)
            .filter(
                Message.sender_id == target_user.id,
                Message.created_at >= day_start,
                Message.created_at < day_end,
            )
            .count()
        )
        emails = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == target_user.id,
                AuditLog.action.ilike("%email%"),
                AuditLog.ts >= day_start,
                AuditLog.ts < day_end,
            )
            .count()
        )
        trend_days.append(
            {
                "day": current_day,
                "label": current_day.strftime("%b %d"),
                "opened": opened,
                "closed": closed,
                "action_items": action_items,
                "internal_msgs": internal_msgs,
                "emails": emails,
            }
        )

    chart_max = max(1, max((row["opened"] + row["closed"]) for row in trend_days))
    chart_width = 680
    chart_height = 180
    left_pad = 24
    right_pad = 12
    top_pad = 18
    bottom_pad = 26
    plot_width = chart_width - left_pad - right_pad
    plot_height = chart_height - top_pad - bottom_pad
    for row in trend_days:
        if len(trend_days) == 1:
            row["x"] = left_pad + plot_width / 2
        else:
            row["x"] = left_pad + (trend_days.index(row) / (len(trend_days) - 1)) * plot_width
        row["opened_y"] = chart_height - bottom_pad - (row["opened"] / chart_max) * plot_height
        row["closed_y"] = chart_height - bottom_pad - (row["closed"] / chart_max) * plot_height

    opened_points = " ".join(f"{row['x']},{row['opened_y']}" for row in trend_days)
    closed_points = " ".join(f"{row['x']},{row['closed_y']}" for row in trend_days)

    all_users = db.query(User).order_by(User.email).all()

    return templates.TemplateResponse(
        request,
        "user_executive.html",
        {
            "request": request,
            "user": user,
            "target_user": target_user,
            "all_users": all_users,
            "days": days,
            "tasks_opened": tasks_opened,
            "tasks_closed": tasks_closed,
            "open_backlog": open_backlog,
            "action_items_total": action_items_total,
            "action_items_open": action_items_open,
            "internal_messages": internal_messages,
            "external_emails": external_emails,
            "closure_rate": closure_rate,
            "overdue_count": overdue_count,
            "work_total": work_total,
            "recent_activity": recent_activity,
            "trend_days": trend_days,
            "opened_points": opened_points,
            "closed_points": closed_points,
        },
    )
