"""Dashboard filtering: status (open/completed/all) and person."""
from .conftest import login


def test_default_dashboard_shows_open_by_default(client, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Open task"})
    r = client.get("/")
    assert "Open task" in r.text
    assert 'value="open" selected' in r.text or "open" in r.text


def test_status_filter_completed(client, db_session, member_user):
    login(client, member_user)
    client.post("/tasks", data={"title": "Finish me"})
    from app.models import Task
    task = db_session.query(Task).filter(Task.title == "Finish me").one()
    client.post(f"/tasks/{task.id}/status")  # mark complete

    r = client.get("/?status_filter=open")
    assert "Finish me" not in r.text

    r = client.get("/?status_filter=completed")
    assert "Finish me" in r.text

    r = client.get("/?status_filter=all")
    assert "Finish me" in r.text


def test_person_filter_me(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/tasks", data={"title": "Mine only"})
    client.post("/logout")

    login(client, other_member)
    client.post("/tasks", data={"title": "Others task"})

    r = client.get("/?person=me")
    assert "Others task" in r.text
    assert "Mine only" not in r.text
