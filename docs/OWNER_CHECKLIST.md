# Owner Checklist — real-world information to provide

_Last updated: 2026-07-14_

Everything the software can build has been built. What it **cannot** invent is
the truth about Georgie, the tours and the business. Every such fact currently
ships as a **placeholder flagged `needs_verification`** (`isVerified: false`),
and sample reviews are dev-only. **Nothing here is fabricated** — you must supply
and verify each item before launch.

**How to read the tables:**
- **Status** starts as `needs_verification` for every row → change to
  `verified` once you enter the real value in the dashboard.
- **Where to edit** names the dashboard area (`/admin/...`) to enter it.

## 1. About Georgie (identity & credentials)

| Item | Status | Where to edit |
|---|---|---|
| Surname / full name | needs_verification | Settings → Brand/About; About Georgie content |
| Phone number | needs_verification | Settings → Contact (`phone`) |
| WhatsApp number | needs_verification | Settings → Contact (`whatsapp`) — powers the WhatsApp button |
| Public email | needs_verification | Settings → Contact (`email`) |
| Languages Georgie speaks | needs_verification | Settings → About / About Georgie page |
| Years of experience | needs_verification | About Georgie page content |
| Guiding licence(s) / registration | needs_verification | About Georgie page content |
| Certifications (mountain/guide) | needs_verification | About Georgie page content |
| First-aid qualification | needs_verification | About Georgie page content |
| Region / base location | needs_verification | Settings → Contact (`region`) |

> Do not publish a credential you cannot evidence. Leave it out until verified.

## 2. Vehicle & transport

| Item | Status | Where to edit |
|---|---|---|
| Vehicle make/model, capacity, 4x4? | needs_verification | About Georgie / tour details; Tours → transport-relevant fields |
| Whether transport/pickup is offered | needs_verification | Tours (inclusions); handled per-inquiry via the transport fields |

## 3. Tours — prices & availability

Seed tours use **`priceDisplay: "contact"`** ("Contact for price"). Replace with
real numbers only when confirmed.

| Item | Status | Where to edit |
|---|---|---|
| Real price per tour (amount + currency) | needs_verification | Tours → each tour → `priceDisplay: amount`, `priceAmount`, `currency` |
| Availability windows / seasons per tour | needs_verification | Tours → `seasons`, `weatherDependency`, scheduling |
| Group size min/max per tour | needs_verification | Tours → `groupSizeMin` / `groupSizeMax` |
| Difficulty, distances, elevation (accuracy) | needs_verification | Tours → itinerary/metrics fields |
| Inclusions / exclusions / what to bring | needs_verification | Tours → respective lists |
| Which tours are private vs shared | needs_verification | Tours → `tourType` |

## 4. Reviews (never fabricated)

Sample reviews exist **only in development** (`isSample: true`) and are never
seeded in production. Real reviews require the guest's content and permission.

| Item | Status | Where to edit |
|---|---|---|
| Real guest reviews (name, country, rating, text) | needs_verification | Reviews → add each real review |
| Permission to publish each review | needs_verification | Reviews → `permissionStatus` (granted/pending/unknown) |
| Source / link (Google, TripAdvisor…) | needs_verification | Reviews → `source` / `sourceUrl` |

## 5. Credibility — awards & partnerships

| Item | Status | Where to edit |
|---|---|---|
| Awards / recognitions | needs_verification | About Georgie page / relevant section |
| Partnerships (hotels, agencies, operators) | needs_verification | About / footer / dedicated section |

## 6. Brand & media assets (licensed)

Placeholder media are neutral SVG gradients — replace with **licensed** assets.

| Item | Status | Where to edit |
|---|---|---|
| Logo | needs_verification | Media → upload; Settings → `logoMediaId` |
| Favicon | needs_verification | Media → upload; Settings → `faviconMediaId` |
| Owner portrait | needs_verification | Media → upload; Settings → `ownerPortraitMediaId` |
| Tour / destination photos (with licence/credit) | needs_verification | Media → upload; set `altText`, `caption`, `credit` |
| Videos (uploaded or YouTube/Vimeo) | needs_verification | Videos / Media → register URL or upload |
| Social sharing image (OG) | needs_verification | Settings → SEO defaults (`socialImageMediaId`) |

> Confirm you hold the rights/licence for every image and video, and record the
> credit. No unlicensed stock.

## 7. Content copy & translations

| Item | Status | Where to edit |
|---|---|---|
| Brand name & tagline (final) | needs_verification | Settings → Brand |
| About / story copy | needs_verification | About Georgie page |
| Georgian (`ka`) translations | needs_verification | Every localized field (ka tab) |
| Arabic (`ar`) translations | needs_verification | Every localized field (ar tab) |
| FAQs (real answers) | needs_verification | FAQs |
| Legal: privacy & terms | needs_verification | Privacy / Terms pages |

## 8. Analytics, domain & secrets

| Item | Status | Where to edit / set |
|---|---|---|
| Google Analytics ID | needs_verification | Settings → Analytics (`gaId`) / env `GA_MEASUREMENT_ID` |
| Search Console verification | needs_verification | Settings → Analytics (`gscVerification`) / env `GSC_VERIFICATION` |
| Meta Pixel ID (optional) | needs_verification | Settings → Analytics (`metaPixelId`) / env `META_PIXEL_ID` |
| Production domain | needs_verification | Deployment env (`FRONTEND_URL`, `PUBLIC_SITE_URL`, `CORS_ORIGINS`, `canonicalBaseUrl`) |
| Production secrets (`JWT_SECRET`, `CSRF_SECRET`) | needs_verification | Deployment secret manager (not in git) |
| Media provider credentials (Cloudinary/S3) | needs_verification | Deployment env |
| SMTP (optional inquiry emails) | needs_verification | Deployment env (`EMAIL_ENABLED`, `SMTP_*`, `INQUIRY_NOTIFY_TO`) |

## 9. Pre-launch sign-off

- [ ] All identity/credential rows verified (or removed if unverifiable).
- [ ] Contact phone / WhatsApp / email real and tested.
- [ ] Every tour has a real price or an intentional "Contact for price".
- [ ] Only real, permission-granted reviews are published; no samples in prod.
- [ ] Logo, favicon, portrait and photos replaced with licensed assets + credits.
- [ ] Georgian and Arabic content reviewed by a fluent speaker (Arabic RTL checks).
- [ ] Privacy & terms finalized.
- [ ] Analytics IDs and domain configured; canonical URL correct.
- [ ] Production secrets set; `COOKIE_SECURE=true`; `APP_ENV=production`.
- [ ] Media provider configured (not local disk).
