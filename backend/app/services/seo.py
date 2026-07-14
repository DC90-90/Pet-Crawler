"""SEO composition: route payload, JSON-LD, sitemap, robots."""
from __future__ import annotations

from typing import Any, Optional

from app.core.config import settings
from app.models.common import is_effectively_published
from app.repositories.collections import (
    articles_repo,
    destinations_repo,
    site_settings_repo,
    tours_repo,
)


def _loc(value: Any, lang: str = "en") -> str:
    if isinstance(value, dict):
        return value.get(lang) or value.get("en") or ""
    return value or ""


async def _settings() -> dict:
    return await site_settings_repo.get("settings") or {}


def _canonical_base(st: dict) -> str:
    seo = st.get("seoDefaults", {}) or {}
    return (seo.get("canonicalBaseUrl") or settings.public_site_url or "").rstrip("/")


def _organization_jsonld(st: dict, base: str) -> dict:
    contact = st.get("contact", {}) or {}
    return {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": st.get("brandName", "Svaneti with Georgie"),
        "url": base or None,
        "email": contact.get("email"),
        "telephone": contact.get("phone"),
        "areaServed": contact.get("region") or "Svaneti, Georgia",
    }


def _breadcrumb_jsonld(path: str, base: str) -> dict:
    parts = [p for p in path.strip("/").split("/") if p]
    items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": base or "/"}]
    acc = base
    for i, part in enumerate(parts, start=2):
        acc = f"{acc}/{part}"
        items.append({"@type": "ListItem", "position": i, "name": part.replace("-", " ").title(),
                      "item": acc})
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": items}


async def _match_entity(path: str) -> tuple[Optional[str], Optional[dict]]:
    """Return (type, doc) for a published entity matching the path, else (None, None)."""
    segments = [s for s in path.strip("/").split("/") if s]
    if len(segments) >= 2:
        prefix, slug = segments[0], segments[1]
        repo_map = {
            "tours": ("tour", tours_repo),
            "destinations": ("destination", destinations_repo),
            "articles": ("article", articles_repo),
            "guide": ("article", articles_repo),
        }
        if prefix in repo_map:
            etype, repo = repo_map[prefix]
            doc = await repo.get_by(slug=slug)
            if doc and is_effectively_published(doc):
                return etype, doc
    return None, None


def _entity_jsonld(etype: str, doc: dict, base: str, lang: str) -> Optional[dict]:
    if etype == "tour":
        return {
            "@context": "https://schema.org",
            "@type": "TouristTrip",
            "name": _loc(doc.get("name"), lang),
            "description": _loc(doc.get("shortDescription"), lang),
        }
    if etype == "article":
        return {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": _loc(doc.get("title"), lang),
            "description": _loc(doc.get("excerpt"), lang),
        }
    if etype == "destination":
        return {
            "@context": "https://schema.org",
            "@type": "TouristDestination",
            "name": _loc(doc.get("name"), lang),
            "description": _loc(doc.get("intro"), lang),
        }
    return None


async def route_seo(path: str, lang: str = "en") -> dict:
    st = await _settings()
    seo_defaults = st.get("seoDefaults", {}) or {}
    base = _canonical_base(st)
    title_pattern = seo_defaults.get("titlePattern") or "%s · Svaneti with Georgie"
    brand = st.get("brandName", "Svaneti with Georgie")
    default_desc = _loc(seo_defaults.get("description"), lang)

    etype, doc = await _match_entity(path)
    json_ld: list[dict] = [_organization_jsonld(st, base), _breadcrumb_jsonld(path, base)]

    if doc:
        seo_block = doc.get("seo", {}) or {}
        entity_title = _loc(seo_block.get("title"), lang) or _loc(
            doc.get("name") or doc.get("title"), lang
        )
        entity_desc = _loc(seo_block.get("description"), lang) or _loc(
            doc.get("shortDescription") or doc.get("excerpt") or doc.get("intro"), lang
        )
        title = title_pattern.replace("%s", entity_title) if "%s" in title_pattern else entity_title
        description = entity_desc or default_desc
        canonical = f"{base}{seo_block.get('canonicalPath') or path}"
        noindex = bool(seo_block.get("noindex"))
        ent_ld = _entity_jsonld(etype, doc, base, lang)
        if ent_ld:
            if etype == "article":
                pass
            json_ld.append(ent_ld)
    else:
        title = title_pattern.replace("%s", brand) if "%s" in title_pattern else brand
        description = default_desc
        canonical = f"{base}{path}"
        noindex = False

    og = {
        "title": title,
        "description": description,
        "type": "website",
        "url": canonical,
        "siteName": brand,
    }
    return {
        "title": title,
        "description": description,
        "canonical": canonical,
        "robots": "noindex,nofollow" if noindex else (seo_defaults.get("robots") or "index,follow"),
        "og": og,
        "jsonLd": json_ld,
    }


async def build_sitemap() -> str:
    st = await _settings()
    base = _canonical_base(st) or settings.public_site_url.rstrip("/")
    langs = st.get("supportedLanguages") or ["en", "ka", "ar"]

    urls: list[str] = ["/", "/tours", "/destinations", "/guide", "/gallery", "/about", "/contact"]
    entries: list[tuple[str, dict]] = [(u, {}) for u in urls]

    for repo, prefix in ((tours_repo, "tours"), (destinations_repo, "destinations"),
                         (articles_repo, "guide")):
        docs = await repo.list_public(page_size=1000)
        for d in docs:
            entries.append((f"/{prefix}/{d['slug']}", d))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
    )
    for path, _ in entries:
        lines.append("  <url>")
        lines.append(f"    <loc>{base}{path}</loc>")
        for lang in langs:
            hreflang = lang
            href = f"{base}{path}" if lang == "en" else f"{base}/{lang}{path}"
            lines.append(
                f'    <xhtml:link rel="alternate" hreflang="{hreflang}" href="{href}"/>'
            )
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines)


def build_robots() -> str:
    base = settings.public_site_url.rstrip("/")
    if settings.is_production:
        body = ["User-agent: *", "Allow: /", "Disallow: /admin", "Disallow: /api/admin"]
    else:
        body = ["User-agent: *", "Disallow: /"]
    body.append(f"Sitemap: {base}/sitemap.xml")
    return "\n".join(body) + "\n"
