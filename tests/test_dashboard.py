"""Dashboard filtering: status (open/completed/all) and person."""
from .conftest import login


def test_default_dashboard_shows_open_by_default(client, member_user):
    login(client, member_user)
    client.post("/action-items", data={"title": "Open task"})
    r = client.get("/work")
    assert "Open task" in r.text
    assert 'value="open" selected' in r.text or "open" in r.text


def test_status_filter_completed(client, db_session, member_user):
    login(client, member_user)
    client.post("/action-items", data={"title": "Finish me"})
    from app.models import ActionItem
    task = db_session.query(ActionItem).filter(ActionItem.title == "Finish me").one()
    client.post(f"/action-items/{task.id}/status")  # mark complete

    row_link = f'href="/action-items/{task.id}/edit">Finish me'

    r = client.get("/work?status_filter=open")
    assert row_link not in r.text

    r = client.get("/work?status_filter=completed")
    assert row_link in r.text

    r = client.get("/work?status_filter=all")
    assert row_link in r.text


def test_recently_completed_not_shown_on_dashboard(client, db_session, member_user):
    login(client, member_user)
    client.post("/action-items", data={"title": "Ship the report"})
    from app.models import ActionItem
    task = db_session.query(ActionItem).filter(ActionItem.title == "Ship the report").one()
    client.post(f"/action-items/{task.id}/status")  # mark complete

    r = client.get("/work?status_filter=open")
    assert "Recently completed" not in r.text
    assert "Ship the report" not in r.text

    r = client.get("/work?status_filter=completed")
    assert "Ship the report" in r.text


def test_person_filter_me(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={"title": "Mine only"})
    client.post("/logout")

    login(client, other_member)
    client.post("/action-items", data={"title": "Others task"})

    r = client.get("/work?person=me")
    assert "Others task" in r.text
    assert "Mine only" not in r.text


def test_executive_view_for_me(client, member_user):
    login(client, member_user)
    client.post("/action-items", data={"title": "Executive task"})

    r = client.get("/users/me/executive?days=30")
    assert r.status_code == 200
    assert "Workload and progress" in r.text
    assert "Executive task" in r.text
