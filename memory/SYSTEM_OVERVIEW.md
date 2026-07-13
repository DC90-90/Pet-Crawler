# 🏗️ DALEEL — Complete System Summary
### Competitor Price & Market Intelligence Platform for Saudi E-commerce Stores

**Production URL:** `https://saudi-pets-monitor.emergent.host` (live, in daily use)
**Stack:** React 18 + FastAPI + MongoDB (Motor) + APScheduler + Playwright

---

## 1. 🕷️ Multi-Tier Crawler Engine (`crawlers.py`, ~1,800 lines)

A waterfall crawling architecture that attempts progressively deeper methods until one succeeds per store:

- **Tier 1 — Salla/Zid JSON API crawl:** Hits known storefront JSON endpoints (`/products.json`, Salla store APIs) with endpoint auto-discovery, endpoint caching per store, and full pagination handling.
- **Tier 2 — Playwright XHR interception:** Launches a headless browser, navigates and auto-scrolls the storefront, intercepts background XHR/API responses, and extracts product payloads from network traffic.
- **Tier 3 — HTML scraping fallback:** Parses rendered HTML product cards with platform-specific CSS selector sets (name/price/image/URL extraction with multiple selector fallbacks).
- **Salla storefront category crawl:** Discovers category IDs via Playwright, captures the store identifier from network requests, then paginates every category (up to 200 categories × 200 pages) to reach full-catalogue coverage (~300+ products minimum target).
- **Tier 4 — Authenticated crawling:** Logs into merchant/store accounts with encrypted stored credentials, handles session cookies, supplements public data with authenticated-only fields (exact stock quantities). Includes:
  - **OTP flow:** Pending-OTP queue, `/api/otp/submit`, `/api/otp/retry`, `/api/otp/status` endpoints and a frontend `OtpBanner.jsx` so the user can type the SMS OTP live during login.
  - **Credential encryption** at rest (with `/api/encryption/verify` health check).
  - Tier-4 status/test-login/clear-session admin endpoints.
- **Saudi Residential Proxies (Webshare):** All blocked stores are crawled through Saudi-IP residential proxies; per-store **proxy bandwidth usage tracking** is recorded and surfaced via `/api/admin/proxy-usage`.
- **Data normalization pipeline:** Every raw product goes through `_normalize_raw_product` → brand extraction, category guessing, animal-type guessing (pet market), weight extraction from names, price parsing from text, URL absolutization.
- **Crawl observability:** Every crawl writes a `crawl_log` (tier attempted, products found, duration, errors) viewable via `/api/stores/{id}/crawl-logs`.
- **External Ingest API** (`POST /api/crawler/ingest`, bearer-token secured): allows an external Saudi-IP machine to run crawls and push snapshots into the platform — bypassing datacenter-IP blocks entirely.
- **APScheduler:** Automatic recurring crawls of all active stores, with pause/resume toggle (`/api/scheduler/toggle-pause`, `/api/scheduler/status`).

---

## 2. 🏪 Own-Store Sync (Zid Merchant API)

- `sync_own_store_prices()` pulls the user's **own catalogue directly from Zid's official Merchant API** (API key + manager token in `.env`) every 6 hours.
- Extracts SKU, **barcode (EAN-validated)**, Arabic name, price, quantity, and `present_on_store` flag into the `my_products` collection.
- Full **sync-run observability**: `sync_runs` collection tracks `started_at/finished_at/sync_status/sync_error/match_added`; surfaced on the Import page (`/api/import/status`, `/api/import/sync-own-store`).
- Sync hardening (iter18): failure isolation, partial-sync detection, stale-data guards.

---

## 3. 🎯 Product Matching Engine (`matcher.py`)

Strict, conservative matcher linking *my products* to *competitor snapshots*:

- **Level 1 — Barcode matching** (confidence 99): exact EAN match, with `_is_valid_barcode` guards against junk/placeholder barcodes.
- **Level 2 — SKU-string matching** (confidence ≥85): normalized SKU comparison, Zid `-suffix` variant safety.
- **Name matching deliberately DISABLED** (user decision — too many false positives).
- **P1 Confidence floor:** matches below 85 confidence are never created.
- **Pack-indicator guard:** blocks matching a single unit to a multipack — fixed in iter20 with **token-boundary Arabic parsing** (`PACK_TOKEN_SPLIT_RE`) so words like `متعددة` no longer cause false substring rejections (unlocked 26 new barcode matches).
- **Price-ratio logic (iter21):** hard-reject of >2.0 price ratios **removed for Level-1 barcode matches** (aggressive discounts are legitimate); a `SUSPICIOUS_PRICE` flag is applied only to Level-2 SKU matches.
- Manual match management: `POST /api/price-intel/confirm-match` and `reject-match`.
- Healing trigger: `POST /api/import/run-matching` re-runs the full matcher.

---

## 4. 📈 Sales Estimation & Market Analytics (`core/utils.py`)

- **Inventory-delta sales estimator:** infers units sold from quantity drops between consecutive snapshots, with **delta clamps** (restock detection, outlier suppression, sold-count sanity limits).
- `compute_product_metrics()`: per-product min/max/avg competitor price, stock signals, sold estimates per time window (7/14/30/90 days).
- `compute_market_position()`: ranks the user's price among all sellers (cheapest/mid/most expensive).
- **Stock signal classification** (in stock / low / out of stock) from qty + boolean flags.
- **TTL cache decorator** (60s) applied to heavy endpoints.

---

## 5. 📊 My Products Dashboard (`MyProductsPage.jsx` + `GET /api/my-products`)

The core screen — a rich analytical table of the user's full catalogue vs. the market:

- Per-product: my price, competitor min/avg/max price, price-gap %, **market position badge**, stock status, estimated units sold (mine + market), **market share %**, competitor count.
- **Iter20 barcode-safe union:** `num_competitors` is computed directly from the snapshot index (all stores carrying the product, incl. out-of-stock/priceless), decoupled from matcher freshness; separate `num_priced_competitors` for pricing math — with an explanatory **"X carry · Y priced" tooltip**.
- Time-window selector (7/14/30/90D), SKU/barcode/name search, category/stock/position filters, saved filters (`/api/saved-filters`).
- **Honest KPI block:** matched-product count, market coverage % (no fair-share inflation), avg market share, total units sold, estimated market revenue — with `has_competitor_pricing` / `has_market_share` splits (iter19).
- **DataFreshnessBanner + FreshnessBadge:** per-store crawl recency indicators (`/api/data-freshness`).
- Product detail panel (`ProductDetailPanel.jsx`): per-competitor price/stock breakdown, price history, velocity.

---

## 6. 💰 Price Intelligence Module (`PriceIntelPage.jsx` + `priceIntel/` components)

- Dedicated dashboard (`/api/price-intel/dashboard`): cheaper/pricier/equal segmentation vs. market, urgent repricing candidates.
- Per-product deep-dive sheet (`/api/price-intel/product/{sku}`): every competitor's current price, history chart, match confidence & method, confirm/reject match controls.
- Tabs, header KPIs, shared UI primitives split into `PriceIntelHeader/Tabs/Shared/DetailSheet`.

---

## 7. 🔍 Insights & Market Intelligence (`InsightsPage.jsx`, `SalesInsights.jsx`)

Endpoints powering multiple analytics tabs:
- `/api/insights/summary` — market overview KPIs
- `/api/insights/leaderboard` — store rankings by estimated sales/revenue
- `/api/insights/top-sellers` — best-selling products in the market
- `/api/insights/trending` — rising products
- `/api/insights/gaps` — products competitors sell that I don't (catalogue gaps)
- `/api/insights/price-wars` — products with rapid multi-store price drops
- `/api/insights/restock-opportunities` — products OOS at competitors but in stock with me
- `/api/insights/sales` — estimated sales analytics with brand/category aggregations (Recharts visualizations)
- Seasonal annotations overlay (`SeasonalAnnotations.jsx` — Ramadan, etc.)

---

## 8. 🏷️ Discounts Module (`DiscountsPage.jsx`)

- `/api/discounts/top-pct` — biggest % discounts in the market
- `/api/discounts/top-amount` — biggest absolute SAR discounts
- `/api/discounts/timeline` — discount activity over time
- `/api/discounts/aggression` — which competitors discount most aggressively

---

## 9. 🔭 Scanner & Opportunities (`ScannerPage.jsx`)

- `/api/scanner/opportunities` — cross-market opportunity finder (underpriced/overpriced items, margin opportunities).

---

## 10. 🔔 Alerts & Notifications

- Full CRUD alerts (`/api/alerts` + toggle/delete): price-drop, stock-out, undercut alerts with thresholds.
- `/api/alerts/check` — evaluation engine; `/api/alerts/auto-generate` — smart alert suggestions.
- Alert feed + `NotificationBell.jsx` (`/api/notifications`).
- **Digests:** generated market summary reports (`/api/digests`, `/digests/latest`, `/digests/generate`) shown in `DigestModal.jsx`.
- Webhooks (Slack/Telegram) and Resend email — **planned, not yet built** (email is MOCKED/pending API key).

---

## 11. 🏬 Store Registry & Competitor Profiles

- `StoreRegistryPage.jsx`: full store CRUD (`/api/stores`), platform tagging (Salla/Zid), per-store manual crawl trigger, crawl logs, Tier-4 credential management.
- `CompetitorProfilePage.jsx` (`/api/stores/{id}/profile`): per-competitor deep dive — catalogue size, pricing posture, discount behavior, estimated sales, raw product browser (`/api/stores/{id}/raw-products`).

---

## 12. 📥 Import, Baseline & Export

- `POST /api/import/products` — CSV/manual catalogue import.
- **Baseline module:** `POST /api/baseline/import` + leaderboard/catalog-gaps/product-stats endpoints — one-time market baseline snapshot analytics.
- `GET /api/export/products` — CSV export of the full dashboard dataset.

---

## 13. 🔐 Authentication & RBAC

- **JWT auth in httpOnly cookies** (register/login/logout/me).
- **Super Admin (god mode, immutable):** `a.disi@taqueen.sa` — cannot be deleted/demoted.
- **3-tier role system** + **per-user `allowed_pages`** granular page access (`UsersPage.jsx` admin UI: create users, change roles, reset passwords, assign pages).
- Admin utilities: recent-snapshots viewer, own-snapshot cleanup, proxy-usage dashboard, `/api/health` + `/api/health/detailed`.

---

## 14. 🎨 Frontend & Visual Identity

- **HRM-SA brand identity:** flat dark `#090E1C`, teal accent `#1E988E`, Space Grotesk + Inter + JetBrains Mono + DIN Next LT Arabic fonts.
- **Light/Dark theme toggle**, Arabic **RTL support**, SAR currency formatting, i18n layer (`lib/i18n.js`).
- **React Query** for all data fetching/caching, **route-based lazy loading**, Recharts charts, shadcn/ui components, Sidebar navigation across 12 pages.

---

## 15. ⚡ Performance Engineering

- 60s TTL cache on heavy endpoints, compound MongoDB indexes on `product_snapshots`, frontend query caching, lazy-loaded routes.
- **Known scale limits (documented):** production has >1M snapshots vs preview's ~271k — this caused the iter21 incident.

---

## 16. 🧪 Test Coverage

**100+ pytest regression tests** across 17 files: matcher pack-indicator, competitor-count union, confidence floor, sales estimator math, KPI baselines, API contracts, sync hardening, coverage split, Tier-4/OTP flows, deployment readiness, truncation/ratio behavior.

---

## 17. 📌 Current Known State / Open Items

| Item | Status |
|---|---|
| `/api/my-products` aggregation re-architecture (50k truncation on prod) | 🔴 **P0 — DEFERRED by user** (hotfix live, dashboard functional) |
| `/api/data-freshness` intermittent 500s at prod scale | 🟡 P1 (masked by TTL cache) |
| Brand missing on 93% of crawled products | 🟡 P1 |
| Test-store cleanup + Market Share tooltip | 🟢 P2 cosmetic |
| `server.py` refactor into `routes/` (5,174 lines) | 🔴 P0 — queued last per user instruction |
| Resend email, curl_cffi Cloudflare bypass, sitemap discovery, webhooks, Mahally enrichment | Backlog |

---

**~7,400 lines of backend logic, 12 frontend pages, ~80 API endpoints, a 4-tier crawler, a strict matching engine, and a complete market-intelligence analytics suite** — live in production and in daily use.

---

## Addendum — July 2026 session (branch `claude/pet-store-market-crawler-3gh4ys`)

Added on top of the system described above:

- **`backend/store_registry.py`** — store registry extracted from `server.py` into a
  single shared module; expanded from 11 to **47 stores** after a market-discovery
  sweep: 24 newly found Saudi Salla/Zid pet stores (Waggy, Cat Fans, Anyab, My Cat ×3,
  Refq, Whiskers, 4 `*.zid.store` shops, 10 `salla.sa`-hosted shops, …) plus 5
  inactive non-Salla/Zid context players (Petzone, Pet Arabia, Beauty Pets, …).
  Each entry stores its platform-verification evidence. Flagged: cutecat.com.sa may
  have migrated from Salla to WooCommerce.
- **`backend/run_market_crawl.py`** — one-command headless pipeline (own-store sync →
  concurrent competitor crawl → matching → CSV/JSON market report) for environments
  without the full dashboard; report math is pure Python so it also runs on FerretDB.
- **`SEED_DEMO_DATA=false`** env flag — skips the synthetic demo seed on real deployments.
- `.env.example` + README runbook (including network egress requirements).
- Note: sandboxed Claude Code sessions have a locked-down egress policy — store
  domains and even the production host are unreachable from there unless the
  environment's network access is set to full/trusted.
