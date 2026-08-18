"""Tasks: work a person plans to accomplish over the next week or two."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit, notifier
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    MESSAGE_BODY_MAX_LEN, Message, STATUS_COMPLETED, STATUS_IN_PROGRESS, Task, TaskNote, User,
)
from datetime import datetime
from urllib.parse import quote
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/tasks/new", response_class=HTMLResponse)
def new_task_form(request: Request, user=Depends(get_current_user)):
    if user is None:
        return _login()
    return templates.TemplateResponse(request, "task_new.html", {"request": request, "user": user})


@router.post("/tasks")
def create_task(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    # Tasks are a personal to-do list — always owned by whoever creates them.
    # Use an Action Item to hand work to someone else.
    task = Task(owner_id=user.id, title=title.strip(), description=description.strip())
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
    return templates.TemplateResponse(
        request,
        "task_edit.html",
        {
            "request": request,
            "user": user,
            "task": task,
            "can_edit": perm.can_edit_task(user, task),
        },
    )


@router.post("/tasks/{task_id}")
def update_task(
    task_id: int,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
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

    # Ownership is never reassignable — tasks stay with whoever created them.
    task.title = title.strip()
    task.description = description.strip()
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


@router.post("/tasks/{task_id}/email")
def email_task(
    task_id: int,
    request: Request,
    to: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    referer = request.headers.get("referer", "/")
    if task is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    to = to.strip().lower()
    # Only allow sending to a known, active user's address — never an arbitrary input.
    recipient = db.query(User).filter(User.email == to, User.is_active.is_(True)).first()
    if not to or recipient is None:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Pick a valid recipient.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    subject = f"FOCUS Task #{task.id}: {task.title}"
    base = str(request.base_url).rstrip("/")
    link = f"{base}/tasks/{task.id}/edit"
    lines = [
        f"{user.email} sent you a note about this task in FOCUS:",
        "",
        f"  Task:    #{task.id} — {task.title}",
        f"  Owner:   {task.owner.email}",
        f"  Status:  {'completed' if task.status == STATUS_COMPLETED else 'in progress'}",
        "",
        note.strip() or "(no note added)",
        "",
        f"Open in FOCUS: {link}",
    ]
    ok, message = notifier.send(db, recipient.email, subject, "\n".join(lines))
    audit.log(db, user, "task.email", target_type="task", target_id=task.id,
              target_label=task.title, details=f"to={recipient.email} sent={ok}")

    msg = f"Email sent to {recipient.email}." if ok else message
    return RedirectResponse(
        f"{referer}{'&' if '?' in referer else '?'}ok={1 if ok else 0}&msg={quote(msg)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/tasks/{task_id}/message")
def message_task(
    task_id: int,
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    task = db.get(Task, task_id)
    referer = request.headers.get("referer", "/")
    if task is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    body = body.strip()[:MESSAGE_BODY_MAX_LEN]
    if not body:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Message cannot be empty.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    msg_row = Message(
        sender_id=user.id,
        recipient_id=task.owner_id,
        body=body,
        related_kind="task",
        related_id=task.id,
        related_label=f"Task #{task.id}: {task.title}",
    )
    db.add(msg_row)
    db.commit()
    audit.log(db, user, "message.send", target_type="task", target_id=task.id,
              target_label=task.title, details=f"to={task.owner.email}")

    return RedirectResponse(
        f"{referer}{'&' if '?' in referer else '?'}ok=1&msg={quote('Message sent to ' + task.owner.email + '.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
