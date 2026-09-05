"""Test fixtures: an isolated in-file SQLite database per test session."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point config at a throwaway database before anything imports the engine.
_TMP = Path(tempfile.mkdtemp(prefix="lifeos-test-"))
os.environ["LIFEOS_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["LIFEOS_SECRET_KEY"] = "test-secret-key"
os.environ["LIFEOS_SCHEDULER_ENABLED"] = "false"

from app.db import SessionLocal, engine  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.security import hash_password  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db(_schema):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def user(db) -> User:
    """A fresh user per test, so data from one test can't leak into another."""
    import uuid

    record = User(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("test-password-123"),
        display_name="Test User",
    )
    db.add(record)
    db.commit()
    return record


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text()

    return _read
