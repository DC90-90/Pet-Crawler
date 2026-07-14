# Test Plan — Svaneti with Georgie

_Last updated: 2026-07-14_

Test strategy and the mapping from required behaviors to where they are
verified. Three layers: **backend integration tests (pytest)**, **frontend unit
tests (Vitest)**, and **end-to-end tests (Playwright)**. Static gates (ruff,
eslint, TypeScript strict) run alongside.

## 1. How to run everything

```bash
# Backend integration tests (in-process mongomock-motor — no Mongo server needed)
cd backend && pytest                 # 31 passing

# Frontend unit tests
cd frontend && npm run test          # vitest run

# End-to-end (Playwright) — needs the app running with the mock DB
cd frontend && npm run test:e2e

# Static gates
make lint                            # ruff + eslint
cd frontend && npm run typecheck     # tsc -b --noEmit
```

Or via the Makefile: `make test` (backend + frontend unit) and `make e2e`.

## 2. Backend tests (pytest) — `backend/tests/`

Backend tests run entirely in-process against **`mongomock-motor`**, so **no
MongoDB server is required**. Current status: **31 tests passing**.

| File | Covers |
|---|---|
| `test_auth.py` | Login success/failure, cookie issuance, refresh rotation, logout, generic errors, lockout after repeated failures, change-password / force-change |
| `test_authz.py` | Auth required on `/api/admin/*` (401 unauth), owner-vs-editor restrictions, CSRF enforcement on mutations |
| `test_tours.py` | Tour CRUD, **draft vs public separation** (draft slug 404 publicly), scheduling / effective visibility, publish bumps content-version |
| `test_public.py` | Public listing/detail, filters, content-version endpoint, ETag `"v<n>"` + `If-None-Match` → 304, SEO route payload + JSON-LD, sitemap/robots |
| `test_inquiries.py` | Inquiry create + validation, rate limiting (5/min/IP), IP hashing, status pipeline |
| `test_media.py` | Upload MIME/size validation, metadata + variants, external video registration, replace-in-place |

### Required-behavior → test map (backend)

| Required behavior | Where |
|---|---|
| Auth (login/refresh/logout/lockout) | `test_auth.py` |
| Authorization (admin gated, roles, CSRF) | `test_authz.py` |
| Tour CRUD | `test_tours.py` |
| Draft/public separation | `test_tours.py`, `test_public.py` |
| Scheduling / effective visibility | `test_tours.py` |
| Offer / popup activation windows | `test_public.py` (effective-visibility logic) |
| Inquiry create / validation / rate-limit | `test_inquiries.py` |
| Media metadata + validation | `test_media.py` |
| Content-version increments | `test_tours.py`, `test_public.py` |
| SEO endpoints (route/sitemap/robots/JSON-LD) | `test_public.py` |

The backend was also smoke-tested end-to-end against a **real Uvicorn process**
(seed → curl) using the mock DB fallback; see `backend/BACKEND_STATUS.md` for
the transcript and the exact commands to repeat it against a real `mongo:7`
container in an environment with registry access.

## 3. Frontend unit tests (Vitest) — `frontend/src/test/`

| File | Covers |
|---|---|
| `i18n.test.ts` | Language resolution, English fallback (`tt`), RTL detection (`isRtl`), direction application |
| `popupFrequency.test.ts` | Popup frequency logic (once ever / session / day / every visit / custom days) |

Extend with form validation (React Hook Form + Zod) and tour-filtering logic as
those modules evolve. Testing uses jsdom + Testing Library.

Target coverage areas: **i18n/RTL**, **popup frequency**, **forms** (inquiry and
admin), **tour filtering**.

## 4. End-to-end tests (Playwright) — `frontend/e2e/`

`public.spec.ts` currently implements the core public journeys. Run the backend
with `USE_MOCK_DB=true SEED_ON_STARTUP=true` and start the frontend, then
`npm run test:e2e` (Playwright config in `frontend/playwright.config.ts`).

Implemented scenarios include: root→language redirect + hero render; meaningful
SEO titles; published tour is public while a draft slug is **not**; Arabic
switches the interface to **RTL**; an unauthorized visitor **cannot** open the
dashboard; a visitor can **submit an inquiry**.

### Mandatory e2e scenario checklist (17)

Track each of these to a Playwright test (extend `public.spec.ts` / add specs
until all pass):

1. Root `/` redirects to a language-prefixed home; hero renders.
2. Public tours list renders published tours only.
3. A **published** tour detail is reachable; a **draft** slug returns not-found.
4. Tour filtering (difficulty/season/duration/family/low-walking/winter/private).
5. "Help me choose" returns a ranked recommendation.
6. Destinations list + detail render with map.
7. Travel-guide article renders; unpublished article not reachable.
8. Gallery and videos render (including an external YouTube/Vimeo embed).
9. Offers page shows only active/effective offers.
10. A popup appears per targeting and respects its **frequency** rule.
11. Language switch to **Georgian** localizes content.
12. Language switch to **Arabic** flips the UI to **RTL** (`dir="rtl"`).
13. Visitor **submits an inquiry** successfully; validation blocks bad input.
14. Inquiry rate limiting / abuse guard behaves.
15. Public **SEO**: pages expose meaningful titles/canonical; sitemap/robots served.
16. Unauthorized visitor **cannot** reach `/admin` (redirected to login).
17. Owner **logs in**, edits/publishes content, and the change appears on the
    public site (content-version refetch) — end-to-end publish loop.

Keep the numbering stable so CI and reviewers can map results to requirements.

## 5. Accessibility testing

- **Automated:** run an axe-core pass (e.g. `@axe-core/playwright`) on key public
  pages (home, tour detail, inquiry) and the login page — target zero critical
  violations. Include a light-and-dark-theme pass.
- **Manual:** keyboard-only walkthrough (skip link, focus order, dialog focus
  trap, `Esc` to close), screen-reader smoke test of the tour detail and inquiry
  form, RTL visual check in Arabic, contrast spot-checks in both themes.
- Assertions to encode: skip link present and functional; images have `alt`;
  status is never color-only; `<html>` `lang`/`dir` correct per language.

## 6. Static gates

| Gate | Command | Expectation |
|---|---|---|
| Python lint | `cd backend && ruff check .` | clean |
| JS/TS lint | `cd frontend && npm run lint` | clean (`--max-warnings=0`) |
| Types | `cd frontend && npm run typecheck` | strict, no errors |
| Backend build/import | `python -c "import app.main"` | imports OK |
| Frontend build | `cd frontend && npm run build` | succeeds |

## 7. Interpreting results

- **Pytest** prints `N passed`; the current baseline is **31 passed**. A failing
  auth/authz/draft-separation test is a **release blocker** — these encode the
  acceptance criteria in `docs/PRODUCT_REQUIREMENTS.md`.
- **Vitest** exits non-zero on any failure; watch mode is `npm run test:watch`.
- **Playwright** produces an HTML report (`playwright-report/`); a failed
  mandatory scenario blocks release. Re-run flaky specs headed
  (`--headed --debug`) to inspect.
- CI (`.github/workflows/ci.yml`) runs backend (ruff + pytest with
  `USE_MOCK_DB=true`) and frontend (lint + typecheck + build) on every PR and
  push to `main`, plus a dependency audit. CI does **not** deploy.

## 8. Test data

Seed content (`app/seed`) is deterministic: 10 tours (9 published, 1 draft to
prove separation), destinations, articles (drafts), FAQs, navigation, settings.
Sample reviews are dev-only (`isSample`, never in production). E2E relies on this
seed via `SEED_ON_STARTUP=true` with the mock DB.
