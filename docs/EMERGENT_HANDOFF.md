# Emergent Handoff — Svaneti with Georgie

_Last updated: 2026-07-14_

How to import and run this **existing, tested** repository on Emergent
(<https://mcp.emergent.sh/>). The goal is to **synchronize** the GitHub codebase
into a running preview — **not** to regenerate it from a blank template.

> **Emergent MCP status (checked 2026-07-14):** **NOT available in this
> session.** No Emergent MCP server was connected (the only MCP servers present
> were GitHub, Google Drive, HIGGSFIELD and Claude Code Remote). No Emergent job
> was created or connected from here — this is stated honestly rather than
> fabricated. Handoff therefore proceeds via **GitHub import** using
> `EMERGENT_PROMPT.md`. The Emergent MCP endpoint, when you connect it, is
> <https://mcp.emergent.sh/>. The steps below apply regardless.

## 0. Golden rules

1. **GitHub is canonical.** Import this repository's branch as-is.
2. **Do not regenerate from a blank template.** This is a real FastAPI + React +
   MongoDB codebase with passing tests, not a scaffold to be replaced.
3. **Preserve** the following without silent rewrites:
   - public routes (`/:lang/...`) and admin routes (`/admin/...`);
   - data models / MongoDB collections (`docs/DATA_MODEL.md`);
   - API contracts (`docs/API_SPECIFICATION.md`);
   - the auth model (Argon2 + JWT HttpOnly cookies + CSRF + refresh rotation);
   - the translation structure (`{ en, ka?, ar? }`, Arabic RTL);
   - the content workflow (draft → scheduled → published → archived +
     content-version);
   - the tests.
4. **Report compatibility changes before big architectural replacements.** If a
   platform constraint requires changing any of the above, surface it and get
   approval first — do not swap the stack or weaken security unilaterally.
5. **Deployment and custom domain remain explicit/manual** — no auto-deploy
   without owner approval.

## 1. Import

1. Connect the GitHub repository and select the working branch (the branch
   carrying this Svaneti application, e.g.
   `claude/mestia-svaneti-tourism-site-*`).
2. Import the branch into the Emergent workspace. Keep the existing directory
   layout (`backend/`, `frontend/`, `docs/`, `scripts/`).
3. Do not accept a "regenerate app" flow — choose import/sync of existing code.

## 2. Managed MongoDB

- Provision Emergent's **managed MongoDB** and set `MONGODB_URI` to its
  connection string; set `MONGODB_DB=svaneti` (or your choice).
- **Remove / do not set `USE_MOCK_DB`** — the mock is dev/test-only and is
  disabled when `APP_ENV=production` anyway.

## 3. Environment variables

Set these from [`.env.example`](../.env.example), with production values:

| Variable | Production value |
|---|---|
| `APP_ENV` | `production` |
| `MONGODB_URI` | managed MongoDB connection string |
| `MONGODB_DB` | `svaneti` |
| `JWT_SECRET` | strong random ≥32 chars (`python -c "import secrets;print(secrets.token_urlsafe(48))"`) |
| `CSRF_SECRET` | strong random ≥16 chars |
| `COOKIE_SECURE` | `true` |
| `COOKIE_SAMESITE` | `lax` (or `none` only if truly cross-site, with HTTPS) |
| `CORS_ORIGINS` | the deployed front-end origin(s) |
| `FRONTEND_URL` / `PUBLIC_SITE_URL` / `BACKEND_URL` | deployed URLs |
| `MEDIA_PROVIDER` | `cloudinary` or `s3` (not `local`) |
| Media creds | `CLOUDINARY_*` or `S3_*` as applicable |
| `ADMIN_SEED_EMAIL` / `ADMIN_SEED_PASSWORD` | the owner's bootstrap creds |
| `FORCE_PASSWORD_CHANGE` | `true` |
| `FEATURE_PAYMENTS` | `false` |
| `SEED_SAMPLE_REVIEWS` | irrelevant in prod (forced false) |
| `VITE_API_BASE_URL` / `VITE_PUBLIC_SITE_URL` / `VITE_MAP_TILES_URL` | deployed front-end build vars |

The backend **refuses to start** in production with insecure defaults (weak
`JWT_SECRET`/`CSRF_SECRET`, missing `MONGODB_URI`, `COOKIE_SECURE` not true).

## 4. Media storage

Configure a real provider (Cloudinary or S3-compatible) via `MEDIA_PROVIDER` and
its credentials. Binaries are stored there, **never** in MongoDB. External
YouTube/Vimeo videos are registered by URL. Ensure the media host is reachable
and allowed by CSP (`img-src`/`media-src`/`frame-src`).

## 5. Initialize the database

Run once against the managed DB:

```bash
# seed baseline content (destinations, tours, articles, FAQs, navigation, settings)
python -m app.seed.run

# create the owner account (reads ADMIN_SEED_EMAIL / ADMIN_SEED_PASSWORD)
python -m scripts.create_admin
```

Indexes are created automatically at backend startup (`ensure_indexes`).

## 6. Run the tests

```bash
cd backend && pytest          # 31 passing (mongomock-motor, no server needed)
cd frontend && npm run lint && npm run typecheck && npm run build
cd frontend && npm run test   # vitest
# e2e optional in the platform: npm run test:e2e (with USE_MOCK_DB backend)
```

Do not remove or weaken tests to make a build pass.

## 7. Produce a preview

- Bring up **backend + frontend as one synchronized deployment** — the public
  site and the owner dashboard are served together and share the same backend so
  content-version syncing works.
- Verify: `/` redirects to a language; a published tour is public and a draft
  slug 404s; `/admin/login` works; publishing in the dashboard updates the
  public site.

## 8. Deployment & domain

- Keep deployment **explicit** — request owner approval before promoting.
- Custom domain and DNS/TLS steps are **manual**: configure the domain, point
  DNS, enable HTTPS, then update `CORS_ORIGINS`, `FRONTEND_URL`,
  `PUBLIC_SITE_URL`, `BACKEND_URL` and the `VITE_*` vars accordingly and rebuild
  the front end.

## 9. What NOT to do

- Do not regenerate the app from scratch or swap the stack.
- Do not weaken authentication, disable CSRF, or loosen CORS to a wildcard with
  credentials.
- Do not commit secrets; use the platform secret manager.
- Do not fabricate Georgie's real-world facts or seed reviews in production.
- Do not split the public site and dashboard into deployments that can't see the
  same content-version.

See the ready-to-paste instruction in [`../EMERGENT_PROMPT.md`](../EMERGENT_PROMPT.md).
