"""Assign work before registration without granting access to pending accounts."""
from datetime import datetime, timedelta

import pytest

from app import config
from app.models import ActionItem, Invite, User
from app.routes.sso import make_holo_token
from .conftest import login


def invite_person(db_session, email="invited@test.local", **overrides):
    invite = Invite(
        email=email, token=f"token-{email}",
        expires_at=datetime.utcnow() + timedelta(days=1),
        **overrides,
    )
    db_session.add(invite)
    db_session.commit()
    return invite


def test_new_invite_is_assignable_before_registration(client, db_session, admin_user):
    login(client, admin_user)
    client.post("/admin/invite", data={"email": "new@test.local", "role": "member"})
    invite = db_session.query(Invite).filter_by(email="new@test.local").one()
    page = client.get("/action-items/new")
    assert f'value="invite:{invite.id}"' in page.text
    assert "new@test.local (invite pending)" in page.text

    response = client.post("/action-items", data={
        "description": "Work before joining", "assignee_id": f"invite:{invite.id}",
    }, follow_redirects=False)
    assert response.status_code == 303
    item = db_session.query(ActionItem).one()
    assert item.assignee.email == invite.email
    assert item.assignee.is_active is False
    assert invite.used_at is None

    edit = client.get(f"/action-items/{item.id}/edit")
    assert f'value="invite:{invite.id}" selected' in edit.text
    assert invite.email in client.get("/work").text
    assert invite.email in client.get("/metrics").text

    original_id = item.assignee_id
    client.post("/logout")
    assert client.post("/login", data={
        "email": invite.email, "password": "not-a-password",
    }).status_code == 401
    response = client.post("/register", data={
        "token": invite.token, "password": "new-valid-password",
    }, follow_redirects=False)
    assert response.status_code == 303
    db_session.refresh(item.assignee)
    assert item.assignee.id == original_id
    assert item.assignee.is_active is True
    assert db_session.query(User).filter_by(email=invite.email).count() == 1
    assert "Work before joining" in client.get("/work?person=me").text
    assert client.post(f"/action-items/{item.id}", data={
        "description": "I have joined", "assignee_id": str(original_id),
    }, follow_redirects=False).status_code == 303
    client.post("/logout")
    assert login(client, item.assignee, password="new-valid-password").status_code == 303


def test_reassign_to_pending_invitee_reuses_account(client, db_session, member_user):
    invite = invite_person(db_session)
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Existing item", "assignee_id": str(member_user.id),
    })
    item = db_session.query(ActionItem).one()
    assert f'value="invite:{invite.id}"' in client.get(
        f"/action-items/{item.id}/edit"
    ).text
    assert client.post(f"/action-items/{item.id}", data={
        "description": "Reassigned", "assignee_id": f"invite:{invite.id}",
    }, follow_redirects=False).status_code == 303
    assignee_id = item.assignee_id
    client.post("/action-items", data={
        "description": "Another item", "assignee_id": f"invite:{invite.id}",
    })
    assert {i.assignee_id for i in db_session.query(ActionItem).all()} == {assignee_id}
    assert db_session.query(User).filter_by(email=invite.email).count() == 1


@pytest.mark.parametrize("invalid_state", ["expired", "used", "deleted"])
def test_stale_invite_cannot_be_assigned(client, db_session, member_user, invalid_state):
    invite = invite_person(db_session)
    value = f"invite:{invite.id}"
    if invalid_state == "expired":
        invite.expires_at = datetime.utcnow() - timedelta(seconds=1)
    elif invalid_state == "used":
        invite.used_at = datetime.utcnow()
    else:
        db_session.delete(invite)
    db_session.commit()
    login(client, member_user)
    assert f'value="{value}"' not in client.get("/action-items/new").text
    response = client.post("/action-items", data={
        "description": "Must not save", "assignee_id": value,
    })
    assert response.status_code == 400
    assert db_session.query(ActionItem).count() == 0
    assert db_session.query(User).filter_by(email=invite.email).count() == 0


def test_invites_deduplicate_and_do_not_reenable_disabled_users(
    client, db_session, member_user, other_member,
):
    invite = invite_person(db_session)
    db_session.add(Invite(
        email=invite.email, token="second-token",
        expires_at=datetime.utcnow() + timedelta(days=1),
    ))
    disabled_invite = invite_person(db_session, other_member.email)
    other_member.is_active = False
    db_session.commit()
    login(client, member_user)
    page = client.get("/action-items/new")
    assert page.text.count("invited@test.local (invite pending)") == 1
    assert other_member.email not in page.text
    response = client.post("/action-items", data={
        "description": "Do not reactivate", "assignee_id": f"invite:{disabled_invite.id}",
    })
    assert response.status_code == 400
    client.post("/logout")
    assert client.post("/register", data={
        "token": disabled_invite.token, "password": "new-valid-password",
    }).status_code == 400
    assert other_member.is_active is False


def test_pending_account_cannot_sso_or_be_enabled_by_admin(
    client, db_session, admin_user, monkeypatch,
):
    invite = invite_person(db_session)
    login(client, admin_user)
    client.post("/action-items", data={
        "description": "Pending access", "assignee_id": f"invite:{invite.id}",
    })
    pending = db_session.query(User).filter_by(email=invite.email).one()
    response = client.post(f"/admin/users/{pending.id}/toggle")
    assert "accept" in response.text.lower()
    assert pending.is_active is False
    response = client.post(f"/admin/users/{pending.id}/reset-password")
    assert "accept" in response.text.lower()
    client.post("/logout")
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "test-shared-secret")
    response = client.get(
        f"/sso/holo?token={make_holo_token(invite.email)}", follow_redirects=False,
    )
    assert response.headers["location"].startswith("/login")
    assert client.get("/work", follow_redirects=False).headers["location"] == "/login"


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_assigned_work_survives_invite_replacement(
    client, db_session, admin_user, state,
):
    invite = invite_person(db_session)
    email = invite.email
    login(client, admin_user)
    client.post("/action-items", data={
        "description": "Keep this work", "assignee_id": f"invite:{invite.id}",
    })
    item = db_session.query(ActionItem).one()
    assignee_id = item.assignee_id
    if state == "expired":
        invite.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.commit()
    else:
        client.post(f"/admin/invite/{invite.id}/revoke")
    edit = client.get(f"/action-items/{item.id}/edit")
    assert f'value="{assignee_id}" selected disabled' in edit.text
    assert client.post(f"/action-items/{item.id}", data={
        "description": "Retained after invite expires",
    }, follow_redirects=False).status_code == 303
    assert item.assignee_id == assignee_id

    client.post("/admin/invite", data={"email": email, "role": "manager"})
    replacement = db_session.query(Invite).filter(
        Invite.email == email, Invite.token != invite.token,
    ).one()
    edit = client.get(f"/action-items/{item.id}/edit")
    assert f'value="invite:{replacement.id}" selected' in edit.text
    client.post("/logout")
    assert client.post("/register", data={
        "token": replacement.token, "password": "fresh-valid-password",
    }, follow_redirects=False).status_code == 303
    account = db_session.get(User, assignee_id)
    assert account.is_active is True
    assert account.role == "manager"
    assert item.assignee_id == assignee_id


@pytest.mark.parametrize("value", ["bad", "invite:bad", "invite:9999", "9999"])
def test_invalid_reassignment_does_not_modify_item(
    client, db_session, member_user, value,
):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Original", "assignee_id": str(member_user.id),
    })
    item = db_session.query(ActionItem).one()
    response = client.post(f"/action-items/{item.id}", data={
        "description": "Do not change", "assignee_id": value,
    })
    assert response.status_code == 400
    db_session.refresh(item)
    assert item.description == "Original"
    assert item.assignee_id == member_user.id
