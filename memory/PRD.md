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
- **Zid Merchant API integration (Feb 2026, in preview)** — Replaced the public storefront crawl with the **authenticated Zid Merchant API** for own-store sync.
  - New function `crawlers.py:_fetch_zid_api_catalog()` paginates `GET https://api.zid.sa/v1/products/?page=N&page_size=200` with the four Zid headers (`Access-Token`, `Store-Id`, `Role: Manager`, `Accept-Language`) until `next` is null. Brief `0.15s` pause between pages to stay under rate limits. Handles `401/403` by returning `auth_failed` so the caller can fall back to the public crawl.
  - `sync_own_store_prices()` now prefers the API path when `ZID_API_TOKEN` + `ZID_STORE_ID` env vars are present; the public crawl is the silent fallback.
  - When the API source wins, the sync **also writes to `db.products` (upsert, idempotent) and `db.product_snapshots` (insert, `source_tier=0`, `confidence_score=99`)** so newly synced products appear on the My Products table immediately — no need to wait for the next scheduled crawl. Previous behaviour required two separate jobs to converge.
  - Verified end-to-end against `pets-houses.com` (Store-Id 92252): pulled **2,081 active products in 41.6s across 21 pages**, all with clean Arabic + English names, prices, and stock levels. My Products page on 7D now shows 2,079 rows (was 1 before). 385 legacy Excel-imported SKUs that no longer exist on Zid were correctly soft-archived. Sync metadata: `source: zid_api`, `tier_used: 0`.
  - One-shot legacy backfill ran: 54 docs with `" Zid"` suffix on the SKU were inspected for collapsibility into the canonical Zid catalogue → zero collapsible duplicates (all 54 represent products genuinely no longer on Zid). 79 docs have name-shaped SKUs that mirror name-shaped SKUs at the Zid source (128 such products in Zid itself) — these need the merchant to fix the SKU field on `web.zid.sa`. Surfaced as soft-archived/badged in the UI.
  - Credentials stored in `/app/backend/.env` as `ZID_API_TOKEN` + `ZID_STORE_ID`. Never logged, never returned to the frontend.
  - `crawlers.py:sync_own_store_prices` extended: when the daily Zid public crawl of pets-houses.com discovers a SKU not yet in `db.my_products`, it now upserts a new row with full normalized metadata (`sku, barcode, name_ar, name_en, image_url, product_url, price, sale_price, quantity, in_stock`, `is_own_store=True`, `discovered_via="auto_sync"`, `first_seen_on_store/last_seen_on_store/last_synced_at` timestamps). Previously these were silently discarded.
  - Every sync now stamps every row: SKUs seen in the crawl get `present_on_store=True, last_seen_on_store=<ts>`; SKUs not seen this run get `present_on_store=False` via `update_many` (soft-archive — row + history preserved). The archive step is skipped if the crawl returns zero products (safety guard against upstream proxy soft-blocks wiping the catalogue).
  - Store doc gains `own_store_sync_discovered`, `own_store_sync_archived` counters.
  - `/api/my-products` gains an `own_only: bool = Query(True)` param. Default `True` filters the catalog query to `sku ∈ db.my_products.distinct("sku")` so the MyProducts page now shows only the user's catalogue (active + soft-archived). `/api/insights/sales` explicitly passes `own_only=False` to preserve its full-market aggregation (filter scope #5a). New response fields per row: `present_on_store`, `last_seen_on_store`, `discovered_via`.
  - Frontend `MyProductsPage.jsx` gains a **Sync from Store** button (admin-callable, hits existing `/api/import/sync-own-store`) and renders two new pill badges per row: `NOT ON STORE` (amber) when `present_on_store=false`, `AUTO-SYNCED` (teal) when `discovered_via="auto_sync"`. Both have data-testids `archived-badge-{sku}` and `autosynced-badge-{sku}`.
  - No new credentials needed — uses the existing public Zid Tier-1 crawl path. Schedule unchanged (every 6h via `_scheduled_own_sync`).
  - Verified end-to-end on preview: PRODUCTS TRACKED dropped from 3,802 (entire market) to 411 (own-store filtered for 90-day window); 14 SKUs auto-discovered from Petsy in the first triggered sync; 150 SKUs correctly soft-archived (Excel-imported SKUs that no longer appear on pets-houses.com). `/api/insights/sales` unchanged: still aggregates 4,131 products with Royal Canin as top brand.

- **My Products table — own-store-first display (Feb 2026, in preview)** — Implements user requirement "this table should be MY store's product list, with market data shown in context around MY prices and MY stock — not generic market data where my store is just one anonymous seller".
  - `server.py:/api/my-products` row builder enriched: when SKU is in `db.my_products`, overrides display fields with own-store values: `name_ar`, `name_en`, `barcode`, and headline `price` come from `db.my_products`; adds new fields `my_price`, `my_quantity`, `my_in_stock`, `my_stock_signal` (derived via existing `get_stock_signal()`), `competitor_min_price`, `competitor_max_price`, `vs_my_price_pct = (comp_min − my_price) / my_price × 100` (positive → I'm cheaper, negative → competitor undercuts), `num_competitors` (= sellers excluding own store).
  - `MyProductsPage.jsx` columns updated: `Price → My Price` (with `Mkt: 95-150` subtitle from competitor range), `vs Lowest → vs My Price` (sortable on `vs_my_price_pct`; green/red colour flipped to match new sign convention; tooltip explains direction), `Sellers → Competitors` (uses `num_competitors`), `Stock → My Stock` (uses `my_stock_signal` + shows `{qty} in stock` underneath the badge), `Est. Sales` and `Revenue` headers prefixed with `Mkt.` and tooltips clarify market-wide context.
  - i18n keys updated EN+AR. New per-row testids: `vs-my-price-{sku}`, `my-stock-qty-{sku}`.
- **My Products KPIs scoped to own store (Feb 2026, in preview)** — Top-of-page KPI cards (Products Tracked, Units Sold Est., Revenue Est., Avg. Market Share) were aggregating market-wide deltas, so "Units Sold" and "Revenue" reflected the whole catalogue's velocity rather than the user's actual sales, and "Avg. Market Share" was a placeholder `100/N`. Fixed in `/api/my-products`:
  - Per-row computes `my_units_sold` by feeding only the own-store snapshot list (`stores_data[own_store_id]`) into the existing `_estimate_sales_from_snapshots()` primitive — no new estimation method.
  - `my_revenue_est = my_units_sold × my_price` per the user's spec (uses today's selling price, not historical snapshot prices).
  - Per-row `market_share_pct` reworked: `my_units_sold / market_units_for_this_sku × 100` (previous formula was "share of total catalog sales", with no business meaning).
  - KPI totals when `own_only=True`: `total_units_sold` = Σ my_units, `total_revenue` = Σ my_revenue, `avg_market_share` = (Σ my_units / Σ market_units) × 100. Two auxiliary fields exposed: `market_units_sold` / `market_revenue` (for future surfacing).
  - When `own_only=False` (the `/api/insights/sales` callsite) the legacy market-wide KPIs are preserved verbatim — that endpoint's contract is unchanged.
  - Verified with synthetic 4-snapshot trajectory (qty 20→17→13→10, my_price=82.8 SAR): API returns my_units=10, my_revenue=828, avg_share=100% — exact algebraic match. Existing `/api/insights/sales` regression: still 4,131 products, 17,588 units, 1.88M SAR revenue, Royal Canin top brand (unchanged).

- **P1 Data Accuracy Guards (Feb 2026, verified on preview)** — Two reinforcing changes to keep dashboard KPIs honest.
  1. **Confidence floor (>= 85)** added to **every dashboard aggregation endpoint**: `/api/my-products`, `/insights/{summary, leaderboard, top-sellers, trending, gaps, price-wars, restock-opportunities, sales}`, `/discounts/{top-pct, top-amount, timeline, aggression}`, `/scanner/opportunities`, `/products/{sku}/velocity`, plus the seller-set fed into `compute_market_position` (floor raised 75 → 85). New constant `MIN_AGGREGATION_CONFIDENCE = 85` in `core/utils.py` (exported via `core/__init__.py`). Effect: Tier-3 HTML-scrape noise (~75) no longer pollutes revenue / sales-velocity / leaderboard / discount KPIs. Verified: `/insights/summary.avg_confidence` jumped from ~85 (raw avg) to 99 (only accepted snapshots).
  2. **Sold-count delta sanity** added to `core/utils._estimate_sales_from_snapshots()` Method 1. Previously `units_from_counter = max(0, last_sc − first_sc)`, which silently lost sales after a counter reset (`5 → 10 → 3 → 8` returned 3 instead of 10) AND let a single bad data point (`10 → 5000`) cap at `30 × days`. Rewritten to **sum CLAMPED per-step positive diffs**: each step is at most `MAX_SOLD_COUNT_DELTA_PER_INTERVAL = 50` units, total still capped at `MAX_DAILY_SALES_PER_SKU × days = 30 × days`. Negative steps (counter reset / partner-sync backfill) are skipped, not absorbed.
  - Regression tests added: `/app/backend/tests/test_sales_estimator.py` (6 cases — monotonic growth, counter reset, per-step spike clamp, qty-depletion fallback, single-snapshot insufficient-data, daily cap). Testing agent iteration_15 added `test_p1_confidence_floor.py` covering all 15 endpoints (21 passed, 1 skipped).

- **Data Freshness banner + SKU/barcode search fix (Feb 2026, verified on preview)** — Two related UX/data-accuracy enhancements.
  1. **`<DataFreshnessBanner />`** — new component at `/app/frontend/src/components/DataFreshnessBanner.jsx`, mounted at the top of **My Products**, **Price Intel**, and **Price Scanner** pages. Surfaces overall crawl-data freshness at a glance: green "Today" / yellow "This Week" / faded "This Month" / red "Stale" pill, plus oldest competitor crawl age, stale-store fraction (e.g. "11/13 stores stale"), next-crawl ETA, and own-store last sync. Expandable to a per-store breakdown (testid `freshness-store-{store_id}`) so the user can see which stores are dragging the cohort down. Backed by new endpoint `GET /api/data-freshness` (TTL-cached 60s) returning `{overall, stores[], next_run, crawl_paused, checked_at}`. Bucketing thresholds: <24h=today, <7d=this_week, <30d=this_month, ≥30d=stale. Own-store entries always show TODAY because Zid Merchant API syncs every 6h. Solves the prior "looks broken at default 30D view" confusion by making staleness an explicit dashboard banner instead of a silent absence of data. Verified by testing agent iteration_16: all 3 pages render the banner correctly with bucket=stale, all 14 store rows have correct testids, expand/refresh interactions work independently, zero console errors after the nested-button fix.
  2. **SKU + barcode search** in `/api/my-products`, `/api/products`, `/api/my-products-list`: previously the `$or` regex only covered `name_ar / name_en / sku`, and the user input was passed straight to MongoDB as a regex — so searching for a 13-digit barcode either returned 10 unrelated products (when the SKU regex partially matched) or 0 (when the SKU column on the catalog row was different from the barcode). Fix: added `barcode` to the `$or` list AND wrapped the user input in `re.escape()` so a raw barcode value like `8005852569199` (or `.*`) is treated as a literal string match. For `/api/my-products` with `own_only=True`, the search additionally scans `db.my_products` directly (sku / barcode / name_ar / name_en) so newly-synced SKUs without a `db.products` catalog row are still findable. Verified by testing agent iteration_16: exact-SKU search now returns 1 product (was 10 unrelated), partial-prefix `8005852` returns Schesir family, `.*` returns 0 (no regex injection), name search regression intact.
  - New tests: `/app/backend/tests/test_iteration16_freshness_search.py` (8 cases — 4 for `/data-freshness` shape, 4 for search behaviour).

- **KPI two-card split + Hobba deactivation + manual crawl backfill (Feb 2026, verified iter17, ready for production deploy)**
  1. **KPI two-card split** on `/api/my-products` (own_only=True). The single ambiguous "REVENUE (EST.)" card was splitting two distinct concepts under one label (my_price × market_units vs market_price × market_units). Now returns explicit fields:
     - `market_revenue` = Σ revenue_est across rows (market_price × market_units) — what the entire market earns on the user's catalogue
     - `my_revenue` = Σ my_price × my_units_sold — what the user's store actually earns
     - Legacy `total_revenue` field retained for backward compat (= sum my_price × market_units) but no longer surfaced in the KPI strip.
     - Frontend `MyProductsPage.jsx` now renders **5 KPI cards** via `lg:grid-cols-5`: PRODUCTS TRACKED, UNITS SOLD (EST.), MKT. REVENUE (EST.), MY REVENUE (EST.), AVG. MARKET SHARE. i18n keys `kpi_mkt_revenue` + `kpi_my_revenue` added in en/ar.
  2. **Hobba deactivated** via `PUT /api/stores/{id}` with `is_active=false`. Reason: upstream `hobbapet.com` has been returning HTTP 500 since April 2026 (documented in handoff). Hobba is now filtered from `/api/data-freshness.stores[]` (which requires `is_active=true`), so the banner bucket flipped from "stale" (71-day bottleneck) back to "today".
  3. **Manual crawl backfill** — triggered all 11 active competitor stores via parallel `/api/stores/{id}/crawl` calls. 10 of 11 succeeded (Hobba was the failure, now deactivated). 19,952 new snapshots written. Matcher re-run after backfill: `product_matches` grew 1,927 → 2,258 (+331 links covering +83 own-store SKUs). KPI numbers on 90D: 184 → 1,178 units / 3,927 → 28,401 SAR market revenue / 41.3% → 30.2% market share.

## Backlog
- **P1 (queued)** Resend email integration — waiting on user API key
- **P1 (deprioritized per user)** Brand extraction at ingestion (does NOT affect matching or category filter, only top-brand analytics)
- **P1 (data hygiene, flagged iter17)** Clean up leftover test stores `TEST_Regression_Store` + `Test Store` from db.stores (or `is_active=false`) — they currently show as "no data" in the expanded freshness banner
- **P1 (flagged iter17)** Update or skip iter16 tests `test_own_store_is_today` and `test_competitors_stale` — assertions baked in the pre-crawl state and now fail since data flipped
- **P1 (flagged iter17, optional)** Tune `/api/insights/summary.avg_confidence` — currently 93.7 (spec target ≥95). Either raise `MIN_AGGREGATION_CONFIDENCE` to ~92 or compute avg over Tier-1 only.
- **P0** Refactor `server.py` (>4,995 lines) into `routes/` — important for stability; queued AFTER all data-quality/UX fixes per user direction
- **P2** Webhook notifications, `curl_cffi` Cloudflare bypass, Sitemap discovery
- **P3** Mahally Apify enrichment, auto platform detection, Salla soft-block detector, manual "Trigger Crawl Now" button next to Data Freshness banner

## Credentials
- **Super Admin (god mode, immutable)**: `a.disi@taqueen.sa` / `Ahmaddc90@`
- Legacy `admin@daleelpets.com` was deleted on startup per user instruction (Feb 2026).
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`

## Preview URL
https://daleel-price-intel.preview.emergentagent.com
