"""Task creation, editing, ownership rules, status toggling, and notes."""
from .conftest import login


def test_member_can_create_task_for_self(client, member_user):
    login(client, member_user)
    r = client.post("/tasks", data={"title": "Ship the report"}, follow_redirects=False)
    assert r.status_code == 303
    r = client.get("/")
    assert "Ship the report" in r.text


def test_task_always_owned_by_creator_even_if_owner_id_submitted(client, db_session,
                                                                   member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Sneaky", "owner_id": str(other_member.id)})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Sneaky").one()
    # owner_id is no longer an accepted field at all — tasks are a personal
    # to-do list, always owned by whoever creates them.
    assert task.owner_id == member_user.id


def test_manager_cannot_assign_task_to_someone_else_either(client, db_session, manager_user,
                                                            other_member):
    login(client, manager_user)
    client.post("/tasks", data={"title": "Planned for other", "owner_id": str(other_member.id)})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Planned for other").one()
    assert task.owner_id == manager_user.id  # never reassignable, even for staff


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


def test_manager_cannot_edit_others_task(client, db_session, member_user, manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Owned by member"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Owned by member").one()

    login(client, manager_user)
    client.post(f"/tasks/{task.id}", data={
        "title": "Edited by manager", "description": "x", "owner_id": str(manager_user.id),
    })
    db_session.refresh(task)
    # Tasks are a personal to-do list — not even a manager can edit or
    # reassign someone else's task. They can only see it for visibility.
    assert task.title == "Owned by member"
    assert task.owner_id == member_user.id


def test_new_task_form_has_no_owner_field(client, member_user):
    login(client, member_user)
    r = client.get("/tasks/new")
    assert "name=\"owner_id\"" not in r.text


def test_task_edit_form_shows_owner_read_only_to_owner(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Read only owner check"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Read only owner check").one()

    r = client.get(f"/tasks/{task.id}/edit")
    assert "<select name=\"owner_id\"" not in r.text
    assert f'value="{member_user.email}" disabled' in r.text


def test_task_edit_page_is_read_only_for_non_owner(client, db_session, member_user, manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Visible but not editable"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Visible but not editable").one()

    login(client, manager_user)
    r = client.get(f"/tasks/{task.id}/edit")
    # A non-owner (even a manager) gets the read-only view: no title input,
    # no note-add form, no status/delete buttons.
    assert "name=\"title\"" not in r.text
    assert f"action=\"/tasks/{task.id}/notes\"" not in r.text
    assert f"action=\"/tasks/{task.id}/delete\"" not in r.text
    assert "Visible but not editable" in r.text


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


def test_manager_cannot_toggle_others_task_status(client, db_session, member_user, manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Hands off"})
    client.post("/logout")

    from app.models import STATUS_IN_PROGRESS, Task
    task = db_session.query(Task).filter(Task.title == "Hands off").one()

    login(client, manager_user)
    client.post(f"/tasks/{task.id}/status")
    db_session.refresh(task)
    assert task.status == STATUS_IN_PROGRESS


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


def test_non_owner_cannot_add_task_note(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Private notes"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Private notes").one()

    login(client, other_member)
    client.post(f"/tasks/{task.id}/notes", data={"body": "sneaky note"})
    db_session.refresh(task)
    assert len(task.notes) == 0


def test_manager_cannot_add_task_note(client, db_session, member_user, manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Manager can't note this"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Manager can't note this").one()

    login(client, manager_user)
    client.post(f"/tasks/{task.id}/notes", data={"body": "manager note"})
    db_session.refresh(task)
    assert len(task.notes) == 0


def test_delete_task_requires_permission(client, db_session, member_user, other_member,
                                          manager_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "To delete"})
    client.post("/logout")

    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "To delete").one()

    login(client, other_member)
    client.post(f"/tasks/{task.id}/delete")
    assert db_session.get(Task, task.id) is not None  # not deleted

    client.post("/logout")
    login(client, manager_user)
    client.post(f"/tasks/{task.id}/delete")
    assert db_session.get(Task, task.id) is not None  # not even a manager can delete it

    client.post("/logout")
    login(client, member_user)
    client.post(f"/tasks/{task.id}/delete")
    assert db_session.get(Task, task.id) is None
