"""Category views combine with the existing person filter."""
import pytest

from app.models import PRESENTATION_CATEGORIES

from .conftest import login
from .test_presentations import add_presentation


@pytest.mark.parametrize("category", PRESENTATION_CATEGORIES)
def test_category_filters_only_matching_records(client, db_session, member_user, category):
    for value in PRESENTATION_CATEGORIES:
        add_presentation(db_session, member_user, title=f"Record {value}", category=value)
    login(client, member_user)
    r = client.get("/presentations", params={"category": category})
    assert r.status_code == 200
    assert f' value="{category}" selected' in r.text
    for value in PRESENTATION_CATEGORIES:
        assert (f"Record {value}" in r.text) == (value == category)
    assert "1 presentation" in r.text


@pytest.mark.parametrize("category", ["", "all"])
def test_all_category_view(client, db_session, member_user, category):
    for value in PRESENTATION_CATEGORIES:
        add_presentation(db_session, member_user, title=f"Record {value}", category=value)
    login(client, member_user)
    r = client.get("/presentations", params={"category": category})
    assert r.status_code == 200
    assert all(f"Record {value}" in r.text for value in PRESENTATION_CATEGORIES)


@pytest.mark.parametrize("person", ["me", "user_id"])
def test_category_and_person_filters_combine(client, db_session, member_user, other_member, person):
    add_presentation(db_session, member_user, title="My event", category="event")
    add_presentation(db_session, member_user, title="My customer", category="customer")
    add_presentation(db_session, other_member, title="Other event", category="event")
    login(client, member_user)
    r = client.get("/presentations", params={
        "category": "event", "person": "me" if person == "me" else str(member_user.id),
    })
    assert "My event" in r.text
    assert "My customer" not in r.text
    assert "Other event" not in r.text


def test_empty_category_view_has_clear_action(client, member_user):
    login(client, member_user)
    r = client.get("/presentations?category=event")
    assert "No presentations match these filters." in r.text
    assert 'href="/presentations">Show all presentations' in r.text


def test_invalid_category_is_rejected(client, member_user):
    login(client, member_user)
    r = client.get("/presentations?category=unknown")
    assert r.status_code == 400
    assert "valid presentation category" in r.text
