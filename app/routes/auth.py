"""Login, logout, and invite-based registration."""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import audit
from .. import permissions as perm
from ..db import get_db
from ..models import User, Invite
from ..security import hash_password, verify_password
from ..web import templates

router = APIRouter()

MIN_PASSWORD_LEN = 8


def _valid_invite(db: Session, token: str) -> Invite | None:
    if not token:
        return None
    invite = db.query(Invite).filter(Invite.token == token).first()
    if invite is None or invite.used_at is not None:
        return None
    if invite.expires_at < datetime.utcnow():
        return None
    return invite


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = "", db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": error, "hall_of_fame": perm.most_active_user(db)},
    )


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    clean_email = email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()
    if user is None or not verify_password(password, user.password_hash):
        audit.log(db, None, "auth.login_failed", target_type="user",
                  target_label=clean_email)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "Invalid email or password",
             "hall_of_fame": perm.most_active_user(db)},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    if not user.is_active:
        audit.log(db, user, "auth.login_disabled", target_type="user",
                  target_id=user.id, target_label=user.email)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"request": request, "error": "This account has been disabled.",
             "hall_of_fame": perm.most_active_user(db)},
            status_code=status.HTTP_403_FORBIDDEN,
        )
    request.session["user_id"] = user.id
    audit.log(db, user, "auth.login", target_type="user", target_id=user.id,
              target_label=user.email)
    if user.must_change_password:
        return RedirectResponse("/account/password", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id:
        user = db.get(User, user_id)
        audit.log(db, user, "auth.logout", target_type="user", target_id=user_id,
                  target_label=user.email if user else "")
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, token: str = "", db: Session = Depends(get_db)):
    invite = _valid_invite(db, token)
    if invite is None:
        return templates.TemplateResponse(
            request, "register.html", {"request": request, "invalid": True}
        )
    return templates.TemplateResponse(
        request,
        "register.html",
        {"request": request, "invalid": False, "token": token, "email": invite.email},
    )


@router.post("/register")
def register(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    invite = _valid_invite(db, token)
    if invite is None:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"request": request, "invalid": True},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    def _reject(message: str):
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "request": request,
                "invalid": False,
                "token": token,
                "email": invite.email,
                "error": message,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < MIN_PASSWORD_LEN:
        return _reject(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if db.query(User).filter(User.email == invite.email).first():
        return _reject("An account for this email already exists")

    user = User(
        email=invite.email,
        password_hash=hash_password(password),
        role=invite.role,
    )
    invite.used_at = datetime.utcnow()
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.log(db, user, "auth.register", target_type="user", target_id=user.id,
              target_label=user.email, details=f"role={user.role}, via invite #{invite.id}")

    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
