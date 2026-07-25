# Daleel — PRD

## Original Problem Statement
SaaS platform for Saudi online store owners to track competitors' prices, inventory, best sellers, categories, and discounts across all Saudi stores (initially Salla & Zid). Real-time market intelligence.

## Core Requirements
- Multi-tier crawler (Tier 1/2/3 fallback + external Saudi-IP ingest)
- Product matching: Barcode > SKU, with confidence flags for large price gaps
- HRM-SA brand identity (flat dark `#090E1C`, teal accent `#1E988E`, Space Grotesk + Inter + JetBrains Mono + DIN Next LT Arabic)
- FastAPI + MongoDB + JWT (httpOnly cookies) + APScheduler
- External ingest API (bearer token)
- Arabic RTL support, SAR currency

## What's Implemented
- **Iter44 Step-1 (Jun 2026)** — LIVE IN WORKSPACE (merged from Pet-Crawler-main #20 zip, PR #23, targeted edits): new read-only super-admin endpoint `GET /api/admin/own-store-price-audit` + `fetch_own_storefront_catalog_raw()` (crawlers.py). Validates the own-store VAT-basis fix against LIVE data BEFORE any price-source switch — answers 4 questions: (q1) SKU coverage both directions (merchant-only/storefront-only, incl. barcode-recoverable), (q2) per-SKU price-ratio distribution (expect ~1.15 taxable / ~1.00 not), (q3) storefront `price` vs `effective_price` divergence, (q4) storefront catalogue completeness. Writes NOTHING, changes NO behaviour (sync still uses Merchant ex-VAT price until Step 2 approved). Server imports 3 new crawlers symbols (`fetch_own_storefront_catalog_raw`, `_fetch_zid_api_catalog`, `_price_amount`). New self-contained test `tests/test_own_store_price_audit.py` (2 tests: all-four-questions + partial-storefront/super_admin-gate). Also synced the two live-test files (`test_iter27_live.py`, `test_iter43_demo_cleanup_live.py`) to the credential-free `DALEEL_TEST_*`/httpx versions from main (no more hardcoded URL/password; skip when env unset). PRESERVED (workspace versions kept — zip only reformatted them): Motor Atlas timeouts, hardened `/api/health` (`_timed`), de-duplicated store_registry import. crawlers.py now IDENTICAL to main; matcher.py/zid_orders.py/store_registry.py untouched. **Verified:** 98 self-contained pytest green (incl. new price-audit 2/2) + 2 live skipped; live endpoint returns HTTP 200 locally (57s, 1184 storefront + 2177 merchant rows, vat_15=1169 → consistent 1.15 ratio). ⚠️ NOTE: endpoint takes ~57s (live external fetches) so it **502s through the preview/prod ingress (~60s proxy cap)** — works when called with a longer budget; it's a rare super_admin diagnostic. Not redeployed (user redeploys).
- **Iter43 (Jun 2026)** — LIVE IN WORKSPACE (merged from Pet-Crawler-main #19 zip, targeted edits): demo-cleanup guard contract hardening + super-admin frontend panel. Backend (`server.py` `demo_cleanup`): real run (`POST ?dry_run=false`) now REQUIRES `confirm_count` to exactly equal the live demo count (409 on missing/mismatch — "delete exactly the set you reviewed, or nothing"); the 200 safety ceiling is replaced by a **1000 catastrophe cap** (detector-drift protection); the real-SKU guard is always-on/never-overridable; the dry-run `guard` payload now carries `real_sku_match` (bool) + `confirm_count_required` (int) for the frontend contract. iter42 GET-is-dry-run-only (405 on `?dry_run=false`) preserved. Frontend: new `DemoCleanupPanel.jsx` (175 lines) wired into `SettingsPage.jsx`, super_admin-gated — fetches the GET dry run on mount, renders the report, disables the destructive button when `real_sku_match`, and POSTs with the exact reviewed `confirm_count`. New test `tests/test_demo_cleanup.py` (3 tests: dry-run-no-write, guard-blocks-real-sku/ceiling, real-run-backs-up-cascades-recomputes). PRESERVED (untouched): Motor Atlas timeouts, hardened `/api/health` (`_timed`), de-duplicated store_registry import (zip's dup skipped), iter26 KPI tooltips in MyProductsPage.jsx + i18n.js (zip was OLDER there — kept workspace; zip added NO new i18n keys). crawlers.py/store_registry.py/matcher.py/zid_orders.py IDENTICAL (untouched). **Verified:** 96 self-contained pytest green (incl. new test_demo_cleanup 3/3); testing_agent 100% backend (12/12) + 100% frontend, zero issues, no retest; live curl confirmed the confirm_count 409 contract + 405 GET-real-run + new guard fields. Not redeployed (user redeploys).
- **Iter41/42 (Jun 2026)** — LIVE IN WORKSPACE (merged from Pet-Crawler-main #18 zip, targeted edits): new super-admin endpoint `/api/admin/demo-cleanup` to remove the synthetic demo-seed catalog from production. iter41 = POST handler: `dry_run=true` (default) returns a full report (demo_products count, by_category, by_store_snapshots, cascade_counts across 11 referencing collections, before totals) with zero writes; real run (`dry_run=false`) backs up EVERY affected doc into `demo_cleanup_backup_<ts>_<collection>` + a manifest BEFORE deleting, cascades deletes across all referencing collections, then force-recomputes store metrics + dashboard cache + page caches so totals update immediately. Safety guard refuses (409) if the detector matches real-crawl-shaped SKUs (`Z.`/`S-PE-`/numeric GTIN 8-14 digits) or >200 demo products. iter42 = GET handler is DRY-RUN ONLY (`GET ?dry_run=false` → 405; destructive path stays POST-only so a prefetched/retried URL can't delete). Helpers added: `_demo_seed_skus()` (single source of demo-SKU detection, also DRY-refactored the subcategory-preview call site), `_demo_cascade_queries()`, `_demo_subcategory_counts()`, `_REAL_SKU_RE`. Verified live on preview: GET dry-run 200, GET dry_run=false→405, POST dry-run 200, unauth→401. PRESERVED (workspace-only, untouched): Motor Atlas timeouts, hardened `/api/health` (`_timed`), de-duplicated store_registry import (zip's dup skipped). crawlers.py/store_registry.py/matcher.py/zid_orders.py IDENTICAL to workspace (untouched). Not yet redeployed to production (user redeploys).
- **Iter40 (Jun 2026)** — LIVE IN WORKSPACE (merged from Pet-Crawler-main #17 zip, surgically, preserving all workspace-only items): (1) shared `_own_orders_aggregate(db, o_start, o_end)` helper — single source for own-store ledger revenue, read by BOTH the My Products KPI path and the store ranking so "My Revenue" can never disagree between surfaces; (2) **classifier v3** (`CLASSIFIER_VERSION=3`): dog signals (كلب/عظم/bone) win the food-parent decision in `guess_category`, cat↔dog wrong-parent flips within food parents, empty-category docs get assigned, treat-names with no clear animal go to pet_food; `_TREAT_SUBSTRINGS` gains جيركي/jerky/دنتال/ليكابل/lickable; (3) **classify-at-insert** in the ingest route — new product rows now get brand/category/subcategory/animal_type/weight set on first insert (was the source of 34 empty-category docs); (4) **Mowkly platform corrected salla→zid** (`store_registry.py`); (5) `/api/admin/store-ranking-preview` now returns a `diagnostics` block (per-store platform_audit, own_orders ledger debug, shared-product percentile_histograms) for super_admin validation; (6) frontend `PriceIntelHeader.jsx` "Not measurable" label only blames Salla when the store IS salla. PRESERVED: Motor Atlas timeouts, hardened `/api/health`, de-duplicated store_registry import (line 30 — zip's duplicate skipped), iter26 KPI tooltips (`MyProductsPage.jsx` + `i18n.js` kept at workspace versions; zip was older there). `matcher.py`/`zid_orders.py` identical — untouched. Verified: 115 self-contained pytest unit tests green (test_subcategories, test_store_ranking, test_metric_rollups, test_page_cache, test_dashboard_cache, test_price_capture, test_sales_estimator, test_zid_orders, test_matcher_pack_indicator, test_own_sold_count_capture, test_iter24_scale_fix); 23/23 live-server curl checks green (auth, health preserved, new diagnostics shape, my-revenue single-source consistency, all core endpoints 200/no-500s, Mowkly=zid). Not yet redeployed to production. NOTE: testing_agent was unavailable (infra error) — verification done via unit tests + serial single-token curl.
- Multi-tier crawler + external ingest endpoint
- Zid Merchant API integration for own-store sync (every 6h)
- Strict barcode/SKU-only matcher (name matching disabled)
- HRM-SA visual identity + light/dark theme toggle
- Super Admin + 3-tier RBAC with per-user `allowed_pages`
- Webshare Saudi residential proxy for blocked Salla stores
- Performance: TTL cache (60s), compound MongoDB indexes, route-based lazy loading, React Query
- Iter15-19: P1 confidence floor (≥85), sold-count delta clamps, DataFreshnessBanner, SKU/barcode search, sync_runs observability, has_competitor_pricing/has_market_share split, honest market-coverage KPI (no fair-share fallback)
- **Iter27 (Feb 2026)** — LIVE IN WORKSPACE: extended the iter25 `dashboard_cache` pattern to cover the Insights page (`/insights/summary`, `/insights/leaderboard`, `/insights/top-sellers`, `/insights/trending`, `/insights/gaps`, `/insights/price-wars`, `/insights/restock-opportunities`, `/insights/sales`) and `/price-intel/dashboard`. New helpers `_cache_key`, `_read_cache_dataset`, `_write_cache_dataset`, `_serve_dashboard` centralize the persistent-cache read/write path. Every insights endpoint has a pure `_<endpoint>_dataset(db, days)` helper so cached and live paths are byte-identical; freshness_pipeline in `/insights/summary` is now bounded to last-90d + confidence_score match (was unbounded $sort+$group over ~1.6M docs); all aggregations now pass `allowDiskUse=True`; price-wars + restock outputs are sorted for cache stability. `/insights/summary` and `/price-intel/dashboard` responses now include `cache: {source, computed_at, age_seconds, stale}` (envelope, not shape-changing). Frontend `InsightsPage.jsx` + `PriceIntelPage.jsx` show "Metrics as of <time>" via `data-testid=insights-cache-freshness` and `data-testid=price-intel-cache-freshness`. Recompute plan registry (`_dashboard_cache_recompute_plan`) covers 10 endpoints; startup warm-up populates all 37 endpoint×window docs (~15s cold). Every crawl / sync / matcher run debounces/forces recompute as before. Tests: `test_iter27_insights_cache.py` (6 new) + `test_dashboard_cache.py` (4, updated) + `test_iter27_live.py` (36 live-preview HTTP tests written by the testing agent) — 46/46 green.
- **Iter26 (Jul 2026)** — LIVE IN WORKSPACE: KPI explainer tooltips. All six KPI cards on `MyProductsPage.jsx` (Products Tracked, Units Sold, Mkt. Revenue, My Revenue, Avg. Market Share, Market Coverage) now expose a small ⓘ icon that shows a bilingual explanation on hover (desktop) or tap (mobile). Uses shadcn/Radix Tooltip (uncontrolled — Radix coordinates cross-card open/close), tap-to-focus for mobile guarantee, `tracking-normal` for Arabic legibility, auto-flipping RTL positioning. Copy sourced from 6 new i18n keys per language (`kpi_*_tip`) + one aria-label key (`kpi_info_label`). No backend changes.
- **Iter25 (Jul 2026)** — LIVE ON PRODUCTION: dashboard cache refactor (`DASHBOARD_CACHE_STD_WINDOWS=(7,14,30,90)` precomputed via `recompute_dashboard_cache`), frontend freshness indicator (`cache.computed_at` surfaces cache age when served from cache).
- **Iter24 (Jul 2026)** — LIVE ON PRODUCTION: `my_products` processes rows in chunks of 100, real Zid Orders integration (`zid_orders.py` — 401 on current token, degrades to estimation), `crawlers.py` change-only writes with daily heartbeat, hardened `/api/health` (async `wait_for` on every DB op), Motor Atlas timeouts (`serverSelectionTimeoutMS=5000`, etc.).
- **Iter23 (Jul 2026)** — READY FOR DEPLOY (workspace, awaiting redeploy):
  1. **/api/my-products truncation FIXED** (the deferred P0): replaced `.to_list(50000)` with a bounded streamed `find()` — `sku: {$in: relevant_skus}` (rendered rows' skus + matched competitor skus + barcode candidates, ~5-7k) + the existing crawled_at window. Served per-sku by the `(sku, crawled_at)` index (IXSCAN, no COLLSCAN, no server-side $sort/$group — iter21 postmortem rule). No row cap. Downstream `by_sku` contract unchanged; zero business-logic changes.
  2. **Stalled-crawler guard**: 503 with clear detail when the window is empty MARKET-WIDE (not merely for a narrow search — that renders zero-metric rows as before). Frontend (`MyProductsPage.jsx`) surfaces the 503 detail as a toast instead of swallowing it.
  3. Load test @1.638M docs (incl. 468k heavy own-store history): days=30 → 220k docs in 0.9s; days=90 → 530k docs in 1.9s; peak RSS 420MB (30d) / 944MB cumulative (90d worst case — see risk note). EXPLAIN: IXSCAN on sku_1_crawled_at_-1.
  4. Preview verification: days=90 KPIs recovered truncated data — matched 888→1057, coverage 42.7→50.8%, share_n 59→319 (matches the iter21 aggregation's correct numbers via the safe path). days=30 unchanged (never truncated on preview). Responses ~0.5s.
  5. Tests: 90 passed across iteration19/20/21 + union + matcher + estimator suites (3 monotonicity sweeps updated to encode the new 503-guard contract).
  - ⚠️ Risk note: 90d worst-case memory at prod scale (~550MB incremental) if own-store sync history is dense; monitor after deploy. Mitigation if needed: latest-only aggregation for non-row skus (semantics-identical).

- **Iter22 (Jul 2026)** — READY FOR DEPLOY (workspace, awaiting redeploy):
  1. **Matcher production crash FIXED**: `_build_competitor_lookups` was running unbounded `$sort+$group` over ~1M+ prod snapshots with no allowDiskUse → threw on every run; matcher had ZERO successful prod runs since 2026-04-17 (prod product_matches frozen at 290 rows, all stamped 2026-04-17). Fix: `MATCH_WINDOW_DAYS=14` `$match` bound + index-backed sort + `allowDiskUse=True` + new `(store_id, sku, crawled_at)` index. Load-tested at 1.17M synthetic snapshots: 3.8s, 120MB peak, plan = IXSCAN (no blocking sort). Matching logic UNCHANGED.
  2. **Wipe guard**: `run_matching_for_all` now refuses to rebuild when the 14-day window has 0 snapshots (crawlers stale/down) — error lands in sync_runs + data-freshness alarm instead of silently wiping matches. Verified live on preview.
  3. **PR #1 merged into workspace** (Zid sold-count fix from GitHub): `_extract_zid_sold_count()` in crawlers.py (probes sold_quantity/sold_count/sales_count/total_sold/sold), degraded-sync alerting (`sync_status: "degraded"` in sync_runs, `own_store_sync_source`/`own_store_sync_warning` in /api/import/status, sync_health alarm), store_registry.py module, run_market_crawl.py, SYSTEM_OVERVIEW.md, 13 new tests (test_own_sold_count_capture.py — all pass).
  4. **New-store rollout GATED** (user decision): store_registry's ~20 newly-discovered stores insert with `is_active=False` (`ACTIVATE_NEW_STORES=False` + `LEGACY_ACTIVE_DOMAINS` in store_registry.py). Scheduler count must NOT jump on deploy. New stores onboard separately next week — flip the flag or activate per-store.
  - Post-deploy verification targets: prod `last_match_status: ok`, `total_matches` in the thousands (expected ~2,000-3,000), `own_store_sync_source: zid_api`, insights 200, scheduler job count unchanged (~14).
  - **DEPLOYED & VERIFIED ON PRODUCTION (2026-07-13)**: matcher completed twice (08:40 scheduled-adjacent + 08:49 manual). total_matches 290 → 2,377 (2,328 barcode@99, 46 sku@95, 2 confirmed; 1,116 matched products). own_store_sync_source=zid_api. Scheduler stayed at 14 jobs (gate worked; 48 store docs, 12 active). Sync 45s; lookups ≤25s; match loop ~2-3min. Schesir 8005852750068 now matches CutePets+Hamtaro @7.75 (Petsy has no snapshot with that EAN in 90d — delisted or non-EAN SKU; Mahally-enrichment candidate).
  - ⚠️ Still broken on prod (pre-existing, NOT this deploy): `/api/insights/summary` now 500s consistently (dies at ~10.2s request timeout, same class as data-freshness — unbounded aggregation at 1M+ scale; cold TTL cache post-restart never warms). `/api/data-freshness` 500 ~100% today. `/api/my-products` truncation bug CONFIRMED VISIBLE: Schesir shows 0 competitors at days=7/14/90 but 2 competitors + full market_position at on_date=today — the 50k truncation drops competitor snapshots at multi-day windows. These are the next P0s: apply the same bounded-aggregation treatment (iter22 pattern) to insights/data-freshness/my-products.

- **Iter21 (Feb 2026)** — PARTIALLY LIVE ON PRODUCTION:
  - **LIVE:** `matcher.py` price-ratio hard-reject removed; SUSPICIOUS_PRICE flag scoped to Level-2 SKU matches only. Carnilove (8595602527212) and other aggressive-discount products now land in product_matches with barcode/conf=99, no annotation noise.
  - **REVERTED via hotfix (same day):** the `$group` aggregation refactor in `my_products()` was rolled back to iter20's `.find().to_list(50000)`. The aggregation returned HTTP 500 on production 90D queries because production's ~1M+ snapshot volume caused the pipeline's `$sort` stage to time out / spill excessively (allowDiskUse=True was set but insufficient). The 50k silent-truncation bug is thus TEMPORARILY back — dashboard functional but 90D KPIs are the iter20 numbers (matched ~617-888, coverage ~29-42%), not the true numbers.
- **Iter20 (Feb 2026)** — LIVE ON PRODUCTION:
  1. Barcode-safe union in `/api/my-products` row builder (`num_competitors` no longer dependent on matcher freshness, still Zid-suffix safe)
  2. `matcher.py:_has_pack_indicator` word-boundary fix (Arabic substring collisions like `متعددة` no longer suppress Level-1 barcode matching — 24 my_skus / 1% of catalogue unblocked)
  3. `num_priced_competitors` field surfaced for FE tooltip

## 🔴 REOPENED — iter21 production incident + backlog

### 1. `/api/my-products` aggregation re-architecture (P0, reopened by iter21 rollback)
**Root cause of the original issue:** `product_snapshots.find(snap_query).to_list(50000)` silently truncates when 90D window exceeds 50k rows on production. MongoDB returns 50k rows in natural (insertion) order → non-deterministic which rows come back → monotonicity violations across time windows (Carnilove: 2 comp @7D, 1 @14D, 1 @30D, 2 @90D on production pre-hotfix).

**Failed iter21 attempt:** Replaced with `$match → $sort → $group ($push full snapshot arrays)` aggregation. Worked on preview (271k snapshots) but 500-ed on production (~1M snapshots) because the server-side `$sort` stage timed out even with `allowDiskUse=True`.

**Constraints for the proper fix:**
- Must not use unfiltered `$sort` at production scale
- Group snaps by `(sku, store_id)` in aggregation; sort each small per-group array in Python
- Consider capping snapshot count per group (`$slice` after `$sortArray` if MongoDB 5.2+) to bound memory
- **MANDATORY: load-test at real production scale (~1M snapshots) before deploy.** Preview's smaller data hides scale-dependent failures — this bug pattern has now bitten us twice in the same week.
- Confirm bit-for-bit parity with iter21 preview results (Carnilove [7:2, 14:2, 30:2, 90:3] strict monotonic)
- Confirm response time < 5s at prod scale
- No memory blowup (Python process should stay under 500MB for one call)

### 2. `/api/data-freshness` intermittent 500 on production (P1, new — same class of problem)
**Symptom:** Endpoint returns 500 at exactly ~10.15s (request timeout) on production, ~1 in 3 requests. Not affected by iter21 code changes — the endpoint's own aggregation at server.py:1180 has grown too slow on production's ~1M+ snapshots.

**Cause:** `$group` by store_id across the entire `product_snapshots` collection with no `$match` filter. Uses `$max: {crawled_at}` + `$sum: 1` per group. On 1M docs the scan itself is heavy.

**User impact today:** Low — the endpoint has `@ttl_cache(60)`, so when one call succeeds the next 60s of requests hit cache. Freshness banner still populates periodically. Not blocking the main dashboard.

**Proposed fix (do this alongside item 1):** Add index on `store_id + crawled_at` if not already present. Alternatively use a materialized view or `snapshot_stats` collection updated by the crawler write path. Deprioritize until user asks — the ttl_cache masks the pain.

### 3. Iter21 baseline expectations
Post-proper-fix, production 90D KPIs should surface as (per preview): matched ≈ 1057, coverage ≈ 50.8%, share_sample ≈ 319, total_units_sold ≈ 19,232, market_revenue ≈ 524,000 SAR. **These are the TRUE numbers** — pre-fix production was returning ~30% of the real data.

## 🚨 CRITICAL LESSON (add to any future scale-sensitive work)
**Preview data ≠ production data.** Preview snapshots are ~271k in 90D. Production is 3-5× that. Any query that touches `product_snapshots` at 90D scope MUST be validated on synthesized production-scale data before deploy — either by copying prod data into a preview DB or by seeding preview to ~1M snapshots synthetically. This bit us twice in one week:
- Iter20 shipped fine because its changes didn't touch snapshot loading.
- Iter21's `.to_list(50000)` → aggregation refactor passed 84 pytest tests on preview but 500-ed within seconds on production.
- The user experience: production dashboard completely empty for ~30 minutes until hotfix.

**Rule from now on:** if code touches `product_snapshots.find/aggregate` in a way that reads more than ~10k rows at production scale, don't ship without a documented load-test run against ~1M-snapshot fixture data.

## Test Coverage
- `/app/backend/tests/test_iteration18_sync_hardening.py` — 11 tests
- `/app/backend/tests/test_iteration19_coverage_split.py` — 25 tests (iter21 KPI baselines widened but ROLLED BACK to iter20 values after hotfix — needs re-adjustment when iter21 proper fix ships)
- `/app/backend/tests/test_iteration20_api_contract.py` — 28 tests (TestKpiBlockIter21 currently pins the ~1057/50.8/319 baselines that only preview shows post-revert; on production they revert to iter20 numbers)
- `/app/backend/tests/test_iteration21_truncation_and_ratio.py` — 10 tests (some assume aggregation is present — will need updating when proper fix ships)
- `/app/backend/tests/test_competitor_count_union.py` — 11 tests
- `/app/backend/tests/test_matcher_pack_indicator.py` — 10 tests
- `/app/backend/tests/test_p1_confidence_floor.py`

## Other Backlog
- **P1** Resend email integration — waiting on user API key
- **P1 (deprioritized)** Brand extraction at ingestion (93% of crawled products land with empty brand)
- **P1** Data-hygiene cleanup: deactivate `TEST_Regression_Store` and `Test Store`
- **P1** Tooltip on AVG. MARKET SHARE KPI
- **P1** 3-tier accent on Market Coverage card
- **P0** `server.py` refactor (>5,200 lines) into `routes/` — queued after data-quality/UX fixes per user
- **P2** Webhook notifications, `curl_cffi` Cloudflare bypass, sitemap discovery
- **P3** Mahally Apify enrichment, auto platform detection, Salla soft-block detector

## Credentials
- **Super Admin (god mode, immutable)**: `a.disi@taqueen.sa` / `Ahmaddc90@`
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`

## URLs
- Preview: https://price-intel-dev.preview.emergentagent.com
- Production: https://saudi-pets-monitor.emergent.host
