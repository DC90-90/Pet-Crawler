"""Tour CRUD, draft/public separation, scheduling, version bump."""
import pytest

from tests.conftest import csrf_headers, login, make_user

pytestmark = pytest.mark.asyncio
EMAIL, PW = "owner@example.com", "Owner!123"


async def _auth(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)


async def test_tour_crud_and_draft_not_public(app_client, mock_db):
    await _auth(app_client, mock_db)
    h = csrf_headers(app_client)
    # create a draft tour
    resp = await app_client.post(
        "/api/admin/tours",
        json={"slug": "draft-tour", "name": {"en": "Draft Tour"}, "status": "draft"},
        headers=h,
    )
    assert resp.status_code == 201
    tour_id = resp.json()["id"]

    # admin can read it
    assert (await app_client.get(f"/api/admin/tours/{tour_id}")).status_code == 200

    # public must NOT see the draft (list or by slug)
    pub_list = await app_client.get("/api/public/tours")
    slugs = [t["slug"] for t in pub_list.json()["items"]]
    assert "draft-tour" not in slugs
    assert (await app_client.get("/api/public/tours/draft-tour")).status_code == 404


async def test_publish_makes_public_and_bumps_version(app_client, mock_db):
    await _auth(app_client, mock_db)
    h = csrf_headers(app_client)
    v0 = (await app_client.get("/api/public/content-version")).json()["version"]

    resp = await app_client.post(
        "/api/admin/tours",
        json={"slug": "pub-tour", "name": {"en": "Pub Tour"}, "status": "draft"},
        headers=h,
    )
    tour_id = resp.json()["id"]

    pr = await app_client.post(f"/api/admin/tours/{tour_id}/publish", headers=h)
    assert pr.status_code == 200
    assert pr.json()["status"] == "published"

    v1 = (await app_client.get("/api/public/content-version")).json()["version"]
    assert v1 == v0 + 1

    # now public
    assert (await app_client.get("/api/public/tours/pub-tour")).status_code == 200


async def test_scheduled_window_not_public_until_publish_at(app_client, mock_db):
    from datetime import timedelta

    from app.models.common import now_utc

    await _auth(app_client, mock_db)
    future = now_utc() + timedelta(days=5)
    # Insert a published-but-future tour directly
    await mock_db.tours.insert_one({
        "_id": "future-1", "slug": "future-tour", "name": {"en": "Future"},
        "status": "published", "publishAt": future, "unpublishAt": None,
    })
    # Insert an expired tour (unpublishAt in the past)
    past = now_utc() - timedelta(days=1)
    await mock_db.tours.insert_one({
        "_id": "past-1", "slug": "past-tour", "name": {"en": "Past"},
        "status": "published", "publishAt": None, "unpublishAt": past,
    })
    # Insert an active tour
    await mock_db.tours.insert_one({
        "_id": "active-1", "slug": "active-tour", "name": {"en": "Active"},
        "status": "published", "publishAt": now_utc() - timedelta(days=1), "unpublishAt": None,
    })

    items = (await app_client.get("/api/public/tours")).json()["items"]
    slugs = {t["slug"] for t in items}
    assert "active-tour" in slugs
    assert "future-tour" not in slugs
    assert "past-tour" not in slugs


async def test_etag_304(app_client, mock_db):
    await _auth(app_client, mock_db)
    r1 = await app_client.get("/api/public/tours")
    etag = r1.headers.get("ETag")
    assert etag
    r2 = await app_client.get("/api/public/tours", headers={"If-None-Match": etag})
    assert r2.status_code == 304
