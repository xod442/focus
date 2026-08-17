"""Outbound email via an unauthenticated SMTP forwarder (invitations, test mail).

Failures never break a request — they're logged and returned as (False, reason)
so the caller can surface them without raising.
"""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .models import MailConfig

logger = logging.getLogger("focus.notifier")

SMTP_TIMEOUT = 5  # seconds — bound the request if the relay is unreachable


def get_config(db: Session) -> MailConfig | None:
    return db.get(MailConfig, 1)


def _send(cfg: MailConfig, recipients: list[str], subject: str, body: str) -> None:
    """Send one message through the relay (no auth). Raises on failure."""
    msg = EmailMessage()
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT) as server:
        server.send_message(msg)


def send_test(db: Session, to_address: str) -> tuple[bool, str]:
    """Send a test email. Returns (ok, message) for the admin UI."""
    cfg = get_config(db)
    if cfg is None or not cfg.host:
        return False, "No forwarder host configured."
    if not cfg.mail_from:
        return False, "No 'from' address configured."
    recipient = (to_address or cfg.default_to or "").strip()
    if not recipient:
        return False, "No recipient — set a default 'to' or enter a test address."
    try:
        _send(cfg, [recipient], "FOCUS test email",
              "This is a test message from FOCUS. If you received it, the "
              "mail forwarder is configured correctly.")
        return True, f"Test email sent to {recipient}."
    except Exception as exc:  # noqa: BLE001 — surface any relay error to the admin
        logger.warning("FOCUS test email failed: %s", exc)
        return False, f"Send failed: {exc}"


def send(db: Session, to_address: str, subject: str, body: str) -> tuple[bool, str]:
    """Send a one-off email (e.g. an invitation) via the forwarder.

    Requires host + from to be set; independent of any other toggle."""
    cfg = get_config(db)
    if cfg is None or not cfg.host:
        return False, "No mail forwarder host configured (set it in the admin console)."
    if not cfg.mail_from:
        return False, "No 'from' address configured for the mail forwarder."
    to_address = (to_address or "").strip()
    if "@" not in to_address:
        return False, "No valid recipient address."
    try:
        _send(cfg, [to_address], subject, body)
        return True, f"Email sent to {to_address}."
    except Exception as exc:  # noqa: BLE001 — surface the relay error
        logger.warning("FOCUS send failed: %s", exc)
        return False, f"Send failed: {exc}"
