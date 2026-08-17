"""Login, logout, and disabled-account behavior."""
from .conftest import login


def test_login_success(client, member_user):
    r = login(client, member_user)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_login_wrong_password(client, member_user):
    r = client.post("/login", data={"email": member_user.email, "password": "nope"})
    assert r.status_code == 401


def test_login_disabled_account(client, db_session, member_user):
    member_user.is_active = False
    db_session.add(member_user)
    db_session.commit()
    r = client.post("/login", data={"email": member_user.email, "password": "correct-horse-battery"})
    assert r.status_code == 403
    assert "disabled" in r.text.lower()


def test_login_forces_password_change(client, db_session, member_user):
    member_user.must_change_password = True
    db_session.add(member_user)
    db_session.commit()
    r = login(client, member_user)
    assert r.headers["location"] == "/account/password"
    # Any other page should also bounce to the password-change form.
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/account/password"


def test_logout_clears_session(client, member_user):
    login(client, member_user)
    client.post("/logout")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
