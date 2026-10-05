"""Documentation link pills, persistence, validation, and editing permissions."""
import pytest

from app.models import AuditLog, PresentationLink

from .conftest import login
from .test_presentations import add_presentation


URL = "https://team.sharepoint.com/:p:/sites/engineering/slides?web=1&download=0"


def test_multiple_links_persist_and_render_on_edit_and_detail(client, db_session, member_user):
    presentation = add_presentation(db_session, member_user, notes="Keep my notes")
    login(client, member_user)
    for label in ("Slides", "Working notes"):
        r = client.post(f"/presentations/{presentation.id}/links",
                        data={"label": label, "url": URL}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].endswith("/edit#documentation")
    db_session.expire_all()
    assert len(presentation.documentation_links) == 2
    assert presentation.notes == "Keep my notes"
    assert db_session.query(AuditLog).filter_by(action="presentation.link_add").count() == 2
    for path in (f"/presentations/{presentation.id}/edit", f"/presentations/{presentation.id}"):
        r = client.get(path)
        assert 'class="documentation-pill"' in r.text
        assert "Slides" in r.text and "Working notes" in r.text
        assert 'target="_blank" rel="noopener noreferrer"' in r.text
        assert "web=1&amp;download=0" in r.text


@pytest.mark.parametrize("user_fixture", ["member_user", "manager_user", "admin_user"])
def test_owner_and_staff_can_add_and_remove(client, db_session, member_user, request, user_fixture):
    presentation = add_presentation(db_session, member_user)
    user = request.getfixturevalue(user_fixture)
    login(client, user)
    assert client.post(f"/presentations/{presentation.id}/links",
                       data={"label": "Slides", "url": URL}).status_code == 200
    link = db_session.query(PresentationLink).one()
    r = client.post(f"/presentations/{presentation.id}/links/{link.id}/remove")
    assert r.status_code == 200
    assert db_session.query(PresentationLink).count() == 0
    assert db_session.query(AuditLog).filter_by(action="presentation.link_remove").count() == 1


def test_other_members_view_but_cannot_modify_links(client, db_session, member_user, other_member):
    presentation = add_presentation(db_session, member_user)
    link = PresentationLink(presentation=presentation, label="Slides", url=URL)
    db_session.add(link)
    db_session.commit()
    login(client, other_member)
    r = client.get(f"/presentations/{presentation.id}")
    assert "Slides" in r.text
    assert "Add link" not in r.text
    assert 'aria-label="Remove Slides link"' not in r.text
    assert client.post(f"/presentations/{presentation.id}/links",
                       data={"label": "New", "url": URL}).status_code == 403
    assert client.post(f"/presentations/{presentation.id}/links/{link.id}/remove").status_code == 403
    assert db_session.query(PresentationLink).count() == 1


@pytest.mark.parametrize("url", [
    "", "javascript:alert(1)", "http://team.sharepoint.com/file", "//team.sharepoint.com/file",
    "https://", "https://user:password@team.sharepoint.com/file",
    "https://team.sharepoint.com:bad/file", "https://[bad/file",
    "https://team.sharepoint.com/path\nbad", "https://team.sharepoint.com\\@evil.test/file",
    "https://team.sharepoint.com/" + "x" * 8192,
])
def test_invalid_urls_rejected_with_values_preserved(client, db_session, member_user, url):
    presentation = add_presentation(db_session, member_user)
    login(client, member_user)
    r = client.post(f"/presentations/{presentation.id}/links",
                    data={"label": "Keep this name", "url": url})
    assert r.status_code == 400
    assert "valid HTTPS documentation URL" in r.text
    assert 'value="Keep this name"' in r.text
    assert db_session.query(PresentationLink).count() == 0


@pytest.mark.parametrize("label", ["", "   ", "x" * 201])
def test_link_requires_short_name(client, db_session, member_user, label):
    presentation = add_presentation(db_session, member_user)
    login(client, member_user)
    r = client.post(f"/presentations/{presentation.id}/links", data={"label": label, "url": URL})
    assert r.status_code == 400
    assert "link name" in r.text
    assert db_session.query(PresentationLink).count() == 0


def test_link_cannot_be_removed_from_another_presentation(client, db_session, member_user):
    first = add_presentation(db_session, member_user)
    second = add_presentation(db_session, member_user)
    link = PresentationLink(presentation=first, label="Slides", url=URL)
    db_session.add(link)
    db_session.commit()
    login(client, member_user)
    assert client.post(f"/presentations/{second.id}/links/{link.id}/remove").status_code == 404
    assert db_session.query(PresentationLink).count() == 1


def test_anonymous_link_changes_require_login(client, db_session, member_user):
    presentation = add_presentation(db_session, member_user)
    for suffix in ("/links", "/links/1/remove"):
        r = client.post(f"/presentations/{presentation.id}{suffix}", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"


def test_label_is_escaped(client, db_session, member_user):
    presentation = add_presentation(db_session, member_user)
    login(client, member_user)
    r = client.post(f"/presentations/{presentation.id}/links",
                    data={"label": "<script>alert(1)</script>", "url": URL})
    assert "&lt;script&gt;" in r.text
    assert "<script>alert(1)</script>" not in r.text
