"""Action-item workload and progress, filterable by owner and workflow status."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status as http_status

from .. import permissions as perm
from ..db import get_db
from ..assignees import assignee_options
from ..deps import get_current_user
from ..models import (
    ActionItem, AuditLog, MESSAGE_BODY_MAX_LEN, Message, STATUS_COMPLETED,
    User, ACTION_STATUSES,
)
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=http_status.HTTP_303_SEE_OTHER)


@router.get("/work", response_class=HTMLResponse)
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

    items_q = db.query(ActionItem)

    if status_filter == "open":
        items_q = items_q.filter(ActionItem.status != STATUS_COMPLETED)
    elif status_filter in ACTION_STATUSES:
        items_q = items_q.filter(ActionItem.status == status_filter)
    # status_filter == "all" → no filter

    if person_id is not None:
        items_q = items_q.filter(ActionItem.assignee_id == person_id)

    items = items_q.order_by(ActionItem.updated_at.desc()).all()
    items.sort(key=lambda i: (
        i.status == STATUS_COMPLETED, not (i.status == "blocked"), not i.overdue,
        {"high": 0, "normal": 1, "low": 2}[i.priority],
    ))
    item_rows = [
        {
            "item": i,
            "can_edit": perm.can_edit_action_item(user, i),
            "stale": i.status != STATUS_COMPLETED and perm.is_stale(i.updated_at),
        }
        for i in items
    ]

    open_items = db.query(ActionItem).filter(ActionItem.status != STATUS_COMPLETED).all()
    workload_rows = []
    for owner in all_users:
        owned = [i for i in open_items if i.assignee_id == owner.id]
        if not owner.is_active and not owned:
            continue
        workload_rows.append({
            "owner": owner, "total": len(owned),
            "not_started": sum(i.status == "not_started" for i in owned),
            "in_progress": sum(i.status == "in_progress" for i in owned),
            "blocked": sum(i.status == "blocked" for i in owned),
            "high": sum(i.priority == "high" for i in owned),
            "overdue": sum(i.overdue for i in owned),
        })

    # Each user's own message queue — only messages addressed to them.
    my_messages = (
        db.query(Message)
        .filter(Message.recipient_id == user.id)
        .order_by(Message.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "all_users": all_users,
            "item_rows": item_rows,
            "status_sel": status_filter,
            "person_sel": person,
            "open_item_count": len(open_items),
            "workload_rows": workload_rows,
            "assignees": assignee_options(db),
            "my_messages": my_messages,
            "message_max_len": MESSAGE_BODY_MAX_LEN,
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
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id, ActionItem.created_at >= cutoff)
        .count()
    )
    tasks_closed = (
        db.query(ActionItem)
        .filter(
            ActionItem.assignee_id == target_user.id,
            ActionItem.status == STATUS_COMPLETED,
            ActionItem.completed_at.isnot(None),
            ActionItem.completed_at >= cutoff,
        )
        .count()
    )
    open_backlog = (
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id, ActionItem.status != STATUS_COMPLETED)
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
        .filter(ActionItem.assignee_id == target_user.id, ActionItem.status != STATUS_COMPLETED,
                ActionItem.due_date < date.today())
        .count()
    )
    recent_activity = []
    for task in (
        db.query(ActionItem)
        .filter(ActionItem.assignee_id == target_user.id)
        .order_by(ActionItem.updated_at.desc())
        .limit(6)
        .all()
    ):
        recent_activity.append(
            {
                "ts": task.updated_at,
                "kind": "Action Item",
                "label": task.display_title,
                "status": task.status,
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
            db.query(ActionItem)
            .filter(
                ActionItem.assignee_id == target_user.id,
                ActionItem.created_at >= day_start,
                ActionItem.created_at < day_end,
            )
            .count()
        )
        closed = (
            db.query(ActionItem)
            .filter(
                ActionItem.assignee_id == target_user.id,
                ActionItem.status == STATUS_COMPLETED,
                ActionItem.completed_at.isnot(None),
                ActionItem.completed_at >= day_start,
                ActionItem.completed_at < day_end,
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
            "internal_messages": internal_messages,
            "external_emails": external_emails,
            "overdue_count": overdue_count,
            "recent_activity": recent_activity,
            "trend_days": trend_days,
            "opened_points": opened_points,
            "closed_points": closed_points,
        },
    )
