"""Shared pytest fixtures: an isolated in-memory DB and TestClient per test.

Env vars must be set before `app.*` is imported anywhere (config values are
read at import time), so this happens at module load, before the imports below.
"""
import os
import tempfile

os.environ.setdefault("FOCUS_SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("FOCUS_COOKIE_SECURE", "0")
os.environ.setdefault("FOCUS_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="focus-test-"), "focus.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import main as main_module  # noqa: E402
from app import notifier  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import MailConfig, ROLE_ADMIN, ROLE_MANAGER, ROLE_MEMBER, User  # noqa: E402
from app.security import hash_password  # noqa: E402

DEFAULT_PASSWORD = "correct-horse-battery"


@pytest.fixture()
def db_session():
    """A fresh, isolated in-memory SQLite database for a single test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = TestingSessionLocal()
    session.add(MailConfig(id=1))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session, monkeypatch):
    """A TestClient wired to the per-test in-memory DB (cookies persist across
    requests, so login -> follow-up request works like a real browser).

    The password-change-enforcement middleware in app.main opens its own
    session directly via `SessionLocal()` (it doesn't use `Depends(get_db)`),
    so overriding the FastAPI dependency alone wouldn't make it see test data.
    Patch that module-level name too, bound to the same test engine.
    """
    bind = db_session.get_bind()
    TestSessionLocal = sessionmaker(bind=bind, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(main_module, "SessionLocal", TestSessionLocal)

    def _override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.clear()


def make_user(db_session, *, email: str, role: str = ROLE_MEMBER,
              password: str = DEFAULT_PASSWORD, must_change_password: bool = False,
              is_active: bool = True) -> User:
    """Create and persist a user directly against the test session."""
    user = User(
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role=role,
        must_change_password=must_change_password,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_user(db_session) -> User:
    return make_user(db_session, email="admin@test.local", role=ROLE_ADMIN)


@pytest.fixture()
def manager_user(db_session) -> User:
    return make_user(db_session, email="manager@test.local", role=ROLE_MANAGER)


@pytest.fixture()
def member_user(db_session) -> User:
    return make_user(db_session, email="member@test.local", role=ROLE_MEMBER)


@pytest.fixture()
def other_member(db_session) -> User:
    return make_user(db_session, email="other@test.local", role=ROLE_MEMBER)


def login(client, user: User, password: str = DEFAULT_PASSWORD):
    """Log a client in as `user` (session cookie persists on the client)."""
    return client.post(
        "/login",
        data={"email": user.email, "password": password},
        follow_redirects=False,
    )


class FakeSMTP:
    """Stand-in for smtplib.SMTP: records every message 'sent' through it, or
    raises OSError if `.connect_error` is set (simulating an unreachable relay).
    Shared by tests exercising app.notifier / the email-a-record routes."""

    sent: list = []
    connect_error = False

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.connect_error:
            raise OSError("connection refused")
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def fake_smtp(monkeypatch):
    """Monkeypatch smtplib.SMTP (as used by app.notifier) with FakeSMTP."""
    FakeSMTP.sent = []
    FakeSMTP.connect_error = False
    monkeypatch.setattr(notifier.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def configure_mail(db_session, **overrides) -> MailConfig:
    """Set up a working mail-forwarder config for tests that send email."""
    cfg = db_session.get(MailConfig, 1)
    cfg.host = "smtp.test.local"
    cfg.mail_from = "focus@test.local"
    cfg.default_to = "default@test.local"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    db_session.add(cfg)
    db_session.commit()
    return cfg
