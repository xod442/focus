"""ORM models: auth + invites, and the Task / Action Item tracker."""
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_MEMBER = "member"
VALID_ROLES = (ROLE_ADMIN, ROLE_MANAGER, ROLE_MEMBER)
# Admin-tool access (console, invites, backups, user management).
STAFF_ROLES = (ROLE_ADMIN, ROLE_MANAGER)

# Shared status values for both Tasks and Action Items.
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
VALID_STATUSES = (STATUS_IN_PROGRESS, STATUS_COMPLETED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default=ROLE_MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default=ROLE_MEMBER)
    # Raw single-use token, stored so the admin can re-copy the link from the
    # home screen. Acceptable for internal, expiring, single-use invites.
    token: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Task(Base):
    """Work a person plans to accomplish over the next week or two. Stays on
    the dashboard, visible to the whole team, until marked completed."""
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default=STATUS_IN_PROGRESS, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id])
    notes: Mapped[list["TaskNote"]] = relationship(
        "TaskNote",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskNote.created_at.desc()",
    )


class TaskNote(Base):
    """One dated, attributed entry in a task's running notes log (e.g. added
    during the weekly team call)."""
    __tablename__ = "task_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship("Task", back_populates="notes")
    author: Mapped["User | None"] = relationship("User")


class ActionItem(Base):
    """Something one person needs another person (or themselves) to do —
    a commitment surfaced and tracked on the weekly team call."""
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default=STATUS_IN_PROGRESS, index=True)
    # Set whenever the item is edited or a note is added; cleared when the
    # assignee (the "owner" actually doing the work) next views it. Drives the
    # dashboard's "review" pill so they notice something changed since they
    # last looked, without needing a separate notification.
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    requested_by: Mapped["User"] = relationship("User", foreign_keys=[requested_by_id])
    assignee: Mapped["User"] = relationship("User", foreign_keys=[assignee_id])
    notes: Mapped[list["ActionItemNote"]] = relationship(
        "ActionItemNote",
        back_populates="action_item",
        cascade="all, delete-orphan",
        order_by="ActionItemNote.created_at.desc()",
    )


class ActionItemNote(Base):
    """One dated, attributed entry in an action item's running notes log."""
    __tablename__ = "action_item_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_item_id: Mapped[int] = mapped_column(ForeignKey("action_items.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    action_item: Mapped["ActionItem"] = relationship("ActionItem", back_populates="notes")
    author: Mapped["User | None"] = relationship("User")


class MailConfig(Base):
    """Single-row config for the outbound (unauthenticated) SMTP forwarder."""
    __tablename__ = "mail_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    host: Mapped[str] = mapped_column(String, default="")   # relay host / IP
    port: Mapped[int] = mapped_column(Integer, default=25)
    mail_from: Mapped[str] = mapped_column(String, default="")
    default_to: Mapped[str] = mapped_column(String, default="")  # fallback / test target
    app_base_url: Mapped[str] = mapped_column(String, default="")  # for links in emails


class AuditLog(Base):
    """Best-effort record of state-changing actions, shown on the admin System Log."""
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_email: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String)
    target_type: Mapped[str] = mapped_column(String, default="")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_label: Mapped[str] = mapped_column(String, default="")
    details: Mapped[str] = mapped_column(Text, default="")


MESSAGE_BODY_MAX_LEN = 250


class Message(Base):
    """A short, in-app ping from one user to another about a task/action item.

    Each user's dashboard shows only messages where they are the recipient.
    "Clearing" a message removes it from the DB entirely — it's a queue of
    quick notifications, not a persistent thread/inbox."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(String(MESSAGE_BODY_MAX_LEN))
    # What the message was sent about — kept as a denormalized snapshot so the
    # message stays meaningful even if the task/action item is later edited or
    # deleted (related_id may no longer resolve to a live record).
    related_kind: Mapped[str] = mapped_column(String, default="")   # "task" | "action_item" | ""
    related_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    related_label: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sender: Mapped["User"] = relationship("User", foreign_keys=[sender_id])
    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_id])
