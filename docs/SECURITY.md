# Security — Svaneti with Georgie

_Last updated: 2026-07-14_

This document states the threat model, the implemented controls, and a
production hardening checklist for the owner. Controls are grounded in the code
under `backend/app/core/security.py`, `backend/app/core/config.py`,
`backend/app/main.py`, and the auth/inquiry/media services.

## 1. Threat model

| Asset | Threats | Primary mitigations |
|---|---|---|
| Owner/editor accounts | Credential theft, brute force, session hijack | Argon2 hashing, rate-limit + lockout, HttpOnly/Secure cookies, rotating refresh, generic errors |
| Admin write endpoints | CSRF, privilege escalation | CSRF double-submit, role checks (owner vs editor), auth on all `/api/admin/*` |
| Public content integrity | Draft leakage, tampering | Server-side effective-visibility; drafts 404; signed preview tokens only |
| Inquiry form | Spam, injection, abuse | Rate limiting, validation, IP hashing, captcha-ready |
| Uploaded media | Malicious files, oversized uploads | MIME allow-list, size cap, filename sanitization, no execution |
| Rich text (articles/descriptions) | Stored XSS | `bleach` sanitization on save |
| Secrets | Leakage, insecure defaults | Env-only secrets, production startup refusal on insecure defaults |
| The browser app | XSS, clickjacking, MIME sniffing | CSP, `X-Frame-Options: DENY`, `nosniff`, Referrer-Policy, HSTS (prod) |

## 2. Authentication & session management

- **Password hashing** — Argon2 (`argon2-cffi`, `PasswordHasher`), cost tunable
  via `ARGON2_TIME_COST` / `ARGON2_MEMORY_KB` / `ARGON2_PARALLELISM`.
  `check_needs_rehash` supports transparent upgrades.
- **Access token** — HS256 JWT in an **HttpOnly** cookie (`access_token`), TTL
  `ACCESS_TOKEN_TTL_MINUTES` (default 15). Never exposed to JS.
- **Refresh token** — random `token_urlsafe(48)`, stored **hashed** (SHA-256
  keyed with the JWT secret) in the `sessions` collection, **rotated on every
  refresh**, revocable on logout. TTL `REFRESH_TOKEN_TTL_DAYS` (default 14).
- **Cookies** — `HttpOnly`, `SameSite` (`COOKIE_SAMESITE`, default `lax`),
  `Secure` when `COOKIE_SECURE=true` (required in prod), optional `COOKIE_DOMAIN`.
- **Generic auth errors** — "Invalid credentials" regardless of whether the
  email exists → no user enumeration.

## 3. CSRF protection

Double-submit token: on login a random `csrf_token` cookie is set (readable by
JS), and every state-changing admin request must send the same value in the
`X-CSRF-Token` header. Comparison is constant-time (`hmac.compare_digest`).
Missing or mismatched tokens are rejected. The public inquiry POST is
CSRF-exempt by design (anonymous) but rate-limited and captcha-ready.

## 4. Rate limiting & account lockout

In-memory fixed-window limiter (`core/rate_limit.py`), keyed per bucket + IP:

| Endpoint | Limit |
|---|---|
| `POST /api/auth/login` | 10 / minute / IP |
| `POST /api/auth/password-reset/request` | 5 / minute / IP |
| `POST /api/public/inquiries` | 5 / minute / IP |

**Account lockout** — after `MAX_FAILED = 5` failed logins the account is locked
for `LOCKOUT_MINUTES = 15`; the counter resets on success and on lock. Failed
logins are audited.

> Note: the limiter is per-process/in-memory. Behind multiple backend replicas,
> back it with a shared store (e.g. Redis) for global limits.

## 5. Input & upload validation

- **Uploads** — MIME allow-list (`MEDIA_ALLOWED_IMAGE` / `MEDIA_ALLOWED_VIDEO`),
  size cap `MEDIA_MAX_MB`, sanitized/normalized filenames, stored under the
  media provider (never executed, never in Mongo).
- **Rich text** — article bodies and tour descriptions are sanitized with
  **`bleach`** (allow-listed tags/attributes) before storage → prevents stored
  XSS.
- **Request validation** — Pydantic v2 schemas validate all inputs; field-level
  errors returned as `errors[]`.
- **IP hashing** — inquiry IPs stored **hashed** (SHA-256 keyed with the CSRF
  secret), not in clear text.

## 6. Security headers

Applied to every response via middleware (`main.py`):

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; img-src 'self' data: https:; media-src 'self' https:; frame-src https://www.youtube.com https://player.vimeo.com; style-src 'self' 'unsafe-inline'; script-src 'self'` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` — **production only** |

CSP `frame-src` intentionally allows YouTube/Vimeo for video embeds. Tighten
`img-src`/`media-src` to your actual media host in production if desired.

## 7. CORS

`CORSMiddleware` with an **explicit allow-list** (`CORS_ORIGINS`, comma
separated), `allow_credentials=True` (cookies), `ETag` exposed. Do **not** use a
wildcard origin with credentials.

## 8. Authorization (roles)

Two roles: **owner** and **editor**.

- All `/api/admin/*` and `/api/auth/me` require a valid access token.
- **Owner-only**: user management (`/api/admin/users`), sensitive site settings
  (secrets/analytics), force-password-change.
- **Editor**: content CRUD and publishing, restricted from the owner-only areas.
- Every mutation writes an **audit log** (`login`, `login_failed`, `create`,
  `edit`, `publish`, `unpublish`, `archive`, `delete`, `media_replace`,
  `user_change`, `settings_change`) with actor, entity, summary and IP.

## 9. Draft confidentiality & preview

Public endpoints return **effective-published** content only; a draft slug
returns `404`. The single path to non-published content is a **signed preview
token** (JWT signed with the CSRF secret, scoped to resource+id, 60-min TTL) via
`/api/public/preview/:resource/:id?token=...`.

## 10. Secrets management

- **Env only.** No secrets in git; `.env` is git-ignored; `.env.example` ships
  placeholders.
- **Production refuses insecure defaults.** `Settings.validate_production()`
  raises at startup if `APP_ENV=production` and: `JWT_SECRET` is the default or
  <32 chars, `CSRF_SECRET` is the default or <16 chars, `MONGODB_URI` is missing,
  or `COOKIE_SECURE` is not true.
- **Mock DB disabled in prod.** `USE_MOCK_DB` / `SEED_ON_STARTUP` are ignored
  when `APP_ENV=production`.
- Generate secrets: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## 11. Password reset architecture

- Reset is **email-optional** (`EMAIL_ENABLED`; SMTP is a safe no-op when off).
- `POST /api/auth/password-reset/request` creates a reset token stored **hashed**;
  the request is rate-limited (5/min/IP) and returns generically (no account
  disclosure). `POST /api/auth/password-reset/confirm` completes with the token.
- Force-password-change: seeded owner accounts can require a password change on
  first login (`FORCE_PASSWORD_CHANGE`), cleared via `change-password`.

## 12. Owner production security checklist

- [ ] `APP_ENV=production` set.
- [ ] Strong, unique `JWT_SECRET` (≥32 chars) and `CSRF_SECRET` (≥16 chars),
      generated with a CSPRNG, stored in the platform secret manager.
- [ ] `COOKIE_SECURE=true` and the whole site served over **HTTPS**.
- [ ] `COOKIE_SAMESITE` appropriate (`lax` typical; `none` only if cross-site,
      and then only with `Secure`).
- [ ] `CORS_ORIGINS` limited to your real front-end origin(s); no wildcard.
- [ ] `MONGODB_URI` points at managed MongoDB with auth + TLS; network locked
      down.
- [ ] `MEDIA_PROVIDER` set to Cloudinary/S3 with scoped credentials; local disk
      not used in prod.
- [ ] `USE_MOCK_DB` / `SEED_ON_STARTUP` unset (and irrelevant — disabled in prod).
- [ ] First owner created; default seed password changed; `FORCE_PASSWORD_CHANGE`
      honored.
- [ ] `FEATURE_PAYMENTS=false` (v1).
- [ ] Sample reviews absent (`SEED_SAMPLE_REVIEWS` forced false in prod).
- [ ] HSTS confirmed present; CSP reviewed against your media/analytics hosts.
- [ ] Backups configured for MongoDB; media store backed up/replicated.
- [ ] Audit log reviewed periodically; editor accounts scoped to least privilege.
- [ ] Dependency and secret scanning enabled in CI (see `.github/workflows/ci.yml`).
- [ ] Consider a shared-store rate limiter if running multiple backend replicas.
