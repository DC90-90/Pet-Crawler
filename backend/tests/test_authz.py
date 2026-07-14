"""Authorization: editor restrictions vs owner."""
import pytest

from tests.conftest import csrf_headers, login, make_user

pytestmark = pytest.mark.asyncio


async def test_editor_cannot_manage_users(app_client, mock_db):
    await make_user(mock_db, "editor@example.com", "Editor!123", role="editor")
    await login(app_client, "editor@example.com", "Editor!123")
    resp = await app_client.post(
        "/api/admin/users",
        json={"email": "new@example.com", "password": "Password!1", "role": "editor"},
        headers=csrf_headers(app_client),
    )
    assert resp.status_code == 403

    resp = await app_client.get("/api/admin/users")
    assert resp.status_code == 403


async def test_owner_can_manage_users(app_client, mock_db):
    await make_user(mock_db, "owner@example.com", "Owner!123", role="owner")
    await login(app_client, "owner@example.com", "Owner!123")
    resp = await app_client.post(
        "/api/admin/users",
        json={"email": "new@example.com", "password": "Password!1", "role": "editor"},
        headers=csrf_headers(app_client),
    )
    assert resp.status_code == 201


async def test_editor_cannot_change_analytics_settings(app_client, mock_db):
    await make_user(mock_db, "editor@example.com", "Editor!123", role="editor")
    await login(app_client, "editor@example.com", "Editor!123")
    resp = await app_client.put(
        "/api/admin/settings",
        json={"brandName": "Edited", "analytics": {"gaId": "G-EVIL"}},
        headers=csrf_headers(app_client),
    )
    assert resp.status_code == 200
    # analytics change must have been stripped for editors
    settings_doc = await mock_db.site_settings.find_one({"_id": "settings"})
    assert settings_doc.get("analytics", {}).get("gaId") in (None, "")
    assert settings_doc.get("brandName") == "Edited"
