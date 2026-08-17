"""Request-scoped auth dependencies."""
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)
