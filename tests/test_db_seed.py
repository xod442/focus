"""Unit tests for app.db seed functions: default admin + manager bootstrap."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.db import Base
from app.models import ROLE_ADMIN, ROLE_MANAGER, User


def _isolated_session_local(monkeypatch):
    """Point app.db's module-level SessionLocal at a fresh in-memory engine,
    independent of the shared `db_session` fixture used by the route tests."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", TestSessionLocal)
    return TestSessionLocal


def test_seed_default_admin_on_empty_db(monkeypatch):
    SessionLocal = _isolated_session_local(monkeypatch)
    db_module.seed_default_admin()

    session = SessionLocal()
    try:
        admin = session.query(User).filter(User.role == ROLE_ADMIN).one()
        assert admin.email == "admin"
        assert admin.must_change_password is True
    finally:
        session.close()


def test_seed_default_manager_creates_manager(monkeypatch):
    SessionLocal = _isolated_session_local(monkeypatch)
    db_module.seed_default_admin()
    db_module.seed_default_manager()

    session = SessionLocal()
    try:
        manager = session.query(User).filter(User.role == ROLE_MANAGER).one()
        assert manager.email == "manager"
        assert manager.must_change_password is True
    finally:
        session.close()


def test_seed_default_manager_fills_in_on_populated_db(monkeypatch):
    """Unlike the admin seed, the manager seed isn't gated on an empty users
    table — it fills in as long as no manager role exists yet."""
    SessionLocal = _isolated_session_local(monkeypatch)
    db_module.seed_default_admin()  # DB now has one user (admin), no manager

    session = SessionLocal()
    try:
        assert session.query(User).filter(User.role == ROLE_MANAGER).count() == 0
    finally:
        session.close()

    db_module.seed_default_manager()

    session = SessionLocal()
    try:
        assert session.query(User).filter(User.role == ROLE_MANAGER).count() == 1
    finally:
        session.close()


def test_seed_default_manager_is_idempotent(monkeypatch):
    SessionLocal = _isolated_session_local(monkeypatch)
    db_module.seed_default_manager()
    db_module.seed_default_manager()  # calling twice must not create a duplicate

    session = SessionLocal()
    try:
        assert session.query(User).filter(User.role == ROLE_MANAGER).count() == 1
    finally:
        session.close()
