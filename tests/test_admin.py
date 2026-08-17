"""Admin console: invites, user management, and access control."""
import re

from .conftest import login


def test_non_staff_cannot_reach_admin(client, member_user):
    login(client, member_user)
    r = client.get("/admin", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_admin_can_create_invite_and_register(client, db_session, admin_user):
    login(client, admin_user)
    r = client.post("/admin/invite", data={"email": "newbie@hpe.com", "role": "member"})
    m = re.search(r"token=([\w\-]+)", r.text)
    assert m, "invite link not found in response"
    token = m.group(1)

    # Registration happens as a separate, logged-out visitor. `fastapi_app`'s
    # get_db override is set on the app object itself, so a fresh TestClient
    # bound to the same app instance still sees the shared in-memory test DB.
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as anon:
        r = anon.post("/register", data={"token": token, "password": "newbiepassword1"},
                       follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/"

    from app.models import User
    created = db_session.query(User).filter(User.email == "newbie@hpe.com").one()
    assert created.role == "member"


def test_reset_password_forces_change(client, db_session, admin_user, member_user):
    login(client, admin_user)
    client.post(f"/admin/users/{member_user.id}/reset-password")
    db_session.refresh(member_user)
    assert member_user.must_change_password is True


def test_toggle_disables_user(client, db_session, admin_user, member_user):
    login(client, admin_user)
    client.post(f"/admin/users/{member_user.id}/toggle")
    db_session.refresh(member_user)
    assert member_user.is_active is False


def test_admin_cannot_disable_self(client, db_session, admin_user):
    login(client, admin_user)
    r = client.post(f"/admin/users/{admin_user.id}/toggle", follow_redirects=False)
    db_session.refresh(admin_user)
    assert admin_user.is_active is True
    from urllib.parse import unquote
    assert "cannot disable" in unquote(r.headers["location"]).lower()


def test_role_change(client, db_session, admin_user, member_user):
    login(client, admin_user)
    client.post(f"/admin/users/{member_user.id}/role", data={"role": "manager"})
    db_session.refresh(member_user)
    assert member_user.role == "manager"


def test_delete_blocked_while_user_owns_open_items(client, db_session, admin_user, member_user):
    login(client, admin_user)
    client.post("/tasks", data={"title": "Owned", "owner_id": str(member_user.id)})
    r = client.post(f"/admin/users/{member_user.id}/delete", follow_redirects=False)
    from urllib.parse import unquote
    assert "still owns" in unquote(r.headers["location"])
    from app.models import User
    assert db_session.get(User, member_user.id) is not None


def test_delete_succeeds_once_items_cleared(client, db_session, admin_user, other_member):
    login(client, admin_user)
    r = client.post(f"/admin/users/{other_member.id}/delete", follow_redirects=False)
    assert r.status_code == 303
    from app.models import User
    assert db_session.get(User, other_member.id) is None
