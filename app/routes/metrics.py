"""Executive metrics: a snapshot of team throughput, workload, and obstacles."""
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette import status

from .. import config
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import ActionItem, AuditLog, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task, User
from ..web import templates

router = APIRouter()

TREND_WEEKS = 8
OLDEST_LIMIT = 10
USAGE_BAR_MAX_PX = 200
USAGE_BAR_MIN_PX = 10
USAGE_DAY_CHOICES = (7, 30, 90)
USAGE_DAYS_DEFAULT = 30


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def _week_start(dt: datetime) -> datetime:
    """Monday 00:00 of the week containing dt."""
    d = dt.date() - timedelta(days=dt.weekday())
    return datetime(d.year, d.month, d.day)


def _usage_rows(db: Session, days: int, current_user_id: int) -> list[dict]:
    """Audit-log activity per active user over the last `days` — a proxy for
    who is actually using the system, ranked so the chart reads like a
    leaderboard. Bar color intensity (HPE green) scales with activity so the
    most active person visually pops against the rest."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    counts = dict(
        db.query(AuditLog.user_email, func.count(AuditLog.id))
        .filter(AuditLog.ts >= cutoff, AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .all()
    )
    active_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    rows = [
        {
            "user_id": u.id,
            "email": u.email,
            "count": counts.get(u.email, 0),
            "is_you": u.id == current_user_id,
        }
        for u in active_users
    ]
    rows.sort(key=lambda r: r["count"], reverse=True)

    usage_max = max([1] + [r["count"] for r in rows])
    for rank, row in enumerate(rows):
        intensity = row["count"] / usage_max if usage_max else 0
        row["height_px"] = max(
            USAGE_BAR_MIN_PX, round(intensity * USAGE_BAR_MAX_PX)
        ) if row["count"] else USAGE_BAR_MIN_PX
        # Lightness runs from ~78% (barely active) down to ~34% (most active) on
        # the HPE green hue, so the tallest/darkest bar is the busiest user.
        lightness = round(78 - intensity * 44)
        row["color"] = f"hsl(162, 65%, {lightness}%)"
        row["color_light"] = f"hsl(162, 65%, {min(lightness + 16, 90)}%)"
        row["color_dark"] = f"hsl(162, 65%, {max(lightness - 16, 12)}%)"
        row["rank"] = rank + 1
    return rows


@router.get("/metrics", response_class=HTMLResponse)
def metrics(
    request: Request,
    usage_days: int = USAGE_DAYS_DEFAULT,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    if usage_days not in USAGE_DAY_CHOICES:
        usage_days = USAGE_DAYS_DEFAULT

    all_tasks = db.query(Task).all()
    all_items = db.query(ActionItem).all()
    users = {u.id: u for u in db.query(User).all()}

    open_tasks = [t for t in all_tasks if t.status == STATUS_IN_PROGRESS]
    done_tasks = [t for t in all_tasks if t.status == STATUS_COMPLETED]
    open_items = [i for i in all_items if i.status == STATUS_IN_PROGRESS]
    done_items = [i for i in all_items if i.status == STATUS_COMPLETED]

    # Per-person open workload: tasks by owner, action items by assignee.
    workload = defaultdict(lambda: {"tasks": 0, "action_items": 0})
    for t in open_tasks:
        workload[t.owner_id]["tasks"] += 1
    for i in open_items:
        workload[i.assignee_id]["action_items"] += 1
    workload_rows = sorted(
        (
            {
                "email": users[uid].email if uid in users else "(unknown)",
                "tasks": v["tasks"],
                "action_items": v["action_items"],
                "total": v["tasks"] + v["action_items"],
            }
            for uid, v in workload.items()
        ),
        key=lambda r: r["total"],
        reverse=True,
    )

    # Stale = open and untouched for longer than the configured window.
    stale_tasks = [t for t in open_tasks if perm.is_stale(t.updated_at)]
    stale_items = [i for i in open_items if perm.is_stale(i.updated_at)]

    # Oldest open items across both lists — the likely obstacles to discuss.
    oldest = sorted(
        [{"kind": "Task", "label": t.title, "owner": users[t.owner_id].email if t.owner_id in users else "?",
          "created_at": t.created_at, "age_weeks": perm.age_weeks(t.created_at)} for t in open_tasks]
        + [{"kind": "Action Item", "label": i.description,
            "owner": users[i.assignee_id].email if i.assignee_id in users else "?",
            "created_at": i.created_at, "age_weeks": perm.age_weeks(i.created_at)} for i in open_items],
        key=lambda r: r["created_at"],
    )[:OLDEST_LIMIT]

    # Completion trend: how many tasks + action items were completed each of
    # the last N weeks (Monday-anchored buckets).
    now = datetime.utcnow()
    week_starts = [_week_start(now) - timedelta(weeks=n) for n in range(TREND_WEEKS - 1, -1, -1)]
    trend = [{"week": ws.strftime("%b %d"), "tasks": 0, "action_items": 0} for ws in week_starts]
    bucket_index = {ws: idx for idx, ws in enumerate(week_starts)}

    for t in done_tasks:
        if t.completed_at is None:
            continue
        ws = _week_start(t.completed_at)
        if ws in bucket_index:
            trend[bucket_index[ws]]["tasks"] += 1
    for i in done_items:
        if i.completed_at is None:
            continue
        ws = _week_start(i.completed_at)
        if ws in bucket_index:
            trend[bucket_index[ws]]["action_items"] += 1
    trend_max = max([1] + [r["tasks"] + r["action_items"] for r in trend])

    usage_rows = _usage_rows(db, usage_days, user.id)

    return templates.TemplateResponse(
        request,
        "metrics.html",
        {
            "request": request,
            "user": user,
            "open_task_count": len(open_tasks),
            "done_task_count": len(done_tasks),
            "open_item_count": len(open_items),
            "done_item_count": len(done_items),
            "stale_task_count": len(stale_tasks),
            "stale_item_count": len(stale_items),
            "stale_weeks": config.STALE_WEEKS,
            "workload_rows": workload_rows,
            "oldest": oldest,
            "trend": trend,
            "trend_max": trend_max,
            "total_open": len(open_tasks) + len(open_items),
            "total_done": len(done_tasks) + len(done_items),
            "usage_rows": usage_rows,
            "usage_days": usage_days,
            "usage_day_choices": USAGE_DAY_CHOICES,
        },
    )
