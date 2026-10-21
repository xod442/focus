"""Database engine, session factory, and schema init."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers before create_all)
    Base.metadata.create_all(engine)
    _ensure_columns()
    _migrate_work()
    seed_default_admin()
    seed_default_manager()
    seed_mail_config()


def _ensure_columns() -> None:
    """Add columns introduced after a table already exists (lightweight migration)."""
    with engine.begin() as conn:
        user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        if "must_change_password" not in user_cols:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN "
                    "must_change_password BOOLEAN NOT NULL DEFAULT 0"
                )
            )
        if "is_active" not in user_cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1")
            )

        action_item_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(action_items)"))
        }
        if action_item_cols and "needs_review" not in action_item_cols:
            conn.execute(
                text("ALTER TABLE action_items ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT 0")
            )
        for name, definition in {
            "title": "VARCHAR(300) NOT NULL DEFAULT ''",
            "priority": "VARCHAR NOT NULL DEFAULT 'normal'",
            "due_date": "DATE",
            "blocked_reason": "TEXT NOT NULL DEFAULT ''",
            "legacy_task_id": "INTEGER",
        }.items():
            if name not in action_item_cols:
                conn.execute(text(f"ALTER TABLE action_items ADD COLUMN {name} {definition}"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_action_items_legacy_task "
            "ON action_items (legacy_task_id)"
        ))
        task_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(tasks)"))}
        if "migrated" not in task_cols:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN migrated BOOLEAN NOT NULL DEFAULT 0"))


def _migrate_work() -> None:
    """Copy legacy TODOs once, keeping source rows for recovery and old links."""
    from .models import ActionItem, ActionItemNote, Message, Task

    with SessionLocal() as db:
        for task in db.query(Task).filter(Task.migrated.is_(False)).all():
            task.migrated = True
            if db.query(ActionItem).filter(ActionItem.legacy_task_id == task.id).first():
                continue
            item = ActionItem(
                title=task.title, description=task.description,
                requested_by_id=task.owner_id, assignee_id=task.owner_id,
                status=task.status, created_at=task.created_at, updated_at=task.updated_at,
                completed_at=task.completed_at, legacy_task_id=task.id,
            )
            db.add(item)
            db.flush()
            for note in task.notes:
                db.add(ActionItemNote(
                    action_item_id=item.id, author_id=note.author_id,
                    body=note.body, created_at=note.created_at,
                ))
            for message in db.query(Message).filter(
                Message.related_kind == "task", Message.related_id == task.id
            ):
                message.related_kind = "action_item"
                message.related_id = item.id
                message.related_label = f"Action Item #{item.id}: {task.title}"
        db.commit()


def seed_default_admin() -> None:
    """Create the default admin on a fresh database (no users yet)."""
    from .models import User, ROLE_ADMIN
    from .security import hash_password

    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return
        db.add(
            User(
                email=config.DEFAULT_ADMIN_USERNAME,
                password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD),
                role=ROLE_ADMIN,
                must_change_password=True,
            )
        )
        db.commit()
    finally:
        db.close()


def seed_default_manager() -> None:
    """Ensure a predefined manager exists; must change password on first login.

    Seeded independently of seed_default_admin (checked by role, not total user
    count), so it fills in even on a database that already has users but no
    manager yet."""
    from .models import User, ROLE_MANAGER
    from .security import hash_password

    db = SessionLocal()
    try:
        if db.query(User).filter(User.role == ROLE_MANAGER).count() > 0:
            return
        db.add(
            User(
                email=config.DEFAULT_MANAGER_USERNAME,
                password_hash=hash_password(config.DEFAULT_MANAGER_PASSWORD),
                role=ROLE_MANAGER,
                must_change_password=True,
            )
        )
        db.commit()
    finally:
        db.close()


def seed_mail_config() -> None:
    """Ensure the single mail-config row exists."""
    from .models import MailConfig

    db = SessionLocal()
    try:
        if db.get(MailConfig, 1) is None:
            db.add(MailConfig(id=1))
            db.commit()
    finally:
        db.close()
