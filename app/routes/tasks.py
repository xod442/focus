"""Tasks: work a person plans to accomplish over the next week or two."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import STAFF_ROLES, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task, TaskNote, User
from datetime import datetime
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tasks/new", response_class=HTMLResponse)
def new_task_form(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    all_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    return templates.TemplateResponse(
        request, "task_new.html", {"request": request, "user": user, "all_users": all_users}
    )


@router.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    owner_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    # Regular members may only create a task for themselves; managers/admins
    # may plan work for anyone on the team.
    if user.role in STAFF_ROLES and owner_id.strip():
        target_owner = int(owner_id)
    else:
        target_owner = user.id

    task = Task(owner_id=target_owner, title=title.strip(), description=description.strip())
    db.add(task)
    db.commit()
    db.refresh(task)
    audit.log(db, user, "task.create", target_type="task", target_id=task.id,
              target_label=task.title)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form(task_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    all_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    return templates.TemplateResponse(
        request,
        "task_edit.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "all_users": all_users,
            "can_edit": perm.can_edit_task(user, task),
            "can_reassign": user.role in STAFF_ROLES,
        },
    )


@router.post("/tasks/{task_id}")
def update_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    owner_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    if not perm.can_edit_task(user, task):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    task.title = title.strip()
    task.description = description.strip()
    if user.role in STAFF_ROLES and owner_id.strip():
        task.owner_id = int(owner_id)
    task.updated_at = datetime.utcnow()
    db.add(task)
    db.commit()
    audit.log(db, user, "task.update", target_type="task", target_id=task.id,
              target_label=task.title)
    return RedirectResponse(f"/tasks/{task.id}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/status")
def toggle_task_status(task_id: int, request: Request, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None or not perm.can_edit_task(user, task):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    if task.status == STATUS_IN_PROGRESS:
        task.status = STATUS_COMPLETED
        task.completed_at = datetime.utcnow()
    else:
        task.status = STATUS_IN_PROGRESS
        task.completed_at = None
    task.updated_at = datetime.utcnow()
    db.add(task)
    db.commit()
    audit.log(db, user, "task.status", target_type="task", target_id=task.id,
              target_label=task.title, details=f"status={task.status}")

    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/notes")
def add_task_note(task_id: int, body: str = Form(...), db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    body = body.strip()
    if body:
        db.add(TaskNote(task_id=task.id, author_id=user.id, body=body))
        task.updated_at = datetime.utcnow()
        db.add(task)
        db.commit()
        audit.log(db, user, "task.note", target_type="task", target_id=task.id,
                  target_label=task.title)
    return RedirectResponse(f"/tasks/{task.id}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/tasks/{task_id}/delete")
def delete_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    if task is None or not perm.can_edit_task(user, task):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    audit.log(db, user, "task.delete", target_type="task", target_id=task.id,
              target_label=task.title)
    db.delete(task)
    db.commit()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
