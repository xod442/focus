"""Admin console: user management, invites, backup/restore, email settings."""
import os
import secrets
import tempfile
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from .. import audit, backup, config, notifier
from ..db import get_db
from ..deps import get_current_user
from ..models import ActionItem, Invite, STAFF_ROLES, Task, User, VALID_ROLES, ROLE_MEMBER
from ..security import generate_token, hash_password
from ..web import templates

router = APIRouter()


def _public_base(request: Request) -> str:
    """Absolute base URL including the edge subpath (ROOT_PATH) if any."""
    base = str(request.base_url).rstrip("/")
    if config.ROOT_PATH and not base.endswith(config.ROOT_PATH):
        base += config.ROOT_PATH
    return base


def _register_link(request: Request, token: str) -> str:
    return f"{_public_base(request)}/register?token={token}"


def _render_admin_home(request, db, user, new_invite_link=None, new_invite_id=None,
                       reset_info=None, msg="", ok=True):
    users = db.query(User).order_by(User.created_at).all()
    now = datetime.utcnow()
    pending = (
        db.query(Invite)
        .filter(Invite.used_at.is_(None), Invite.expires_at > now)
        .order_by(Invite.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin_home.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "pending": pending,
            "register_base": f"{_public_base(request)}/register?token=",
            "new_invite_link": new_invite_link,
            "new_invite_id": new_invite_id,
            "reset_info": reset_info,
            "cfg": notifier.get_config(db),
            "backups": backup.list_backups(),
            "msg": msg,
            "ok": ok,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_console(request: Request, ok: int = 1, msg: str = "",
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.role not in STAFF_ROLES:
        return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    return _render_admin_home(request, db, user, msg=msg, ok=bool(ok))


# ── User management ──────────────────────────────────────────────────────────

@router.post("/admin/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.id == user_id:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('You cannot disable your own account.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('User not found.')}", status_code=status.HTTP_303_SEE_OTHER
        )
    target.is_active = not target.is_active
    db.add(target)
    db.commit()
    audit.log(db, user, "admin.user_toggle", target_type="user", target_id=target.id,
              target_label=target.email, details=f"is_active={target.is_active}")
    state = "enabled" if target.is_active else "disabled"
    return RedirectResponse(
        f"/admin?ok=1&msg={quote(f'{target.email} {state}.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/users/{user_id}/role")
def set_user_role(user_id: int, role: str = Form(...), request: Request = None,
                  db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if role not in VALID_ROLES:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Invalid role.')}", status_code=status.HTTP_303_SEE_OTHER
        )
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('User not found.')}", status_code=status.HTTP_303_SEE_OTHER
        )
    target.role = role
    db.add(target)
    db.commit()
    audit.log(db, user, "admin.user_role", target_type="user", target_id=target.id,
              target_label=target.email, details=f"role={role}")
    return RedirectResponse(
        f"/admin?ok=1&msg={quote(f'{target.email} is now {role}.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/users/{user_id}/reset-password")
def reset_password(user_id: int, request: Request, db: Session = Depends(get_db),
                   user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    target = db.get(User, user_id)
    if target is None:
        return _render_admin_home(request, db, user, msg="User not found.", ok=False)
    # Issue a temporary password and force a change at next login.
    temp = secrets.token_urlsafe(9)
    target.password_hash = hash_password(temp)
    target.must_change_password = True
    db.add(target)
    db.commit()
    audit.log(db, user, "admin.password_reset", target_type="user",
              target_id=target.id, target_label=target.email)
    return _render_admin_home(
        request, db, user,
        reset_info={"email": target.email, "temp": temp},
    )


@router.post("/admin/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    if user.id == user_id:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('You cannot delete your own account.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    target = db.get(User, user_id)
    if target is None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('User not found.')}", status_code=status.HTTP_303_SEE_OTHER
        )
    # Guard rails: don't orphan tasks/action items tied to this person — the
    # admin must reassign or complete them first.
    owns_tasks = db.query(Task).filter(Task.owner_id == user_id).count()
    owns_items = (
        db.query(ActionItem)
        .filter((ActionItem.requested_by_id == user_id) | (ActionItem.assignee_id == user_id))
        .count()
    )
    if owns_tasks or owns_items:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote(f'{target.email} still owns {owns_tasks} task(s) and {owns_items} action item(s) — reassign or complete them first, or disable the account instead.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    email = target.email
    db.delete(target)
    db.commit()
    audit.log(db, user, "admin.user_delete", target_type="user", target_label=email)
    return RedirectResponse(
        f"/admin?ok=1&msg={quote(f'{email} deleted.')}", status_code=status.HTTP_303_SEE_OTHER
    )


# ── Invitations ───────────────────────────────────────────────────────────────

@router.post("/admin/invite")
def create_invite(
    request: Request,
    email: str = Form(...),
    role: str = Form(ROLE_MEMBER),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)

    email = email.strip().lower()
    role = role if role in VALID_ROLES else ROLE_MEMBER
    token = generate_token()
    invite = Invite(
        email=email,
        role=role,
        token=token,
        expires_at=datetime.utcnow() + timedelta(days=config.INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.commit()
    audit.log(db, user, "admin.invite_create", target_type="invite",
              target_id=invite.id, target_label=email, details=f"role={role}")

    return _render_admin_home(
        request, db, user,
        new_invite_link=_register_link(request, token),
        new_invite_id=invite.id,
    )


def _invite_email_body(link: str) -> str:
    return (
        "You've been invited to FOCUS — the team's task and action item tracker.\n\n"
        "Set up your account using this single-use link (it will expire):\n\n"
        f"{link}\n"
    )


@router.post("/admin/invite/{invite_id}/email")
def email_invite(invite_id: int, request: Request, db: Session = Depends(get_db),
                 user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    invite = db.get(Invite, invite_id)
    if invite is None or invite.used_at is not None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Invitation not found or already used.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    link = _register_link(request, invite.token)
    ok, message = notifier.send(db, invite.email,
                                "Your FOCUS invitation", _invite_email_body(link))
    audit.log(db, user, "admin.invite_email", target_type="invite",
              target_id=invite.id, target_label=invite.email,
              details=f"sent={ok}")
    return RedirectResponse(
        f"/admin?ok={1 if ok else 0}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/invite/{invite_id}/revoke")
def revoke_invite(invite_id: int, request: Request, db: Session = Depends(get_db),
                  user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    invite = db.get(Invite, invite_id)
    if invite is not None and invite.used_at is None:
        db.delete(invite)
        db.commit()
        audit.log(db, user, "admin.invite_revoke", target_type="invite",
                  target_id=invite_id, target_label=invite.email)
    return RedirectResponse(
        f"/admin?ok=1&msg={quote('Invitation revoked.')}", status_code=status.HTTP_303_SEE_OTHER
    )


# ── Backup / restore ──────────────────────────────────────────────────────────

@router.post("/admin/backup")
def backup_now(request: Request, db: Session = Depends(get_db),
               user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    try:
        path = backup.make_backup()
        name = os.path.basename(path)
        audit.log(db, user, "admin.backup_create", target_type="backup",
                  target_label=name)
        return RedirectResponse(
            f"/admin?ok=1&msg={quote('Backup created: ' + name)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception as exc:  # noqa: BLE001 — surface backup failure to the admin
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Backup failed: ' + str(exc))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get("/admin/backup/download/{name}")
def download_backup(name: str, request: Request, db: Session = Depends(get_db),
                    user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    path = backup.safe_path(name)
    if path is None:
        return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    return FileResponse(path, filename=name, media_type="application/octet-stream")


def _do_restore(source_path: str, label: str) -> RedirectResponse:
    """Validate, safety-backup the current DB, then restore. Returns a redirect."""
    ok, why = backup.is_valid_focus_db(source_path)
    if not ok:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Restore rejected: ' + why)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    backup.make_backup()          # safety snapshot of current DB
    backup.restore_from(source_path)
    return RedirectResponse(
        f"/admin?ok=1&msg={quote('Database restored from ' + label + '. A safety backup was taken first — you may need to sign in again.')}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/admin/restore")
async def restore_upload(request: Request, file: UploadFile = File(...),
                         db: Session = Depends(get_db), user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    data = await file.read()
    audit.log(db, user, "admin.restore", target_type="backup",
              target_label=file.filename or "uploaded file",
              details="source=upload")
    db.close()  # release the pooled connection before we rewrite the DB file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    try:
        tmp.write(data)
        tmp.close()
        return _do_restore(tmp.name, file.filename or "uploaded file")
    finally:
        os.unlink(tmp.name)


@router.post("/admin/restore/{name}")
def restore_existing(name: str, request: Request, db: Session = Depends(get_db),
                     user=Depends(get_current_user)):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    path = backup.safe_path(name)
    if path is None:
        return RedirectResponse(
            f"/admin?ok=0&msg={quote('Backup not found.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    audit.log(db, user, "admin.restore", target_type="backup", target_label=name,
              details="source=existing_backup")
    db.close()
    return _do_restore(path, name)


# ── Email settings ────────────────────────────────────────────────────────────

@router.post("/admin/mail-config")
def update_mail_config(
    request: Request,
    enabled: str = Form("off"),
    host: str = Form(""),
    port: int = Form(25),
    mail_from: str = Form(""),
    default_to: str = Form(""),
    app_base_url: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    cfg = notifier.get_config(db)
    cfg.enabled = enabled == "on"
    cfg.host = host.strip()
    cfg.port = port
    cfg.mail_from = mail_from.strip()
    cfg.default_to = default_to.strip()
    cfg.app_base_url = app_base_url.strip()
    db.add(cfg)
    db.commit()
    audit.log(db, user, "admin.mail_config", target_type="mail_config",
              details=f"host={cfg.host} enabled={cfg.enabled}")
    return RedirectResponse(
        f"/admin?ok=1&msg={quote('Email settings saved.')}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/admin/mail-test")
def send_test_email(
    request: Request,
    to_address: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    if user is None or user.role not in STAFF_ROLES:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    ok, message = notifier.send_test(db, to_address)
    return RedirectResponse(
        f"/admin?ok={1 if ok else 0}&msg={quote(message)}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
