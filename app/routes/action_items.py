"""Action Items: something one person needs another person (or themselves) to do."""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit
from .. import permissions as perm
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    ActionItem, ActionItemNote, STATUS_COMPLETED, STATUS_IN_PROGRESS, User,
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
