"""Additive presentation schema upgrades and database backup/restore."""
import sqlite3

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import backup, config, db as db_module
from app.db import Base
from app.models import Presentation, PresentationLink, Task, User
from app.security import hash_password

from .conftest import login


def test_user_with_presentations_cannot_be_deleted(client, db_session, admin_user, member_user):
    db_session.add(Presentation(owner_id=member_user.id, title="Keep the owner", category="event"))
    db_session.commit()
    login(client, admin_user)
    r = client.post(f"/admin/users/{member_user.id}/delete", follow_redirects=False)
    assert "ok=0" in r.headers["location"]
    assert "presentation" in r.headers["location"]
    assert db_session.get(User, member_user.id) is not None


def test_startup_and_old_backup_restore_preserve_work_and_add_presentations(tmp_path, monkeypatch):
    live_path = tmp_path / "focus.db"
    old_path = tmp_path / "old-focus.db"
    engine = create_engine(f"sqlite:///{live_path}")
    session_local = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(config, "DB_PATH", str(live_path))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_local)
    try:
        old_tables = [
            table for table in Base.metadata.sorted_tables
            if table.name not in ("presentations", "presentation_links")
        ]
        Base.metadata.create_all(engine, tables=old_tables)
        with session_local() as db:
            user = User(email="existing@test.local", password_hash=hash_password("test-password"))
            db.add(user)
            db.flush()
            task = Task(owner_id=user.id, title="Existing work")
            db.add(task)
            db.commit()
            task_id = task.id
            user_id = user.id

        with sqlite3.connect(live_path) as source, sqlite3.connect(old_path) as dest:
            source.backup(dest)
        assert backup.is_valid_focus_db(str(old_path))[0]
        assert "presentations" not in inspect(engine).get_table_names()

        db_module.init_db()
        db_module.init_db()
        assert "presentations" in inspect(engine).get_table_names()
        with session_local() as db:
            assert db.get(Task, task_id).title == "Existing work"
            presentation = Presentation(
                owner_id=user_id, title="Persisted presentation", category="customer"
            )
            db.add(PresentationLink(
                presentation=presentation, label="Slides",
                url="https://team.sharepoint.com/slides",
            ))
            db.commit()

        snapshot = backup.make_backup()
        with sqlite3.connect(snapshot) as copy:
            assert copy.execute("SELECT title FROM presentations").fetchone()[0] == "Persisted presentation"
            assert copy.execute("SELECT label FROM presentation_links").fetchone()[0] == "Slides"

        backup.restore_from(str(old_path))
        with session_local() as db:
            assert db.get(Task, task_id).title == "Existing work"
            assert db.get(User, user_id).email == "existing@test.local"
            assert db.query(Presentation).count() == 0
            assert db.query(PresentationLink).count() == 0
    finally:
        engine.dispose()
