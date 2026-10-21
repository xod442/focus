"""Action-item assignees include live invitations, without granting login access."""
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import Invite, PENDING_INVITE_PASSWORD_HASH, User


@dataclass(frozen=True)
class AssigneeOption:
    value: str
    email: str
    user_id: int | None
    pending: bool = False
    disabled: bool = False


def assignee_options(db: Session, current: User | None = None) -> list[AssigneeOption]:
    users = {u.email: u for u in db.query(User).all()}
    options = {
        u.email: AssigneeOption(str(u.id), u.email, u.id)
        for u in users.values() if u.is_active and not u.is_pending_registration
    }
    invites = (
        db.query(Invite)
        .filter(Invite.used_at.is_(None), Invite.expires_at > datetime.utcnow())
        .order_by(Invite.created_at.desc(), Invite.id.desc())
        .all()
    )
    for invite in invites:
        if invite.email in options:
            continue
        account = users.get(invite.email)
        if account is not None and not account.is_pending_registration:
            continue
        options[invite.email] = AssigneeOption(
            f"invite:{invite.id}", invite.email, account.id if account else None, pending=True,
        )
    if current is not None and current.email not in options:
        options[current.email] = AssigneeOption(
            str(current.id), current.email, current.id,
            pending=current.is_pending_registration, disabled=True,
        )
    return sorted(options.values(), key=lambda option: option.email)


def resolve_assignee(db: Session, value: str, current_id: int | None = None) -> User:
    value = value.strip()
    if value.startswith("invite:"):
        invite_id = value.removeprefix("invite:")
        invite = db.get(Invite, int(invite_id)) if invite_id.isascii() and invite_id.isdigit() else None
        if invite is None or invite.used_at is not None or invite.expires_at <= datetime.utcnow():
            raise HTTPException(400, "This invitation is no longer available. Reload the assignment form.")
        account = db.query(User).filter(User.email == invite.email).first()
        if account is not None:
            if not account.is_pending_registration and not account.is_active:
                raise HTTPException(400, "This account is disabled and cannot receive new assignments.")
            return account
        # A stable user ID keeps existing work and messages attached when the
        # invite is accepted. The unusable password and inactive flag block login.
        account = User(
            email=invite.email, role=invite.role,
            password_hash=PENDING_INVITE_PASSWORD_HASH, is_active=False,
        )
        db.add(account)
        db.flush()
        return account

    account = db.get(User, int(value)) if value.isascii() and value.isdigit() else None
    if account is None:
        raise HTTPException(400, "Select a valid assignee.")
    if account.id != current_id and (not account.is_active or account.is_pending_registration):
        raise HTTPException(400, "Select an active user or a current invitation.")
    return account
