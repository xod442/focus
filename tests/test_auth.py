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


def test_login_page_hides_hall_of_fame_with_no_activity(client):
    r = client.get("/login")
    assert "Hall of Fame" not in r.text


def test_login_page_shows_hall_of_fame_leader(client, member_user, other_member):
    # member_user logs in twice (2 audit entries); other_member once — member
    # should be the displayed leader.
    login(client, member_user)
    client.post("/logout")
    login(client, member_user)
    client.post("/logout")
    login(client, other_member)
    client.post("/logout")

    r = client.get("/login")
    assert "Hall of Fame" in r.text
    assert member_user.email in r.text
    assert "action" in r.text.lower()


def test_login_hall_of_fame_shown_on_failed_login_too(client, member_user, other_member):
    login(client, member_user)
    client.post("/logout")

    r = client.post("/login", data={"email": other_member.email, "password": "wrong"})
    assert r.status_code == 401
    assert "Hall of Fame" in r.text
    assert member_user.email in r.text


def test_most_active_user_breaks_ties_alphabetically(client, db_session, member_user,
                                                       other_member):
    from app import permissions as perm
    from app.models import AuditLog

    # Give both users exactly one audit entry each (a tie).
    db_session.add_all([
        AuditLog(user_id=member_user.id, user_email=member_user.email, action="x"),
        AuditLog(user_id=other_member.id, user_email=other_member.email, action="x"),
    ])
    db_session.commit()

    winner = perm.most_active_user(db_session)
    assert winner is not None
    expected = min(member_user.email, other_member.email)
    assert winner["email"] == expected
    assert winner["count"] == 1
