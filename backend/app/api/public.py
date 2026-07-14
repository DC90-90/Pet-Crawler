"""Public API — anonymous, effective-published content only."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.helpers import apply_etag, client_ip, lang_param, pagination
from app.core.config import settings
from app.core.rate_limit import enforce
from app.core.security import verify_preview_token
from app.models.common import is_effectively_published
from app.repositories.collections import (
    RESOURCE_REPOS,
    articles_repo,
    banners_repo,
    destinations_repo,
    faqs_repo,
    gallery_albums_repo,
    navigation_repo,
    offers_repo,
    pages_repo,
    popups_repo,
    reviews_repo,
    site_settings_repo,
    tours_repo,
    videos_repo,
)
from app.schemas.dto import InquiryCreateRequest, RecommendRequest
from app.services import inquiry as inquiry_service
from app.services import seo as seo_service
from app.services import serializers
from app.services.content_version import get_version

router = APIRouter(prefix="/api/public", tags=["public"])


async def _etag_or_304(request: Request, response: Response) -> bool:
    """Apply ETag header; return True if a 304 should be returned."""
    return (await apply_etag(request, response)) == "not-modified"


@router.get("/content-version")
async def content_version():
    return await get_version()


@router.get("/settings")
async def public_settings(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    doc = await site_settings_repo.get("settings") or {}
    doc.pop("updatedBy", None)
    return await serializers.serialize_settings(doc)


@router.get("/navigation")
async def public_navigation(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    return await navigation_repo.get("navigation") or {}


@router.get("/pages/{key}")
async def public_page(key: str, request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    from app.models.common import now_utc

    page = await pages_repo.get_by(key=key)
    if not page:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found")
    now = now_utc()
    visible = []
    for section in sorted(page.get("sections", []), key=lambda s: s.get("order", 0)):
        if section.get("hidden"):
            continue
        start = section.get("startAt")
        end = section.get("endAt")
        if start and _aware(start) > now:
            continue
        if end and _aware(end) <= now:
            continue
        visible.append(section)
    page = dict(page)
    page["sections"] = visible
    return page


def _aware(dt):
    from datetime import timezone

    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.get("/tours")
async def public_tours(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    qp = request.query_params
    page, size = pagination(request)
    extra: dict = {}
    if qp.get("destination"):
        extra["destinationIds"] = qp["destination"]
    if qp.get("season"):
        extra["seasons"] = qp["season"]
    if qp.get("difficulty"):
        extra["difficulty"] = qp["difficulty"]
    if qp.get("family") == "true":
        extra["familyFriendly"] = True
    if qp.get("lowWalking") == "true":
        extra["lowWalking"] = True
    if qp.get("winter") == "true":
        extra["winter"] = True
    if qp.get("private") == "true":
        extra["tourType"] = "private"
    if qp.get("q"):
        extra["slug"] = {"$regex": qp["q"], "$options": "i"}

    sort_key = qp.get("sort", "displayOrder")
    sort_map = {
        "displayOrder": [("featured", -1), ("displayOrder", 1)],
        "newest": [("publishedAt", -1)],
        "name": [("slug", 1)],
    }
    sort = sort_map.get(sort_key, sort_map["displayOrder"])
    items = await tours_repo.list_public(extra or None, sort=sort, page=page, page_size=size)
    items = await serializers.serialize_tours(items)
    return {"items": items, "page": page, "pageSize": size}


@router.get("/tours/{slug}")
async def public_tour(slug: str, request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    doc = await tours_repo.get_public_by_slug(slug)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Tour not found")
    return await serializers.serialize_tour(doc)


@router.post("/tours/recommend")
async def recommend(body: RecommendRequest):
    tours = await tours_repo.list_public(page_size=500)

    def score(t: dict) -> int:
        s = 0
        if body.difficulty and t.get("difficulty") == body.difficulty:
            s += 3
        if body.family and t.get("familyFriendly"):
            s += 3
        if body.lowWalking and t.get("lowWalking"):
            s += 3
        if body.winter and t.get("winter"):
            s += 3
        if body.season and body.season in (t.get("seasons") or []):
            s += 2
        if body.durationDays and t.get("durationDays"):
            if abs((t.get("durationDays") or 0) - body.durationDays) <= 1:
                s += 2
        if body.interests:
            overlap = set(body.interests) & set(t.get("categories") or [])
            s += len(overlap)
        if t.get("featured"):
            s += 1
        return s

    ranked = sorted(tours, key=lambda t: (score(t), t.get("featured", False)), reverse=True)
    return {"items": await serializers.serialize_tours(ranked[: body.limit])}


@router.get("/destinations")
async def public_destinations(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    page, size = pagination(request)
    items = await destinations_repo.list_public(
        sort=[("displayOrder", 1)], page=page, page_size=size
    )
    items = await serializers.serialize_destinations(items)
    return {"items": items, "page": page, "pageSize": size}


@router.get("/destinations/{slug}")
async def public_destination(slug: str, request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    doc = await destinations_repo.get_public_by_slug(slug)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Destination not found")
    return await serializers.serialize_destination(doc)


@router.get("/articles")
async def public_articles(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    page, size = pagination(request)
    items = await articles_repo.list_public(sort=[("publishedAt", -1)], page=page, page_size=size)
    items = await serializers.serialize_articles(items)
    return {"items": items, "page": page, "pageSize": size}


@router.get("/articles/{slug}")
async def public_article(slug: str, request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    doc = await articles_repo.get_public_by_slug(slug)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article not found")
    return await serializers.serialize_article(doc)


@router.get("/gallery")
async def public_gallery(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    albums = await gallery_albums_repo.list(
        {"published": True}, sort=[("displayOrder", 1)], page_size=200
    )
    return await serializers.serialize_gallery(albums)


@router.get("/videos")
async def public_videos(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    items = await videos_repo.list(
        {"published": True}, sort=[("featured", -1), ("displayOrder", 1)], page_size=200
    )
    items = await serializers.serialize_videos(items)
    return {"items": items}


@router.get("/offers")
async def public_offers(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    items = await offers_repo.list_public(sort=[("priority", -1)], page_size=200)
    return {"items": items}


@router.get("/banners")
async def public_banners(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    path = request.query_params.get("path", "/")
    lang = lang_param(request)
    now_active = await banners_repo.list({"active": True}, sort=[("priority", -1)], page_size=200)
    result = [b for b in now_active if _target_match(b, path, lang, None, time_windowed=True)]
    result = await serializers.serialize_banners(result)
    return {"items": result}


@router.get("/popups")
async def public_popups(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    path = request.query_params.get("path", "/")
    lang = lang_param(request)
    device = request.query_params.get("device")
    popups = await popups_repo.list({"active": True}, sort=[("priority", -1)], page_size=200)
    result = [p for p in popups if _target_match(p, path, lang, device, time_windowed=True)]
    result = await serializers.serialize_popups(result)
    return {"items": result}


def _target_match(doc: dict, path: str, lang: str, device: str | None, *, time_windowed: bool) -> bool:
    from app.models.common import now_utc

    if time_windowed:
        now = now_utc()
        start, end = doc.get("startAt"), doc.get("endAt")
        if start and _aware(start) > now:
            return False
        if end and _aware(end) <= now:
            return False
    targets = doc.get("pageTargets") or ["*"]
    if "*" not in targets and not any(_glob_match(t, path) for t in targets):
        return False
    langs = doc.get("languageTargets") or []
    if langs and lang not in langs:
        return False
    devices = doc.get("deviceTargets")
    if device and devices and device not in devices:
        return False
    return True


def _glob_match(pattern: str, path: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, pattern)


@router.get("/reviews")
async def public_reviews(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    query: dict = {"published": True}
    if settings.is_production:
        query["isSample"] = {"$ne": True}
    items = await reviews_repo.list(query, sort=[("createdAt", -1)], page_size=200)
    return {"items": items}


@router.get("/faqs")
async def public_faqs(request: Request, response: Response):
    if await _etag_or_304(request, response):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=dict(response.headers))
    items = await faqs_repo.list({"published": True}, sort=[("displayOrder", 1)], page_size=500)
    grouped: dict[str, list] = {}
    for f in items:
        grouped.setdefault(f.get("category", "general"), []).append(f)
    return {"groups": grouped}


@router.post("/inquiries", status_code=status.HTTP_201_CREATED)
async def create_inquiry(request: Request, body: InquiryCreateRequest):
    enforce(request, "inquiry", 5, 60)
    if not body.consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Consent is required")
    created = await inquiry_service.create_inquiry(body.model_dump(), client_ip(request))
    return {"ok": True, "id": created["id"]}


@router.get("/seo/route")
async def seo_route(request: Request):
    path = request.query_params.get("path", "/")
    lang = lang_param(request)
    return await seo_service.route_seo(path, lang)


@router.get("/preview/{resource}/{doc_id}")
async def preview(resource: str, doc_id: str, request: Request):
    token = request.query_params.get("token", "")
    if not verify_preview_token(token, resource, doc_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid preview token")
    repo = RESOURCE_REPOS.get(resource)
    if not repo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown resource")
    doc = await repo.get(doc_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found")
    doc = dict(doc)
    doc["_preview"] = True
    doc["_effectivePublished"] = is_effectively_published(doc)
    return doc
