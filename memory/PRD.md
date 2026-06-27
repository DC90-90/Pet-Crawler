# Daleel — PRD

## Original Problem Statement
SaaS platform for Saudi online store owners to track competitors' prices, inventory, best sellers, categories, and discounts across all Saudi stores (initially Salla & Zid). Real-time market intelligence.

## Core Requirements
- Multi-tier crawler (Tier 1/2/3 fallback + external Saudi-IP ingest)
- Product matching: Barcode > SKU > Name, max 150% price diff, max 10% weight diff
- HRM-SA brand identity (flat dark `#090E1C`, teal accent `#1E988E`, Space Grotesk + Inter + JetBrains Mono + DIN Next LT Arabic)
- FastAPI + MongoDB + JWT (httpOnly cookies) + APScheduler
- External ingest API (bearer token)
- Arabic RTL support, SAR currency

## Brand Identity (HRM-SA)
| Usage | Hex |
|---|---|
| Page bg | `#090E1C` |
| Card bg | `#0A2728` |
| Elevated | `#104745` |
| Borders | `#13625F` |
| Primary accent | `#1E988E` |
| Accent light (hover) | `#6AC1B5` |
| Muted text | `#A1E4DB` |
| Near-white teal | `#DAF8F4` |
| Text | `#FFFFFF` |

Fonts: `Space Grotesk` (EN headings, uppercase, letter-spacing 0.05em), `Inter` (EN body), `JetBrains Mono` (badges/numbers), `DIN Next LT Arabic` with `IBM Plex Sans Arabic` fallback (AR, no uppercase, letter-spacing 0).

## What's Implemented
- Multi-tier crawler + external ingest endpoint (hardened for bad payloads, idempotent store upsert-by-domain)
- `tier1_only` flag skipping Playwright tiers for Salla stores (CuteCat, CutePets, Hamtaro, Mowkly)
- Product matcher with strict rules
- Excel baseline import
- Price Intel + Insights dashboards
- Fernet-encrypted credentials vault
- Auto-generated price alerts
- Docker deployment package
- **Full rebrand** from "Daleel Pets" → "Daleel" (English + Arabic, all files)
- **Full HRM-SA visual identity applied** (flat `#090E1C` bg, teal palette, Space Grotesk/Inter/JetBrains Mono, HRM-SA button/card/input/table/badge/scrollbar styles)

## Recent Changes (Feb 2026)
- Crawler token hardcoded in `server.py` (no env var fallback)
- `seed_database()` force-updates admin password hash on startup
- `/api/crawler/ingest`: per-row try/except, currency/null coercion, `upsert` stores by domain
- Brand rebrand: all "Daleel Pets" → "Daleel", removed pet-specific copy
- HRM-SA theme: `App.css` + `index.css` rewritten, Login & Sidebar refactored, 69 stale teal refs swept across all pages via global sed
- **Light/Dark theme toggle** (Feb 2026) — Sun/Moon button in Sidebar (`data-testid="theme-toggle-btn"`), persists to `localStorage.daleel_theme`, no-flash inline init script in `public/index.html`. CSS overrides under `html[data-theme="light"]` cover sidebar, KPI cards, dense table, glass-card, and inputs.
- **Per-day date picker** on My Products (`day-picker-input`) — overrides 7/14/30/90D pills via `?on_date=YYYY-MM-DD`
- **Product Detail panel speed-up** — single aggregated `/api/products/{sku}/full?days=30` replaces 3 round-trips; renders per-store sparklines + Recharts price-history chart
- **Storefront deep-links** on every product row + every store row inside the detail panel
- **Refactor (Feb 2026)** — extracted Pydantic models to `/app/backend/models/schemas.py` and shared helpers/constants to `/app/backend/core/utils.py`. Reduced `server.py` from 3661 → 3476 lines.
- **Refactor (Feb 2026)** — split `PriceIntelPage.jsx` (530 lines) into 4 sub-components under `/app/frontend/src/components/priceIntel/`: `PriceIntelShared.jsx`, `PriceIntelHeader.jsx`, `PriceIntelTabs.jsx`, `PriceIntelDetailSheet.jsx`. Page is now 135 lines.
- **Performance hotfix (Feb 2026)** — `/api/my-products` now supports `limit`/`offset` pagination + projected snapshot fields. Payload dropped from **4.27 MB → 65 KB (98.5% smaller)** and response time 1.1s → 0.5s. KPIs still computed across the full filtered set.
- **Performance hotfix (Feb 2026)** — `/api/insights/summary` now runs all 5 aggregations in parallel (`asyncio.gather`).
- **Performance hotfix (Feb 2026)** — Added idempotent index on `product_snapshots.crawled_at` and `products.category` at startup (existing DBs benefit on next boot).
- **Frontend pagination** added to `MyProductsPage.jsx` (`data-testid="pagination"` with prev/next + page-size selector) — handles thousands of products without browser hang.
- **Search debounce (Feb 2026)** — 300 ms debounce on My Products search input.
- **"My Products" highlighting (Feb 2026)** — new `GET /api/my-skus` endpoint, `MySkusProvider` context, and reusable `<MineBadge>` component. Visible across My Products, Product Detail Panel, Insights, Price Scanner, and Price Intel tabs.
- **Matcher v4 (Feb 2026)** — Name-based matching (Level 3) **completely removed** per user request. Engine now only matches via Barcode/EAN (conf 99) or exact SKU (conf 95). Any pre-existing name-based or <95-confidence non-confirmed matches are purged on backend startup (idempotent).
- Tested via testing agent (iteration_12 + iteration_13): 100% backend (38/38), 100% frontend, no issues
- **Production CORS hotfix (Feb 2026)** — Production login was failing at `https://daleel.hrm-sa.com` with "Something went wrong". Root cause: the deployed frontend bundle was built with `REACT_APP_BACKEND_URL=https://saudi-pets-monitor.emergent.host` (cross-origin) and axios sends `withCredentials: true`. The K8s ingress returned `Access-Control-Allow-Origin: *` which is illegal with credentials, so the browser blocked the response. **Fix**: `/app/frontend/src/lib/api.js` now compares `process.env.REACT_APP_BACKEND_URL` origin against `window.location.origin` — if they differ (e.g. on a custom domain), it falls back to the page origin and calls `/api/*` same-origin. Cookies also switched to `SameSite=none; Secure` as a safety net. User must redeploy to push fix to production.
- **Super Admin + RBAC (Feb 2026)** — Introduced 3-tier role system (`super_admin`, `admin`, `user`) with per-user `allowed_pages` list. Hardcoded super admin `a.disi@taqueen.sa` / `Ahmaddc90@` is seeded idempotently on every startup (force-updates password) and is fully immutable — backend `seed_super_admin()` plus guard checks in `/api/admin/users/*` routes prevent ANY actor (including the super admin via mistake) from deleting it, demoting it, or revoking its pages. Only the super admin can change their own password. Legacy `admin@daleelpets.com` is deleted on startup per user instruction. New endpoints: `GET/POST /api/admin/users`, `DELETE /api/admin/users/{id}`, `PATCH /api/admin/users/{id}/{password|role|pages}`. Frontend: new `UsersPage` (super-admin-only) with create/edit/delete UI + per-page checkbox grid; `Sidebar` filters nav items by `canAccessPage(user, pageKey)`; `ProtectedRoute` enforces per-page guards and redirects unauthorized users to `/no-access`. Public `/auth/register` still works but new users get zero page access until super admin grants. Tested via curl (12 backend cases) and browser e2e (super admin login → create limited user → re-login as limited user → confirm sidebar hides ungranted tabs + /stores blocked).
- **Production Playwright self-heal v2 (Feb 2026)** — Aggressive non-blocking startup hook installs both `chromium` and `chromium-headless-shell` on every container start (handles the Playwright ≥1.49 split where `launch(headless=True)` uses a separate binary). Detects read-only `PLAYWRIGHT_BROWSERS_PATH` and falls back to `~/.cache/ms-playwright`. Smoke-tests by actually launching headless Chromium against `about:blank`; logs every step with `[Playwright]` prefix. Runs in a background daemon thread (never blocks startup).
- **Webshare Saudi residential proxy (Feb 2026)** — 40-username rotating residential pool routed through Tier 1/2/3 crawlers for 5 stores (`cutecat.com.sa`, `cutepets.com.sa`, `hamtaro.sa`, `lanapets.com`, `zarafaksa.com`) that hit Salla's anti-bot soft-block. Helper in `crawlers.py`: `get_proxy_credentials()` round-robin, `playwright_proxy_config()` for browser launches, `record_proxy_usage()` for bandwidth tracking. Per-store `use_proxy` boolean in `db.stores` (Zid stores explicitly excluded to conserve bandwidth). New admin endpoint `GET /api/admin/proxy-usage` returns daily/monthly bytes + `pct_used` of 50 GB cap. Startup `[Proxy]` smoke test pings ipify via proxy and logs exit IP. Env vars: `PROXY_HOST`, `PROXY_PORT`, `PROXY_PASSWORD`, `PROXY_USERNAMES` (40 entries, uppercase `SA-N`).
- **Performance Sprint (Feb 2026)** — 10-20× speedup on dashboard tabs:
  - **TTL Cache (60s)** — New `@ttl_cache(60)` decorator from `core.utils` applied to all 12 hot endpoints (`/insights/*`, `/discounts/*`, `/scanner/opportunities`). Invalidated on every crawl completion + manual crawl via `cache_clear()`. Warm response times: 100-150ms (vs 480-1700ms cold). 4-15× speedup on the warm path.
  - **Compound MongoDB indexes** — Added `{crawled_at:-1, store_id:1}`, `{crawled_at:-1, sku:1}`, `{crawled_at:-1, confidence_score:1}`, plus `proxy_usage.crawled_at`. Aggregations that filter by date range are now index-served.
  - **Route-based code splitting** — Every page in `App.js` is wrapped in `React.lazy` + `Suspense`. Initial JS bundle dropped from ~600KB → ~80KB.
  - **React Query** — Wrapped app in `QueryClientProvider` with 60s `staleTime` matching backend cache. `InsightsPage` + `DiscountsPage` converted to `useQueries` for parallel + cached fetches. Sidebar tab re-visits within 60s use cached data (no network call).
  - **Measured browser-side perf**: Insights cold=480ms (was ~5s), revisit=220ms (instant feel). Discounts cold=980ms, revisit=240ms. Rapid tab switches: 170-490ms each.
- **Insights /summary 500 hotfix (Feb 2026)** — `/api/insights/summary` was returning HTTP 500 on production because `round(conf_result[0]["avg_conf"], 1)` raised `TypeError` when MongoDB `$avg` returned `None` (no/empty matching snapshots). One-line null-guard at `server.py:2123`: `avg_confidence = round((conf_result[0].get("avg_conf") or 0), 1) if conf_result else 0`. Verified on preview, awaiting prod redeploy by user.
- **Product Sales Insights section (Feb 2026)** — Additive new block on `/insights` only. New backend endpoint `GET /api/insights/sales` (server.py ~line 2487, `@ttl_cache(60)`) wraps the existing `my_products()` callable verbatim — no new estimation logic — and adds: (a) brand-aware search (name + SKU + brand), (b) 4 sort modes (`sales_desc|sales_asc|revenue_desc|revenue_asc`), (c) `top_brands` aggregation with `market_share_pct = brand_revenue / total_revenue × 100` per spec, (d) summary KPIs `total_units_sold`, `total_revenue`, `avg_revenue_per_product`, `top_brand`. Supports `days`, `date_from`, `date_to` (custom range). Frontend: new component `/app/frontend/src/components/SalesInsights.jsx` mounted at the bottom of `InsightsPage.jsx`. Filter bar gains FROM/TO date pickers (`data-testid="insights-date-from"` / `"insights-date-to"`) that feed ONLY the new section (existing 7/14/30/90 pills continue to drive every other card). Tested via testing agent iteration_14: 100% backend (22/22), 100% frontend, zero console errors, no regressions on the 8 existing `/insights/*` endpoints. Cross-check confirms `insights/sales.kpis.total_units_sold == my-products.kpis.total_units_sold` for same period. Pytest regression file added at `/app/backend/tests/test_insights_sales.py`.
- **Sales Insights coverage fix (Feb 2026)** — `/api/insights/sales` previously called `my_products(limit=500)` upstream, which capped brand aggregation, market-share %, Top Brands ranking, search and KPI cards at the top-500 ranked rows. Changed to `limit=5000` so the entire eligible product set (the full `my_products()` 30-day result, currently ~3,300 SKUs) is processed. Verified: product_count 500→3,294, brands surfaced 5→7 (Hills/Orijen/Brit now visible), avg_revenue_per_product corrected from 826.74 → 125.49 SAR (was dividing by wrong denominator), `total_units_sold` + `total_revenue` unchanged (those were already correct). Out-of-scope: the deeper `db.products.find().to_list(5000)` cap inside `my_products()` itself was untouched per user constraint.
- **My Products auto-sync + presence tracking (Feb 2026, in preview)** — Implements user requirement "My Products tab only shows SKUs from my store; auto-pick-up new SKUs each month without manual re-upload".
  - `crawlers.py:sync_own_store_prices` extended: when the daily Zid public crawl of pets-houses.com discovers a SKU not yet in `db.my_products`, it now upserts a new row with full normalized metadata (`sku, barcode, name_ar, name_en, image_url, product_url, price, sale_price, quantity, in_stock`, `is_own_store=True`, `discovered_via="auto_sync"`, `first_seen_on_store/last_seen_on_store/last_synced_at` timestamps). Previously these were silently discarded.
  - Every sync now stamps every row: SKUs seen in the crawl get `present_on_store=True, last_seen_on_store=<ts>`; SKUs not seen this run get `present_on_store=False` via `update_many` (soft-archive — row + history preserved). The archive step is skipped if the crawl returns zero products (safety guard against upstream proxy soft-blocks wiping the catalogue).
  - Store doc gains `own_store_sync_discovered`, `own_store_sync_archived` counters.
  - `/api/my-products` gains an `own_only: bool = Query(True)` param. Default `True` filters the catalog query to `sku ∈ db.my_products.distinct("sku")` so the MyProducts page now shows only the user's catalogue (active + soft-archived). `/api/insights/sales` explicitly passes `own_only=False` to preserve its full-market aggregation (filter scope #5a). New response fields per row: `present_on_store`, `last_seen_on_store`, `discovered_via`.
  - Frontend `MyProductsPage.jsx` gains a **Sync from Store** button (admin-callable, hits existing `/api/import/sync-own-store`) and renders two new pill badges per row: `NOT ON STORE` (amber) when `present_on_store=false`, `AUTO-SYNCED` (teal) when `discovered_via="auto_sync"`. Both have data-testids `archived-badge-{sku}` and `autosynced-badge-{sku}`.
  - No new credentials needed — uses the existing public Zid Tier-1 crawl path. Schedule unchanged (every 6h via `_scheduled_own_sync`).
  - Verified end-to-end on preview: PRODUCTS TRACKED dropped from 3,802 (entire market) to 411 (own-store filtered for 90-day window); 14 SKUs auto-discovered from Petsy in the first triggered sync; 150 SKUs correctly soft-archived (Excel-imported SKUs that no longer appear on pets-houses.com). `/api/insights/sales` unchanged: still aggregates 4,131 products with Royal Canin as top brand.

- **My Products table — own-store-first display (Feb 2026, in preview)** — Implements user requirement "this table should be MY store's product list, with market data shown in context around MY prices and MY stock — not generic market data where my store is just one anonymous seller".
  - `server.py:/api/my-products` row builder enriched: when SKU is in `db.my_products`, overrides display fields with own-store values: `name_ar`, `name_en`, `barcode`, and headline `price` come from `db.my_products`; adds new fields `my_price`, `my_quantity`, `my_in_stock`, `my_stock_signal` (derived via existing `get_stock_signal()`), `competitor_min_price`, `competitor_max_price`, `vs_my_price_pct = (comp_min − my_price) / my_price × 100` (positive → I'm cheaper, negative → competitor undercuts), `num_competitors` (= sellers excluding own store).
  - Sales/revenue estimates remain market-wide (unchanged per spec); only the UI label changes.
  - `MyProductsPage.jsx` columns updated: `Price → My Price` (with `Mkt: 95-150` subtitle from competitor range), `vs Lowest → vs My Price` (sortable on `vs_my_price_pct`; green/red colour flipped to match new sign convention; tooltip explains direction), `Sellers → Competitors` (uses `num_competitors`), `Stock → My Stock` (uses `my_stock_signal` + shows `{qty} in stock` underneath the badge), `Est. Sales` and `Revenue` headers prefixed with `Mkt.` and tooltips clarify market-wide context.
  - i18n keys updated EN+AR. New per-row testids: `vs-my-price-{sku}`, `my-stock-qty-{sku}`.
  - Verified on preview with real data: Schesir Can Baby Salmon 70g shows My Price 8.05 SAR / Mkt 9.52 / +18.3% (I'm cheaper, green), 4 in stock (LOW), 1 competitor; Dr. Elsey's 8.16Kg shows My 82.8 / Mkt 75-86.89 / -9.4% (undercut, red), 10 in stock (MEDIUM), 3 competitors. `/api/insights/sales` regression-checked → still 4,131 products, 1.88M SAR rev, Royal Canin top brand. No other endpoint affected.

## Backlog
- **P1** Resend email integration (alerts + weekly digest)
- **P1** Multi-tenant role-based access
- **P2** Webhook notifications (Slack/Telegram)
- **Refactor (next pass)** Continue splitting `server.py` route handlers into `routes/` modules (auth, products, insights, alerts, stores, crawler, baseline, price-intel) — current pass extracted models + shared utils only

## Credentials
- **Super Admin (god mode, immutable)**: `a.disi@taqueen.sa` / `Ahmaddc90@`
- Legacy `admin@daleelpets.com` was deleted on startup per user instruction (Feb 2026).
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`

## Preview URL
https://daleel-price-intel.preview.emergentagent.com
