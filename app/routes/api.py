"""Read-only JSON API (/api/v1/...) for external integrations — namely VISTA,
the executive dashboard that aggregates HOLO and FOCUS.

Guarded by a static key in the `X-API-Key` header, entirely independent of the
session-cookie auth used everywhere else in the app. An empty `FOCUS_API_KEY`
disables the API outright (every route 404s), mirroring the "empty secret =
feature disabled" convention used by the HOLO SSO hand-off.
"""
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import config
from .. import permissions as perm
from ..db import get_db
from ..models import ActionItem, AuditLog, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task, User

router = APIRouter(prefix="/api/v1", tags=["api"])

TREND_WEEKS = 8
OLDEST_LIMIT = 10
ACTIVITY_DAY_CHOICES = (7, 30, 90)
ACTIVITY_DAYS_DEFAULT = 30


def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """Every route in this router depends on this — treat a disabled API the
    same as a route that doesn't exist, rather than leaking that it's just
    locked (matches how the rest of the app hides staff-only routes)."""
    if not config.API_KEY:
        raise HTTPException(status_code=404, detail="Not found")
    if not x_api_key or not secrets.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _week_start(dt: datetime) -> datetime:
    d = dt.date() - timedelta(days=dt.weekday())
    return datetime(d.year, d.month, d.day)


@router.get("/summary", dependencies=[Depends(require_api_key)])
def summary(db: Session = Depends(get_db)):
    """The same figures shown on FOCUS's own /metrics page, in JSON. Meant for
    a periodic pull, not per-request computation."""
    all_tasks = db.query(Task).all()
    all_items = db.query(ActionItem).all()
    users = {u.id: u for u in db.query(User).all()}

    open_tasks = [t for t in all_tasks if t.status == STATUS_IN_PROGRESS]
    done_tasks = [t for t in all_tasks if t.status == STATUS_COMPLETED]
    open_items = [i for i in all_items if i.status == STATUS_IN_PROGRESS]
    done_items = [i for i in all_items if i.status == STATUS_COMPLETED]

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

    stale_tasks = [t for t in open_tasks if perm.is_stale(t.updated_at)]
    stale_items = [i for i in open_items if perm.is_stale(i.updated_at)]

    oldest = sorted(
        [{"kind": "task", "label": t.title,
          "owner": users[t.owner_id].email if t.owner_id in users else "?",
          "created_at": t.created_at.isoformat() + "Z",
          "age_weeks": round(perm.age_weeks(t.created_at), 1)} for t in open_tasks]
        + [{"kind": "action_item", "label": i.description,
            "owner": users[i.assignee_id].email if i.assignee_id in users else "?",
            "created_at": i.created_at.isoformat() + "Z",
            "age_weeks": round(perm.age_weeks(i.created_at), 1)} for i in open_items],
        key=lambda r: r["created_at"],
    )[:OLDEST_LIMIT]

    now = datetime.utcnow()
    week_starts = [_week_start(now) - timedelta(weeks=n) for n in range(TREND_WEEKS - 1, -1, -1)]
    trend = [{"week": ws.strftime("%Y-%m-%d"), "tasks": 0, "action_items": 0} for ws in week_starts]
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

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "open_tasks": len(open_tasks),
        "done_tasks": len(done_tasks),
        "open_action_items": len(open_items),
        "done_action_items": len(done_items),
        "stale_tasks": len(stale_tasks),
        "stale_action_items": len(stale_items),
        "stale_weeks": config.STALE_WEEKS,
        "workload": workload_rows,
        "oldest_open": oldest,
        "completion_trend": trend,
        "total_open": len(open_tasks) + len(open_items),
        "total_done": len(done_tasks) + len(done_items),
        "total_users": len(users),
    }


@router.get("/users", dependencies=[Depends(require_api_key)])
def users_list(db: Session = Depends(get_db)):
    """User roster — no password hashes, ever."""
    users = db.query(User).order_by(User.email).all()
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "must_change_password": u.must_change_password,
                "created_at": u.created_at.isoformat() + "Z",
            }
            for u in users
        ],
    }


@router.get("/activity", dependencies=[Depends(require_api_key)])
def activity(days: int = Query(ACTIVITY_DAYS_DEFAULT), db: Session = Depends(get_db)):
    """Per-user audit-log activity over the trailing `days` — the same data
    behind FOCUS's own /metrics usage chart, plus each user's most recent
    login, in JSON."""
    if days not in ACTIVITY_DAY_CHOICES:
        days = ACTIVITY_DAYS_DEFAULT
    cutoff = datetime.utcnow() - timedelta(days=days)

    counts = dict(
        db.query(AuditLog.user_email, func.count(AuditLog.id))
        .filter(AuditLog.ts >= cutoff, AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .all()
    )
    last_logins = dict(
        db.query(AuditLog.user_email, func.max(AuditLog.ts))
        .filter(AuditLog.action == "auth.login", AuditLog.user_email != "")
        .group_by(AuditLog.user_email)
        .all()
    )

    users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    rows = [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "activity_count": counts.get(u.email, 0),
            "last_login": last_logins[u.email].isoformat() + "Z" if u.email in last_logins else None,
        }
        for u in users
    ]
    rows.sort(key=lambda r: r["activity_count"], reverse=True)
    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "days": days,
        "users": rows,
    }
