"""Shared navigation destinations and role-based visibility."""
import pytest

from .conftest import login


@pytest.mark.parametrize("user_fixture", ["member_user", "manager_user", "admin_user"])
def test_navigation_groups_account_and_staff_links(client, request, user_fixture):
    user = request.getfixturevalue(user_fixture)
    login(client, user)

    r = client.get("/")
    assert r.status_code == 200
    assert 'aria-label="Main navigation"' in r.text
    assert 'aria-controls="primary-nav"' in r.text
    assert 'href="/" aria-current="page">Home' in r.text
    assert 'href="/work"' in r.text
    assert 'href="/presentations"' in r.text
    assert '<summary>Account</summary>' in r.text
    header_after_navigation = r.text.split("</nav>", 1)[1].split("</header>", 1)[0]
    assert 'aria-label="Signed-in user"' in header_after_navigation
    assert f'<span class="account-email">{user.email}</span>' in header_after_navigation
    assert f'<span class="account-role">{user.role}</span>' in header_after_navigation
    assert 'href="/account/password"' in r.text
    assert 'method="post" action="/logout"' in r.text
    assert ('<summary>Manage</summary>' in r.text) == (user.role != "member")
    assert ('href="/admin/log"' in r.text) == (user.role != "member")


def test_navigation_marks_metrics_active(client, member_user):
    login(client, member_user)
    r = client.get("/metrics")
    assert 'href="/metrics" aria-current="page">Metrics' in r.text
    assert 'href="/" aria-current="page"' not in r.text


@pytest.mark.parametrize("path", ["/work", "/tasks/new", "/action-items/new"])
def test_navigation_marks_work_active(client, member_user, path):
    login(client, member_user)
    r = client.get(path)
    assert 'href="/work" aria-current="page">Work' in r.text


def test_navigation_preserves_holo_launcher(client, member_user, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "test-navigation-sso")
    login(client, member_user)
    r = client.get("/")
    assert 'href="/go/holo" target="_blank" rel="noopener"' in r.text


def test_login_page_has_no_signed_in_navigation(client):
    r = client.get("/login")
    assert 'id="primary-nav"' not in r.text
    assert 'action="/logout"' not in r.text
    assert 'aria-label="Signed-in user"' not in r.text
