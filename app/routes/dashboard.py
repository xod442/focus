"""Home dashboard: two sections (Tasks, Action Items), filterable by status
and by person so anyone can get laser-focused on just their own items."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status as http_status

from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import ActionItem, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task, User
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=http_status.HTTP_303_SEE_OTHER)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    status_filter: str = "open",
    person: str = "",
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
        },
    )
