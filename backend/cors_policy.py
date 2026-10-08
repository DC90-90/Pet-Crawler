"""Explicit origins for credentialed browser requests; no wildcard fallback."""
from urllib.parse import urlsplit
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


def allowed_origins(value):
    origins = list(dict.fromkeys(part.strip().rstrip("/") for part in value.split(",") if part.strip()))
    if not origins:
        raise ValueError("CORS_ORIGINS must contain an explicit frontend origin")
    for origin in origins:
        url = urlsplit(origin)
        if (url.scheme not in ("http", "https") or not url.netloc or url.path
                or url.query or url.fragment or url.username or url.password or "*" in origin):
            raise ValueError("CORS_ORIGINS must contain only explicit HTTP(S) origins")
    return origins


class CookieOriginMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, origins):
        super().__init__(app)
        self.origins = frozenset(origins)

    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        if (request.method in {"POST", "PUT", "PATCH", "DELETE"}
                and request.cookies.get("daleel_token") and origin and origin not in self.origins):
            return JSONResponse({"detail": "Origin is not permitted"}, status_code=403)
        return await call_next(request)