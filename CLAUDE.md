# CLAUDE.md — Svaneti with Georgie

Repository conventions and non-negotiable rules. Keep this file concise.

## What this is

A tourism website + CMS for a local Svaneti (Georgia) guide, "Georgie".
Two systems in one deployment: a **dynamic public site** and a **secure owner
dashboard/CMS**. Content published in the dashboard appears on the public site
without editing source or rebuilding — the public app polls a content-version
counter and refetches.

## Stack

- **backend/** — FastAPI · Pydantic v2 · MongoDB (Motor) · Argon2 · JWT cookies.
  Layered: `api/` (routers) → `services/` (business logic) → `repositories/`
  (Mongo access) → `models/` + `schemas/` (Pydantic).
- **frontend/** — Vite · React · TypeScript (strict) · Tailwind v4 · **HeroUI v3**
  (`@heroui/react`, compound components, `onPress` not `onClick`, no provider) ·
  React Router · TanStack Query · React Hook Form + Zod · i18next · Framer Motion.

## Commands

Run from repo root unless noted.

| Task | Command |
|---|---|
| Start everything (Docker) | `make up` / `docker compose up` |
| Start Mongo only | `make db` |
| Backend dev | `cd backend && uvicorn app.main:app --reload` |
| Seed database | `make seed` (`python -m app.seed.run`) |
| Create admin | `make admin` (`python -m scripts.create_admin`) |
| Frontend dev | `cd frontend && npm run dev` |
| Backend tests | `cd backend && pytest` |
| Frontend unit tests | `cd frontend && npm run test` |
| E2E (Playwright) | `cd frontend && npm run test:e2e` |
| Lint | `make lint` (ruff + eslint) |
| Format | `make format` |
| Typecheck | `cd frontend && npm run typecheck` |
| Production build | `make build` |
| Reset dev data | `make reset` |

## Architecture rules (non-negotiable)

1. **No drafts in public API.** `/api/public/*` returns effective-published
   content only. Preview requires a signed token.
2. **No binary media in MongoDB.** Store only metadata; bytes go to the media
   provider (local dev disk → Cloudinary/S3 in prod).
3. **Publishing bumps `content_meta.version`.** Public responses send
   `ETag: "v<version>"`; `/api/public/content-version` drives frontend refetch.
4. **Localized text** = `{ en, ka?, ar? }`. English required. Arabic renders
   full RTL (dir="rtl", logical CSS, mirrored components) — not translated LTR.
5. **Security:** Argon2 hashing, HttpOnly+SameSite cookies (Secure in prod),
   CSRF double-submit on cookie-auth mutations, login + inquiry rate limits,
   upload MIME/size validation, rich-text sanitization, security headers,
   generic auth errors, audit logging. No secrets in git; validate prod env on
   startup.
6. **Do not invent Georgie's real-world facts.** Placeholders carry
   `verificationStatus:"needs_verification"` / `isVerified:false`. Sample reviews
   are dev-only (`isSample:true`) and never seeded in production.
7. **HeroUI v3 only** — compound components (`Card.Header`), semantic variants
   (`primary/secondary/tertiary/danger`), `onPress`. Do not reintroduce v2
   patterns (`HeroUIProvider`, flat props) or framer-motion for component
   animation (HeroUI animates in CSS; Framer Motion is only for page reveals).

## Layout

```
backend/app/{api,services,repositories,models,schemas,core,seed}
frontend/src/{app,components,features,pages/{public,admin},lib,i18n,styles}
docs/  scripts/  tests/  .github/workflows/
```

## Definition of done for a content type

model → repository → service (with publish/version bump) → admin API →
admin UI (list + form + publish) → public API (published-only) → public render →
seed data → test. Update `docs/` if the contract changes.
