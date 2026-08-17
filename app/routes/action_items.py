"""Action Items: something one person needs another person (or themselves) to do."""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit, notifier
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    ActionItem, ActionItemNote, MESSAGE_BODY_MAX_LEN, Message, STATUS_COMPLETED,
    STATUS_IN_PROGRESS, User,
)
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/action-items/new", response_class=HTMLResponse)
def new_item_form(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    all_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    return templates.TemplateResponse(
        request, "action_item_new.html", {"request": request, "user": user, "all_users": all_users}
    )


@router.post("/action-items")
def create_item(
    request: Request,
    description: str = Form(...),
    assignee_id: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    assignee = int(assignee_id) if assignee_id.strip() else user.id
    item = ActionItem(
        requested_by_id=user.id,
        assignee_id=assignee,
        description=description.strip(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    audit.log(db, user, "action_item.create", target_type="action_item", target_id=item.id,
              target_label=item.description[:80])
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/action-items/{item_id}/edit", response_class=HTMLResponse)
def edit_item_form(item_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    all_users = db.query(User).filter(User.is_active.is_(True)).order_by(User.email).all()
    return templates.TemplateResponse(
        request,
        "action_item_edit.html",
        {
            "request": request,
            "user": user,
            "item": item,
            "all_users": all_users,
            "can_edit": perm.can_edit_action_item(user, item),
        },
    )


@router.post("/action-items/{item_id}")
def update_item(
    item_id: int,
    request: Request,
    description: str = Form(...),
    assignee_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    if not perm.can_edit_action_item(user, item):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    item.description = description.strip()
    if assignee_id.strip():
        item.assignee_id = int(assignee_id)
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    audit.log(db, user, "action_item.update", target_type="action_item", target_id=item.id,
              target_label=item.description[:80])
    return RedirectResponse(f"/action-items/{item.id}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/action-items/{item_id}/status")
def toggle_item_status(item_id: int, request: Request, db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None or not perm.can_edit_action_item(user, item):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    if item.status == STATUS_IN_PROGRESS:
        item.status = STATUS_COMPLETED
        item.completed_at = datetime.utcnow()
    else:
        item.status = STATUS_IN_PROGRESS
        item.completed_at = None
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    audit.log(db, user, "action_item.status", target_type="action_item", target_id=item.id,
              target_label=item.description[:80], details=f"status={item.status}")

    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/action-items/{item_id}/notes")
def add_item_note(item_id: int, body: str = Form(...), db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    body = body.strip()
    if body:
        db.add(ActionItemNote(action_item_id=item.id, author_id=user.id, body=body))
        item.updated_at = datetime.utcnow()
        db.add(item)
        db.commit()
        audit.log(db, user, "action_item.note", target_type="action_item", target_id=item.id,
                  target_label=item.description[:80])
    return RedirectResponse(f"/action-items/{item.id}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/action-items/{item_id}/email")
def email_item(
    item_id: int,
    request: Request,
    to: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    referer = request.headers.get("referer", "/")
    if item is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    to = to.strip().lower()
    # Only allow sending to a known, active user's address — never an arbitrary input.
    recipient = db.query(User).filter(User.email == to, User.is_active.is_(True)).first()
    if not to or recipient is None:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Pick a valid recipient.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    short_desc = item.description if len(item.description) <= 60 else item.description[:57] + "..."
    subject = f"FOCUS Action Item #{item.id}: {short_desc}"
    base = str(request.base_url).rstrip("/")
    link = f"{base}/action-items/{item.id}/edit"
    lines = [
        f"{user.email} sent you a note about this action item in FOCUS:",
        "",
        f"  Action Item: #{item.id} — {item.description}",
        f"  Requested by: {item.requested_by.email}",
        f"  Assigned to:  {item.assignee.email}",
        f"  Status:       {'completed' if item.status == STATUS_COMPLETED else 'in progress'}",
        "",
        note.strip() or "(no note added)",
        "",
        f"Open in FOCUS: {link}",
    ]
    ok, message = notifier.send(db, recipient.email, subject, "\n".join(lines))
    audit.log(db, user, "action_item.email", target_type="action_item", target_id=item.id,
              target_label=item.description[:80], details=f"to={recipient.email} sent={ok}")

    msg = f"Email sent to {recipient.email}." if ok else message
    return RedirectResponse(
        f"{referer}{'&' if '?' in referer else '?'}ok={1 if ok else 0}&msg={quote(msg)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/action-items/{item_id}/message")
def message_item(
    item_id: int,
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    referer = request.headers.get("referer", "/")
    if item is None:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    body = body.strip()[:MESSAGE_BODY_MAX_LEN]
    if not body:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Message cannot be empty.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    short_desc = item.description if len(item.description) <= 60 else item.description[:57] + "..."
    msg_row = Message(
        sender_id=user.id,
        recipient_id=item.assignee_id,
        body=body,
        related_kind="action_item",
        related_id=item.id,
        related_label=f"Action Item #{item.id}: {short_desc}",
    )
    db.add(msg_row)
    db.commit()
    audit.log(db, user, "message.send", target_type="action_item", target_id=item.id,
              target_label=item.description[:80], details=f"to={item.assignee.email}")

    return RedirectResponse(
        f"{referer}{'&' if '?' in referer else '?'}ok=1&msg={quote('Message sent to ' + item.assignee.email + '.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/action-items/{item_id}/delete")
def delete_item(item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None or not perm.can_edit_action_item(user, item):
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    audit.log(db, user, "action_item.delete", target_type="action_item", target_id=item.id,
              target_label=item.description[:80])
    db.delete(item)
    db.commit()
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
