# Svaneti with Georgie — tourism website + CMS

A bilingual-plus (English / Georgian / Arabic) tourism website and content
management system for **Georgie**, a local guide in Upper Svaneti, Georgia
(Mestia, Ushguli and the surrounding mountains). It is **two systems in one
deployment**:

- a **dynamic public site** that markets tours, destinations, offers and a
  travel guide to international visitors; and
- a **secure owner dashboard / CMS** where Georgie publishes and edits every
  piece of content.

Content published in the dashboard appears on the public site **without a
rebuild or code change**: the public app polls a `content_version` counter and
refetches when it changes.

> **Brand & facts:** The brand name, tagline and every real-world fact about
> Georgie (surname, phone, prices, licences, reviews…) are **editable
> placeholders** flagged `needs_verification`. Nothing about Georgie is
> invented. Before go-live, complete [`docs/OWNER_CHECKLIST.md`](docs/OWNER_CHECKLIST.md).

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 · FastAPI · Pydantic v2 · MongoDB (Motor async) · Argon2 · JWT (HttpOnly cookies) · CSRF double-submit |
| Frontend | Vite · React 19 · TypeScript (strict) · Tailwind CSS v4 · **HeroUI v3** · React Router · TanStack Query · React Hook Form + Zod · i18next · Framer Motion |
| Media | Provider abstraction: local disk (dev) → Cloudinary / S3 (prod) + external YouTube / Vimeo. **No binaries in MongoDB** — metadata only. |
| Infra | Docker Compose (mongo + backend + frontend), GitHub Actions CI |

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Quickstart

### Option A — Docker (one command)

```bash
cp .env.example .env          # then edit secrets (see "Environment" below)
docker compose up             # or: make up
```

This starts three services — `mongo`, `backend` (:8000) and `frontend` (:5173).
Then seed content and create the first owner (in a second terminal):

```bash
docker compose exec backend python -m app.seed.run          # seed content
docker compose exec backend python -m scripts.create_admin  # create owner
```

### Option B — Local (no Docker for the app)

**Backend** (Python 3.11):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Mongo on :27017 (docker compose up -d mongo, or make db). To run WITHOUT Mongo,
# see "Running without MongoDB" below.
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Node 22):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

**Seed + first owner** (from repo root, backend venv active):

```bash
make seed          # python -m app.seed.run
make admin         # python -m scripts.create_admin
```

Interactive API docs: <http://localhost:8000/api/docs>.

---

## Environment

Copy `.env.example` to `.env` and fill it in. Highlights:

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` \| `production`. Production **refuses to start** with insecure defaults. |
| `MONGODB_URI` / `MONGODB_DB` | Mongo connection + database name (`svaneti`). |
| `JWT_SECRET` / `CSRF_SECRET` | Auth secrets. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `COOKIE_SECURE` | Must be `true` in production (HTTPS). |
| `CORS_ORIGINS` | Comma-separated allow-list of front-end origins. |
| `MEDIA_PROVIDER` | `local` \| `cloudinary` \| `s3`. |
| `ADMIN_SEED_EMAIL` / `ADMIN_SEED_PASSWORD` | Used by `make admin` to bootstrap the owner. |
| `FORCE_PASSWORD_CHANGE` | `true` → owner must change password on first login. |
| `FEATURE_PAYMENTS` | Online payments feature flag — **off** in v1. |
| `SEED_SAMPLE_REVIEWS` | Dev-only sample reviews. Forced `false` when `APP_ENV=production`. |

Full annotated list lives in [`.env.example`](.env.example). Front-end build-time
`VITE_*` vars are mirrored at the bottom of that file.

### Seeding & the first owner

- **Seed content** — `make seed` (`python -m app.seed.run`) loads destinations,
  10 tours (9 published, 1 left as a draft to demonstrate draft/public
  separation), articles, FAQs, navigation and settings. Sample reviews are
  seeded **only** outside production and are marked `isSample`.
- **Create the owner** — `make admin` (`python -m scripts.create_admin`) reads
  `ADMIN_SEED_EMAIL` / `ADMIN_SEED_PASSWORD` and, when `FORCE_PASSWORD_CHANGE=true`,
  forces a password change on first login. Re-running updates the existing owner.

### Running without MongoDB (dev only)

For a quick spin-up with no database server, the backend has an **in-process
mock DB** (`mongomock-motor`). It is disabled in production.

```bash
cd backend
USE_MOCK_DB=true SEED_ON_STARTUP=true uvicorn app.main:app --port 8000
```

`USE_MOCK_DB` and `SEED_ON_STARTUP` are hard-disabled when `APP_ENV=production`.
This mode is what the Playwright e2e suite uses.

---

## Routes

### Public site (language-prefixed: `/:lang/...`, `lang ∈ {en, ka, ar}`)

The root `/` redirects to a detected language. Arabic (`ar`) renders full RTL.

| Path | Page |
|---|---|
| `/:lang` | Home |
| `/:lang/tours` · `/:lang/tours/:slug` | Tours list · tour detail |
| `/:lang/destinations` · `/:lang/destinations/:slug` | Destinations list · detail |
| `/:lang/experiences` | Experiences / categories |
| `/:lang/about-georgie` | About the guide |
| `/:lang/gallery` · `/:lang/videos` | Photo gallery · videos |
| `/:lang/offers` | Offers |
| `/:lang/travel-guide` · `/:lang/travel-guide/:slug` | Travel guide list · article |
| `/:lang/reviews` | Guest reviews |
| `/:lang/plan-your-trip` · `/:lang/inquiry` · `/:lang/contact` | Planning · inquiry form · contact |
| `/:lang/privacy` · `/:lang/terms` | Legal |
| `/:lang/design-system` | **Dev-only** design-system showcase (not linked in nav) |
| `/:lang/*` | 404 |

### Admin dashboard

| Path | Page |
|---|---|
| `/admin/login` | Login |
| `/admin` | Overview |
| `/admin/pages`, `/tours`, `/destinations`, `/media`, `/banners`, `/offers`, `/popups`, `/gallery`, `/videos`, `/articles`, `/reviews`, `/faqs`, `/inquiries`, `/navigation`, `/seo`, `/settings`, `/users`, `/audit` | CMS modules |

Full HTTP contract: [`docs/API_SPECIFICATION.md`](docs/API_SPECIFICATION.md).

---

## Tests & quality

| Task | Command |
|---|---|
| Backend tests (pytest, uses `mongomock-motor`) | `cd backend && pytest` — **31 passing** |
| Frontend unit tests (Vitest) | `cd frontend && npm run test` |
| End-to-end (Playwright) | `cd frontend && npm run test:e2e` (backend with `USE_MOCK_DB=true`) |
| Lint | `make lint` (ruff + eslint) |
| Format | `make format` |
| Typecheck | `cd frontend && npm run typecheck` |
| Production build | `make build` |

Strategy, matrix and the mandatory e2e scenarios: [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md).

---

## Documentation map

| Doc | Contents |
|---|---|
| [`docs/PRODUCT_REQUIREMENTS.md`](docs/PRODUCT_REQUIREMENTS.md) | Mission, audiences, feature scope, non-goals, acceptance criteria |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System diagram, request flow, layers, publishing, i18n, deployment |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | MongoDB collections and schemas |
| [`docs/API_SPECIFICATION.md`](docs/API_SPECIFICATION.md) | Public / auth / admin HTTP API |
| [`docs/UI_UX_SPECIFICATION.md`](docs/UI_UX_SPECIFICATION.md) | The "Alpine" design system, IA, accessibility |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, controls, production checklist |
| [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) | Test strategy and matrix |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | Build plan, decisions, assumptions |
| [`docs/OWNER_CHECKLIST.md`](docs/OWNER_CHECKLIST.md) | Real-world info only the owner can supply |
| [`docs/EMERGENT_HANDOFF.md`](docs/EMERGENT_HANDOFF.md) · [`EMERGENT_PROMPT.md`](EMERGENT_PROMPT.md) | Importing into Emergent |
| [`CLAUDE.md`](CLAUDE.md) | Repository conventions and non-negotiable rules |

---

## License / media note

Placeholder media are neutral SVG gradients with clear replacement
instructions — no unlicensed stock is committed. Replace them with licensed
assets before launch (see the Owner Checklist).
