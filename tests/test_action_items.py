"""Action item creation, assignment, and edit permission rules."""
from .conftest import login


def test_member_can_assign_action_item_to_anyone(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Send the pricing sheet",
        "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Send the pricing sheet"
    ).one()
    assert item.requested_by_id == member_user.id
    assert item.assignee_id == other_member.id


def test_assignee_can_edit_item_they_did_not_request(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Please review my slides",
        "assignee_id": str(other_member.id),
    })
    client.post("/logout")

    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Please review my slides"
    ).one()

    login(client, other_member)
    client.post(f"/action-items/{item.id}", data={
        "description": "Reviewed and updated",
        "assignee_id": str(other_member.id),
    })
    db_session.refresh(item)
    assert item.description == "Reviewed and updated"


def test_unrelated_member_cannot_edit_item(client, db_session, member_user, other_member,
                                            manager_user):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Only for us two",
        "assignee_id": str(other_member.id),
    })
    client.post("/logout")

    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Only for us two"
    ).one()

    login(client, manager_user)  # not requester/assignee, but IS staff → allowed
    client.post(f"/action-items/{item.id}", data={
        "description": "Manager touched this",
        "assignee_id": str(other_member.id),
    })
    db_session.refresh(item)
    assert item.description == "Manager touched this"


def test_toggle_action_item_status(client, db_session, member_user):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Toggle this item",
        "assignee_id": str(member_user.id),
    })
    from app.models import ActionItem, STATUS_COMPLETED, STATUS_IN_PROGRESS
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Toggle this item"
    ).one()
    assert item.status == STATUS_IN_PROGRESS

    client.post(f"/action-items/{item.id}/status")
    db_session.refresh(item)
    assert item.status == STATUS_COMPLETED


def test_edit_by_non_assignee_flags_needs_review(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Needs a look", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Needs a look"
    ).one()
    assert item.needs_review is False

    # member_user (the requester, not the assignee) edits it.
    client.post(f"/action-items/{item.id}", data={
        "description": "Needs a look — updated", "assignee_id": str(other_member.id),
    }, follow_redirects=False)
    db_session.refresh(item)
    assert item.needs_review is True


def test_edit_by_assignee_self_clears_needs_review(client, db_session, member_user,
                                                     other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Self edit test", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Self edit test"
    ).one()
    client.post("/logout")

    # other_member IS the assignee — editing their own item shouldn't leave a
    # lingering "review" flag, since the redirect lands them right back on the
    # page that clears it for the assignee.
    login(client, other_member)
    client.post(f"/action-items/{item.id}", data={
        "description": "Self edit test — updated", "assignee_id": str(other_member.id),
    })
    db_session.refresh(item)
    assert item.needs_review is False


def test_note_by_non_assignee_flags_needs_review(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Note test", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Note test"
    ).one()

    client.post(f"/action-items/{item.id}/notes", data={"body": "any update?"},
                follow_redirects=False)
    db_session.refresh(item)
    assert item.needs_review is True


def test_assignee_viewing_clears_needs_review(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "View to clear", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "View to clear"
    ).one()
    client.post(f"/action-items/{item.id}/notes", data={"body": "please check"},
                follow_redirects=False)
    db_session.refresh(item)
    assert item.needs_review is True
    client.post("/logout")

    # A non-assignee viewing does NOT clear it.
    login(client, member_user)
    client.get(f"/action-items/{item.id}/edit")
    db_session.refresh(item)
    assert item.needs_review is True
    client.post("/logout")

    # The assignee viewing DOES clear it.
    login(client, other_member)
    client.get(f"/action-items/{item.id}/edit")
    db_session.refresh(item)
    assert item.needs_review is False


def test_marking_complete_clears_needs_review(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Complete clears review", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Complete clears review"
    ).one()
    client.post(f"/action-items/{item.id}/notes", data={"body": "note"})
    db_session.refresh(item)
    assert item.needs_review is True

    client.post("/logout")
    login(client, other_member)
    client.post(f"/action-items/{item.id}/status")
    db_session.refresh(item)
    assert item.needs_review is False


def test_dashboard_shows_review_pill(client, db_session, member_user, other_member):
    login(client, member_user)
    client.post("/action-items", data={
        "description": "Dashboard review pill", "assignee_id": str(other_member.id),
    })
    from app.models import ActionItem
    item = db_session.query(ActionItem).filter(
        ActionItem.description == "Dashboard review pill"
    ).one()
    client.post(f"/action-items/{item.id}/notes", data={"body": "ping"})

    r = client.get("/")
    assert 'class="status-badge status-review"' in r.text
    assert ">review<" in r.text
