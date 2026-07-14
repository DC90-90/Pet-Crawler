"""Optional SSR HTML shell: inject per-route SEO meta into a base template.

Guarded at the router level by SERVE_FRONTEND. Reuses the same logic behind
GET /api/public/seo/route so server-rendered <head> matches the API payload.
"""
from __future__ import annotations

import html
import json
import os
import re

from app.core.config import settings
from app.services.seo import route_seo

_LANG_PREFIX = re.compile(r"^/(en|ka|ar)(?=/|$)")

BUILTIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Svaneti with Georgie</title>
<meta name="description" content="" />
</head>
<body>
<div id="root"></div>
<script type="module" src="/src/main.tsx"></script>
</body>
</html>
"""


def strip_lang_prefix(path: str) -> str:
    stripped = _LANG_PREFIX.sub("", path or "/")
    return stripped or "/"


def detect_lang(path: str) -> str:
    m = _LANG_PREFIX.match(path or "")
    return m.group(1) if m else "en"


def load_shell() -> str:
    dist_dir = os.getenv("FRONTEND_DIST_DIR", "./frontend/dist")
    index_path = os.path.abspath(os.path.join(dist_dir, "index.html"))
    try:
        if os.path.isfile(index_path):
            with open(index_path, encoding="utf-8") as fh:
                return fh.read()
    except OSError:
        pass
    return BUILTIN_TEMPLATE


def _canonical_base() -> str:
    return (settings.public_site_url or "").rstrip("/")


def _esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _build_head_tags(seo: dict, path: str, noindex: bool) -> str:
    base = _canonical_base()
    og = seo.get("og", {}) or {}
    tags: list[str] = []

    tags.append(f'<link rel="canonical" href="{_esc(seo.get("canonical"))}" />')
    if noindex:
        tags.append('<meta name="robots" content="noindex,nofollow" />')
    else:
        tags.append(f'<meta name="robots" content="{_esc(seo.get("robots") or "index,follow")}" />')

    # hreflang alternates for en/ka/ar
    clean = strip_lang_prefix(path)
    for lang in ("en", "ka", "ar"):
        href = f"{base}{clean}" if lang == "en" else f"{base}/{lang}{clean}"
        tags.append(f'<link rel="alternate" hreflang="{lang}" href="{_esc(href)}" />')
    tags.append(f'<link rel="alternate" hreflang="x-default" href="{_esc(base + clean)}" />')

    # Open Graph
    tags.append(f'<meta property="og:title" content="{_esc(og.get("title") or seo.get("title"))}" />')
    tags.append(
        '<meta property="og:description" '
        f'content="{_esc(og.get("description") or seo.get("description"))}" />'
    )
    tags.append(f'<meta property="og:type" content="{_esc(og.get("type") or "website")}" />')
    tags.append(f'<meta property="og:url" content="{_esc(og.get("url") or seo.get("canonical"))}" />')
    tags.append(f'<meta property="og:site_name" content="{_esc(og.get("siteName"))}" />')
    og_image = og.get("image") or seo.get("ogImage")
    if og_image:
        tags.append(f'<meta property="og:image" content="{_esc(og_image)}" />')

    # Twitter
    tags.append('<meta name="twitter:card" content="summary_large_image" />')
    tags.append(f'<meta name="twitter:title" content="{_esc(seo.get("title"))}" />')
    tags.append(f'<meta name="twitter:description" content="{_esc(seo.get("description"))}" />')
    if og_image:
        tags.append(f'<meta name="twitter:image" content="{_esc(og_image)}" />')

    # JSON-LD (escape </script> to avoid breaking out)
    for entry in seo.get("jsonLd", []) or []:
        payload = json.dumps(entry, ensure_ascii=False).replace("</", "<\\/")
        tags.append(f'<script type="application/ld+json">{payload}</script>')

    return "\n".join(tags)


def _replace_title(shell: str, title: str) -> str:
    new_title = f"<title>{_esc(title)}</title>"
    if re.search(r"<title>.*?</title>", shell, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(r"<title>.*?</title>", new_title, shell, count=1,
                      flags=re.IGNORECASE | re.DOTALL)
    return shell.replace("</head>", f"{new_title}\n</head>", 1)


def _replace_description(shell: str, description: str) -> str:
    new_meta = f'<meta name="description" content="{_esc(description)}" />'
    pattern = r'<meta\s+name=["\']description["\'][^>]*>'
    if re.search(pattern, shell, flags=re.IGNORECASE):
        return re.sub(pattern, new_meta, shell, count=1, flags=re.IGNORECASE)
    return shell.replace("</head>", f"{new_meta}\n</head>", 1)


async def render_shell(path: str) -> str:
    clean = strip_lang_prefix(path)
    lang = detect_lang(path)
    seo = await route_seo(clean, lang)

    # Unknown/unmatched routes: generic title + noindex (SPA handles 404 client-side).
    known_prefixes = (
        "/", "/tours", "/destinations", "/experiences", "/about-georgie", "/gallery",
        "/videos", "/offers", "/travel-guide", "/reviews", "/plan-your-trip", "/contact",
        "/inquiry", "/privacy", "/terms",
    )
    noindex = not (clean in known_prefixes or any(
        clean.startswith(p + "/") for p in known_prefixes if p != "/"
    ))

    shell = load_shell()
    shell = _replace_title(shell, seo.get("title") or "Svaneti with Georgie")
    shell = _replace_description(shell, seo.get("description") or "")
    head_tags = _build_head_tags(seo, path, noindex)
    shell = shell.replace("</head>", f"{head_tags}\n</head>", 1)
    return shell
