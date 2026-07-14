# API Specification — Svaneti with Georgie

Base URL: `${BACKEND_URL}` (default `http://localhost:8000`). All app routes are
under `/api`. Interactive OpenAPI docs at `/api/docs`.

## Conventions

- JSON everywhere. Errors: `{ "detail": "message" }` (+ `errors[]` for field
  validation). Auth errors are generic ("Invalid credentials").
- Auth for admin routes = HttpOnly cookie `access_token` (short-lived) +
  refresh cookie `refresh_token` (rotated). State-changing admin requests
  require CSRF header `X-CSRF-Token` matching the `csrf_token` cookie.
- Public list endpoints support `?lang=en|ka|ar` (affects which localized
  strings are prioritized) and pagination `?page=&pageSize=`.
- Public responses carry `ETag: "v<content_version>"` and honor
  `If-None-Match` → `304`.

## Public API (`/api/public/*`, anonymous, published-only)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/public/content-version` | `{ version, updatedAt }` for polling. |
| GET | `/api/public/settings` | Public site settings (no secrets). |
| GET | `/api/public/navigation` | Menu + footer. |
| GET | `/api/public/pages/:key` | Modular page (e.g. `home`) with visible sections resolved. |
| GET | `/api/public/tours` | Published tours; filters: `destination, season, duration, difficulty, family, lowWalking, winter, private, q, sort`. |
| GET | `/api/public/tours/:slug` | Single published tour (404 if draft). |
| POST| `/api/public/tours/recommend` | Deterministic "Help me choose" → ranked tours. |
| GET | `/api/public/destinations` / `/:slug` | Published destinations. |
| GET | `/api/public/articles` / `/:slug` | Published travel-guide articles. |
| GET | `/api/public/gallery` | Published albums + media. |
| GET | `/api/public/videos` | Published videos. |
| GET | `/api/public/offers` | Active/effective offers. |
| GET | `/api/public/banners?path=&lang=&device=` | Effective banners for a route. |
| GET | `/api/public/popups?path=&lang=&device=&visitor=` | Eligible popups (client enforces frequency). |
| GET | `/api/public/reviews` | Published reviews (sample ones excluded in prod). |
| GET | `/api/public/faqs` | Published FAQs grouped by category. |
| POST| `/api/public/inquiries` | Create inquiry (rate-limited, validated, CSRF-exempt but captcha-ready). |
| GET | `/api/public/seo/route?path=` | Route SEO payload (title, description, canonical, OG, JSON-LD) for the SSR shell. |
| GET | `/sitemap.xml`, `/robots.txt` | SEO infra (served at root). |

## Auth API (`/api/auth/*`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/login` | Email+password → sets cookies (rate-limited, lockout). |
| POST | `/api/auth/logout` | Revoke refresh, clear cookies. |
| POST | `/api/auth/refresh` | Rotate refresh, issue new access. |
| GET  | `/api/auth/me` | Current user. |
| POST | `/api/auth/change-password` | Change own password (clears forcePasswordChange). |
| POST | `/api/auth/password-reset/request` | Begin reset (email optional; token stored). |
| POST | `/api/auth/password-reset/confirm` | Complete reset with token. |

## Admin API (`/api/admin/*`, auth required; editor-restricted where noted)

Generic CRUD pattern per resource `R` in {tours, destinations, banners, offers,
popups, media, gallery-albums, videos, articles, reviews, faqs, redirects}:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/admin/:R` | List incl. drafts; filters + pagination. |
| POST | `/api/admin/:R` | Create → audit `create`. |
| GET | `/api/admin/:R/:id` | Read one. |
| PUT | `/api/admin/:R/:id` | Update → audit `edit`. |
| DELETE | `/api/admin/:R/:id` | Delete (guarded for referenced media) → audit `delete`. |
| POST | `/api/admin/:R/:id/publish` | status→published, bump content-version. |
| POST | `/api/admin/:R/:id/unpublish` | status→draft, bump version. |
| GET | `/api/admin/:R/:id/preview-token` | Signed preview token (published+draft). |

Additional admin endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET/PUT | `/api/admin/settings` | Site settings (owner only for secrets/analytics). |
| GET/PUT | `/api/admin/navigation` | Menus & footer. |
| GET/PUT | `/api/admin/pages/:key` | Page builder sections (reorder, hide, schedule). |
| GET | `/api/admin/overview` | Dashboard counters (published/draft/inquiries/etc). |
| GET | `/api/admin/inquiries` | List/filter/search inquiries. |
| PUT | `/api/admin/inquiries/:id` | Status + notes + timeline. |
| GET | `/api/admin/inquiries/export.csv` | CSV export of selected/all. |
| POST | `/api/admin/media/upload` | Multipart upload (validated, MIME/size) → metadata + variants. |
| POST | `/api/admin/media/external` | Register YouTube/Vimeo URL. |
| POST | `/api/admin/media/:id/replace` | Replace file, keep refs → audit. |
| GET | `/api/admin/audit-logs` | Paginated audit trail. |
| GET | `/api/admin/users` · POST · PUT · DELETE | User mgmt (owner only). |

## Preview

`GET /api/public/preview/:R/:id?token=...` returns draft content when the signed
token is valid — the only way anonymous requests see non-published data.

## Rate limits

- `/api/auth/login`: 10/min/IP + per-account lockout after N failures.
- `/api/public/inquiries`: 5/min/IP.
- Uploads: size cap (`MEDIA_MAX_MB`), MIME allow-list.

## Security headers (all responses)

`Content-Security-Policy`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Strict-Transport-Security` (prod), `Permissions-Policy`.
