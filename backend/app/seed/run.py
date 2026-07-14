"""Idempotent seed of all content per DATA_MODEL. Run: python -m app.seed.run"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from app.core.config import settings
from app.core.db import close_client, ensure_indexes
from app.models.common import now_utc
from app.repositories.collections import (
    articles_repo,
    banners_repo,
    destinations_repo,
    faqs_repo,
    gallery_albums_repo,
    media_repo,
    navigation_repo,
    offers_repo,
    pages_repo,
    popups_repo,
    reviews_repo,
    site_settings_repo,
    tours_repo,
    videos_repo,
)
from app.seed import content as C

logger = logging.getLogger("app.seed")
NS = uuid.UUID("d3f0e2a1-0000-4000-8000-000000000000")


def sid(kind: str, key: str) -> str:
    return str(uuid.uuid5(NS, f"{kind}:{key}"))


def slugify(text: str) -> str:
    import re

    s = text.lower()
    s = s.replace("×", "x").replace("&", "and")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


async def _upsert(repo, doc_id: str, doc: dict) -> None:
    existing = await repo.get(doc_id)
    doc = {**doc, "id": doc_id}
    if existing:
        # Preserve createdAt / createdBy on update
        doc.setdefault("createdAt", existing.get("createdAt"))
        await repo.replace(doc_id, doc)
    else:
        await repo.create(doc)


def _envelope(published: bool) -> dict:
    now = now_utc()
    return {
        "status": "published" if published else "draft",
        "publishAt": now if published else None,
        "unpublishAt": None,
        "publishedAt": now if published else None,
        "createdAt": now,
        "updatedAt": now,
        "verificationStatus": "needs_verification",
        "isVerified": False,
    }


async def seed_settings() -> None:
    await _upsert(site_settings_repo, "settings", {
        "brandName": "Svaneti with Georgie",
        "tagline": C.L("Local journeys through Mestia, Ushguli and the mountains of Svaneti."),
        "aboutText": C.L("Placeholder about text — replace with Georgie's verified bio."),
        "contact": {"phone": None, "whatsapp": None, "email": None, "region": "Svaneti, Georgia"},
        "socials": [],
        "supportedLanguages": ["en", "ka", "ar"],
        "defaultLanguage": "en",
        "currency": "GEL",
        "timezone": "Asia/Tbilisi",
        "analytics": {"gaId": None, "gscVerification": None, "metaPixelId": None},
        "cookieNotice": C.L("This site uses cookies. Placeholder notice."),
        "emergencyNotice": {"enabled": False, "text": C.L("")},
        "globalCta": {"label": C.L("Plan your trip"), "href": "/contact"},
        "seoDefaults": {
            "titlePattern": "%s · Svaneti with Georgie",
            "description": C.L("Guided journeys through Svaneti — Mestia, Ushguli and beyond."),
            "canonicalBaseUrl": settings.public_site_url,
            "robots": "index,follow",
        },
        "updatedAt": now_utc(),
    })


async def seed_navigation() -> None:
    await _upsert(navigation_repo, "navigation", {
        "mainMenu": [
            {"label": C.L("Tours"), "href": "/tours"},
            {"label": C.L("Destinations"), "href": "/destinations"},
            {"label": C.L("Experiences"), "href": "/experiences"},
            {"label": C.L("Travel Guide"), "href": "/travel-guide"},
            {"label": C.L("Gallery"), "href": "/gallery"},
            {"label": C.L("About Georgie"), "href": "/about-georgie"},
            {"label": C.L("Contact"), "href": "/contact"},
        ],
        "footerGroups": [
            {"title": C.L("Explore"), "links": [
                {"label": C.L("Tours"), "href": "/tours"},
                {"label": C.L("Destinations"), "href": "/destinations"},
                {"label": C.L("Experiences"), "href": "/experiences"},
                {"label": C.L("Offers"), "href": "/offers"},
            ]},
            {"title": C.L("Discover"), "links": [
                {"label": C.L("Travel Guide"), "href": "/travel-guide"},
                {"label": C.L("Gallery"), "href": "/gallery"},
                {"label": C.L("Videos"), "href": "/videos"},
                {"label": C.L("Reviews"), "href": "/reviews"},
            ]},
            {"title": C.L("Company"), "links": [
                {"label": C.L("About Georgie"), "href": "/about-georgie"},
                {"label": C.L("Plan Your Trip"), "href": "/plan-your-trip"},
                {"label": C.L("Contact"), "href": "/contact"},
            ]},
        ],
        "socialLinks": [],
        "legalLinks": [
            {"label": C.L("Privacy"), "href": "/privacy"},
            {"label": C.L("Terms"), "href": "/terms"},
        ],
        "ctaButton": {"label": C.L("Plan Your Trip"), "href": "/plan-your-trip"},
    })


async def seed_home_page() -> None:
    await _upsert(pages_repo, sid("page", "home"), {
        "key": "home",
        "title": "Home",
        "sections": [
            {"id": sid("sec", "home-hero"), "type": "hero", "hidden": False, "order": 1,
             "data": {
                 "heading": C.L("Svaneti, Guided by a Local"),
                 "subheading": C.L(
                     "Private, small-group and custom journeys through Mestia, Ushguli "
                     "and the high Caucasus — planned and led by a local guide."),
                 "badge": C.L("Mestia · Ushguli · Svaneti"),
                 "primaryCta": {"label": C.L("Explore Tours"), "href": "/tours"},
                 "secondaryCta": {"label": C.L("Chat with Georgie"), "href": "/inquiry"},
                 "overlayIntensity": 0.5,
                 "mediaUrl": None,
             }},
            {"id": sid("sec", "home-tours"), "type": "tourGrid", "hidden": False, "order": 2,
             "data": {"title": C.L("Featured tours"), "featuredOnly": True}},
            {"id": sid("sec", "home-dest"), "type": "destinationGrid", "hidden": False, "order": 3,
             "data": {"title": C.L("Destinations")}},
            {"id": sid("sec", "home-faq"), "type": "faq", "hidden": False, "order": 4,
             "data": {"title": C.L("Frequently asked questions")}},
            {"id": sid("sec", "home-cta"), "type": "cta", "hidden": False, "order": 5,
             "data": {"title": C.L("Plan your journey"),
                      "cta": {"label": C.L("Plan Your Trip"), "href": "/plan-your-trip"}}},
        ],
        "updatedAt": now_utc(),
    })


_GRADIENTS = [
    ("#2b5876", "#4e4376"), ("#134e5e", "#71b280"), ("#3a1c71", "#d76d77"),
    ("#1f4037", "#99f2c8"), ("#0f2027", "#2c5364"), ("#42275a", "#734b6d"),
]


def _placeholder_svg(index: int) -> bytes:
    c1, c2 = _GRADIENTS[(index - 1) % len(_GRADIENTS)]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" '
        f'viewBox="0 0 1600 900"><defs><linearGradient id="g" x1="0" y1="0" '
        f'x2="1" y2="1"><stop offset="0" stop-color="{c1}"/>'
        f'<stop offset="1" stop-color="{c2}"/></linearGradient></defs>'
        f'<rect width="1600" height="900" fill="url(#g)"/>'
        f'<text x="50%" y="50%" fill="#ffffff" opacity="0.6" font-size="48" '
        f'font-family="sans-serif" text-anchor="middle" dominant-baseline="middle">'
        f'Placeholder {index}</text></svg>'
    )
    return svg.encode("utf-8")


async def seed_media_placeholders() -> list[str]:
    """Write real SVG gradient placeholder files so URLs resolve via /media."""
    from app.services.media import get_provider

    provider = get_provider()
    ids = []
    for i in range(1, 7):
        mid = sid("media", f"placeholder-{i}")
        storage_key = f"placeholders/placeholder-{i}.svg"
        url = storage_key
        try:
            url = provider.save_bytes(storage_key, _placeholder_svg(i))
        except Exception as exc:  # noqa: BLE001 - provider stubs (cloudinary/s3)
            logger.warning("Could not write placeholder %s: %s", i, exc)
            url = f"/media/{storage_key}"
        await _upsert(media_repo, mid, {
            "kind": "image", "provider": "local",
            "storageKey": storage_key,
            "originalFilename": f"placeholder-{i}.svg", "mimeType": "image/svg+xml",
            "width": 1600, "height": 900,
            "altText": C.L(f"Placeholder image {i}"),
            "caption": C.L("Placeholder — replace with a licensed photo."),
            "tags": ["placeholder"], "variants": {
                "thumb": {"url": url, "w": 200, "h": 150},
                "card": {"url": url, "w": 600, "h": 400},
                "hero": {"url": url, "w": 1600, "h": 900},
                "original": {"url": url, "w": 1600, "h": 900},
            },
            "usageRefs": [], "archived": False, "createdAt": now_utc(),
        })
        ids.append(mid)
    return ids


async def seed_destinations(media_ids: list[str]) -> dict[str, str]:
    mapping = {}
    for order, (slug, name, (lat, lng), alt) in enumerate(C.DESTINATIONS, start=1):
        did = sid("destination", slug)
        mapping[slug] = did
        await _upsert(destinations_repo, did, {
            **_envelope(True),
            "slug": slug,
            "name": C.L(name),
            "intro": C.L(f"{name} is a placeholder destination in Svaneti."),
            "description": C.L(f"<p>Placeholder description of {name}. Replace with verified copy.</p>"),
            "coordinates": {"lat": lat, "lng": lng},
            "altitudeM": alt,
            "bestSeasons": ["summer", "autumn"],
            "galleryMediaIds": media_ids[:2],
            "videoIds": [],
            "relatedTourIds": [],
            "culturalNotes": C.L("Placeholder cultural notes."),
            "practicalAdvice": C.L("Placeholder practical advice."),
            "accessibilityInfo": C.L("Placeholder accessibility info."),
            "safetyNotice": C.L("Placeholder safety notice."),
            "relatedArticleIds": [],
            "displayOrder": order,
            "seo": {"noindex": False},
        })
    return mapping


async def seed_tours(media_ids: list[str], dest_map: dict[str, str]) -> None:
    for t in C.TOURS:
        tid = sid("tour", t["slug"])
        doc = {**C.TOUR_DEFAULTS, **_envelope(t["publish"])}
        for k, v in t.items():
            if k == "publish":
                continue
            doc[k] = v
        doc["coverMediaId"] = media_ids[0]
        doc["galleryMediaIds"] = media_ids[:3]
        doc["destinationIds"] = list(dest_map.values())[:2]
        doc["seo"] = {"noindex": False}
        await _upsert(tours_repo, tid, doc)


async def seed_articles() -> None:
    for title in C.ARTICLES:
        slug = slugify(title)
        aid = sid("article", slug)
        await _upsert(articles_repo, aid, {
            **_envelope(False),  # drafts
            "slug": slug,
            "title": C.L(title),
            "excerpt": C.L(f"Placeholder excerpt for '{title}'."),
            "body": C.L(f"<p>Draft placeholder body for '{title}'. Needs verification.</p>"),
            "author": "Georgie (placeholder)",
            "categories": ["guide"],
            "tags": ["svaneti", "mestia"],
            "readingMinutes": 4,
            "seo": {"noindex": True},
        })


async def seed_faqs() -> None:
    for order, (q, cat, a) in enumerate(C.FAQS, start=1):
        fid = sid("faq", slugify(q))
        await _upsert(faqs_repo, fid, {
            "question": C.L(q), "answer": C.L(a), "category": cat,
            "displayOrder": order, "published": True,
        })


async def seed_gallery(media_ids: list[str]) -> None:
    for slug, title in [("svaneti-highlights", "Svaneti Highlights"),
                        ("mestia-life", "Mestia Life")]:
        gid = sid("album", slug)
        await _upsert(gallery_albums_repo, gid, {
            "title": C.L(title), "slug": slug, "category": "landscape",
            "coverMediaId": media_ids[0], "mediaIds": media_ids[:4],
            "displayOrder": 1, "published": True,
            "createdAt": now_utc(), "updatedAt": now_utc(),
        })


async def seed_videos() -> None:
    for slug, title, url in [
        ("intro-to-svaneti", "Introduction to Svaneti",
         "https://www.youtube.com/watch?v=placeholder1"),
        ("winter-in-mestia", "Winter in Mestia",
         "https://www.youtube.com/watch?v=placeholder2"),
    ]:
        vid = sid("video", slug)
        await _upsert(videos_repo, vid, {
            "title": C.L(title), "caption": C.L("Placeholder video — replace URL."),
            "kind": "youtube", "externalUrl": url, "featured": True,
            "displayOrder": 1, "published": True,
            "createdAt": now_utc(), "updatedAt": now_utc(),
        })


async def seed_banner_offer_popup(media_ids: list[str]) -> None:
    now = now_utc()
    await _upsert(banners_repo, sid("banner", "welcome"), {
        "name": "Welcome announcement", "placement": "announcement",
        "title": C.L("Planning a trip to Svaneti?"),
        "subtitle": C.L("Placeholder banner — edit in the dashboard."),
        "desktopMediaId": media_ids[0], "mobileMediaId": media_ids[0],
        "overlayIntensity": 0.4, "cta": {"label": C.L("Contact"), "href": "/contact"},
        "pageTargets": ["*"], "languageTargets": [], "priority": 10, "active": True,
        "startAt": None, "endAt": None, "createdAt": now, "updatedAt": now,
    })
    # a scheduled (future-window) offer
    await _upsert(offers_repo, sid("offer", "early-season"), {
        **_envelope(True),
        "title": C.L("Early-season enquiry offer (sample)"),
        "description": C.L("Placeholder offer — no real discount is implied."),
        "discountType": "display", "terms": C.L("Sample terms; needs verification."),
        "relatedTourIds": [], "featured": True, "priority": 5, "languageTargets": [],
        "startAt": now + timedelta(days=7), "endAt": now + timedelta(days=60),
    })
    await _upsert(popups_repo, sid("popup", "newsletter"), {
        "title": C.L("Stay in touch"),
        "body": C.L("Placeholder popup content."),
        "mediaId": media_ids[0], "cta": {"label": C.L("Contact"), "href": "/contact"},
        "startAt": None, "endAt": None, "pageTargets": ["*"], "languageTargets": [],
        "deviceTargets": ["desktop", "mobile"], "delaySeconds": 8,
        "scrollDepthPercent": 40, "exitIntent": False, "audience": "new",
        "frequency": "once_session", "dismissible": True, "priority": 1,
        "active": True, "createdAt": now_utc(), "updatedAt": now_utc(),
    })


async def seed_reviews() -> None:
    if not settings.sample_reviews_enabled:
        logger.info("Sample reviews disabled (prod or flag off) — skipping.")
        return
    for i, (name, country, rating, text) in enumerate(C.SAMPLE_REVIEWS, start=1):
        rid = sid("review", f"sample-{i}")
        await _upsert(reviews_repo, rid, {
            "reviewerName": name, "country": country, "rating": rating, "text": text,
            "source": "manual", "permissionStatus": "unknown", "featured": i == 1,
            "published": True, "isSample": True, "createdAt": now_utc(),
        })


async def ensure_dev_owner() -> None:
    """Dev-only owner bootstrap for e2e (SEED_ON_STARTUP). Never in production.

    Uses ADMIN_SEED_EMAIL / ADMIN_SEED_PASSWORD with forcePasswordChange=False so a
    test can log straight into the admin. Production must use scripts/create_admin.
    The password is never printed.
    """
    if settings.is_production:
        return
    from app.core.security import hash_password
    from app.models.common import new_id
    from app.repositories.collections import users_repo

    email = settings.admin_seed_email.lower().strip()
    password = settings.admin_seed_password
    if not email or not password:
        return
    existing = await users_repo.get_by(email=email)
    if existing:
        await users_repo.update(existing["id"], {
            "passwordHash": hash_password(password),
            "role": "owner", "isActive": True, "forcePasswordChange": False,
            "updatedAt": now_utc(),
        })
    else:
        await users_repo.create({
            "id": new_id(), "email": email, "passwordHash": hash_password(password),
            "role": "owner", "name": "Owner", "isActive": True,
            "forcePasswordChange": False, "failedLoginCount": 0,
            "createdAt": now_utc(), "updatedAt": now_utc(),
        })
    logger.info("Dev owner ensured: %s", email)


async def run() -> None:
    logger.info("Seeding Svaneti content (env=%s)...", settings.app_env)
    try:
        await ensure_indexes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_indexes: %s", exc)
    await seed_settings()
    await seed_navigation()
    await seed_home_page()
    media_ids = await seed_media_placeholders()
    dest_map = await seed_destinations(media_ids)
    await seed_tours(media_ids, dest_map)
    await seed_articles()
    await seed_faqs()
    await seed_gallery(media_ids)
    await seed_videos()
    await seed_banner_offer_popup(media_ids)
    await seed_reviews()
    logger.info("Seed complete.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    async def _main():
        try:
            await run()
        finally:
            await close_client()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
