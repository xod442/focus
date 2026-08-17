"""Clearing a message from the recipient's dashboard queue, and replying to
one (which sends a new message back to whoever sent it)."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette import status

from .. import audit
from ..db import get_db
from ..deps import get_current_user
from ..models import MESSAGE_BODY_MAX_LEN, Message

router = APIRouter()


def _login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/messages/{message_id}/clear")
def clear_message(message_id: int, request: Request, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    if user is None:
        return _login()
    message = db.get(Message, message_id)
    # Only the recipient may clear their own message out of their queue.
    if message is not None and message.recipient_id == user.id:
        audit.log(db, user, "message.clear", target_type="message", target_id=message.id,
                  target_label=message.related_label or message.body[:60])
        db.delete(message)
        db.commit()
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/messages/{message_id}/reply")
def reply_message(
    message_id: int,
    request: Request,
    body: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return _login()
    referer = request.headers.get("referer", "/")
    original = db.get(Message, message_id)
    # Only the recipient of a message may reply to it — that's the only
    # person who legitimately sees it in their queue.
    if original is None or original.recipient_id != user.id:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    body = body.strip()[:MESSAGE_BODY_MAX_LEN]
    if not body:
        return RedirectResponse(
            f"{referer}{'&' if '?' in referer else '?'}ok=0&msg={quote('Message cannot be empty.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    # The reply goes back to whoever sent the original — carrying the same
    # task/action item context — so the two can keep going back and forth
    # until one of them clears it.
    reply = Message(
        sender_id=user.id,
        recipient_id=original.sender_id,
        body=body,
        related_kind=original.related_kind,
        related_id=original.related_id,
        related_label=original.related_label,
    )
    db.add(reply)
    db.commit()
    audit.log(db, user, "message.reply", target_type="message", target_id=original.id,
              target_label=original.related_label or original.body[:60],
              details=f"to={original.sender.email}")

    return RedirectResponse(
        f"{referer}{'&' if '?' in referer else '?'}ok=1&msg={quote('Reply sent to ' + original.sender.email + '.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
