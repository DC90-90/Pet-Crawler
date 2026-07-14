"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.db import close_client, ensure_indexes

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start in production with insecure config
    settings.validate_production()
    try:
        await ensure_indexes()
    except Exception as exc:  # noqa: BLE001 - index build best-effort at startup
        logger.warning("Index creation skipped/failed: %s", exc)
    # Dev-only convenience: seed on startup when explicitly requested.
    if os.getenv("SEED_ON_STARTUP", "").lower() == "true" and not settings.is_production:
        try:
            from app.seed.run import ensure_dev_owner
            from app.seed.run import run as seed_run

            await seed_run()
            await ensure_dev_owner()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup seed failed: %s", exc)
    yield
    await close_client()


app = FastAPI(
    title="Svaneti with Georgie API",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; media-src 'self' https:; "
        "frame-src https://www.youtube.com https://player.vimeo.com; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'",
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# --- Routers ---------------------------------------------------------------
from app.api import (  # noqa: E402
    audit,
    auth,
    inquiries,
    media,
    overview,
    pages,
    public,
    settings as settings_router,
    users,
)
from app.api import admin_crud  # noqa: E402

app.include_router(auth.router)
app.include_router(public.router)
app.include_router(media.router)
app.include_router(overview.router)
app.include_router(inquiries.router)
app.include_router(audit.router)
app.include_router(users.router)
app.include_router(settings_router.router)
app.include_router(pages.router)
# admin_crud has catch-all /{resource} routes; include LAST so specific routers win
app.include_router(admin_crud.router)


# --- SEO infra at root -----------------------------------------------------
@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    from app.services.seo import build_sitemap

    xml = await build_sitemap()
    return Response(content=xml, media_type="application/xml")


@app.get("/robots.txt", include_in_schema=False)
async def robots():
    from app.services.seo import build_robots

    return PlainTextResponse(build_robots())


@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({"service": "svaneti-backend", "docs": "/api/docs"})


# --- Serve local media files ------------------------------------------------
_media_dir = os.path.abspath(settings.media_local_dir)
os.makedirs(_media_dir, exist_ok=True)
app.mount(
    settings.media_public_base, StaticFiles(directory=_media_dir), name="media"
)


# --- Optional SSR frontend shell (registered LAST) --------------------------
# Guarded by SERVE_FRONTEND so it never interferes with the Vite dev server.
_media_prefix = settings.media_public_base.rstrip("/") or "/media"
_SSR_EXCLUDED_PREFIXES = ("/api", _media_prefix)
_SSR_EXCLUDED_EXACT = {"/sitemap.xml", "/robots.txt", "/favicon.ico"}

def _serve_frontend_enabled() -> bool:
    # Read at request time so the flag can be toggled without re-importing the app.
    return os.getenv("SERVE_FRONTEND", "").lower() == "true"


@app.get("/{full_path:path}", include_in_schema=False)
async def ssr_shell(full_path: str, request: Request):
    from fastapi import HTTPException
    from fastapi.responses import HTMLResponse

    from app.services.ssr import render_shell

    path = "/" + full_path.lstrip("/")
    # /api, /media, /sitemap.xml, /robots.txt are registered earlier and win.
    # When SSR is disabled, or for excluded paths, behave as a normal 404.
    if not _serve_frontend_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if path in _SSR_EXCLUDED_EXACT or any(
        path == p or path.startswith(p + "/") for p in _SSR_EXCLUDED_PREFIXES
    ):
        raise HTTPException(status_code=404, detail="Not found")
    html = await render_shell(path)
    return HTMLResponse(content=html)
