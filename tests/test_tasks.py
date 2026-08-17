"""Task creation, editing, ownership rules, status toggling, and notes."""
from .conftest import login


def test_member_can_create_task_for_self(client, member_user):
    login(client, member_user)
    r = client.post("/tasks", data={"title": "Ship the report"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/")
    assert "Ship the report" in r.text


def test_member_cannot_assign_task_to_someone_else(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Sneaky", "owner_id": str(other_member.id)})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Sneaky").one()
    # Regular members can't set owner_id — it's forced back to themselves.
    assert task.owner_id == member_user.id


def test_manager_can_assign_task_to_anyone(client, db_session, manager_user, other_member):
    login(client, manager_user)
    client.post("/tasks", data={"title": "Planned for other", "owner_id": str(other_member.id)})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Planned for other").one()
    assert task.owner_id == other_member.id


def test_owner_can_edit_own_task(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Original"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Original").one()
    r = client.post(f"/tasks/{task.id}", data={"title": "Updated", "description": "new desc"},
                     follow_redirects=False)
    assert r.status_code == 303
    db_session.refresh(task)
    assert task.title == "Updated"
    assert task.description == "new desc"


def test_non_owner_member_cannot_edit_task(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Mine"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Mine").one()

    login(client, other_member)
    client.post(f"/tasks/{task.id}", data={"title": "Hacked", "description": "x"})
    db_session.refresh(task)
    assert task.title == "Mine"  # unchanged


def test_manager_can_edit_any_task(client, db_session, member_user, manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Owned by member"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Owned by member").one()

    login(client, manager_user)
    client.post(f"/tasks/{task.id}", data={"title": "Edited by manager", "description": "x"})
    db_session.refresh(task)
    assert task.title == "Edited by manager"


def test_toggle_task_status(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Toggle me"})
    from app.models import STATUS_COMPLETED, STATUS_IN_PROGRESS, Task
    task = db_session.query(Task).filter(Task.title == "Toggle me").one()
    assert task.status == STATUS_IN_PROGRESS

    client.post(f"/tasks/{task.id}/status")
    db_session.refresh(task)
    assert task.status == STATUS_COMPLETED
    assert task.completed_at is not None

    client.post(f"/tasks/{task.id}/status")
    db_session.refresh(task)
    assert task.status == STATUS_IN_PROGRESS
    assert task.completed_at is None


def test_add_task_note(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Notable"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Notable").one()
    client.post(f"/tasks/{task.id}/notes", data={"body": "discussed on call"})
    db_session.refresh(task)
    assert len(task.notes) == 1
    assert task.notes[0].body == "discussed on call"
    assert task.notes[0].author_id == member_user.id


def test_delete_task_requires_permission(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "To delete"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "To delete").one()

    login(client, other_member)
    client.post(f"/tasks/{task.id}/delete")
    assert db_session.get(Task, task.id) is not None  # not deleted

    client.post("/logout")
    login(client, member_user)
    client.post(f"/tasks/{task.id}/delete")
    assert db_session.get(Task, task.id) is None
