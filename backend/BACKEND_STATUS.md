# Backend Status — Svaneti with Georgie

_Generated 2026-07-14._

## Summary

The FastAPI backend is implemented per `docs/DATA_MODEL.md`, `docs/API_SPECIFICATION.md`
and `CLAUDE.md`: layered `api → services → repositories → models/schemas`, Motor async
MongoDB, Argon2 auth with JWT HttpOnly cookies + CSRF double-submit, rate limiting,
media provider abstraction with Pillow variants, publishing/version-bump, SEO route +
sitemap/robots, seed + admin bootstrap, Docker, and a pytest suite.

## Verification (all green)

| Check | Result |
|---|---|
| `python -c "import app.main"` (PYTHONPATH=.) | IMPORT OK |
| `ruff check .` | All checks passed |
| `pytest` | **31 passed** |
| Real uvicorn server + seed + curl smoke test | Passed (see below) |

### HTTP smoke test (real uvicorn process)
- `GET /api/public/content-version` → `{"version":1,...}`
- `GET /api/public/tours` → 9 published tours; draft `custom-svaneti-itinerary` NOT present
- `GET /api/public/tours/custom-svaneti-itinerary` (draft) → **404**
- `GET /api/public/tours/ushguli-shkhara-private-day-journey` (published) → **200**
- `GET /api/admin/tours` (no auth) → **401**
- ETag `"v1"` returned; `If-None-Match` → **304**
- `GET /api/public/seo/route?path=…` → JSON-LD `[LocalBusiness, BreadcrumbList, TouristTrip]`
- `GET /sitemap.xml` → 24 url entries incl. hreflang alternates; `GET /robots.txt` OK
- `POST /api/public/inquiries` → `{"ok":true,"id":…}`
- Security headers present (CSP, X-Frame-Options, X-Content-Type-Options)
- Production startup with insecure defaults → refused (RuntimeError)

## Known gap: real MongoDB container could not be started

The verification prompt asks to `docker run -d mongo:7` for a real-DB smoke test. In
this sandbox the organization egress policy blocks the Docker registry blob CDN:

```
docker pull mongo:7 → 403 Forbidden
  (production.cloudfront.docker.com/.../blobs/... : 403)
https://fastdl.mongodb.org/.../mongodb-...tgz → CONNECT tunnel failed, response 403
```

Per the proxy rules, org-policy 403s must not be routed around. No `mongod` binary or
apt package was available locally either.

### What was done instead
- The full pytest suite runs against **mongomock-motor** (in-process, no server).
- A **real uvicorn process** smoke test was run end-to-end over HTTP. To make the seed
  and the server share storage without a reachable Mongo, a **dev-only, in-process mock
  DB fallback** is used (`USE_MOCK_DB=true` + `SEED_ON_STARTUP=true`). This exercises the
  real ASGI server, routing, seed logic, ETag/304, SEO, sitemap and inquiries; only the
  storage engine is in-memory.

### To run the real-DB smoke test in an environment with registry access
```bash
docker run -d -p 27017:27017 --name svaneti-mongo-test mongo:7
cd backend && MONGODB_URI=mongodb://localhost:27017 python -m app.seed.run
MONGODB_URI=mongodb://localhost:27017 python -m scripts.create_admin
MONGODB_URI=mongodb://localhost:27017 uvicorn app.main:app --port 8000
curl localhost:8000/api/public/content-version
curl localhost:8000/api/public/tours
docker rm -f svaneti-mongo-test
```
The application code path is identical; only `USE_MOCK_DB` is omitted so the real Motor
client is used. `USE_MOCK_DB` / `SEED_ON_STARTUP` are hard-disabled when `APP_ENV=production`.

## Frontend/backend contract alignment (added)

- Public serializers (`app/services/serializers.py`) resolve media IDs to public URLs.
  Rule: usable variant/original URL → else local file at `storageKey` → `MEDIA_PUBLIC_BASE/…`
  → external videos keep `externalUrl` → else `null` (frontend shows gradient placeholder).
  Added, additively (original `*MediaId` fields kept):
  - tours & destinations: `coverUrl`, `galleryUrls[]`
  - articles: `coverUrl`
  - videos: `posterUrl`, `url` (uploaded); `externalUrl` kept
  - banners: `desktopUrl`, `mobileUrl`
  - popups: `mediaUrl`
  - public settings: `logoUrl`, `ownerPortraitUrl`, `faviconUrl`
- `GET /api/public/gallery` now returns a flat `items[]` (plus `albums` and `media`), each
  `{id,url,thumbUrl,altText,caption,location,credit,category,width,height}` for resolvable media.
- Seed placeholders now write **real SVG gradient files** to `MEDIA_LOCAL_DIR` so URLs resolve
  and are served by the `/media` mount; uploaded media likewise resolve to working `/media/…`.
- Seed navigation / footer / legal / page CTA hrefs use the real frontend routes
  (`/travel-guide`, `/about-georgie`, `/experiences`, `/plan-your-trip`, `/inquiry`, …; no lang prefix).
- Seed home hero `data` uses `heading/subheading/badge/primaryCta/secondaryCta/overlayIntensity/mediaUrl`.
- Dev e2e bootstrap: when `SEED_ON_STARTUP=true` and `APP_ENV!=production`, startup also ensures
  the owner account (`ADMIN_SEED_EMAIL`/`ADMIN_SEED_PASSWORD`) with `forcePasswordChange=false`
  so Playwright can log straight in. Hard-disabled in production (use `scripts/create_admin`).
  Password is never printed.

## Optional SSR HTML shell (added)

`app/services/ssr.py` + a catch-all GET in `app/main.py` (registered LAST, after `/api`,
`/media`, `/sitemap.xml`, `/robots.txt`, which take precedence). Gated by env flag
**`SERVE_FRONTEND` (default false)** — checked at request time so it never interferes with
the Vite dev server. When enabled, any non-excluded path:
1. loads a base shell — `FRONTEND_DIST_DIR/index.html` (default `./frontend/dist/index.html`)
   if present, else a built-in template with `<div id="root"></div>` and the module script;
2. strips a leading `/en|/ka|/ar` prefix and calls the **same** `route_seo()` logic behind
   `GET /api/public/seo/route`;
3. injects into `<head>`: `<title>`, `<meta name="description">` (safe regex replace of any
   existing ones, else insert before `</head>`), canonical link, en/ka/ar + x-default
   hreflang alternates, Open Graph + Twitter tags, and one `<script type="application/ld+json">`
   per JSON-LD entry. All values HTML-escaped; `</` escaped inside JSON-LD.
4. returns `text/html`. Unknown routes still return the shell (SPA handles 404 client-side)
   but with a generic title and `robots: noindex,nofollow`.

**Deployment:** production/Emergent may set `SERVE_FRONTEND=true` to serve the built SPA with
per-route meta from one FastAPI app, OR keep it false and let nginx serve the SPA (client-side
SEO + `/api/public/seo/route` still apply).

### `.env.example` (root file — outside backend/ scope, not edited). Needed line:
```
SERVE_FRONTEND=false                # true = FastAPI serves built SPA with per-route SSR meta
FRONTEND_DIST_DIR=./frontend/dist   # base HTML shell source when SERVE_FRONTEND=true
```

## Notes / assumptions
- All of "Georgie's" real-world facts are placeholders flagged
  `verificationStatus=needs_verification` / `isVerified=false`. Contact fields are null.
- Seed publishes 9 of 10 tours; `custom-svaneti-itinerary` is left as a draft to prove
  draft/public separation. The 12 travel-guide articles are seeded as drafts per spec.
- Sample reviews are seeded only when `APP_ENV!=production` and `SEED_SAMPLE_REVIEWS=true`,
  and are marked `isSample=true` with `[SAMPLE REVIEW …]` text.
- Cloudinary/S3 media providers are stubs behind `MEDIA_PROVIDER`; LocalProvider is fully
  implemented with Pillow thumb/card/hero variants.
- Email is a safe no-op unless `EMAIL_ENABLED=true`.
