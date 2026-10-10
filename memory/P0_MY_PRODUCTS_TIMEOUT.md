# P0 My Products timeout — verified mitigation, rollout held

Date: 2026-10-10. Scope: user-authorized P0 code and isolated/preview verification only.

## Decision

**The error handling and read-only caching fix is verified locally. Production cold-scan performance remains unproven; this is NOT production resolution or rollout approval.** No deployment, production reads/writes, index change, credential change, scheduler change, write-permit enablement, or broad refactor was performed in this continuation. Test fixture setup/cleanup used disposable loopback Mongo databases; ordinary preview login used existing credentials/security writes only.

## Confirmed cause and evidence boundary

Reviewed the retained actual production traceback in `deployer-agent-docs/RCA_0107107d-2d21-47fb-8ee5-836d2779725f.MD`, lines 21–37. It shows `GET /api/my-products?...days=30` → `my_products` → `_my_products_dataset` → `catalog_views.dataset` → Mongo aggregate receive → **`TimeoutError: The read operation timed out`**. The source and RCA connect this to `price_cohort.build_cohorts`; the configured socket read timeout is **45,000 ms**. It is not a CORS/auth/cache-write exception. The retained report separately identifies Price Intel hitting this shared aggregation.

The reported production indexes are time-leading, not store-leading. The full 180-day aggregation is independent of the sales window. This supports a costly-read diagnosis, but no new production explain/timing was obtained here, and the proposed store-leading index has NOT been tested/applied. Local fixtures do not reproduce production collection size, Atlas load, network, or its 45-second incident.

## Targeted implementation

- `price_cohort.py`: compact projection before `$$ROOT` grouping; retain the **entire 180-day** latest-offer, excluded-seller and discount corroboration history; add `maxTimeMS=15000`; close cursor on success/failure. No eligibility/identifier filtering before latest selection, no limit, no historical price substitution.
- Latest selection, strict GTIN/manual/blacklist/parent/variant matching, pack checks and current-price exclusion rules are unchanged. Reuse the already-loaded parent registry instead of reading it twice.
- `comparison_views.py`: remove the inherited 50,000-row catalogue cap; collect the complete cursor. No page/row truncation introduced.
- `my_products_cache.py`: per-process/event-loop read-through LRU (four entries, 64 MiB encoded payload budget), read-only persisted-cache lookup, and concurrent-request coalescing. Every hit checks the source revision. Successful full computations only; oversize results remain complete but are not retained. **No GET-side database writes, attempted or actual.** No writer permit or capability changes.
- Keys include cache schema, code digest, price policy, KSA day, and sales window. Reject missing/malformed/wrong-key/future/expired cache metadata and revision mismatches. Pre/post-compute revision validation rejects mixed-version computations rather than caching them.
- Maximum cache age remains **300 seconds**, further shortened by earliest own-price, own-stock, competitor seven-day cutoff; future observation entering the five-minute tolerance; or historical evidence leaving the inclusive 180-day window. No stale-on-error behavior.
- `price_read_limits.py`: 20-second asynchronous read budget, with explicit **503 + Retry-After: 5**, retryable `price_query_timeout` / `price_database_unavailable`; source/freshness races also return explicit 503. Never return a timeout/partial cursor as empty data. Serialization and scheduling overhead are outside a strict hard-real-time guarantee.
- Surgical `server.py` edits wire the endpoint and existing explicit background cache writer. The latter accepts only revision-stamped datasets; no background operation was enabled or invoked against preview/production data.

## Measurements

Mongo command counts include `find`, `aggregate`, `distinct`, and `getMore`, not merely logical queries. Local ASGI timings include application/response serialization but not an external network/authentication roundtrip. Independent before/after runs are not controlled production load benchmarks.

| Scenario | Response time | Mongo read commands | Snapshot aggregates |
|---|---:|---:|---:|
| Pre-fix observer, cold (one retained run) | 918.92 ms | 25 | 1 |
| Pre-fix observer, repeat (one retained run) | 892.53 ms | 25 | 1 |
| Revised observer, cold, baseline-shaped fixture (median of 3) | 1041.77 ms | 24 | 1 |
| Revised observer, memory-warm (median of 5) | 11.15 ms | 1 | 0 |
| Revised persisted valid cache, first read (one run) | 250.64 ms | 3 | 0 |
| **All 2,832 products matched**, cold (median of 3) | **1223.77 ms** | **22** | **1** |
| **All 2,832 products matched**, memory-warm (median of 5) | **15.28 ms** | **1** | **0** |

- Baseline-shaped fixture: 2,832 own products, 100,811 snapshots, seven competitor stores; intentionally includes many invalid GTIN-like identifiers. It must not be presented as a fully matched catalogue.
- Separate realistic matching fixture: **2,832 valid-GTIN products, all matched to three stores; 101,952 snapshots**. Every product has expected competitor minimum SAR80, average SAR93.33, three eligible sellers. Six API pages return all 2,832 unique SKUs and consistent totals; no cache DB documents were created.
- Cold counts: baseline-shaped 15 finds + 1 aggregate + 1 distinct + 7 getMores; fully matched 15 finds + 1 aggregate + 1 distinct + 5 getMores. Warm: one revision find.
- Five concurrent cold callers: **one** cohort computation/aggregate, four coalesced waiters. Combined baseline-shaped command counts: 23 finds + 7 getMores + 1 distinct + 1 aggregate = 32. Cancelling the first caller does not poison the remaining waiter.
- Projection explain: same **100,810 docs / 100,811 keys** examined. Original 343 ms vs revised 384 ms in final combined run. Latest accumulator memory 12,927,853 → 8,598,501 bytes; revised history-expiry accumulator adds 907,776 bytes. **No cold-query speedup or reduction in scan volume is claimed.**
- Real external preview authenticated smoke: **200**, 2,351 existing catalogue rows, 1,274.56 ms with limit=5 in final combined run. Preview health also returned 200. These are not production data or timings.

## Verification

**173 current checks passed:** 156 safe reviewed regressions + 3 P0 primary checks + 14 supplementary/fully-matched checks, zero final failures/errors/skips in these selected artifacts. The 156 suite includes real parent/child SAR46/SAR85 variants, pack/GTIN/manual/blacklist/latest-OOS correctness, release observer/write denial, and unrelated reviewed contracts. This is not the full legacy suite.

- Actual ASGI cold/warm/persisted cache, six-page completeness, unchanged KPIs, byte-budget bypass without truncation, custom-filter live reads, revision invalidation/race handling, malformed/future metadata, wrong policy/build/day/window keys.
- Five **endpoint-level**, controlled-clock/real-Mongo tests now verify a warm response becomes live recomputation at domain boundaries while age <300s: own price expires → null, competitor price expires → null, independently aged quantity → null, future competitor enters tolerance → SAR40, expired 180-day clearance evidence → minimum changes from SAR19 to SAR100. Warm responses immediately before each boundary preserve exact prior values. No database mutation occurs between their measured requests.
- Real Mongo `maxTimeMS=1` raises ExecutionTimeout on the large fixture; using that limit through the endpoint returns retryable 503. Default production-code aggregate option is captured as 15,000 ms.
- **MOCKED/INJECTED failure tests**: ExecutionTimeout, NetworkTimeout, raw TimeoutError, partial-cursor/getMore failure, shortened application deadline and source race. All reject incomplete data; a subsequent successful request works without manually clearing failed flight state. Isolated ASGI authentication is overridden; business queries use real Mongo. Actual preview smoke uses real existing authentication.
- Measured observer requests: **zero attempted and zero actual business writes**. No persistent test credentials created.

## Failure history and corrections

- Iteration47 retained pre-fix evidence: repeat recomputation and injected HTTP500s. Its historical replay expects old behavior and is deliberately excluded from current pytest collection (`__test__ = False`), not counted as a passing current regression. Helpers remain reusable; original JSON/XML preserved.
- Iteration48 initially missed memory caching/coalescing under `CountingGuardedDatabase`: exact-type name detection treated its subclass as a raw Motor DB, producing an unstable client cache key. Corrected to `isinstance(GuardedDatabase)` without changing release-control enforcement. Warm/concurrency expectations are now hard assertions.
- Test instrumentation initially accumulated warm counts and aliased its event list; corrected independent resets and event snapshots. First self-retest failed the resulting lost-event assertion; second passed. Preview test previously skipped because its helper lacked an environment password; supplied the existing password to the test subprocess, with no auth/credential changes. Skipping authentication failures was removed.
- Iteration49 initially covered some freshness boundaries only at cohort/cache-validator level. Added the five real endpoint transition tests and the fully matched benchmark rather than overstating that earlier report. Frozen clock now recognizes base Mongo datetime objects; no production clock logic changed.

## Durable artifacts / rerun

- RCA and original baseline: `test_reports/iteration_47.json`, `p0_my_products/baseline_pre_fix.json`, `pytest/p0_my_products_baseline.xml`.
- Initial post-fix report/failures: `iteration_48.json`, `p0_my_products/self_retest_01.{log,xml}`. Historical findings are superseded by the final reruns, not erased.
- Primary earlier successful rerun: `p0_my_products/self_retest_02.{log,xml}` (3 pass, including external preview).
- Supplementary independent report: `iteration_49.json`; expanded results: `p0_my_products/final_boundaries_01.{log,xml}` (14 pass).
- **Authoritative final combined P0 run:** `p0_my_products/final_p0.{log,xml}`: **17 passed in59.913s**, zero failures/errors/skips. The table above uses this final run's JSONs: `fix_validation_post_fix.json`, `cache_boundaries_results.json`, `cache_boundaries_benchmarks.json`, `fully_matched_benchmark.json` in that directory. Prior XML/logs remain historical; latest JSON measurements supersede earlier samples.
- Reviewed final rerun: `p0_my_products/final_reviewed.log`, eight `test_reports/pytest/*-final.xml` selected by `scripts/run_reviewed_tests.py` (156). Historical `preview-scope-final.xml` is NOT counted.
- Reproduce: run the three current P0 modules (`test_p0_my_products_fix.py`, `test_p0_cache_boundaries.py`, `test_p0_fully_matched_catalog.py`) separately or with compatible module fixtures; use loopback `MONGO_URL` from backend env, and supply existing `SUPER_ADMIN_PASSWORD` as test-process `DALEEL_TEST_PASSWORD` before imports for the external smoke. Run `python scripts/run_reviewed_tests.py` for the 156 isolated regressions. Never point fixture clients at a live/shared catalogue.

## Remaining rollout limitations / next action items

1. **P0 remains open for production resolution:** a cold process still scans 180 days. If that scan exceeds 15 seconds, the user receives an honest retryable 503, not restored results. Do not deploy on the strength of warm-cache results alone.
2. Memory caching/coalescing is per worker, lost on restart and not shared across pods. Each process/window can require its own cold computation; oversized values bypass retention. Persisted cache is optional, not populated by GETs. Mutations not publishing an observation revision can remain represented until the existing 300s/earlier temporal expiry; legacy/unfenced writers are not solved here.
3. A future separately authorized cold-path investigation must evaluate representative production-scale data and query plans; index/materialized-latest design remains a proposal, not an applied/proven fix. No production index change is bundled in this patch.
4. Price Intel shares compact projection and Mongo deadline, but its generic page cache/application-level error mapping was not migrated in this P0-only scope. Do not claim its production failures resolved.
5. Production recovery, exact image/provenance, scheduler ownership, backup/restore and earlier readiness gates remain open. Existing Zid approval/proxy blockers and **MOCKED/unavailable email** remain unchanged. All P1/P2 features and broad server refactor remain deferred.

Potential focused enhancement after authorization: track cold-compute duration and 503 rate by window/worker so warm traffic cannot hide cold-path regressions.