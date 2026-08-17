"""Single sign-on hand-off with HOLO: token generation/verification (both
directions), gating on config, and redirect targets."""
from urllib.parse import unquote

import pytest
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app import config
from app.models import AuditLog
from .conftest import login


def _token_for(email: str, secret: str = "shared-test-secret") -> str:
    serializer = URLSafeTimedSerializer(secret, salt=config.SSO_SALT)
    return serializer.dumps({"email": email})


def test_holo_button_hidden_when_sso_not_configured(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    login(client, member_user)
    r = client.get("/")
    assert "holo-link" not in r.text
    assert "/go/holo" not in r.text


def test_holo_button_shown_when_sso_configured(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    login(client, member_user)
    r = client.get("/")
    assert "holo-link" in r.text
    assert "/go/holo" in r.text


def test_go_holo_redirects_to_holo_with_valid_token(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    monkeypatch.setattr(config, "HOLO_BASE_URL", "http://localhost:9093")
    login(client, member_user)

    r = client.get("/go/holo", follow_redirects=False)
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("http://localhost:9093/sso/focus?token=")

    token = location.split("token=", 1)[1]
    serializer = URLSafeTimedSerializer("shared-test-secret", salt=config.SSO_SALT)
    payload = serializer.loads(token, max_age=config.SSO_TOKEN_MAX_AGE)
    assert payload["email"] == member_user.email


def test_go_holo_requires_login(client):
    r = client.get("/go/holo", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_go_holo_disabled_redirects_home_when_no_secret(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    login(client, member_user)
    r = client.get("/go/holo", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_token_cannot_be_verified_with_wrong_secret(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "correct-secret")
    login(client, member_user)
    r = client.get("/go/holo", follow_redirects=False)
    token = r.headers["location"].split("token=", 1)[1]

    wrong_serializer = URLSafeTimedSerializer("wrong-secret", salt=config.SSO_SALT)
    with pytest.raises(BadSignature):
        wrong_serializer.loads(token)


def test_sso_from_holo_logs_in_matching_user(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    token = _token_for(member_user.email)

    r = client.get(f"/sso/holo?token={token}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    # The session is really established — a follow-up request works as that user.
    r2 = client.get("/", follow_redirects=False)
    assert r2.status_code == 200


def test_sso_from_holo_audits_login(client, db_session, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    token = _token_for(member_user.email)
    client.get(f"/sso/holo?token={token}", follow_redirects=False)

    entry = db_session.query(AuditLog).filter(AuditLog.action == "sso.login_from_holo").first()
    assert entry is not None
    assert entry.user_id == member_user.id
    assert entry.user_email == member_user.email


def test_sso_from_holo_rejects_unknown_email(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    token = _token_for("nobody-here@test.local")
    r = client.get(f"/sso/holo?token={token}", follow_redirects=False)
    assert r.status_code == 303
    location = unquote(r.headers["location"])
    assert location.startswith("/login?error=")
    assert "No FOCUS account" in location


def test_sso_from_holo_rejects_disabled_user(client, db_session, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "shared-test-secret")
    member_user.is_active = False
    db_session.add(member_user)
    db_session.commit()

    token = _token_for(member_user.email)
    r = client.get(f"/sso/holo?token={token}", follow_redirects=False)
    location = unquote(r.headers["location"])
    assert location.startswith("/login?error=")
    assert "No FOCUS account" in location


def test_sso_from_holo_disabled_without_secret(client, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "")
    r = client.get("/sso/holo?token=whatever", follow_redirects=False)
    location = unquote(r.headers["location"])
    assert location.startswith("/login?error=")
    assert "not enabled" in location


def test_sso_from_holo_rejects_wrong_secret(client, member_user, monkeypatch):
    monkeypatch.setattr(config, "SSO_SHARED_SECRET", "correct-secret")
    token = _token_for(member_user.email, secret="wrong-secret")
    r = client.get(f"/sso/holo?token={token}", follow_redirects=False)
    location = unquote(r.headers["location"])
    assert location.startswith("/login?error=")
    assert "Invalid" in location
