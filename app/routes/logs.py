"""Admin: System Log — a read-only, filterable view of every audit trail entry."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette import status

from ..db import get_db
from ..deps import get_current_user
from ..models import AuditLog, STAFF_ROLES
from ..web import templates

router = APIRouter()

PAGE_SIZE = 50


def _guard(user):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role not in STAFF_ROLES:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return None


@router.get("/admin/log", response_class=HTMLResponse)
def audit_log(
    request: Request,
    page: int = 1,
    user_email: str = "",
    action: str = "",
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    blocked = _guard(user)
    if blocked:
        return blocked

    filters = []
    if user_email:
        filters.append(AuditLog.user_email == user_email)
    if action:
        filters.append(AuditLog.action == action)

    base = select(AuditLog)
    for f in filters:
        base = base.where(f)

    count_query = select(func.count()).select_from(AuditLog)
    for f in filters:
        count_query = count_query.where(f)
    total = db.scalar(count_query) or 0

    page = max(page, 1)
    total_pages = max((total + PAGE_SIZE - 1) // PAGE_SIZE, 1)
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    rows = (
        db.execute(base.order_by(AuditLog.ts.desc()).offset(offset).limit(PAGE_SIZE))
        .scalars()
        .all()
    )

    # Distinct values for the filter dropdowns.
    users = [
        row[0] for row in
        db.execute(
            select(AuditLog.user_email)
            .where(AuditLog.user_email != "")
            .distinct()
            .order_by(AuditLog.user_email)
        )
    ]
    actions = [
        row[0] for row in
        db.execute(select(AuditLog.action).distinct().order_by(AuditLog.action))
    ]

    return templates.TemplateResponse(
        request,
        "admin_log.html",
        {
            "request": request,
            "user": user,
            "rows": rows,
            "users": users,
            "actions": actions,
            "user_sel": user_email,
            "action_sel": action,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )
