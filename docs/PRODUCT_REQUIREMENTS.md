# Product Requirements — Svaneti with Georgie

_Last updated: 2026-07-14_

## 1. Mission

Help **Georgie**, a local guide in Upper Svaneti, Georgia, attract and convert
**international visitors** to guided experiences in and around **Mestia,
Ushguli and the Upper Svaneti mountains**. The product replaces ad-hoc social
messaging with a credible, multilingual web presence that:

1. presents Georgie's tours, destinations and story persuasively;
2. helps a prospective traveller **self-select the right experience**; and
3. captures a qualified **inquiry** (there are no online payments in v1).

The whole thing must be **maintainable by Georgie alone**, in three languages,
without a developer — hence the built-in CMS.

### Success looks like

- A visitor lands, understands what Svaneti offers, finds a matching tour, and
  submits an inquiry — in their language, on their phone.
- Georgie edits a price, publishes a new tour, or posts an offer from the
  dashboard and it appears on the live site within seconds, no rebuild.

## 2. Audiences

The public experience is designed for a range of visitor intents. Content,
filtering ("Help me choose"), and tour metadata all map to these:

| Audience | What they need surfaced |
|---|---|
| General leisure travellers | Overview, highlights, easy planning, trust signals |
| European hikers / trekkers | Distances, elevation gain, difficulty, seasons, trail detail |
| Adventure seekers | Challenging/strenuous tours, multi-day itineraries |
| Cultural travellers | Svan towers, Ushguli heritage, cultural notes, local life |
| Photographers | Gallery, viewpoints, best seasons/light, video |
| Couples | Private tours, scenic and relaxed framing |
| Families | Family-friendly flag, min age, low-intensity options |
| Older / low-activity visitors | `lowWalking` flag, accessibility notes, transport |
| Winter visitors | `winter` flag, seasonal tours, weather dependency notes |
| Gulf / Arab travellers | Full Arabic RTL site, Arabic content, relevant framing |
| Private-transport seekers | Transport needs captured in the inquiry, private tour type |

No audience is served with fabricated claims — see Non-goals.

## 3. The two systems

### 3.1 Public site (dynamic, anonymous)

Reads **published-only** content from `/api/public/*`. Language-prefixed routes
(`/:lang/...`), English default, Georgian and Arabic supported, Arabic in full
RTL. Every page is data-driven; a `content_version` counter makes edits appear
without a rebuild. SEO shell (titles, canonical, OG, JSON-LD, sitemap, robots).

### 3.2 Owner CMS / dashboard (authenticated)

Secure `/admin` area. Roles: **owner** (full control incl. users, settings
secrets, analytics) and **editor** (content, restricted from sensitive
settings/users). Every content type follows: create → edit → save draft →
schedule/publish → appears live. Full audit trail.

## 4. Feature scope by module

| Module | Scope |
|---|---|
| **Tours** | Rich tour records: localized name/descriptions, cover + gallery + promo video, destinations, categories, duration, distances, elevation/altitude, difficulty, fitness, group size, tour type (private/shared/custom), seasons, weather dependency, family-friendly / low-walking / winter flags, inclusions/exclusions/what-to-bring, itinerary, safety notes, price (**amount or "Contact for price"**), offers link, featured, SEO. Draft/schedule/publish. |
| **Destinations** | Places (Mestia, Ushguli…) with intro/description, coordinates + map, altitude, best seasons, gallery, videos, related tours & articles, cultural/practical/accessibility/safety notes. |
| **Banners** | Announcement/hero/internal/promo banners with placement, targeting (route globs, language), scheduling, priority, active flag, desktop/mobile media, overlay intensity, CTA. |
| **Offers** | Promotions with discount type (percent/fixed/display), code, terms, related tours, scheduling (auto-expire), featured, priority, language targeting. |
| **Popups** | Modals with targeting (page/language/device/audience), triggers (delay, scroll depth, exit intent), and **frequency** (once ever/session/day/every visit/custom days); client enforces frequency. Dismissible. |
| **Media** | Upload (validated) or register external YouTube/Vimeo; metadata, alt text/captions/credit, variants (thumb/card/hero), usage refs, replace-in-place, archive. **No binaries in Mongo.** |
| **Gallery** | Albums grouping media, with cover, ordering, publish flag. |
| **Videos** | Uploaded or YouTube/Vimeo, with poster, caption, featured, ordering. |
| **Travel guide** | Articles/blog with excerpt, rich body (sanitized), cover, author, categories/tags, related tours/destinations, reading time, SEO, draft/publish. |
| **Reviews** | Guest reviews with reviewer, country, rating, source, permission status, featured/published, `isSample` (dev only). **Never fabricated.** |
| **FAQs** | Localized Q&A grouped by category, ordering, publish flag. |
| **Inquiries** | Public lead form → CRM: contact, dates (+flexible), group size/children, selected tour, interests, activity level, transport needs, accommodation status, message, consent, marketing opt-in; status pipeline, notes, timeline, CSV export. Rate-limited & validated. |
| **Navigation** | Main menu, footer groups, social links, legal links, CTA button — all localized. |
| **SEO** | Per-route title/description/canonical/OG/robots defaults + per-document SEO block; sitemap.xml, robots.txt, JSON-LD. |
| **Settings** | Brand, tagline, logo/favicon/portrait, about, contact, socials, languages, currency, timezone, analytics IDs, cookie notice, emergency notice, global CTA, SEO defaults. |
| **Users** | Owner/editor accounts, activation, force-password-change (owner only). |
| **Audit** | Immutable log of logins, create/edit/publish/delete, media replace, settings/user changes. |

## 5. Non-goals (v1)

- **No online payments.** Isolated behind a disabled `FEATURE_PAYMENTS` flag.
  Conversion is via inquiry, not checkout.
- **No fabricated facts or reviews.** Georgie's real-world details are
  placeholders (`needs_verification`); sample reviews exist only in development,
  are marked `isSample`, and are never seeded in production.
- **No unlicensed media** committed to the repo.
- **No automated translation** presented as authoritative — English is
  required per field; `ka`/`ar` are entered/verified by the owner.
- No multi-tenant, no booking-calendar/availability engine, no separate mobile
  app — responsive web only.
- Only two roles (`owner`, `editor`).

## 6. Acceptance criteria

The build is accepted when all of the following hold:

1. **Two synchronized systems** — a dynamic public site and a secure owner
   dashboard in one deployment; dashboard edits appear on the public site with
   no source edit or rebuild (content-version polling).
2. **Draft/public separation** — `/api/public/*` never returns drafts or
   scheduled/unpublished content; a draft slug returns 404 publicly; preview
   requires a signed token.
3. **Publishing workflow** — draft → scheduled → published → archived, with
   effective-visibility windows (`publishAt`/`unpublishAt`) computed server-side.
4. **Full content coverage** — every module in §4 has model → repository →
   service → admin API → admin UI → public API → public render → seed → test
   for acceptance-critical flows.
5. **Trilingual + RTL** — en/ka/ar with English fallback; Arabic renders full
   RTL (`dir="rtl"`, logical CSS, mirrored components).
6. **Security** — Argon2 hashing, JWT HttpOnly cookies + rotating refresh, CSRF
   double-submit, login rate-limit + lockout, inquiry rate-limit, upload
   MIME/size validation, rich-text sanitization, security headers, CORS
   allow-list, generic auth errors, audit logging, prod insecure-default refusal.
7. **Media discipline** — no binary media in MongoDB; provider abstraction with
   variants; external video by URL.
8. **SEO shell** — per-route metadata, canonical, OG, JSON-LD, sitemap.xml with
   hreflang alternates, robots.txt.
9. **Owner-editable everything** — brand, contact, prices, tours, reviews, media
   and SEO all editable in the dashboard; no developer needed for content.
10. **No fabricated facts** — placeholders flagged for verification; the owner
    checklist enumerates what must be supplied before launch.
11. **Quality gates pass** — ruff + eslint clean, TypeScript strict typecheck,
    backend pytest (31) green, frontend unit tests green, Playwright e2e green,
    production builds succeed.
12. **Portable deployment** — `docker compose up` runs the full stack;
    seed + admin bootstrap documented; Emergent import path documented.
