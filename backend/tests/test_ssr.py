"""Optional SSR HTML shell with per-route SEO meta injection."""
import pytest

from app.seed import run as seed_run

pytestmark = pytest.mark.asyncio


async def test_ssr_disabled_by_default_returns_404(app_client, mock_db, monkeypatch):
    monkeypatch.delenv("SERVE_FRONTEND", raising=False)
    resp = await app_client.get("/en/tours")
    assert resp.status_code == 404


async def test_ssr_tour_route_injects_title_and_jsonld(app_client, mock_db, monkeypatch):
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", "/tmp/does-not-exist-svaneti")  # force built-in template
    await seed_run.run()

    resp = await app_client.get("/en/tours/ushguli-shkhara-private-day-journey")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text

    # <title> contains the tour name
    import re

    m = re.search(r"<title>(.*?)</title>", body, flags=re.IGNORECASE | re.DOTALL)
    assert m and "Ushguli and Shkhara" in m.group(1)

    # TouristTrip JSON-LD block present
    assert 'application/ld+json' in body
    assert '"@type": "TouristTrip"' in body or '"@type":"TouristTrip"' in body

    # canonical + hreflang alternates + OG tags present
    assert '<link rel="canonical"' in body
    assert 'hreflang="ar"' in body
    assert 'property="og:title"' in body


async def test_ssr_home_route_has_site_title(app_client, mock_db, monkeypatch):
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", "/tmp/does-not-exist-svaneti")
    await seed_run.run()

    resp = await app_client.get("/en")
    assert resp.status_code == 200
    import re

    m = re.search(r"<title>(.*?)</title>", resp.text, flags=re.IGNORECASE | re.DOTALL)
    assert m and "Svaneti with Georgie" in m.group(1)

    # excluded paths still 404 through the catch-all guard
    assert (await app_client.get("/sitemap.xml")).status_code == 200  # real handler wins


async def test_ssr_unknown_route_is_noindex(app_client, mock_db, monkeypatch):
    monkeypatch.setenv("SERVE_FRONTEND", "true")
    monkeypatch.setenv("FRONTEND_DIST_DIR", "/tmp/does-not-exist-svaneti")
    await seed_run.run()
    resp = await app_client.get("/en/this-route-does-not-exist")
    assert resp.status_code == 200
    assert 'content="noindex,nofollow"' in resp.text
