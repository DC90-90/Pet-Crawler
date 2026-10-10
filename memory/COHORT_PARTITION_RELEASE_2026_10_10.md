# Conditional per-store cohort rollout — 2026-10-10

## Goal and approval
Fix real My Products analytics loading while preserving genuine data, complete results,180-day history,7-day freshness and strict product identity. User explicitly approved: **“Yes, implement and test it, then deploy only if those checks pass.”** This is a new authorized code-only rollout after diagnostics rolloutea587861 succeeded but did not fix analytics.

No production business-data writes, index builds, materialization/backfills, crawler/writer enablement, auth/config/secret changes, history/matching relaxation or broad server.py refactor authorized. Existing-account login/security bookkeeping allowed for verification. No credentials created/changed.

## Why this candidate
Prior active run`ea587861-e2ed-4b55-bda5-62bd548b8060`, success12:20:48UTC, fails during INITIAL cohort aggregate/get_cursor before first batch. Default and actual existing-index hinted fallback both time out. Real production arrays prove appropriate store/SKU-leading indexes exist; no duplicate-index fix justified. See `LIVE_ANALYTICS_PLANS_2026_10_10.md` and RCA_ea587861. Raw RCA's30-day-history/add-maxTimeMS shorthand is inaccurate: cohort180days and explicit15s maxTimeMS already existed.

## Implementation
Application changes only:
- `backend/cohort_reads.py` (new132lines): complete per-store snapshot reader. Validates EXISTING exact store_id1/crawled_at-1 nonsparse/nonpartial/nonhidden simple-collation index and collection collation via read-only metadata. Does not create/modify indexes.
- `backend/price_cohort.py`: calls reader before unchanged matching/history/freshness/selection logic. Original snapshot_pipeline is unchanged; no broadened/shortened predicates, identity prefilter, result cap or stale-cache fallback.

Behavior:
- Per-event-loop semaphore caps active cohort reads at2 across concurrent callers in the worker. Two tasks consume all requested stores, not unbounded task fanout. Other independent analytics modules are not covered by this semaphore.
- All partitions finish before any data is returned. Failure cancels/drains sibling async workers, attempts cursor closure, propagates existing typed503/no-partial contract and prevents dataset cache success.
- maxTimeMS15000 per aggregate and shared20s caller deadline unchanged; waiting for metadata/queue/partitions is inside caller deadline.
- Empty active set legitimately returns no competitor rows; duplicate active IDs deduplicated; single store follows original path.
- Unsafe/missing metadata/index or non-simple collection collation follows original unified query. Cross-store string offer-ID collision/non-string BSON IDs also rerun original grouping to retain exact Mongo semantics, not a Python min/max approximation. Legacy null/missing IDs stay keyed by store/SKU.
- Cursor/worker cancellation does NOT guarantee Motor's already-running server operation is killed; per-op maxTimeMS remains applied. No killOp/profiling/admin commands added.
- Success log: `COHORT_PARTITION_COMPLETED stores=... rows=... elapsed_ms=...`; fallback logs distinguish metadata uncertainty and ambiguous grouping. No raw product/credential logging.
- MyProducts/shared cohorts optimized. MarketShare's separate latest-snapshot read and ranking sort are UNCHANGED, so no promise all dashboards recovered.
- Manual `/api/admin/analytics-read-plan?pipeline=cohort` STILL describes original all-store baseline, not new partition execution. Automatic timeout diagnostics receive the actual failed single-store pipeline.

## Acceptance gates declared before testing
Disposable loopback Mongo only: at least200k snapshots,10stores,4KiB unused payload, full history-window coverage; balanced and ~80% concentrated-store workloads. Seven alternating measured pairs after labelled warmup. Compare against BOTH original default and existing-index-hinted monolith, using same2000 batch size/15s limit and production-observed index key order.
- FULL-row canonical BSON/Extended JSON equality every run (types, missing/null, arrays/attributes/variants, flags and timestamps), with SHA256/byte counts.
- Balanced median slowest partition first batch <=80% of faster original baseline's first-batch median.
- Both workload total complete-read medians <=120% of faster original baseline; every new read <20s.
- Correctness: fallback strategy branches explicitly exercised; collisions, metadata failure, cancellation vs budget expiry, global concurrency, cursor closure, no partial/cache success, zero observer business-write attempts/actual writes.

## Test evidence and corrections
- Initial iteration58 passed but main identified acceptance weaknesses: four-field comparator mislabeled full parity, wrong SKU index order, default101 baseline batch vs actual2000, history fixtures not reaching179days, branch patch potentially inactive, missing explicit caller-cancel proof, tautological nonempty preview assertion.
- Testing agent corrected TESTS ONLY; no application edits after initial implementation. Initial tests/reports/artifacts archived in `test_reports/archive_iter58/`. Do not cite weak original parity claim as full evidence.
- Iteration59:10/10 strengthened tests pass. Actual fixtures200k docs/10stores/4KiB/179.458-day observed span;82% concentrated-store skew; full-row parity vs both baselines on every measured run. Real matching/query outputs, not mocked timings.
- Existing156reviewed+50targeted regressions also pass on candidate source. Nonduplicated total**216passes,0failures/errors/skips**. Backend compilation passes.
- Preview authenticated MyProducts14/30days:200,total2351,page5,~1.1s; MarketShare overview200; ranking200. Frontend unchanged, prior build/browser evidence retained; new candidate desktop smoke200.
- **MOCKED only controlled branch/failure/cursor/cancellation fixtures.** Real-Mongo parity/performance and real preview HTTP evidence separate. No app integration newly mocked; existing email remains MOCKED/unavailable.

### Final measured local gate results
| Workload | Faster old total median | New complete total median | Old first-batch median | New slowest-partition first-batch median |
|---|---:|---:|---:|---:|
| balanced |879.921ms|475.087ms|714.448ms|90.860ms|
|82%skew|866.439ms|579.537ms|693.345ms|571.983ms|

All original gates pass without relaxation. These are warmed LOCAL seven-pair observations, NOT production p95, cold Atlas equivalence or a guaranteed live cure. Test fixture payload is synthetic; no fabricated user-facing application responses.

Authoritative artifacts:
- `test_reports/iteration_59_final_acceptance.json`: source/test/benchmark hashes and216counts.
- `test_reports/iteration_59.json`, `pytest/iteration_59_iter58.xml`, `iteration_59_run_iter58.log`.
- `test_reports/p0_my_products/iter58_partition_benchmark.json`: final corrected full-row evidence (filename retained by test; distinguish archived earlier artifact).
- `test_reports/p0_my_products/iter58_preview_read_smoke.json`.
- Candidate regression JUnit iteration58 p0_fix/cache_boundaries/fully_matched/regression_chunk1/iter52_compact and eight reviewed group-final XMLs.

## Deployment status and next action
After gates passed, main dispatched NEW authorized deploy ONCE for job`ed9d1a13-aad8-4edb-b9b9-c2499e55e587`. Returned **accepted/queued/running**. No completion/new active run/live recovery result received yet. Dispatcher says do NOT re-dispatch or wait/poll; outcome arrives asynchronously.

Requested post-rollout checks:
1. Confirm new run/source/cohort_reads file/hash, liveURL, health and observer/write guards unchanged.
2. One bounded MyProducts30d/page25 read, record response timing/total/page/cache source and truthful price availability. Correlate current-run COHORT_PARTITION_COMPLETED; a memory-cache-only200 does not prove cold recovery. If needed one14d read, no cache invalidation/retry storm.
3. Separate bounded MarketShare smoke; unchanged path may still fail. No claim all dashboards fixed.
4. On failure inspect current partition/fallback/timeout traces, distinguish baseline manual explain from new execution. No speculative further deploy/index/data changes.

P1/P2 external integrations/features and broad refactor remain deferred. Suggested later safeguard: per-store query latency/timeout alerts. **Production recovery remains UNVERIFIED until actual data reads succeed.**