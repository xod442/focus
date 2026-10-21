"""Legacy TODO migration and retired-route compatibility."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import db as db_module
from app.models import ActionItem, Message, Task, TaskNote, User

from .conftest import login


def test_task_links_redirect_to_action_items(client, db_session, member_user):
    item = ActionItem(
        requested_by_id=member_user.id, assignee_id=member_user.id,
        title="Migrated", description="", legacy_task_id=17,
    )
    db_session.add(item)
    db_session.commit()
    login(client, member_user)
    assert client.get("/tasks/new", follow_redirects=False).headers["location"] == "/action-items/new"
    response = client.get("/tasks/17/edit", follow_redirects=False)
    assert response.headers["location"] == f"/action-items/{item.id}/edit"
    assert client.get("/tasks/999/edit").status_code == 404


@pytest.mark.parametrize("path", ["/tasks", "/tasks/1", "/tasks/1/status", "/tasks/1/notes", "/tasks/1/delete"])
def test_retired_task_writes_cannot_create_a_second_work_list(client, member_user, path):
    login(client, member_user)
    response = client.post(path, data={"title": "Old form", "body": "Old note"})
    assert response.status_code == 410
    assert "Action Items" in response.text


def test_migration_preserves_work_notes_and_messages_and_runs_once(db_session, member_user, monkeypatch):
    now = datetime.utcnow() - timedelta(days=20)
    task = Task(
        owner_id=member_user.id, title="Existing commitment", description="Keep details",
        created_at=now, updated_at=now, status="completed", completed_at=now,
    )
    db_session.add(task)
    db_session.flush()
    db_session.add(TaskNote(task_id=task.id, author_id=member_user.id, body="Original note", created_at=now))
    message = Message(
        sender_id=member_user.id, recipient_id=member_user.id, body="Existing message",
        related_kind="task", related_id=task.id, related_label="Legacy title",
    )
    db_session.add(message)
    db_session.commit()
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    db_module._migrate_work()
    db_module._migrate_work()
    db_session.expire_all()
    item = db_session.query(ActionItem).one()
    assert item.title == task.title
    assert item.description == task.description
    assert item.requested_by_id == item.assignee_id == member_user.id
    assert item.created_at == item.updated_at == item.completed_at == now
    assert item.status == "completed"
    assert item.notes[0].body == "Original note"
    assert item.notes[0].created_at == now
    assert item.notes[0].author_id == member_user.id
    assert message.related_kind == "action_item"
    assert message.related_id == item.id
    assert "Existing commitment" in message.related_label
    db_session.delete(item)
    db_session.commit()
    db_module._migrate_work()
    assert db_session.query(ActionItem).count() == 0


def test_schema_upgrade_preserves_existing_action_items(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", sessionmaker(bind=engine))
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE action_items (id INTEGER PRIMARY KEY, requested_by_id INTEGER,"
                "assignee_id INTEGER, description TEXT, status VARCHAR, created_at DATETIME,"
                "updated_at DATETIME, completed_at DATETIME)"
            ))
            conn.execute(text(
                "INSERT INTO action_items VALUES (1, 1, 1, 'Original action', 'in_progress',"
                "'2026-01-01', '2026-01-01', NULL)"
            ))
            conn.execute(text(
                "CREATE TABLE tasks (id INTEGER PRIMARY KEY, owner_id INTEGER, title VARCHAR,"
                "description TEXT, status VARCHAR, created_at DATETIME, updated_at DATETIME,"
                "completed_at DATETIME)"
            ))
        db_module.Base.metadata.create_all(engine)
        db_module._ensure_columns()
        db_module._ensure_columns()
        with sessionmaker(bind=engine)() as db:
            item = db.get(ActionItem, 1)
            assert item.display_title == "Original action"
            assert item.priority == "normal"
            assert item.due_date is None
            assert item.status == "in_progress"
            db.add(User(id=1, email="legacy@test.local", password_hash="unused"))
            db.commit()
        db_module._migrate_work()
    finally:
        engine.dispose()
