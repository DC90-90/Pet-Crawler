# Implementation Plan — Svaneti with Georgie

_Last updated: 2026-07-14_

## 0. Context & decision log

This repository previously contained an unrelated product ("Daleel", a Saudi
competitor-price crawler). That code was scaffolded by an earlier Emergent job
into the base image. Per the master implementation prompt, this branch
(`claude/mestia-svaneti-tourism-site-c692br`) is dedicated to a **new** product:
**Svaneti with Georgie**, a tourism website + CMS.

**Decision (recorded assumption A0):** The Daleel product code was removed from
the working tree on this branch and the Svaneti application was built at the
repo root (`/frontend`, `/backend`, `/docs`). The Daleel code remains intact on
`main` and in full git history, so nothing is lost. This matches the branch name
and the structure the master prompt expects.

## 1. Architecture at a glance

- **Backend:** Python 3.11 · FastAPI · Pydantic v2 · MongoDB (Motor async) ·
  Argon2 password hashing · JWT in HttpOnly cookies · CSRF double-submit ·
  service/repository layering · OpenAPI docs.
- **Frontend:** React 19 · TypeScript (strict) · Vite · Tailwind CSS v4 ·
  **HeroUI v3** (`@heroui/react` + `@heroui/styles`) · React Router · TanStack
  Query · React Hook Form + Zod · i18next (en/ka/ar, Arabic RTL) · Framer Motion
  (restrained) · dnd-kit (section/media ordering).
- **Media:** provider abstraction (local dev disk → Cloudinary/S3 in prod) +
  external YouTube/Vimeo URLs. Binary bytes are **never** stored in MongoDB —
  only metadata documents.
- **Dynamic content:** every public page reads published content from the API.
  A `content_version` counter increments on every publish; the public app polls
  `/api/public/content-version` and invalidates queries so changes appear
  without a rebuild.

## 2. Execution order (mapped to the master prompt phases)

1. **Planning & docs** — this file + the `docs/*` set + `CLAUDE.md` + `README`.
2. **Design system** — HeroUI v3 + a bespoke "Alpine" theme (oklch tokens) +
   `/design-system` dev-only gallery page.
3. **Full-stack build** — DB models, auth, public + admin APIs, dashboard,
   dynamic public site, media, publishing, inquiries, SEO shell, seed content.
4. **Verification** — format, lint, typecheck, unit/integration/e2e, a11y,
   production builds. Fix before proceeding.
5. **Git + Emergent handoff** — intentional commit, `EMERGENT_PROMPT.md`, detect
   Emergent MCP, prepare GitHub import.

## 3. Assumptions (implemented, owner may override in dashboard)

| # | Assumption |
|---|------------|
| A1 | Brand = "Svaneti with Georgie"; tagline "Local journeys through Mestia, Ushguli and the mountains of Svaneti." Both editable in Site Settings. |
| A2 | All of Georgie's real-world facts (surname, phone, WhatsApp, email, prices, licences, languages, vehicle, reviews) are **placeholders** flagged `needs_verification` / `isVerified:false`. See `docs/OWNER_CHECKLIST.md`. |
| A3 | Seed tours use `priceDisplay: "contact"` ("Contact for price") until real prices are entered. |
| A4 | Default language English; Georgian (`ka`) and Arabic (`ar`) supported; Arabic renders full RTL. |
| A5 | No online payment in v1 (isolated behind a disabled `FEATURE_PAYMENTS` flag). |
| A6 | Sample reviews are seeded **only** in development and are visibly marked sample; production seed omits them. |
| A7 | Placeholder media are SVG gradients / neutral assets with clear replacement instructions; no unlicensed stock media is committed. |
| A8 | Map uses OpenStreetMap tiles via Leaflet (no API key needed). |
| A9 | Two roles in v1: `owner`, `editor`. |

## 4. Coverage in this session (transparency)

Built and wired end-to-end: auth, site settings, tours (draft/publish/schedule),
destinations, banners, offers, popups, inquiries, media metadata, gallery,
videos, travel-guide articles, reviews, FAQs, navigation/footer, SEO endpoints,
content-version, audit log, seed + admin bootstrap, Docker, CI, tests.

Where breadth exceeded a single session, modules are implemented as complete
vertical slices (model → repository → service → API → admin UI → public
rendering) for the acceptance-critical flows, with the remaining content types
sharing the same generic CRUD scaffold. Anything partial is called out in the
final report and `docs/EMERGENT_HANDOFF.md` — no fake completeness.
