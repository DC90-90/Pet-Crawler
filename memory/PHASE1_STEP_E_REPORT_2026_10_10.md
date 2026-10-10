# Phase 1 — Step E report (preview, 2026-10-10 ~21:05 UTC)

Scope: EMERGENT_PROMPT.md Step E.1–E.4 after the E.2b recrawls. No republish, no Phase 2.

## E.1 Own store (Pets Houses, Zid)
- own_store_sync_crawled **2648** (> 2000) · own_store_sync_source **zid_api** · tier_used 0 (merchant API) · complete true
- own_store_price_basis: storefront_inc_vat 972 · merchant_computed_inc_vat 1667 · merchant_non_taxable 9 · merchant_assumed_inc_vat 0 · hidden 0
- snapshots_created 2050 (598 deduped unchanged) · products_new 642 · products_updated 2006 · archived 20
- variant detail (merchant API): candidates 339 · fetched 339 · failed 0 → quarantined this sync **0** (unresolved_parent_variants 0 %)
- my_products 2993 = 2255 roots + 738 variant children; 325 roots are parent shells (`parent_listing_has_child_offers`, no price by design)

## E.2 Competitor crawls (crawl_logs, latest run)
| store | tier_used | products_found | snapshots_created | stop_reason | complete | quarantined (this crawl) | top reasons |
|---|---|---|---|---|---|---|---|
| Mowkly (Zid) | 1 | 3280 | 4864 | explicit_end | **true** | **0** (was 1227 before E.2b) | — |
| CutePets (Salla, via proxy) | 1 | 3000 | 2832 | **page_cap** | **false** | 168 | unresolved_parent_variants 167 (5.6 %), price_missing_or_invalid 1 |
- Mowkly zid_variant_detail_public: candidates 1227 · fetched 1227 · failed 0 · pages 137 · expected_count 3280 = observed 3280.
- CutePets: 200 pages × 15 = 3000; cursor chain continues past page 200 (verified via proxy: page 215 still returns 15 items with a `cursor.next`). `page=N` without the cursor token returns page 1, so the true catalogue size is unknown without walking the chain. Detail-barcode supplement: missing 603 · filled 3 (DOM) · details route 404 · dom_failed 32.
- CutePets unresolved parents are Salla multi-size listings ("حجمين", "3 أحجام", "4 مقاسات"): listing API publishes no per-option SKUs and the store's `/details` route 404s. Zid-side target (< 5 %) met: Mowkly 0 %, own 0 %.

## E.3 Matching + caches
- run-matching: "Matching started for 2993 products" → sync_runs manual_match_only ok, match_added 386, 5 min 41 s.
- product_matches **401 rows → 386 distinct own SKUs** (CutePets 326, Mowkly 73, Zarafa 1, Petsy 1; all `verified_offer`, confidence 99). Market coverage 12.9 %.
- Barcode coverage: own GTIN-like 2347/2993 · Mowkly 3907/4864 rows · CutePets 2348/2832.
- refresh-caches: server finished (`dashboard_cache recomputed, page_caches recomputed`) but the edge returned 502 (ingress timeout). `market-share/dataset` page cache fails at every window: **`DocumentTooLarge` (> 16 MB BSON)** → Market Share serves `live_fallback` (~3.1 s). Pre-existing design limit surfaced by real data.

## E.4 UI (preview, super-admin, 1920×800)
- My Products: 2993 products, 100 rows/page. Price Intel: full table 2993 rows, matched 386, cheapest 291, red 9, yellow 22, avg confidence 96 %. Market Share → My Products tab: 2993 rows (50/page). Scanner: 18 overpriced rows.
- Market Share shares all "Unavailable": sealed-day window, competitor units need ≥ 2 crawl days per store; Mowkly/CutePets have exactly 1 (today). Own store shows `store_publishes_no_sales_signal` despite 3 crawl days with exact qty → sales-evidence/label issue, Phase 2 (D.2, 48 h gap rule).
- Endpoint latency: my-products 0.20 s · price-intel/dashboard 2.9 s (6.4 MB body) · market-share/overview 3.1 s · market-share/my-products 3.2 s · scanner 0.21 s.

## Hand checks vs live storefronts — 0 mismatches
1. **8005852750068** Schesir Tuna & Surimi 85 g — ours 6.99 / qty 39 / in stock = pets-houses.com variant "حبة" 6.99 / 39 (carton 79.71 correctly not matched). CutePets 7.75 in stock = live 7.75 in stock.
2. **0763163284426** Kit Cat Tuna Kitten Mousse 400 g — ours 7.01 / qty 0 / OOS = merchant API 6.10 ex-VAT × 1.15, qty 0, is_published false (public storefront 404, consistent). Mowkly 8.00 / in stock / qty 2419 = live variant "حبه" 8.00 / 2419 (box variant 763163284426BOX 194.80 correctly excluded — E.2b child resolution working). CutePets 8.48 in stock = live.
3. **8699245859829** Beso litter baby powder 20 kg — ours 79.35 / qty 39 / in stock = live. CutePets 74.51 in stock = live; Zarafa 83.95 in stock = live; Petsy 87 / qty 29 = live. UI: 2nd of 4.

## Health (preview)
- /api/health 200, scheduler_active_jobs 15, boot done · /api/ready 200 · /api/release mode active, source_state unstamped-workspace.

## Observations (not fixed, not Phase 1 blockers)
- Detail panels show duplicate "legacy or unverified offer" rows (Aug 25) per store, labelled STALE.
- Data-freshness banner text "30-day dashboards will appear empty" is stale wording; 6/10 stores not crawled since Aug/Sep.
- Preview my_products contains 1 test row (`FIVE-SELLER-SKU`).
- price-intel/dashboard served `live_fallback` even after recompute (cache key/revision mismatch suspected).
