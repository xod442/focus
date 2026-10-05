"""Presentation persistence, validation, visibility, and ownership rules."""
from datetime import date
from html import escape, unescape
import re

import pytest

from app import permissions
from app.models import (
    AuditLog, PRESENTATION_CATEGORIES, PRESENTATION_NOTES_MAX_LEN,
    PRESENTATION_STAGES, PRESENTATION_TITLE_MAX_LEN, Presentation,
)

from .conftest import login, make_user


def form(**changes):
    return {
        "title": "Customer launch", "category": "customer", "stage": "collaborate",
        "delivery_date": "", "notes": "", **changes,
    }


def add_presentation(db, owner, **changes):
    presentation = Presentation(owner_id=owner.id, **form(**changes))
    # Form strings are intentionally separate from the ORM's date type.
    presentation.delivery_date = None
    db.add(presentation)
    db.commit()
    db.refresh(presentation)
    return presentation


def test_member_creation_persists_every_field_and_audits(client, db_session, member_user):
    login(client, member_user)
    notes = "  Discovery notes\n\nNext steps:\n  build slides  "
    response = client.post("/presentations", data=form(
        title="  Customer launch  ", category="technical_spotlight", stage="deliver",
        delivery_date="2026-11-02", notes=notes,
    ), follow_redirects=False)
    assert response.status_code == 303
    presentation = db_session.query(Presentation).one()
    db_session.expire_all()
    assert presentation.owner_id == member_user.id
    assert presentation.title == "Customer launch"
    assert presentation.category == "technical_spotlight"
    assert presentation.stage == "deliver"
    assert presentation.delivery_date == date(2026, 11, 2)
    assert presentation.notes == notes
    assert presentation.created_at and presentation.updated_at
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    assert "Presentation saved." in page.text
    assert notes in page.text
    assert 'rows="14"' in page.text
    entry = db_session.query(AuditLog).filter_by(action="presentation.create").one()
    assert (entry.user_id, entry.target_type, entry.target_id) == (
        member_user.id, "presentation", presentation.id,
    )


@pytest.mark.parametrize("category", PRESENTATION_CATEGORIES)
@pytest.mark.parametrize("stage", PRESENTATION_STAGES)
def test_all_categories_and_stages_can_be_created(client, db_session, member_user,
                                                 category, stage):
    login(client, member_user)
    assert client.post("/presentations", data=form(category=category, stage=stage)).status_code == 200
    presentation = db_session.query(Presentation).one()
    assert (presentation.category, presentation.stage) == (category, stage)
    assert presentation.delivery_date is None


def test_stage_defaults_to_collaborate(client, db_session, member_user):
    login(client, member_user)
    data = form()
    del data["stage"]
    assert client.post("/presentations", data=data).status_code == 200
    assert db_session.query(Presentation).one().stage == "collaborate"


@pytest.mark.parametrize(("changes", "message"), [
    ({"title": " \n "}, "Title is required"),
    ({"title": "x" * (PRESENTATION_TITLE_MAX_LEN + 1)}, "Title must be"),
    ({"category": "unknown"}, "Choose a valid category"),
    ({"category": ""}, "Choose a valid category"),
    ({"stage": "unknown"}, "Choose a valid stage"),
    ({"stage": ""}, "Choose a valid stage"),
    ({"delivery_date": "2026-02-30"}, "Delivery date must be"),
    ({"delivery_date": "20261102"}, "Delivery date must be"),
    ({"delivery_date": "not-a-date"}, "Delivery date must be"),
    ({"delivery_date": "2026-11-02T12:00:00"}, "Delivery date must be"),
    ({"notes": "x" * (PRESENTATION_NOTES_MAX_LEN + 1)}, "Notes must be"),
])
def test_invalid_creation_preserves_original_form_values(client, db_session, member_user,
                                                         changes, message):
    login(client, member_user)
    data = form(notes="First line\nSecond line", **{
        key: value for key, value in changes.items() if key != "notes"
    })
    if "notes" in changes:
        data["notes"] = changes["notes"]
    response = client.post("/presentations", data=data)
    assert response.status_code == 400
    assert message in response.text
    for field in ("title", "notes", "delivery_date"):
        assert escape(data[field], quote=True) in response.text
    if "delivery_date" in changes:
        assert 'type="text" name="delivery_date"' in response.text
    assert db_session.query(Presentation).count() == 0
    assert db_session.query(AuditLog).filter_by(action="presentation.create").count() == 0


def test_owner_update_saves_all_fields_and_clears_date(client, db_session, member_user):
    presentation = add_presentation(db_session, member_user)
    presentation.delivery_date = date(2026, 11, 2)
    db_session.commit()
    created_at, updated_at = presentation.created_at, presentation.updated_at
    login(client, member_user)
    notes = ("Editable working notes\n" * 1000) + "\nFinal line"
    response = client.post(f"/presentations/{presentation.id}", data=form(
        title="Updated event", category="event", stage="deliver", notes=notes,
    ))
    assert response.status_code == 200
    assert "Presentation saved." in response.text
    db_session.expire_all()
    assert (presentation.title, presentation.category, presentation.stage) == (
        "Updated event", "event", "deliver",
    )
    assert presentation.delivery_date is None
    assert presentation.notes == notes
    assert presentation.created_at == created_at
    assert presentation.updated_at > updated_at
    assert db_session.query(AuditLog).filter_by(action="presentation.update").one().target_id == presentation.id
    # Progression gates must not prevent moving backwards.
    client.post(f"/presentations/{presentation.id}", data=form(stage="collaborate"))
    db_session.refresh(presentation)
    assert presentation.stage == "collaborate"


def test_invalid_update_is_atomic(client, db_session, member_user):
    presentation = add_presentation(db_session, member_user, notes="Original\nnotes")
    login(client, member_user)
    response = client.post(f"/presentations/{presentation.id}", data=form(
        title="Unsaved title", notes="Unsaved\nnotes", delivery_date="bad-date",
    ))
    assert response.status_code == 400
    assert "Unsaved title" in response.text and "Unsaved\nnotes" in response.text
    db_session.refresh(presentation)
    assert presentation.title == "Customer launch"
    assert presentation.notes == "Original\nnotes"
    assert db_session.query(AuditLog).filter_by(action="presentation.update").count() == 0


@pytest.mark.parametrize("staff_fixture", ["manager_user", "admin_user"])
def test_staff_can_create_for_reassign_and_edit_others(client, db_session, request,
                                                     staff_fixture, member_user, other_member):
    staff = request.getfixturevalue(staff_fixture)
    login(client, staff)
    assert client.post("/presentations", data=form(owner_id=str(member_user.id))).status_code == 200
    presentation = db_session.query(Presentation).one()
    assert presentation.owner_id == member_user.id
    assert client.get(f"/presentations/{presentation.id}/edit").status_code == 200
    response = client.post(f"/presentations/{presentation.id}", data=form(
        owner_id=str(other_member.id), title="Reassigned", stage="develop",
    ))
    assert response.status_code == 200
    db_session.refresh(presentation)
    assert presentation.owner_id == other_member.id
    assert presentation.title == "Reassigned"
    assert presentation.stage == "develop"


@pytest.mark.parametrize("owner_id", ["other", "not-an-id", "999999999999999999999999"])
def test_member_cannot_spoof_creation_owner(client, db_session, member_user, other_member,
                                          owner_id):
    login(client, member_user)
    chosen = str(other_member.id) if owner_id == "other" else owner_id
    assert client.post("/presentations", data=form(owner_id=chosen)).status_code == 403
    assert db_session.query(Presentation).count() == 0


def test_member_owner_can_submit_self_but_cannot_reassign(client, db_session, member_user,
                                                        other_member):
    login(client, member_user)
    client.post("/presentations", data=form(owner_id=str(member_user.id)))
    presentation = db_session.query(Presentation).one()
    response = client.post(f"/presentations/{presentation.id}", data=form(
        owner_id=str(other_member.id), title="Forbidden",
    ))
    assert response.status_code == 403
    db_session.refresh(presentation)
    assert presentation.owner_id == member_user.id
    assert presentation.title == "Customer launch"
    assert client.post(f"/presentations/{presentation.id}", data=form(
        owner_id=str(member_user.id), title="Allowed",
    )).status_code == 200


def test_unrelated_member_can_view_but_not_edit(client, db_session, member_user, other_member):
    presentation = add_presentation(db_session, member_user, notes="Team-visible\nnotes")
    login(client, other_member)
    assert "Customer launch" in client.get("/presentations").text
    response = client.get(f"/presentations/{presentation.id}")
    assert response.status_code == 200
    assert "Team-visible\nnotes" in response.text and "readonly" in response.text
    assert "Save changes" not in response.text and "Edit presentation" not in response.text
    assert client.get(f"/presentations/{presentation.id}/edit").status_code == 403
    assert client.post(f"/presentations/{presentation.id}", data=form(title="Forbidden")).status_code == 403
    db_session.refresh(presentation)
    assert presentation.title == "Customer launch"


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/presentations"), ("get", "/presentations/new"),
    ("post", "/presentations"), ("get", "/presentations/1"),
    ("get", "/presentations/1/edit"), ("post", "/presentations/1"),
])
def test_all_endpoints_require_authentication(client, method, path):
    response = getattr(client, method)(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/presentations/999"), ("get", "/presentations/999/edit"),
    ("post", "/presentations/999"),
    ("get", "/presentations/999999999999999999999999"),
    ("get", "/presentations/999999999999999999999999/edit"),
    ("post", "/presentations/999999999999999999999999"),
])
def test_missing_presentations_are_404(client, member_user, method, path):
    login(client, member_user)
    assert getattr(client, method)(path).status_code == 404


def test_person_filters_include_everyone_me_and_any_user(client, db_session, member_user,
                                                        other_member):
    add_presentation(db_session, member_user, title="My launch")
    add_presentation(db_session, other_member, title="Other spotlight")
    login(client, member_user)
    for path in ("/presentations", "/presentations?person=everyone"):
        page = client.get(path).text
        assert "My launch" in page and "Other spotlight" in page
    page = client.get("/presentations?person=me").text
    assert "My launch" in page and "Other spotlight" not in page
    page = client.get(f"/presentations?person={other_member.id}").text
    assert "Other spotlight" in page and "My launch" not in page
    assert "No presentations match these filters." in client.get("/presentations?person=999").text
    for value in ("bad", "-1", "999999999999999999999999", "0"):
        assert client.get(f"/presentations?person={value}").status_code == 400


@pytest.mark.parametrize("submitted_owner", ["omit", "same"])
def test_staff_preserves_inactive_owner_without_reassignment(client, db_session,
                                                            manager_user, submitted_owner):
    inactive = make_user(db_session, email="inactive@test.local", is_active=False)
    unrelated_inactive = make_user(db_session, email="hidden@test.local", is_active=False)
    presentation = add_presentation(db_session, inactive)
    login(client, manager_user)
    page = client.get(f"/presentations/{presentation.id}/edit")
    assert page.status_code == 200
    assert "(inactive — current owner)" in page.text
    assert inactive.email in page.text and unrelated_inactive.email not in page.text
    data = form(title="Inactive owner's update")
    if submitted_owner == "same":
        data["owner_id"] = str(inactive.id)
    assert client.post(f"/presentations/{presentation.id}", data=data).status_code == 200
    db_session.refresh(presentation)
    assert presentation.owner_id == inactive.id
    assert presentation.title == "Inactive owner's update"
    assert presentation.title in unescape(client.get(f"/presentations?person={inactive.id}").text)


@pytest.mark.parametrize("owner_id", ["inactive", "999", "bad", "999999999999999999999999"])
def test_staff_cannot_assign_invalid_or_inactive_owner(client, db_session, admin_user,
                                                     member_user, owner_id):
    inactive = make_user(db_session, email="inactive@test.local", is_active=False)
    presentation = add_presentation(db_session, member_user)
    login(client, admin_user)
    chosen = str(inactive.id) if owner_id == "inactive" else owner_id
    for path in ("/presentations", f"/presentations/{presentation.id}"):
        response = client.post(path, data=form(title="Not saved", owner_id=chosen))
        assert response.status_code == 400
        assert "Choose a valid active owner" in response.text
    db_session.refresh(presentation)
    assert presentation.owner_id == member_user.id
    assert presentation.title == "Customer launch"
    assert db_session.query(Presentation).count() == 1


def test_notes_and_titles_are_escaped_in_every_view(client, db_session, member_user):
    title = '<script>alert("title")</script>'
    notes = '</textarea><script>alert("notes")</script>\n& final line'
    presentation = add_presentation(db_session, member_user, title=title, notes=notes)
    login(client, member_user)
    for path in ("/presentations", f"/presentations/{presentation.id}",
                 f"/presentations/{presentation.id}/edit"):
        page = client.get(path)
        assert page.status_code == 200
        assert '<script>alert("title")</script>' not in page.text
        assert '<script>alert("notes")</script>' not in page.text
        assert "&lt;script&gt;" in page.text
        if path != "/presentations":
            assert "&lt;/textarea&gt;" in page.text
            assert "\n&amp; final line" in page.text
            assert re.search(r'<textarea[^>]+rows="(?:1[2-9]|[2-9]\d)"', page.text)
    assert presentation.notes == notes


def test_permission_helpers(member_user, other_member, manager_user, admin_user, db_session):
    presentation = add_presentation(db_session, member_user)
    assert permissions.can_edit_presentation(member_user, presentation)
    assert permissions.can_edit_presentation(manager_user, presentation)
    assert permissions.can_edit_presentation(admin_user, presentation)
    assert not permissions.can_edit_presentation(other_member, presentation)
    assert not permissions.can_edit_presentation(None, presentation)
    assert permissions.can_assign_presentation(manager_user)
    assert permissions.can_assign_presentation(admin_user)
    assert not permissions.can_assign_presentation(member_user)
    assert not permissions.can_assign_presentation(None)
