"""Public inquiry create + validation + rate limit; admin update."""
import pytest

from tests.conftest import csrf_headers, login, make_user

pytestmark = pytest.mark.asyncio


def _payload(**over):
    base = {
        "fullName": "Test Traveler",
        "email": "traveler@example.com",
        "message": "I would like to visit Ushguli.",
        "consent": True,
    }
    base.update(over)
    return base


async def test_create_inquiry_ok(app_client, mock_db):
    resp = await app_client.post("/api/public/inquiries", json=_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] and body["id"]
    doc = await mock_db.inquiries.find_one({"_id": body["id"]})
    assert doc["status"] == "new"
    assert doc.get("ipHash")  # hashed, not raw
    assert "ip" not in doc


async def test_inquiry_requires_consent(app_client, mock_db):
    resp = await app_client.post("/api/public/inquiries", json=_payload(consent=False))
    assert resp.status_code == 422


async def test_inquiry_validation_email(app_client, mock_db):
    resp = await app_client.post("/api/public/inquiries", json=_payload(email="not-an-email"))
    assert resp.status_code == 422


async def test_inquiry_rate_limit(app_client, mock_db):
    codes = []
    for _ in range(7):
        r = await app_client.post("/api/public/inquiries", json=_payload())
        codes.append(r.status_code)
    assert 429 in codes  # limit is 5/min


async def test_admin_update_inquiry_status(app_client, mock_db):
    r = await app_client.post("/api/public/inquiries", json=_payload())
    inq_id = r.json()["id"]

    await make_user(mock_db, "owner@example.com", "Owner!123")
    await login(app_client, "owner@example.com", "Owner!123")
    upd = await app_client.put(
        f"/api/admin/inquiries/{inq_id}",
        json={"status": "contacted", "noteText": "Called them"},
        headers=csrf_headers(app_client),
    )
    assert upd.status_code == 200
    assert upd.json()["status"] == "contacted"
    assert len(upd.json()["notes"]) == 1


async def test_inquiry_csv_export(app_client, mock_db):
    await app_client.post("/api/public/inquiries", json=_payload())
    await make_user(mock_db, "owner@example.com", "Owner!123")
    await login(app_client, "owner@example.com", "Owner!123")
    resp = await app_client.get("/api/admin/inquiries/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "fullName" in resp.text
