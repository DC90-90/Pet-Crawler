"""Shared helpers for API routers: cookies, ETag, pagination, localization."""
from __future__ import annotations

from fastapi import Request, Response

from app.core.config import settings
from app.core.rate_limit import client_ip as _client_ip
from app.services.content_version import get_version

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"


def client_ip(request: Request) -> str:
    return _client_ip(request)


def _samesite() -> str:
    val = settings.cookie_samesite.lower()
    return val if val in ("lax", "strict", "none") else "lax"


def set_auth_cookies(response: Response, tokens: dict) -> None:
    secure = settings.cookie_secure
    samesite = _samesite()
    domain = settings.cookie_domain or None
    response.set_cookie(
        ACCESS_COOKIE, tokens["access_token"], httponly=True, secure=secure,
        samesite=samesite, domain=domain, max_age=settings.access_token_ttl_minutes * 60, path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, tokens["refresh_token"], httponly=True, secure=secure,
        samesite=samesite, domain=domain, max_age=settings.refresh_token_ttl_days * 86400,
        path="/",
    )
    # CSRF cookie is readable by JS (double-submit) so NOT httponly
    response.set_cookie(
        CSRF_COOKIE, tokens["csrf_token"], httponly=False, secure=secure,
        samesite=samesite, domain=domain, max_age=settings.refresh_token_ttl_days * 86400, path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    domain = settings.cookie_domain or None
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, domain=domain, path="/")


async def apply_etag(request: Request, response: Response) -> str | None:
    """Set ETag from content version; return 'not-modified' if client cache hits."""
    version = (await get_version())["version"]
    etag = f'"v{version}"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=0, must-revalidate"
    inm = request.headers.get("if-none-match")
    if inm and inm.strip() == etag:
        return "not-modified"
    return None


def pagination(request: Request, default_size: int = 50, max_size: int = 200) -> tuple[int, int]:
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        size = int(request.query_params.get("pageSize", default_size))
    except (TypeError, ValueError):
        size = default_size
    size = max(1, min(size, max_size))
    return page, size


def lang_param(request: Request) -> str:
    lang = request.query_params.get("lang", "en")
    return lang if lang in ("en", "ka", "ar") else "en"
