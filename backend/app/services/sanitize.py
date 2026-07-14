"""Rich-text sanitization using bleach."""
from __future__ import annotations

import bleach

ALLOWED_TAGS = [
    "p", "br", "strong", "em", "u", "s", "a", "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "hr", "span", "figure",
    "figcaption", "img", "table", "thead", "tbody", "tr", "th", "td",
]
ALLOWED_ATTRS = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "span": ["class"],
    "*": ["class"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(value: str | None) -> str:
    if not value:
        return ""
    return bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )


RICH_TEXT_FIELDS = {"fullDescription", "body", "description", "answer"}


def sanitize_localized(value: dict | None) -> dict | None:
    """Sanitize each language variant of a LocalizedText rich field."""
    if not isinstance(value, dict):
        return value
    return {k: (sanitize_html(v) if isinstance(v, str) else v) for k, v in value.items()}
