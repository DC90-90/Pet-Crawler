# Daleel — دليل | PRD & Progress Log

## Original Problem Statement
SaaS web application "Daleel" for Saudi store owners to track and monitor competitor stores in the Saudi market (Salla, Zid platforms). Monitor product prices, stock/quantity, best sellers, categories, and discounts. Multi-tier crawler architecture; strict product matching (Barcode → SKU priority).

**User language**: English. **Production**: https://saudi-pets-monitor.emergent.host (user manages deployments — NEVER save to GitHub or redeploy).

## Architecture
- React 18 + Tailwind frontend (`/app/frontend`)
- FastAPI backend (`/app/backend/server.py`, >8500 lines — refactor to routes/ requested LAST)
- MongoDB (Motor) — write-time rollups: `metric_daily_rollups`, `sku_store_coverage`, `sku_sales_daily`, `dashboard_cache`
- Crawler: `crawlers.py` (multi-tier, VAT inflation, pagination, iter63 Salla detail-supplement)
- Matcher: `matcher.py` (GTIN-14 normalization, pack/collision guards iter51-53)
- `salla_revenue_estimate.py`, `salla_sold_velocity.py`, `zid_orders.py`, `store_registry.py`

## PRESERVATION RULE (recurrence count: 7)
User uploads GitHub main ZIPs. NEVER overwrite workspace wholesale — surgically merge.
Workspace-only fixes that must survive every ZIP sync:
- server.py: Atlas timeouts, asyncio.wait_for health probes, **iter63 ranking fix (own store gets NO fabricated revenue estimate)**
- tests/test_ranking_revenue_sort.py: workspace iter63 version KEPT over ZIP iter62 version (user ruling, Jun 2026)
- tests/test_page_cache.py: 6-line isolation guard KEPT (user ruling)
- tests/test_iter45_regression.py: workspace-only, kept

## Known ZIP-ahead drift NOT yet synced (user deferred — "separate task later")
- iter60 "seller list full set": ZIP has `seller_set.py` module + server.py integration + core/utils.py `compute_market_position(max_age_days, min_confidence)` signature + matcher.py `barcode $first` line + `tests/test_seller_list_full_set.py`. All deliberately skipped in ZIP(17) sync per user ruling.
- ZIP tools files not copied: tools_match_gap.py, tools_seller_coverage.py, tools_zarafa_probe.js

## Implemented (chronological highlights)
- iter25/26: dashboard_cache + page caches (write-time, 24h max-age, debounced post-crawl recompute)
- iter30-34: write-time rollups replace raw snapshot reads for Insights
- iter38/40: Market Strength ranking + shared _own_orders_aggregate
- iter51-53: pack-count / variant / barcode-sanity guards (Scanner + matcher)
- iter55-59: Salla revenue estimate (±50%), sold-badge measured-approx tier
- iter61: matcher barcode normalization (GTIN-14), crawler persists competitor barcodes
- iter62: ranking sorted by unified revenue axis (exact > approx > estimate > none)
- iter63 (workspace): removed fabricated own-store velocity estimate (production bug: "pets houses #1")
- **Jun 2026 — ZIP(17) sync**: crawlers.py +149 lines (Salla Tier 2.5 detail-supplement, `SALLA_DETAIL_SUPPLEMENT_CAP=300`, line 1321) + test_salla_detail_supplement.py (12 tests) + PR#42 updates to test_salla_revenue_estimate/sold_velocity/store_ranking. 67/67 tests pass on sync-affected suites. Backend restarted healthy.
- **Jul 31 2026 — ZIP(18) sync (iter64, PR #43)**: crawlers.py +186/−21 — `_maybe_salla_detail_supplement` wrapper runs after ANY successful Salla tier (T1/T2/T2.5/T3 + dead-path), guaranteed one `detail_barcode_supplement` endpoints_tried entry per Salla crawl ("ran" with per-status failure counts e.g. failed_403, or "skipped" with reason), politeness guard `SALLA_DETAIL_MIN_PRODUCTS=50`, lightweight store-identifier capture + caching. Tests: test_salla_detail_supplement.py updated, test_salla_supplement_all_tiers.py NEW. 77/77 sync-affected tests pass; full suite failures unchanged (rate-limiter 429 + known flaky/data-drift). Backend restarted healthy. Prior rulings preserved (iter63 ranking test, page_cache guard, no iter60 files).
- **Jul 31 2026 — Production stale-build investigation**: proved production Redeploy (booted 14:25 UTC) shipped pre-iter63 build while workspace had iter63 since 14:05 (commit 0dd393f 14:16). Support confirmed: Redeploy packages CURRENT WORKSPACE (not GitHub), no agent/user access to inspect deployed image or restart production. Remediation: user re-clicks Redeploy; escalate to support@emergent.sh if still stale. Post-deploy check: /api/health uptime_seconds resets + next Zarafa crawl_log carries detail_barcode_supplement entry.
- **Jun 2026 — Metric computation audit (report-only)**: full map of every dashboard metric → source collection / window / compute-time. Flags found: Insights price_drops random 8-25 fallback when 0; Scanner Sales(14d) column hardcoded 0; Scanner "Zero Sales" KPI actually counts gap≥25%; Discounts frontend reads `days_on_sale` but backend sends `days_on_discount` (renders undefined); Discounts+Scanner still read raw product_snapshots at request time (60s TTL only); market avg / velocity computed differently across detail panel vs scanner vs rollups.

## Pending Issues
- P0 Zid discount capture gap: user's external crawler must send `sale_price` in /api/crawler/ingest payload (BLOCKED on user)
- P1 Zid sync_own_store_orders 401: needs OAuth Authorization token from user (BLOCKED)
- P1 Flaky test_same_second_rerun (timing)
- Pre-existing: test_subcategories integration failure; full-suite pytest runs hit login rate-limiter 429 (run subsets)
- Data-drift: test_competitor_count_union Beaphar case needs fresh 30d snapshots in DB

## Backlog
- P0 server.py refactor into routes/ (user: do LAST)
- P1 iter60 seller_set reconciliation (deferred from ZIP(17) sync)
- P1 brand missing on 93% of crawled products; new-store rollout (ACTIVATE_NEW_STORES); Resend email (needs key); deactivate TEST_Regression_Store/Test Store; AVG MARKET SHARE tooltip; 3-tier accent Market Coverage card
- P2 curl_cffi Cloudflare bypass; sitemap discovery; webhooks (Slack/Telegram)
- P3 Mahally Apify enrichment; auto platform detection
