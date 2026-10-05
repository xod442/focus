"""FOCUS home: entry points for Work and Presentations."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ActionItem, Message, Presentation, STATUS_IN_PROGRESS, Task
from ..web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=303)

    # Preserve existing bookmarked dashboard filters when moving Work off "/".
    if any(key in request.query_params for key in ("status_filter", "person", "ok", "msg")):
        return RedirectResponse(f"/work?{request.url.query}", status_code=303)

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "user": user,
            "my_task_count": db.query(Task).filter(
                Task.owner_id == user.id, Task.status == STATUS_IN_PROGRESS
            ).count(),
            "my_item_count": db.query(ActionItem).filter(
                ActionItem.assignee_id == user.id, ActionItem.status == STATUS_IN_PROGRESS
            ).count(),
            "my_message_count": db.query(Message).filter(Message.recipient_id == user.id).count(),
            "my_presentation_count": db.query(Presentation).filter(
                Presentation.owner_id == user.id
            ).count(),
        },
    )
