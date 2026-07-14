"""Public serializers that resolve media IDs to public URLs.

All additions are additive: existing *MediaId fields are preserved and new
resolved *Url fields are added so the frontend can consume ready URLs while
falling back to gradient placeholders when a URL is null.
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from app.core.config import settings
from app.repositories.collections import media_repo

_VARIANT_PRIORITY = ("original", "hero", "card", "thumb")


def _variant_url(doc: dict) -> Optional[str]:
    variants = doc.get("variants") or {}
    for key in _VARIANT_PRIORITY:
        v = variants.get(key)
        if isinstance(v, dict) and v.get("url"):
            return v["url"]
    return None


def _thumb_url(doc: dict) -> Optional[str]:
    variants = doc.get("variants") or {}
    v = variants.get("thumb")
    if isinstance(v, dict) and v.get("url"):
        return v["url"]
    return None


def _local_file_exists(storage_key: str | None) -> bool:
    if not storage_key:
        return False
    base = os.path.abspath(settings.media_local_dir)
    full = os.path.abspath(os.path.join(base, storage_key.lstrip("/")))
    return full.startswith(base) and os.path.isfile(full)


def resolve_media_doc_url(doc: Optional[dict]) -> Optional[str]:
    """Resolve a media doc to a public URL string, or None (frontend placeholder)."""
    if not doc:
        return None
    # External videos keep their externalUrl.
    if doc.get("kind") == "external_video" or doc.get("provider") in ("youtube", "vimeo"):
        return doc.get("externalUrl")
    # A usable variant / original URL wins.
    url = _variant_url(doc)
    if url:
        return url
    # Local file present on disk → serve via the /media mount.
    if doc.get("provider") == "local" and _local_file_exists(doc.get("storageKey")):
        base = settings.media_public_base.rstrip("/")
        return f"{base}/{doc['storageKey'].lstrip('/')}"
    # Any other explicit external URL.
    if doc.get("externalUrl"):
        return doc["externalUrl"]
    return None


async def collect_media(ids: Iterable[Optional[str]]) -> dict[str, dict]:
    unique = list({i for i in ids if i})
    if not unique:
        return {}
    docs = await media_repo.list({"_id": {"$in": unique}}, page_size=len(unique) + 10)
    return {d["id"]: d for d in docs}


class MediaResolver:
    def __init__(self, docs_by_id: dict[str, dict]):
        self._by_id = docs_by_id

    def url(self, media_id: Optional[str]) -> Optional[str]:
        if not media_id:
            return None
        return resolve_media_doc_url(self._by_id.get(media_id))

    def urls(self, ids: Optional[list[str]]) -> list[str]:
        out: list[str] = []
        for mid in ids or []:
            u = self.url(mid)
            if u:
                out.append(u)
        return out

    def gallery_item(self, media_id: str, category: Optional[str]) -> Optional[dict]:
        doc = self._by_id.get(media_id)
        if not doc:
            return None
        url = resolve_media_doc_url(doc)
        if not url:
            return None
        return {
            "id": doc["id"],
            "url": url,
            "thumbUrl": _thumb_url(doc) or url,
            "altText": doc.get("altText") or {"en": ""},
            "caption": doc.get("caption") or {"en": ""},
            "location": doc.get("location"),
            "credit": doc.get("credit"),
            "category": category,
            "width": doc.get("width"),
            "height": doc.get("height"),
        }


# --- Per-type serializers ---------------------------------------------------
async def serialize_tours(docs: list[dict]) -> list[dict]:
    ids: list[Optional[str]] = []
    for d in docs:
        ids.append(d.get("coverMediaId"))
        ids.extend(d.get("galleryMediaIds") or [])
    r = MediaResolver(await collect_media(ids))
    return [
        {**d, "coverUrl": r.url(d.get("coverMediaId")),
         "galleryUrls": r.urls(d.get("galleryMediaIds"))}
        for d in docs
    ]


async def serialize_tour(doc: dict) -> dict:
    return (await serialize_tours([doc]))[0]


async def serialize_destinations(docs: list[dict]) -> list[dict]:
    ids: list[Optional[str]] = []
    for d in docs:
        ids.append(d.get("coverMediaId"))
        ids.extend(d.get("galleryMediaIds") or [])
    r = MediaResolver(await collect_media(ids))
    return [
        {**d, "coverUrl": r.url(d.get("coverMediaId")),
         "galleryUrls": r.urls(d.get("galleryMediaIds"))}
        for d in docs
    ]


async def serialize_destination(doc: dict) -> dict:
    return (await serialize_destinations([doc]))[0]


async def serialize_articles(docs: list[dict]) -> list[dict]:
    r = MediaResolver(await collect_media(d.get("coverMediaId") for d in docs))
    return [{**d, "coverUrl": r.url(d.get("coverMediaId"))} for d in docs]


async def serialize_article(doc: dict) -> dict:
    return (await serialize_articles([doc]))[0]


async def serialize_videos(docs: list[dict]) -> list[dict]:
    ids: list[Optional[str]] = []
    for d in docs:
        ids.append(d.get("posterMediaId"))
        ids.append(d.get("mediaId"))
    r = MediaResolver(await collect_media(ids))
    return [
        {**d, "posterUrl": r.url(d.get("posterMediaId")), "url": r.url(d.get("mediaId"))}
        for d in docs
    ]


async def serialize_banners(docs: list[dict]) -> list[dict]:
    ids: list[Optional[str]] = []
    for d in docs:
        ids.append(d.get("desktopMediaId"))
        ids.append(d.get("mobileMediaId"))
    r = MediaResolver(await collect_media(ids))
    return [
        {**d, "desktopUrl": r.url(d.get("desktopMediaId")),
         "mobileUrl": r.url(d.get("mobileMediaId"))}
        for d in docs
    ]


async def serialize_popups(docs: list[dict]) -> list[dict]:
    r = MediaResolver(await collect_media(d.get("mediaId") for d in docs))
    return [{**d, "mediaUrl": r.url(d.get("mediaId"))} for d in docs]


async def serialize_settings(doc: dict) -> dict:
    r = MediaResolver(
        await collect_media(
            [doc.get("logoMediaId"), doc.get("ownerPortraitMediaId"), doc.get("faviconMediaId")]
        )
    )
    return {
        **doc,
        "logoUrl": r.url(doc.get("logoMediaId")),
        "ownerPortraitUrl": r.url(doc.get("ownerPortraitMediaId")),
        "faviconUrl": r.url(doc.get("faviconMediaId")),
    }


async def serialize_gallery(albums: list[dict]) -> dict:
    ids: list[Optional[str]] = []
    for a in albums:
        ids.extend(a.get("mediaIds") or [])
        ids.append(a.get("coverMediaId"))
    resolver = MediaResolver(await collect_media(ids))
    items: list[dict] = []
    for a in albums:
        for mid in a.get("mediaIds") or []:
            item = resolver.gallery_item(mid, a.get("category"))
            if item:
                items.append(item)
    media_docs = list(resolver._by_id.values())
    return {"albums": albums, "media": media_docs, "items": items}
