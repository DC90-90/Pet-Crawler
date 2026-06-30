# Daleel — PRD

## Original Problem Statement
SaaS platform for Saudi online store owners to track competitors' prices, inventory, best sellers, categories, and discounts across all Saudi stores (initially Salla & Zid). Real-time market intelligence.

## Core Requirements
- Multi-tier crawler (Tier 1/2/3 fallback + external Saudi-IP ingest)
- Product matching: Barcode > SKU, max 150% price diff, max 10% weight diff
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
- **Iter20 (Feb 2026)**: Two related fixes:
  1. **Barcode-safe union in /api/my-products row builder** — `num_competitors` now unions the `product_matches` link table with snapshot stores whose SKU passes `^\d{8,14}$` AND equals the my_sku/my_barcode exactly. This makes the count robust to matcher staleness while structurally preventing Zid-suffix false positives. New row field `num_priced_competitors` is the narrower count used for the `has_competitor_pricing` KPI gate. OOS competitors with a price still count toward both. The union is provably additive (zero SKUs lose coverage). Verified end-to-end: Beaphar SKU 8711231124985 went from 0 → 6 competitors live. Catalogue 90D Market Coverage widened from 37.2% → 42.7% (+5.5pp), share_sample_size 49 → 59. The widening exposes coverage that was always real but hidden by matcher gaps.
  2. **matcher.py `_has_pack_indicator` word-boundary fix** — previously used naive substring matching against PACK_KEYWORDS. Arabic compound words like `متعددة` (= "multiple", a color descriptor) contain `عدد` as a substring, silently flagging products as multipacks and SKIPPING Level-1 barcode matching. Same bug for `Backpack` (contains `pack`), `كرتونية` (contains `كرتون`). Fixed by tokenizing on whitespace+punctuation (new `PACK_TOKEN_SPLIT_RE`) and checking keyword membership at the TOKEN level. 24 of 2,466 my_products (1%) were affected. After re-running the matcher, 7 of those 24 now have 26 new barcode-method matches at conf=99 (including Beaphar going from 1 SKU-match → 8 barcode matches).

## Iter20 deployment notes
- KPIs WILL move on prod after deploy: matched_products 774 → ~888, market_coverage_pct 37.2% → ~42.7%, share_sample_size 49 → ~59. This is intentional, not a regression. Update internal dashboards' baseline copy.
- After deploy, run `POST /api/import/run-matching` once to heal `product_matches` table. The row-builder works regardless (defense-in-depth), but the table is also used by Price Intel and Market Position so a healed table is healthier overall.
- New row field `num_priced_competitors` exposed in `/api/my-products` payload for future FE use (tooltip showing "X carry / Y priced").

## Test Coverage (Iter20)
- `/app/backend/tests/test_competitor_count_union.py` — 11 tests (union additivity, Zid-suffix safety, proprietary-SKU fallback, OOS handling, Beaphar end-to-end)
- `/app/backend/tests/test_matcher_pack_indicator.py` — 10 tests (true positives preserved, all 4 substring-collision classes neutralized)
- `/app/backend/tests/test_iteration20_api_contract.py` — 28 tests (created by testing_agent_v3_fork: row payload contract, KPI block, matcher heal state, smoke test of 9 sibling endpoints)
- iter18 test updated: `has_market_data` → `has_market_share`
- iter19 KPI baselines widened: 774 → 888 ±10, 37.2 → 42.7 ±1, 49 → 59 ±5
- Full sweep: **84/84 backend tests pass**

## Backlog
- 🟡 **OPEN — DEFERRED BY USER (iter19 follow-up)** Production-vs-preview KPI discrepancy. User explicitly paused this mid-session. Resume only on user instruction. Diagnostic checklist preserved in CHANGELOG.
- **P1** Resend email integration — waiting on user API key
- **P1 (deprioritized)** Brand extraction at ingestion (93% of crawled products land with empty brand)
- **P1** Data-hygiene cleanup: deactivate `TEST_Regression_Store` and `Test Store` so they stop appearing as `no_data` in the freshness banner
- **P1** Tooltip on AVG. MARKET SHARE KPI explaining "computed over the N matched products"
- **P1** Synthetic regression test injecting a known-bad `sync_runs` row to exercise the banner's red-alarm override deterministically
- **P1** 3-tier accent on Market Coverage card (red <10 / yellow 10-30 / green >30) instead of binary
- **P0** `server.py` refactor (>5,000 lines) into `routes/` — per user direction, queued after data-quality/UX fixes
- **P2** Webhook notifications, `curl_cffi` Cloudflare bypass, sitemap discovery
- **P3** Mahally Apify enrichment, auto platform detection, Salla soft-block detector, manual "Trigger Crawl Now" button on the freshness banner

## Credentials
- **Super Admin (god mode, immutable)**: `a.disi@taqueen.sa` / `Ahmaddc90@`
- Crawler token (hardcoded): `zj7n4vATDYACt-FswvDd_EITEwti5WciV2yZt3I2IgHbDi7XKP9myrd2xSFYZGjO`

## Preview URL
https://daleel-price-intel.preview.emergentagent.com
