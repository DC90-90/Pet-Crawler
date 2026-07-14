"""Media upload: metadata + variants, MIME rejection, deletion guard."""
import io

import pytest
from PIL import Image

from tests.conftest import csrf_headers, login, make_user

pytestmark = pytest.mark.asyncio
EMAIL, PW = "owner@example.com", "Owner!123"


def _png_bytes(w=800, h=600) -> bytes:
    img = Image.new("RGB", (w, h), (100, 140, 90))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _auth(app_client, mock_db):
    await make_user(mock_db, EMAIL, PW)
    await login(app_client, EMAIL, PW)


async def test_image_upload_metadata_and_variants(app_client, mock_db):
    await _auth(app_client, mock_db)
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    resp = await app_client.post(
        "/api/admin/media/upload", files=files, headers=csrf_headers(app_client)
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()
    assert doc["kind"] == "image"
    assert doc["width"] == 800 and doc["height"] == 600
    assert doc["mimeType"] == "image/png"
    for variant in ("thumb", "card", "hero", "original"):
        assert variant in doc["variants"]
        assert "url" in doc["variants"][variant]
    # filename sanitized/stored
    assert doc["originalFilename"] == "photo.png"


async def test_upload_rejects_disallowed_mime(app_client, mock_db):
    await _auth(app_client, mock_db)
    files = {"file": ("evil.exe", b"MZ\x00\x00", "application/x-msdownload")}
    resp = await app_client.post(
        "/api/admin/media/upload", files=files, headers=csrf_headers(app_client)
    )
    assert resp.status_code == 400


async def test_upload_requires_csrf(app_client, mock_db):
    await _auth(app_client, mock_db)
    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    resp = await app_client.post("/api/admin/media/upload", files=files)
    assert resp.status_code == 403


async def test_delete_guard_when_in_use(app_client, mock_db):
    await _auth(app_client, mock_db)
    await mock_db.media.insert_one({
        "_id": "m-used", "kind": "image", "provider": "local",
        "usageRefs": [{"collection": "tours", "docId": "t1"}], "archived": False,
    })
    r = await app_client.delete("/api/admin/media/m-used", headers=csrf_headers(app_client))
    assert r.status_code == 409
    r2 = await app_client.delete(
        "/api/admin/media/m-used?force=true", headers=csrf_headers(app_client)
    )
    assert r2.status_code == 200


async def test_uploaded_image_resolves_publicly_as_cover(app_client, mock_db):
    await _auth(app_client, mock_db)
    h = csrf_headers(app_client)
    # 1. upload an image
    files = {"file": ("cover.png", _png_bytes(), "image/png")}
    up = await app_client.post("/api/admin/media/upload", files=files, headers=h)
    media_id = up.json()["id"]

    # 2. create a tour referencing it as cover, then publish
    cr = await app_client.post(
        "/api/admin/tours",
        json={"slug": "cover-tour", "name": {"en": "Cover Tour"},
              "coverMediaId": media_id, "galleryMediaIds": [media_id]},
        headers=h,
    )
    tour_id = cr.json()["id"]
    await app_client.post(f"/api/admin/tours/{tour_id}/publish", headers=h)

    # 3. public tour exposes a resolved, working /media URL
    pub = await app_client.get("/api/public/tours/cover-tour")
    body = pub.json()
    assert body["coverUrl"] and body["coverUrl"].startswith("/media/")
    assert body["galleryUrls"] and body["galleryUrls"][0].startswith("/media/")


async def test_register_external_video(app_client, mock_db):
    await _auth(app_client, mock_db)
    resp = await app_client.post(
        "/api/admin/media/external",
        json={"url": "https://www.youtube.com/watch?v=abc123", "title": "Intro"},
        headers=csrf_headers(app_client),
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["kind"] == "external_video"
    assert doc["provider"] == "youtube"
