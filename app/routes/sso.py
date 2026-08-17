"""Single sign-on hand-off with HOLO (same host, separate app/DB):
- outgoing: generate a short-lived signed token carrying the current user's
  email, then redirect to HOLO's SSO-accepting route.
- incoming: verify a token HOLO generated the same way, and log the person
  into FOCUS if a matching account exists.
"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session
from starlette import status

from .. import audit, config
from ..db import get_db
from ..deps import get_current_user
from ..models import User

router = APIRouter()


def _serializer() -> URLSafeTimedSerializer:
    # Built fresh on each use (not at import time) so it always reflects the
    # current config.SSO_SHARED_SECRET.
    return URLSafeTimedSerializer(config.SSO_SHARED_SECRET or "unused", salt=config.SSO_SALT)


def make_holo_token(email: str) -> str:
    return _serializer().dumps({"email": email})


def _login_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login?error={quote(message)}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/go/holo")
def go_to_holo(request: Request, db=Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if not config.SSO_SHARED_SECRET:
        # Not configured on this deployment — nothing to hand off to.
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

    token = make_holo_token(user.email)
    audit.log(db, user, "sso.launch_holo", target_type="user", target_id=user.id,
              target_label=user.email)
    return RedirectResponse(
        f"{config.HOLO_BASE_URL}/sso/focus?token={token}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/sso/holo")
def sso_from_holo(request: Request, token: str = "", db: Session = Depends(get_db)):
    if not config.SSO_SHARED_SECRET:
        return _login_redirect("Single sign-on from HOLO is not enabled on this server.")
    if not token:
        return _login_redirect("Missing sign-on token.")

    try:
        payload = _serializer().loads(token, max_age=config.SSO_TOKEN_MAX_AGE)
    except SignatureExpired:
        return _login_redirect("That sign-on link expired — go back to HOLO and try again.")
    except BadSignature:
        return _login_redirect("Invalid sign-on token.")

    email = (payload.get("email") or "").strip().lower()
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first() if email else None
    if user is None:
        return _login_redirect(f"No FOCUS account exists for {email or 'that address'}.")

    request.session["user_id"] = user.id
    audit.log(db, user, "sso.login_from_holo", target_type="user", target_id=user.id,
              target_label=user.email)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
