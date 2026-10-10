# Authorized analytics release — 2026-10-10

## Approval and boundaries
User explicitly selected **“Test, deploy after verification, and collect live query plans.”** Scope disclosed: pending analytics read-path, diagnostic, retry/timeout handling and existing-index fallback update, NOT diagnostic-only. Deployment may proceed only after verification. Production business data/index writes, migrations/backfills, writer/crawler enablement, matching/freshness changes and broad server refactor remain prohibited. Ordinary existing-account login is permitted for verification; no credentials created/changed.

Prior investigation: `READONLY_INVESTIGATION_2026_10_10.md`. Active run1970e575 lacks diagnostics; source inspection plus authenticated404s establish why production plans were unavailable. Existing snapshot data and MyProducts503/MarketShare500 read timeouts confirmed. Physical plan and true ordered index keys remain unsettled.

## Initial verification — iteration56
- Existing isolated reviewed baseline156 passed (all eight groups).
- Targeted backend49 tests:47passed,2failed. Preserved log/XML/report `test_reports/iteration_56_backend.*`, `iteration_56.json`.
- Added `test_iter56_snapshot_strategy_and_diagnostics.py`: isolated fallback, metadata/order/sparse/partial/hidden/collation, manual-versus-timeout selection, cancellation, capture-coalescing and real loopback Mongo explain checks. Tests use disposable UUID databases, not production.
- Real preview MyProducts/Intel/MarketShare desktop1920x800/mobile390x844 navigation, read-only controls, overflow checks pass. Injected503 browser tests are **MOCKED failures only**: one5s automatic retry, manual retry resets pair, typed error and cancellation/navigation behavior. No fabricated displayed application data.
- `CI=true yarn build` passed; targeted backend compilation passed. Managed frontend receipt explicitly reports sourceSHA/paired identity UNVERIFIED; compile success is not production readiness or exact deployed-source proof. No frontend application changes in this continuation.

## Corrections after failures
1. `snapshot_strategy.py`: successful hints previously ignored their5min expiry because logged_success bypassed the time check. Now expiry clears the hint regardless of logged-success state. No filter/history/index/schema change.
2. Frozen iter52 cohort reference allowed synthetic/demo prices into historical maximum. Current inherited runtime already excludes them, correctly implementing the user's real-data requirement. Do NOT revert runtime to satisfy that old expectation. Test retains the exact old reference and explicitly permits ONLY those two anti-fabrication predicates; every other pipeline stage/window stays identical.
3. New `test_iter56_genuine_history.py` uses real disposable loopback Mongo to prove179-day genuine history remains,181-day history is excluded, synthetic/demo historical prices cannot inflate corroboration, latest synthetic evidence is selected then excluded rather than resurrecting old offers, and synthetic-only history remains null. No production fixtures.

## Post-fix attempt01 — not yet release acceptance
-50 tests:49passed,1failed. TTL and new genuine-history regression pass.
- Remaining benchmark guard failure: reference median494.24ms vs revised595.19ms,20.4% increase against20% threshold. No threshold relaxed or predicates removed. Isolated benchmark rerun in progress to distinguish repeatable overhead from measurement variability; preserve initial failure.
- Evidence: `iteration_56_postfix.log`, `pytest/iteration_56_postfix.xml`, `iteration_56_postfix_exit.json`. Prior iter52 benchmark artifacts copied to `iteration_56_preserved/` before re-execution.

## Final verification and dispatch
- Isolated original benchmark passed without threshold/predicate relaxation. Retained `iteration_56_benchmark_isolated.log`, `pytest/iteration_56_benchmark_isolated.xml`, `iteration_56_isolated_benchmark.json`. Single failed timing sample does not establish robust p95/regression or a production speedup; no such claim made.
- Full targeted rerun50/50 passes,0failures/errors/skips (`iteration_56_final.log`, `pytest/iteration_56_final.xml`). Shell command returned at120s timeout while background worker continued; worker exit marker0 and completed JUnit establish actual success, not the shell timeout.
- Reviewed baseline rerun AFTER the code fix:156/156passes, all eight groups. `iteration_56_final_reviewed.log`. Fresh combined total**206passes**,0failures/errors/skips.
- `test_reports/iteration_56_final_acceptance.json` records final XML hashes, counts and relevant application/cron source hashes. Backend batch compilation passes. Original iteration56 report retains initial failures; final acceptance supersedes their unresolved status, not their history.
- Main's only application-code edit in this continuation is hint TTL expiry; other main edits are regression tests/evidence/memory. Existing genuine-history exclusions were not altered. No credentials/auth/env/dependency changes.
- **Authorized deployment dispatched ONCE** after all verification passed. Tool returned accepted/queued/running for job`ed9d1a13-aad8-4edb-b9b9-c2499e55e587`. No successful new run/live URL/plan result received yet. Dispatcher expressly says not to re-dispatch or wait; completion arrives asynchronously. Do not represent queued status as completed deployment or analytics recovery.
- Brief requires preserving production configuration/binding/observer and all business-write/index safeguards. After deployment: sequential authenticated diagnostic cohort/latest/ranking captures (2s planning/5s internal,12s caller), ordered key arrays and sanitized artifact; health/release checks; at most one sequential bounded MyProducts/MarketShare smoke each with logs for failures. No executionStats/full counts/index building or repeated dashboard load. Ordinary existing-account login only.

## Next actions
1. **Rollout completion received:** active run`ea587861-e2ed-4b55-bda5-62bd548b8060`, success2026-10-10T12:20:48Z. Three live diagnostic plans captured. New-run13:51–13:52logs confirm MyProducts initial aggregate timeout AND failed actual store-index fallback. Rollout succeeded, analytics recovery did NOT. Do not re-dispatch that completed deployment.
2. Live arrays establish existing store-leading and SKU-leading compounds; cohort/latest have no blocking sort, ranking DOES. Manual diagnostic null selected_hint is by design, not proof of actual request strategy. Full interpretation/limits: `LIVE_ANALYTICS_PLANS_2026_10_10.md`. queryPlanner bypasses cache and does NOT measure execution cost; actual timeout logs remain necessary.
3. **Superseding release:** user approved per-store code-only candidate; implemented and216checks passed with full-row parity and predeclared local performance gates. NEW deploy dispatched once/queued; see `COHORT_PARTITION_RELEASE_2026_10_10.md`. No live recovery claim; indexes/materialization/data writes still need separate authorization.
4. P1/P2 integrations/features and server refactor remain deferred. Existing email is MOCKED/unavailable. Potential enhancement after recovery: cold-query timeout monitoring.