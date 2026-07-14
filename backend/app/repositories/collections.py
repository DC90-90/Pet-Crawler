"""Concrete repository instances per collection + a resource registry."""
from __future__ import annotations

from app.repositories.base import BaseRepository

# Publishing-envelope collections
tours_repo = BaseRepository("tours", publishable=True)
destinations_repo = BaseRepository("destinations", publishable=True)
articles_repo = BaseRepository("articles", publishable=True)
offers_repo = BaseRepository("offers", publishable=True)

# Non-envelope (published bool / active bool) collections
banners_repo = BaseRepository("banners")
popups_repo = BaseRepository("popups")
media_repo = BaseRepository("media")
gallery_albums_repo = BaseRepository("gallery_albums")
videos_repo = BaseRepository("videos")
reviews_repo = BaseRepository("reviews")
faqs_repo = BaseRepository("faqs")
redirects_repo = BaseRepository("redirects")

# System collections
users_repo = BaseRepository("users")
sessions_repo = BaseRepository("sessions")
inquiries_repo = BaseRepository("inquiries")
audit_logs_repo = BaseRepository("audit_logs")
pages_repo = BaseRepository("pages")
site_settings_repo = BaseRepository("site_settings")
navigation_repo = BaseRepository("navigation")
content_meta_repo = BaseRepository("content_meta")
password_resets_repo = BaseRepository("password_resets")

# Registry keyed by the URL segment used in /api/admin/:R
RESOURCE_REPOS: dict[str, BaseRepository] = {
    "tours": tours_repo,
    "destinations": destinations_repo,
    "banners": banners_repo,
    "offers": offers_repo,
    "popups": popups_repo,
    "media": media_repo,
    "gallery-albums": gallery_albums_repo,
    "videos": videos_repo,
    "articles": articles_repo,
    "reviews": reviews_repo,
    "faqs": faqs_repo,
    "redirects": redirects_repo,
}

# Which resources carry the publishing envelope (support publish/unpublish/schedule)
ENVELOPE_RESOURCES = {"tours", "destinations", "offers", "articles"}

# Entity name used in audit logs, per resource
RESOURCE_ENTITY = {
    "tours": "tour",
    "destinations": "destination",
    "banners": "banner",
    "offers": "offer",
    "popups": "popup",
    "media": "media",
    "gallery-albums": "gallery_album",
    "videos": "video",
    "articles": "article",
    "reviews": "review",
    "faqs": "faq",
    "redirects": "redirect",
}
