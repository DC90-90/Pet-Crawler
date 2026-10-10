# OPEN production incident — loading followed by analytics timeout

2026-10-10. User reports “no data at all” and provides two screenshots of daleel.hrm-sa.com: My Products first shows Loading…, products tracked “-”, coverage0%/0÷0; later the entire content becomes “Price analysis timed out before a complete result was available. No partial or empty results were returned.” All restored navigation links are visible. The zero figures are loading placeholders, NOT evidence of an empty database.

## Verified by current read-only production RCA
- Serving run **1970e575-b7af-48b5-95e6-318ac726f897**, platform-initiated redeploy08:20:15→08:27:12UTC, supersedesd57077e1. New navigation/error UI is live; data-read failure persists.
- DB binding unchanged (`saudi-pets-monitor-daleel_pets`,51collections). Bounded indexed reads succeed; a real BSON-Date snapshot exists at **2026-10-09T20:57:11Z**, about12hours old at deployment, inside7-day freshness. This establishes recent data exists, not complete collection integrity/counts.
- Observed live logs: My Products503`price_query_timeout`; Market Share overview, Price Intel dashboard/ranking, multiple Insights endpoints500; Stores latest aggregate also times out. Actual error `pymongo.errors.NetworkTimeout`/socket read timeout during aggregation. Auth/me, my-skus, comparison-stores, baseline/catalog-gaps200. Do NOT infer statuses of unobserved Scanner/Discounts/Alerts/Import endpoints from these.
- Previous15s query/20s request/cache mitigation and navigation restoration have not restored production analytics reads. No new application or production changes made during this follow-up.
- Current RCA: `deployer-agent-docs/RCA_1970e575-b7af-48b5-95e6-318ac726f897.MD`. Raw report recommendations have significant caveats below; do not implement them blindly.

## Important corrections / pending verification
1. **Index KEY ORDER is not yet authoritative.** Both reported generated names `sku_1_crawled_at_-1` and `store_id_1_crawled_at_-1` are shown with alphabetically ordered JSON key objects. This could be tool serialization rather than reversed BSON index order. Earlier categorical “missing store-leading index” conclusion is provisional until driver-ordered pairs/query plan verify it. No index addition/drop/repair is authorized or applied.
2. Requested server-side metadata-only pipeline to remove ambiguity: `[{"$indexStats":{}},{"$project":{"_id":0,"name":1,"ordered_keys":{"$objectToArray":"$key"}}}]`. Server-side arrays preserve BSON field sequence even if the tool sorts object properties. Request bounded maxTimeMS if supported; if permission/tool unavailable, retain uncertainty. Also requested bounded queryPlanner-only explain; diagnostic tool currently reports no explain surface. No executionStats full scans or unbounded counts authorized in follow-up.
3. Stored legacy cache `my_products:v1:days=30`, computedOct9 21:14, is~12hours old and wrong schema. **NOT an eligible warm cache** under300sTTL. Bypassing freshness/schema checks to serve it is forbidden, as is any200-empty fallback. Main explicitly rejected those RCA suggestions.
4. Empty`ZID_OAUTH_TOKEN` env is an optional manual override, not sufficient proof of missing runtime OAuth: `zid_orders.py` reads encrypted tokens fromMongo first. Do not instruct secret replacement/redeploy as a guaranteed orders fix. Ordersauth failure remains separate from shared analytics reads.
5. Old successful sync_runs do not establish current scheduler ownership or resumption. Current read-only/refreshOFF state is intentional; do not enable crawlers/writers to fix data reads. Current scheduler resume remains unverified.

## Existing diagnostics examined — NOT invoked
- `/api/admin/ensure-snapshot-indexes` is a broad schema-writing POST; never use without separate approval.
- `/api/admin/maintenance/plan/query-indexes` looks read-only but performs unbounded counts on large collections; not appropriate while diagnosing these timeouts.
- `/api/admin/perf-probe` returns index names only, performs seller reads and executionStats scans, and its explain command is blocked by the default-deny DB guard without maintenance. Do not treat it as safe cheap queryPlanner instrumentation.

## Next action
Await queued read-only index-order/query-plan evidence; then propose the smallest evidence-backed repair. User's production data/index/config/write/deploy freeze remains in force. No shortened180-day history, relaxed7-day freshness, truncated offers, stale-cache success, fake zero data or broad refactor. No new code fix/test completion claim in this follow-up. The app remains operationally broken for heavy analytics reads; existing preview tests are NOT proof of production recovery.