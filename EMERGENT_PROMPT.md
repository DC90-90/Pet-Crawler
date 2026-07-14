# Emergent instruction — Svaneti with Georgie

_Paste this to Emergent as the task for this repository._

---

You are working with an **existing, tested codebase** — **do not** treat this as
a blank template and **do not** regenerate the app from scratch.

**What it is:** "Svaneti with Georgie", a tourism website + CMS. Backend is
**FastAPI + Pydantic v2 + MongoDB (Motor)**; frontend is **Vite + React 19 +
TypeScript + Tailwind v4 + HeroUI v3**. It is one deployment serving both a
**dynamic public site** (language-prefixed routes `/:lang/...`, en/ka/ar with
Arabic RTL) and a **secure owner dashboard** (`/admin`). Content published in the
dashboard appears on the public site with no rebuild via a content-version
counter. Backend tests: **31 passing** (pytest with `mongomock-motor`).

## Do this

1. **Import & synchronize** this GitHub branch as-is. GitHub is canonical.
2. **Preserve** — without silent rewrites — the architecture, the public routes
   (`/:lang/...`) and admin routes (`/admin/...`), the MongoDB data models, the
   API contracts, the auth model (Argon2 + JWT HttpOnly cookies + CSRF
   double-submit + rotating refresh), the i18n structure (`{ en, ka?, ar? }`,
   Arabic full RTL), the content workflow (draft → scheduled → published →
   archived + content-version), and the tests.
3. **Configure managed MongoDB** — set `MONGODB_URI` to the managed connection
   string, `MONGODB_DB=svaneti`, and **do not set `USE_MOCK_DB`**.
4. **Set environment variables** (see below).
5. **Configure media storage** — set `MEDIA_PROVIDER` to `cloudinary` or `s3`
   with credentials; never store binaries in MongoDB; external videos are URLs.
6. **Initialize the database** — run `python -m app.seed.run` then
   `python -m scripts.create_admin` against the managed DB.
7. **Run the tests** — `cd backend && pytest`; `cd frontend && npm run lint &&
   npm run typecheck && npm run build && npm run test`. Do not remove or weaken
   tests to make a build pass.
8. **Produce a preview** with **backend + frontend as one synchronized
   deployment** so the public site and dashboard share the same backend and
   content-version syncing works.
9. **Ask before large architectural replacements.** If a platform constraint
   forces a change to any preserved item above, report the compatibility change
   and get approval first.
10. Keep **deployment and custom-domain steps explicit/manual** — request owner
    approval before promoting; configure domain/DNS/TLS manually, then update the
    URL/CORS/`VITE_*` vars and rebuild the front end.

## Do NOT

- Regenerate from a blank template or swap the stack.
- Weaken authentication, disable CSRF, or set a wildcard CORS with credentials.
- Commit secrets — use the platform secret manager.
- Fabricate Georgie's real-world facts or seed sample reviews in production.

## Environment variables to set

```
APP_ENV=production
MONGODB_URI=<managed connection string>
MONGODB_DB=svaneti
JWT_SECRET=<strong random, >=32 chars>
CSRF_SECRET=<strong random, >=16 chars>
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
CORS_ORIGINS=<deployed frontend origin>
FRONTEND_URL=<deployed frontend url>
PUBLIC_SITE_URL=<deployed public url>
BACKEND_URL=<deployed backend url>
MEDIA_PROVIDER=cloudinary   # or s3
# Cloudinary: CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET
# S3:         S3_ENDPOINT / S3_REGION / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY / S3_PUBLIC_BASE
ADMIN_SEED_EMAIL=<owner email>
ADMIN_SEED_PASSWORD=<owner bootstrap password>
FORCE_PASSWORD_CHANGE=true
FEATURE_PAYMENTS=false
# Frontend build-time:
VITE_API_BASE_URL=<deployed backend url>
VITE_PUBLIC_SITE_URL=<deployed public url>
VITE_MAP_TILES_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
```

Generate secrets with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
The backend refuses to start in production with insecure defaults.

## Commands to run

```bash
# database init (against managed Mongo)
python -m app.seed.run
python -m scripts.create_admin

# quality gates
cd backend && pytest
cd frontend && npm ci && npm run lint && npm run typecheck && npm run build && npm run test
```

Full detail in [`docs/EMERGENT_HANDOFF.md`](docs/EMERGENT_HANDOFF.md).
