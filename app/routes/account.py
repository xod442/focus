"""Self-service account actions (change password)."""
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from .. import audit
from ..security import hash_password, verify_password
from ..web import templates

router = APIRouter()

MIN_PASSWORD_LEN = 8


@router.get("/account/password", response_class=HTMLResponse)
def password_form(request: Request, user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "account_password.html",
        {"request": request, "user": user, "must_change": user.must_change_password},
    )


@router.post("/account/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    def reject(error: str):
        return templates.TemplateResponse(
            request,
            "account_password.html",
            {
                "request": request,
                "user": user,
                "must_change": user.must_change_password,
                "error": error,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not verify_password(current_password, user.password_hash):
        return reject("Current password is incorrect")
    if len(new_password) < MIN_PASSWORD_LEN:
        return reject(f"New password must be at least {MIN_PASSWORD_LEN} characters")
    if new_password != confirm_password:
        return reject("New passwords do not match")

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.add(user)
    db.commit()
    audit.log(db, user, "account.password_change", target_type="user",
              target_id=user.id, target_label=user.email)

    # Success: advance to the main dashboard. The change flag is now cleared, so
    # the enforcement middleware no longer bounces the request back here.
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
