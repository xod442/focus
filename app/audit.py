"""Best-effort audit logging: records every state-changing action for the
admin System Log. Never raises — a logging failure must not block the
underlying action, mirroring the notifier's "best effort" philosophy.
"""
from sqlalchemy.orm import Session

from .models import AuditLog, User


def log(
    db: Session,
    user: "User | None",
    action: str,
    *,
    target_type: str = "",
    target_id: int | None = None,
    target_label: str = "",
    details: str = "",
) -> None:
    """Record one audit entry. `user` may be None (e.g. a failed login)."""
    try:
        entry = AuditLog(
            user_id=user.id if user is not None else None,
            user_email=user.email if user is not None else "",
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            details=details,
        )
        db.add(entry)
        db.commit()
    except Exception:  # noqa: BLE001 — logging must never break the request
        db.rollback()
