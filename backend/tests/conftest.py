"""Shared pytest fixtures. Uses mongomock-motor so no real DB is required."""
from __future__ import annotations

import os

# Configure a safe test environment BEFORE importing the app.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-secret-value-that-is-long-enough-123456")
os.environ.setdefault("CSRF_SECRET", "test-csrf-secret-value-123456")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("SEED_SAMPLE_REVIEWS", "true")
os.environ.setdefault("MEDIA_LOCAL_DIR", "/tmp/svaneti-test-media")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

from app.core import db as db_module  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.common import new_id, now_utc  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture()
def mock_db():
    client = AsyncMongoMockClient()
    database = client["svaneti_test"]
    db_module.set_db(database)
    yield database
    db_module.set_db(None)  # type: ignore[arg-type]


@pytest_asyncio.fixture()
async def app_client(mock_db):
    from app.main import app

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            client._mock_db = mock_db  # type: ignore[attr-defined]
            yield client


async def make_user(db, email: str, password: str, role: str = "owner") -> dict:
    doc = {
        "_id": new_id(),
        "email": email.lower(),
        "passwordHash": hash_password(password),
        "role": role,
        "name": role.title(),
        "isActive": True,
        "forcePasswordChange": False,
        "failedLoginCount": 0,
        "createdAt": now_utc(),
        "updatedAt": now_utc(),
    }
    await db.users.insert_one(doc)
    return doc


async def login(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["csrfToken"]


def csrf_headers(client: AsyncClient) -> dict:
    token = client.cookies.get("csrf_token")
    return {"X-CSRF-Token": token} if token else {}
