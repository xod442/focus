"""FOCUS home and compatibility for existing Work bookmarks."""
from .conftest import login


def test_home_requires_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_home_links_to_both_areas_and_shows_personal_counts(client, member_user, other_member):
    login(client, other_member)
    client.post("/tasks", data={"title": "Other person's task"})
    client.post("/action-items", data={
        "description": "Assigned to me", "assignee_id": member_user.id,
    })
    client.post("/logout")
    login(client, member_user)
    client.post("/tasks", data={"title": "My task"})

    r = client.get("/")
    assert r.status_code == 200
    assert "Your focus, in one place" in r.text
    assert "1 open task" in r.text
    assert "1 assigned action item" in r.text
    assert 'href="/work">Open Work' in r.text
    assert 'href="/presentations">Open Presentations' in r.text
    assert "0 presentations owned by you" in r.text
    assert "Other person's task" not in r.text


def test_legacy_work_filters_redirect_preserving_query(client, member_user):
    login(client, member_user)
    r = client.get("/?status_filter=completed&person=me", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/work?status_filter=completed&person=me"


def test_work_creation_redirects_stay_in_work(client, member_user):
    login(client, member_user)
    for url, data in (
        ("/tasks", {"title": "New task"}),
        ("/action-items", {"description": "New action item", "assignee_id": member_user.id}),
    ):
        r = client.post(url, data=data, follow_redirects=False)
        assert r.headers["location"] == "/work"


def test_subpath_home_links_and_legacy_redirect(client, member_user, monkeypatch):
    from app import config
    from app.web import templates

    monkeypatch.setattr(config, "ROOT_PATH", "/focus")
    monkeypatch.setitem(templates.env.globals, "rp", "/focus")
    login(client, member_user)
    r = client.get("/")
    assert 'href="/focus/work">Open Work' in r.text
    assert 'href="/focus/presentations">Open Presentations' in r.text
    assert 'href="/focus/presentations/new"' in r.text
    r = client.get("/?person=me", follow_redirects=False)
    assert r.headers["location"] == "/focus/work?person=me"
