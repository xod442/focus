"""Action Items: something one person needs another person (or themselves) to do."""
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit, notifier
from .. import permissions as perm
from ..assignees import assignee_options, resolve_assignee
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    ActionItem, ActionItemNote, MESSAGE_BODY_MAX_LEN, Message, STATUS_COMPLETED,
    STATUS_IN_PROGRESS, User,
    ACTION_PRIORITIES, ACTION_STATUSES, STATUS_NOT_STARTED, STATUS_BLOCKED, STAFF_ROLES,
)
from ..web import templates

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


def _fields(
    title: str, description: str, priority: str, due_date: str,
) -> tuple[str, str, str, date | None]:
    title = title.strip()
    if not title or len(title) > 300:
        raise HTTPException(400, "Enter a title between 1 and 300 characters.")
    if priority not in ACTION_PRIORITIES:
        raise HTTPException(400, "Select a valid priority.")
    try:
        due = date.fromisoformat(due_date) if due_date else None
    except ValueError:
        raise HTTPException(400, "Enter a valid due date.") from None
    return title, description.strip(), priority, due


def _reassign(db: Session, item: ActionItem, assignee: User, user: User) -> None:
    if item.assignee_id == assignee.id:
        return
    previous = item.assignee.email
    item.assignee = assignee
    item.needs_review = True
    item.updated_at = datetime.utcnow()
    db.add(ActionItemNote(
        action_item_id=item.id, author_id=user.id,
        body=f"Owner changed from {previous} to {assignee.email}.",
    ))
    db.add(Message(
        sender_id=user.id, recipient_id=assignee.id,
        body=f"Assigned to you: {item.display_title}"[:MESSAGE_BODY_MAX_LEN],
        related_kind="action_item", related_id=item.id,
        related_label=f"Action Item #{item.id}: {item.display_title}",
    ))


@router.post("/action-items/transfer")
def transfer_items(
    source_id: int = Form(...), assignee_id: str = Form(...),
    db: Session = Depends(get_db), user=Depends(get_current_user),
):
    if user is None:
        return _login()
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "Only managers and admins may transfer workloads.")
    source = db.get(User, source_id)
    if source is None:
        raise HTTPException(400, "Select an existing source owner.")
    assignee = resolve_assignee(db, assignee_id)
    if source.id == assignee.id:
        raise HTTPException(400, "Choose a different new owner.")
    items = db.query(ActionItem).filter(
        ActionItem.assignee_id == source.id, ActionItem.status != STATUS_COMPLETED
    ).all()
    for item in items:
        _reassign(db, item, assignee, user)
    db.commit()
    for item in items:
        audit.log(db, user, "action_item.reassign", target_type="action_item",
                  target_id=item.id, target_label=item.display_title,
                  details=f"from={source.email} to={assignee.email}")
    return RedirectResponse(
        f"/work?msg={quote(f'Transferred {len(items)} open action items to {assignee.email}.')}",
        status_code=303,
    )


@router.get("/action-items/new", response_class=HTMLResponse)
def new_item_form(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return _login()
    assignees = assignee_options(db)
    return templates.TemplateResponse(
        request, "action_item_new.html", {"request": request, "user": user, "assignees": assignees}
    )


@router.post("/action-items")
def create_item(
    request: Request,
    description: str = Form(""),
    assignee_id: str = Form(""),
    title: str = Form(""),
    priority: str = Form("normal"),
    due_date: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()

    title, description, priority, due = _fields(title or description[:300], description, priority, due_date)
    assignee = resolve_assignee(db, assignee_id if assignee_id.strip() else str(user.id))
    item = ActionItem(
        requested_by_id=user.id,
        assignee_id=assignee.id,
        title=title, description=description, priority=priority, due_date=due,
        status=STATUS_NOT_STARTED,
    )
    db.add(item)
    db.flush()
    if assignee.id != user.id:
        db.add(Message(
            sender_id=user.id, recipient_id=assignee.id,
            body=f"Assigned to you: {item.display_title}"[:MESSAGE_BODY_MAX_LEN], related_kind="action_item",
            related_id=item.id, related_label=f"Action Item #{item.id}: {item.display_title}",
        ))
        item.needs_review = True
    db.commit()
    audit.log(db, user, "action_item.create", target_type="action_item", target_id=item.id,
              target_label=item.display_title[:80])
    return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/action-items/{item_id}/edit", response_class=HTMLResponse)
def edit_item_form(item_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)

    # Reading an item clears attention without changing its workflow status.
    if item.needs_review and user.id == item.assignee_id:
        item.needs_review = False
        db.add(item)
        db.commit()

    assignees = assignee_options(db, item.assignee)
    return templates.TemplateResponse(
        request,
        "action_item_edit.html",
        {
            "request": request,
            "user": user,
            "item": item,
            "assignees": assignees,
            "can_edit": perm.can_edit_action_item(user, item),
        },
    )


@router.post("/action-items/{item_id}")
def update_item(
    item_id: int,
    request: Request,
    description: str | None = Form(None),
    assignee_id: str = Form(""),
    title: str | None = Form(None),
    priority: str | None = Form(None),
    due_date: str | None = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)
    if not perm.can_edit_action_item(user, item):
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)

    title, description, priority, due = _fields(
        title if title is not None else item.display_title,
        description if description is not None else item.description,
        priority if priority is not None else item.priority,
        due_date if due_date is not None else (item.due_date.isoformat() if item.due_date else ""),
    )
    previous_owner = item.assignee.email
    item.title, item.description, item.priority, item.due_date = title, description, priority, due
    if assignee_id.strip():
        assignee = resolve_assignee(db, assignee_id, current_id=item.assignee_id)
        _reassign(db, item, assignee, user)
    item.needs_review = True
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    audit.log(db, user, "action_item.update", target_type="action_item", target_id=item.id,
              target_label=item.display_title[:80],
              details=f"from={previous_owner} to={item.assignee.email}")
    return RedirectResponse(f"/action-items/{item.id}/edit", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/action-items/{item_id}/status")
def toggle_item_status(item_id: int, request: Request,
                       status_value: str = Form(""), blocked_reason: str = Form(""),
                       db: Session = Depends(get_db),
                       user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None or not perm.can_edit_action_item(user, item):
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)

    new_status = status_value or (
        STATUS_IN_PROGRESS if item.status == STATUS_COMPLETED else STATUS_COMPLETED
    )
    if new_status not in ACTION_STATUSES:
        raise HTTPException(400, "Select a valid status.")
    if new_status == STATUS_BLOCKED and not blocked_reason.strip():
        raise HTTPException(400, "Add a short reason so the team can help unblock this work.")
    if item.status != new_status or (new_status == STATUS_BLOCKED and item.blocked_reason != blocked_reason.strip()):
        db.add(ActionItemNote(
            action_item_id=item.id, author_id=user.id,
            body=f"Status: {item.status.replace('_', ' ')} → {new_status.replace('_', ' ')}"
                 + (f". Blocked: {blocked_reason.strip()}" if new_status == STATUS_BLOCKED else ""),
        ))
    previous_status = item.status
    item.status = new_status
    item.blocked_reason = blocked_reason.strip() if new_status == STATUS_BLOCKED else ""
    if new_status == STATUS_COMPLETED:
        if previous_status != STATUS_COMPLETED:
            item.completed_at = datetime.utcnow()
    else:
        item.completed_at = None
    item.needs_review = new_status != STATUS_COMPLETED and user.id != item.assignee_id
    item.updated_at = datetime.utcnow()
    db.add(item)
    db.commit()
    audit.log(db, user, "action_item.status", target_type="action_item", target_id=item.id,
              target_label=item.display_title[:80], details=f"status={item.status}")

    referer = request.headers.get("referer", "/work")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/action-items/{item_id}/notes")
def add_item_note(item_id: int, body: str = Form(...), db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    if user is None:
        return _login()
    item = db.get(ActionItem, item_id)
    if item is None:
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)
    body = body.strip()
    if body:
        db.add(ActionItemNote(action_item_id=item.id, author_id=user.id, body=body))
        item.needs_review = True
        item.updated_at = datetime.utcnow()
        db.add(item)
        db.commit()
        audit.log(db, user, "action_item.note", target_type="action_item", target_id=item.id,
                  target_label=item.display_title[:80])
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
    referer = request.headers.get("referer", "/work")
    if item is None:
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)

    to = to.strip().lower()
    # Only allow sending to a known, active user's address — never an arbitrary input.
    recipient = db.query(User).filter(User.email == to, User.is_active.is_(True)).first()
    if not to or recipient is None:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Pick a valid recipient.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    short_desc = item.display_title if len(item.display_title) <= 60 else item.display_title[:57] + "..."
    subject = f"FOCUS Action Item #{item.id}: {short_desc}"
    base = str(request.base_url).rstrip("/")
    link = f"{base}/action-items/{item.id}/edit"
    lines = [
        f"{user.email} sent you a note about this action item in FOCUS:",
        "",
        f"  Action Item: #{item.id} — {item.display_title}",
        f"  Requested by: {item.requested_by.email}",
        f"  Assigned to:  {item.assignee.email}",
        f"  Status:       {item.status.replace('_', ' ')}",
        f"  Priority:     {item.priority}",
        f"  Due date:     {item.due_date or 'None'}",
        f"  Description:  {item.description}",
        f"  Blocked:      {item.blocked_reason or 'No'}",
        "",
        note.strip() or "(no note added)",
        "",
        f"Open in FOCUS: {link}",
    ]
    ok, message = notifier.send(db, recipient.email, subject, "\n".join(lines))
    audit.log(db, user, "action_item.email", target_type="action_item", target_id=item.id,
              target_label=item.display_title[:80], details=f"to={recipient.email} sent={ok}")

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
    referer = request.headers.get("referer", "/work")
    if item is None:
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)

    body = body.strip()[:MESSAGE_BODY_MAX_LEN]
    if not body:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Message cannot be empty.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    short_desc = item.display_title if len(item.display_title) <= 60 else item.display_title[:57] + "..."
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
              target_label=item.display_title[:80], details=f"to={item.assignee.email}")

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
        return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)
    audit.log(db, user, "action_item.delete", target_type="action_item", target_id=item.id,
              target_label=item.display_title[:80])
    db.delete(item)
    db.commit()
    return RedirectResponse("/work", status_code=status.HTTP_303_SEE_OTHER)
