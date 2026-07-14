"""Public endpoints: content-version, SEO route, sitemap, offers, popups, reviews."""
import pytest

from app.seed import run as seed_run

pytestmark = pytest.mark.asyncio


async def test_content_version_shape(app_client, mock_db):
    resp = await app_client.get("/api/public/content-version")
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body and "updatedAt" in body


async def test_seed_and_public_surfaces(app_client, mock_db):
    await seed_run.run()

    # published tours present, draft custom itinerary absent
    tours = (await app_client.get("/api/public/tours")).json()["items"]
    slugs = {t["slug"] for t in tours}
    assert "ushguli-shkhara-private-day-journey" in slugs
    assert "custom-svaneti-itinerary" not in slugs  # seeded as draft

    # destinations published
    dests = (await app_client.get("/api/public/destinations")).json()["items"]
    assert len(dests) >= 8

    # articles are drafts → none public
    arts = (await app_client.get("/api/public/articles")).json()["items"]
    assert arts == []

    # faqs grouped
    faqs = (await app_client.get("/api/public/faqs")).json()
    assert "groups" in faqs and faqs["groups"]

    # sample reviews visible in dev
    reviews = (await app_client.get("/api/public/reviews")).json()["items"]
    assert any(r.get("isSample") for r in reviews)


async def test_public_tours_include_resolved_media_fields(app_client, mock_db):
    await seed_run.run()
    resp = await app_client.get("/api/public/tours")
    items = resp.json()["items"]
    assert items
    first = items[0]
    assert "coverUrl" in first            # resolved single URL (str|null)
    assert "galleryUrls" in first          # resolved list
    assert isinstance(first["galleryUrls"], list)
    assert "coverMediaId" in first         # original id field preserved (additive)
    # seeded placeholders write real SVG files → resolvable URL
    assert first["coverUrl"] and first["coverUrl"].startswith("/media/")

    # detail endpoint too
    detail = await app_client.get(f"/api/public/tours/{first['slug']}")
    assert "coverUrl" in detail.json()


async def test_public_gallery_has_items_and_albums(app_client, mock_db):
    await seed_run.run()
    body = (await app_client.get("/api/public/gallery")).json()
    assert "albums" in body and "items" in body
    assert isinstance(body["items"], list) and body["items"]
    item = body["items"][0]
    for key in ("id", "url", "thumbUrl", "altText", "caption", "category", "width", "height"):
        assert key in item
    assert item["url"].startswith("/media/")


async def test_public_banner_and_settings_resolved_urls(app_client, mock_db):
    await seed_run.run()
    banners = (await app_client.get("/api/public/banners?path=/tours")).json()["items"]
    assert banners
    assert "desktopUrl" in banners[0] and "mobileUrl" in banners[0]

    settings_body = (await app_client.get("/api/public/settings")).json()
    for key in ("logoUrl", "ownerPortraitUrl", "faviconUrl"):
        assert key in settings_body


async def test_offer_effective_activation(app_client, mock_db):
    from datetime import timedelta

    from app.models.common import now_utc

    # active offer
    await mock_db.offers.insert_one({
        "_id": "o-active", "title": {"en": "Active"}, "status": "published",
        "publishAt": now_utc() - timedelta(days=1), "unpublishAt": None, "priority": 5,
    })
    # draft offer
    await mock_db.offers.insert_one({
        "_id": "o-draft", "title": {"en": "Draft"}, "status": "draft",
        "publishAt": None, "unpublishAt": None, "priority": 9,
    })
    items = (await app_client.get("/api/public/offers")).json()["items"]
    ids = {o["id"] for o in items}
    assert "o-active" in ids and "o-draft" not in ids


async def test_popup_eligibility_by_path_and_device(app_client, mock_db):
    await mock_db.popups.insert_one({
        "_id": "p1", "title": {"en": "P"}, "active": True,
        "pageTargets": ["/tours*"], "languageTargets": [], "deviceTargets": ["desktop"],
    })
    # matching path + device
    r = await app_client.get("/api/public/popups?path=/tours/x&device=desktop")
    assert any(p["id"] == "p1" for p in r.json()["items"])
    # wrong device excluded
    r2 = await app_client.get("/api/public/popups?path=/tours/x&device=mobile")
    assert all(p["id"] != "p1" for p in r2.json()["items"])
    # wrong path excluded
    r3 = await app_client.get("/api/public/popups?path=/about&device=desktop")
    assert all(p["id"] != "p1" for p in r3.json()["items"])


async def test_seo_route_shape(app_client, mock_db):
    await seed_run.run()
    r = await app_client.get(
        "/api/public/seo/route?path=/tours/ushguli-shkhara-private-day-journey"
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("title", "description", "canonical", "og", "jsonLd"):
        assert key in body
    assert isinstance(body["jsonLd"], list) and len(body["jsonLd"]) >= 2


async def test_sitemap_and_robots(app_client, mock_db):
    await seed_run.run()
    sm = await app_client.get("/sitemap.xml")
    assert sm.status_code == 200
    assert "<urlset" in sm.text
    assert "ushguli-shkhara-private-day-journey" in sm.text
    assert 'hreflang="ar"' in sm.text

    robots = await app_client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text
