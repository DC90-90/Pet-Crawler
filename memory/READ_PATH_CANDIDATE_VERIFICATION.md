# Read-path candidate — tested improvements, primary production timeout OPEN

Date:2026-10-10, final acceptance10:13–10:15UTC. **Unpublished code. NOT a verified production recovery or rollout recommendation.**

## Current production truth
- Run1970e575 remains the last investigated serving run. Its DB binding is unchanged and recent crawler snapshots exist. Heavy reads time out; small reads work. Screenshots show Loading→503, not an empty database.
- Deployer withdrew the missing-store-index diagnosis. Generated index name/source strongly support a store-leading index; earlier displayed key order was a serialization artifact. No actual queryPlanner or server-side ordered index metadata could be retrieved: the available production data tool has no aggregate/explain surface. Do not add a duplicate index as a presumed cure. A single-field ascending time index can also support reverse traversal; “missing DESC” is not sufficient evidence for another index.
- Full RCA:`deployer-agent-docs/RCA_1970e575-b7af-48b5-95e6-318ac726f897.MD`. Prior12h cache is invalid under300sTTL. No stale-cache/empty-success fallback, index/data/config change, crawler enabling or deployment performed here.

## Rejected experiments / evidence retained
1. **Late materialization via IDs + $lookup** preserved values but was~2x slower locally. Entire mechanism removed. `snapshot_reads.py` now contains NO lookup/pointer logic. Iter51 JSON/benchmark remain evidence; its historical test module is `__test__=False`, not counted as a passing current regression.
2. Moving Market Share's many-field projection before grouping was not reliably faster. Restored EXACT previous post-group query shape, now proven byte-for-byte BSON equal to the reference. Only its deadline/cursor-completion handling changed.
3. Fixed the Market Share benchmark reference: initial helper compared a retired implementation and then mismatched active-store scope. Final reference uses identical active IDs/current pre-change code. An own-store range does not imply33% more rows—the fixture has no own-store snapshots. Disregard that numerical assertion in troubleshooting output.
4. Timing of byte-identical A/A query commands varied>20% in intermediate runs. Final test asserts BSON equality and records control variability instead of misclassifying it as a code regression/speedup. Other changed-query performance guards remain. All failing logs preserved (`iteration_52_findings_retest.log`, `iteration_52_final_acceptance*.log`). No Market Share query speedup claimed.

## Retained, scoped changes
- `snapshot_reads.py`: complete cursor drain without200,000-row cap,15sMongo deadline/20sread budget, cursor cleanup, typed503 failures; no cache writes. Optional projection in traditional latest pipeline.
- `store_views.py`: leaderboard loads only store/comparable/identity/time fields; top sellers only returned fields; summary only required eligibility fields. Ranking uses the existing7-day eligibility window to reduce scanned working set for canonical BSON-Date observations. Default latest/profile and historical counts retain full history/full stored fields;220-day-old fixture remains present where required. Projection retains `data_origin`, `superseded_parent`, `last_crawl_at` to avoid changing eligibility.
- `comparison_views.summarize_positions`: pure computation reused by market summary, eliminating its second complete cohort read. No price/history recomputation with different inputs.
- `price_cohort.py`: previous180-day pipeline restored (same history/variants/discount semantics); all callers now receive bounded retryable errors rather than raw Mongo exceptions. **Its expensive production cold work remains essentially unchanged.**
- `market_share.py`: same previous query and supplied history window, bounded complete read; removed inherited own-catalog/store list caps. Confidence argument documented as legacy compatibility: latest is selected before shared-policy confidence exclusion. Filtering confidence before latest resurrects older prices and was NOT added.
- `server.py`: generic GET cache fallback no longer attempts persistence; explicit background cache writers unchanged. Future-dated caches rejected. No enabling any writer or release capability.
- No frontend, authentication behavior, credentials, dependencies or protected environment changes in this read-path phase.

## Final verification
**185 selected checks passed:**156safe reviewed +29final targeted/P0/guard/diagnostic checks. Final29 XML has zero failures/errors/skips,112.048s.

- Full existing price/variant/freshness/cold/warm/revision/observer suite,180-day outlier/clearance history, latest low-confidence/OOS suppression,2kg46/4kg85 variants and complete2,832-product fixture rerun.
- Fixture2,832valid-GTIN own products,101,953snapshots, both256B and4KiB unused payload variants. Real Mongo only in disposable loopback DBs with observed index family. No production test data/index changes.
- Historical raw fields/default latest result parity;220-day row retained for historical counts;200,001-row transport fixture verifies no cap (**MOCKED cursor transport**, explicitly separate from realMongo benchmarks).
- Explicit503 injected initial/getMore/deadline failures; no partial/empty-success result. Market summary context invoked once. **Observer business writes attempted=0, actual=0.**
- Tests identified an instrumented-wrapper path attempting generic cache writes; removed fallback persistence entirely rather than bypassing guard or relaxing assertions.
- Apparent auth finding resolved without auth code changes: six failed logins split across different ingress peers were not a valid test of5/minute PER-IP. Two controlled isolated-ASGI stable-peer checks each produced `[401,401,401,401,401,429]`, including changing spoofed X-Forwarded-For values. Real external proxy/client-IP policy remains a separate environment concern, not a production-auth-fix claim. No account created/password changed.
- Final low-confidence/exclusion tests prove latest low-confidence offer is retained then rejected (older trusted price not resurrected); persisted demo/parent exclusion flags survive compact projections.

## Measurements (local fixture; not production guarantees)
Three-run medians. Commands include aggregate/getMore. These compare the common snapshot-read portion, not whole end-to-end endpoints unless labelled ASGI.

|4KiB fixture read|Median|Read commands|Result bytes|
|---|---:|---:|---:|
|Previous full latest read|435.87ms|4|39,964,220|
|Compact leaderboard read|245.75ms|2|985,629|
|Ranking7-day compact read|189.57ms|2|4,560,112|

256B medians:full403.81ms, leaderboard273.94ms, ranking211.69ms;2commands each. The historical full/leaderboard reads return8,497latest records, ranking8,496 (the220-day record is intentionally ineligible).

Unchanged180-day cohort:reference498.40ms vsrevised485.77ms on4KiB,2commands each; **no meaningful cold speedup claim**. MyProducts ASGI4KiB cold1811.68ms, warm7.53ms; ranking295.92ms, leaderboard273.31ms. Identical MarketShare A/A query:251.15 vs249.76ms;59,842docs/keys examined each, zero spills. Control timing variability remains relevant and three runs do not establish robust p95.

Real authenticated preview, final run: Stores200/180.10ms; leaderboard200/162.84ms; ranking200/187.66ms; Market Share overview200/1348.96ms; top sellers200/165.08ms; My Products14d200/1377.09ms and30d200/1398.25ms. This does NOT validate production scale.

## Durable artifacts
- Main final29:`test_reports/iteration_52_final_acceptance3.log`, `test_reports/pytest/iteration_52_final_acceptance3.xml`.
- Reviewed156:`test_reports/iteration_52_final_reviewed.log`, selected safe reviewed JUnit files.
- Latest metrics:`test_reports/iter52_readpath_benchmark.json`, `test_reports/iter52_preview_smoke.json`.
- Tests:`backend/tests/test_iter52_compact_reads.py`, `test_iter52_findings.py`, existing17P0 and7read-only guards.
- Historical reports iterations51/52 retain original rejected performance/initial findings; this document supersedes their unresolved-status recommendations where final tests explicitly corrected them.
- No new UI changes; backend preview smoke screenshot:`/root/.emergent/automation_output/20261010_093757/`.

## Blocker / next decision
**Primary My Products cold timeout NOT FIXED. Do not present this candidate as production recovery.** Need actual server-side production query plan/scan metrics before choosing a targeted repair. Available production diagnostic tools cannot obtain it. Next proposed step requires user's decision: add/test a narrowly scoped super-admin-only READ-ONLY query-plan diagnostic (fixed server-generated pipelines, queryPlanner-only, bounded runtime, sanitized metadata, no arbitrary commands/data/index writes), then explicitly authorize an instrumented deployment, or add it preview-only and let user choose when to deploy. A deployment would also include the retained tested read-path changes; do not label it diagnostic-only code if it includes them. No diagnostic endpoint implemented or deployment authorized yet.

All P1/P2, Zid approval, proxy configuration, **MOCKED/unavailable email**, and deferred broad refactor remain unchanged. Potential later safeguard: separate cold-query/timeout monitoring from cache-hit metrics.