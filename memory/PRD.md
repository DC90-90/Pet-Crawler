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
- Multi-tier crawler + external ingest endpoint
- Zid Merchant API integration for own-store sync (every 6h)
- Strict barcode/SKU-only matcher (name matching disabled)
- HRM-SA visual identity + light/dark theme toggle
- Super Admin + 3-tier RBAC with per-user `allowed_pages`
- Webshare Saudi residential proxy for blocked Salla stores
- Performance: TTL cache (60s), compound MongoDB indexes, route-based lazy loading, React Query
- Iter15-19: P1 confidence floor (≥85), sold-count delta clamps, DataFreshnessBanner, SKU/barcode search, sync_runs observability, has_competitor_pricing/has_market_share split, honest market-coverage KPI (no fair-share fallback)
- **Iter20 (Feb 2026)** — LIVE ON PRODUCTION:
  1. Barcode-safe union in `/api/my-products` row builder (`num_competitors` no longer dependent on matcher freshness, still Zid-suffix safe)
  2. `matcher.py:_has_pack_indicator` word-boundary fix (Arabic substring collisions like `متعددة` no longer suppress Level-1 barcode matching — 24 my_skus / 1% of catalogue unblocked)
  3. `num_priced_competitors` field surfaced for FE tooltip
- **Iter21 (Feb 2026)** — PARTIALLY LIVE ON PRODUCTION:
  - **LIVE:** `matcher.py` price-ratio hard-reject removed; SUSPICIOUS_PRICE flag scoped to Level-2 SKU matches only. Carnilove (8595602527212) and other aggressive-discount products now land in product_matches with barcode/conf=99, no annotation noise.
  - **REVERTED via hotfix (same day):** the `$group` aggregation refactor in `my_products()` was rolled back to iter20's `.find().to_list(50000)`. The aggregation returned HTTP 500 on production 90D queries because production's ~1M+ snapshot volume caused the pipeline's `$sort` stage to time out / spill excessively (allowDiskUse=True was set but insufficient). The 50k silent-truncation bug is thus TEMPORARILY back — dashboard functional but 90D KPIs are the iter20 numbers (matched ~617-888, coverage ~29-42%), not the true numbers.

- **Iter22 (Jul 2026)** — READY FOR DEPLOY (workspace, awaiting redeploy):
  1. **Matcher production crash FIXED**: `_build_competitor_lookups` was running unbounded `$sort+$group` over ~1M+ prod snapshots with no allowDiskUse → threw on every run; matcher had ZERO successful prod runs since 2026-04-17 (prod product_matches frozen at 290 rows, all stamped 2026-04-17). Fix: `MATCH_WINDOW_DAYS=14` `$match` bound + index-backed sort + `allowDiskUse=True` + new `(store_id, sku, crawled_at)` index. Load-tested at 1.17M synthetic snapshots: 3.8s, 120MB peak, plan = IXSCAN (no blocking sort). Matching logic UNCHANGED.
  2. **Wipe guard**: `run_matching_for_all` now refuses to rebuild when the 14-day window has 0 snapshots (crawlers stale/down) — error lands in sync_runs + data-freshness alarm instead of silently wiping matches. Verified live on preview.
  3. **PR #1 merged into workspace** (Zid sold-count fix from GitHub): `_extract_zid_sold_count()` in crawlers.py (probes sold_quantity/sold_count/sales_count/total_sold/sold), degraded-sync alerting (`sync_status: "degraded"` in sync_runs, `own_store_sync_source`/`own_store_sync_warning` in /api/import/status, sync_health alarm), store_registry.py module, run_market_crawl.py, SYSTEM_OVERVIEW.md, 13 new tests (test_own_sold_count_capture.py — all pass).
  4. **New-store rollout GATED** (user decision): store_registry's ~20 newly-discovered stores insert with `is_active=False` (`ACTIVATE_NEW_STORES=False` + `LEGACY_ACTIVE_DOMAINS` in store_registry.py). Scheduler count must NOT jump on deploy. New stores onboard separately next week — flip the flag or activate per-store.
  - Post-deploy verification targets: prod `last_match_status: ok`, `total_matches` in the thousands (expected ~2,000-3,000), `own_store_sync_source: zid_api`, insights 200, scheduler job count unchanged (~14).
  - **DEPLOYED & VERIFIED ON PRODUCTION (2026-07-13)**: matcher completed twice (08:40 scheduled-adjacent + 08:49 manual). total_matches 290 → 2,377 (2,328 barcode@99, 46 sku@95, 2 confirmed; 1,116 matched products). own_store_sync_source=zid_api. Scheduler stayed at 14 jobs (gate worked; 48 store docs, 12 active). Sync 45s; lookups ≤25s; match loop ~2-3min. Schesir 8005852750068 now matches CutePets+Hamtaro @7.75 (Petsy has no snapshot with that EAN in 90d — delisted or non-EAN SKU; Mahally-enrichment candidate).
  - ⚠️ Still broken on prod (pre-existing, NOT this deploy): `/api/insights/summary` now 500s consistently (dies at ~10.2s request timeout, same class as data-freshness — unbounded aggregation at 1M+ scale; cold TTL cache post-restart never warms). `/api/data-freshness` 500 ~100% today. `/api/my-products` truncation bug CONFIRMED VISIBLE: Schesir shows 0 competitors at days=7/14/90 but 2 competitors + full market_position at on_date=today — the 50k truncation drops competitor snapshots at multi-day windows. These are the next P0s: apply the same bounded-aggregation treatment (iter22 pattern) to insights/data-freshness/my-products.

- **Iter23 (Jul 2026)** — READY FOR DEPLOY (workspace, awaiting redeploy):
  1. **/api/my-products truncation FIXED** (the deferred P0): replaced `.to_list(50000)` with a bounded streamed `find()` — `sku: {$in: relevant_skus}` (rendered rows' skus + matched competitor skus + barcode candidates, ~5-7k) + the existing crawled_at window. Served per-sku by the `(sku, crawled_at)` index (IXSCAN, no COLLSCAN, no server-side $sort/$group — iter21 postmortem rule). No row cap. Downstream `by_sku` contract unchanged; zero business-logic changes.
  2. **Stalled-crawler guard**: 503 with clear detail when the window is empty MARKET-WIDE (not merely for a narrow search — that renders zero-metric rows as before). Frontend (`MyProductsPage.jsx`) surfaces the 503 detail as a toast instead of swallowing it.
  3. Load test @1.638M docs (incl. 468k heavy own-store history): days=30 → 220k docs in 0.9s; days=90 → 530k docs in 1.9s; peak RSS 420MB (30d) / 944MB cumulative (90d worst case — see risk note). EXPLAIN: IXSCAN on sku_1_crawled_at_-1.
  4. Preview verification: days=90 KPIs recovered truncated data — matched 888→1057, coverage 42.7→50.8%, share_n 59→319 (matches the iter21 aggregation's correct numbers via the safe path). days=30 unchanged (never truncated on preview). Responses ~0.5s.
  5. Tests: 90 passed across iteration19/20/21 + union + matcher + estimator suites (3 monotonicity sweeps updated to encode the new 503-guard contract).
  - ⚠️ Risk note: 90d worst-case memory at prod scale (~550MB incremental) if own-store sync history is dense; monitor after deploy. Mitigation if needed: latest-only aggregation for non-row skus (semantics-identical).

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
- Preview: https://daleel-price-intel.preview.emergentagent.com
- Production: https://saudi-pets-monitor.emergent.host
