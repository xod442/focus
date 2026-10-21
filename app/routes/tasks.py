"""Compatibility for retired TODO bookmarks and stale forms."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ActionItem

router = APIRouter(include_in_schema=False)


@router.get("/tasks/new")
def legacy_new_task(user=Depends(get_current_user)):
    return RedirectResponse("/action-items/new" if user else "/login", status_code=303)


@router.get("/tasks/{task_id}/edit")
def legacy_task(task_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    item = db.query(ActionItem).filter(ActionItem.legacy_task_id == task_id).first()
    if item is None:
        raise HTTPException(404, "The migrated action item was not found.")
    return RedirectResponse(f"/action-items/{item.id}/edit", status_code=303)


@router.post("/tasks")
@router.post("/tasks/{path:path}")
def retired_tasks(user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)
    raise HTTPException(410, "TODOs have moved to Action Items. Reload Work to continue.")
