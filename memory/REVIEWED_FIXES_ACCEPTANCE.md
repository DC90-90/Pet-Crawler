# Independently reviewed Daleel fixes — preview acceptance

Updated: **2026-10-09**. Latest scope: **release-safety remediation documentation and evidence reconciliation**. The final release-safety section below is authoritative: **163 saved passing checks = 156 isolated + 7 preview API checks**. Earlier 104/133/143/144 totals and their Git checkpoints are historical. **Production remains NO-GO** while B1–B7 evidence is incomplete. This documentation continuation made no application/configuration changes, ran no new application tests/builds, and performed no production access, refresh, backfill, credential rotation, direct Git write, or deployment.

## Historical checkout and Git handoff — matcher continuation
- Requested repository: `DC90-90/Pet-Crawler`.
- Requested destination branch: `conflict_130726_1244`.
- Actual local checkout: `/app`, branch **`main`**.
- Current local/reference HEAD verified for the matcher continuation: **`aa2c44225430e65650deaf37608789c22d117503`**. Earlier four-fix reference: `daa86dfbe95230df8165c83230a4e574f2290d14`; six-fix reference: `65f6474399bbb89d37b25cd98a8d8062f804be98`.
- That HEAD is this continuation's **starting checkpoint**, NOT a claimed remote commit for today's fixes. No direct commit/push or branch switch was performed. A resulting remote fix commit is pending the user's **Save to GitHub** action; none is invented here.
- Preview: https://price-intel-dev.preview.emergentagent.com

## Package application and reconciliation
1. Downloaded/extracted the uploaded ZIP outside the repository and read `README.txt`, `REVIEW.html`, `review.json`, and the overlay script.
2. Initial check-only aborted on **only `frontend/yarn.lock`**: the reviewed base expected it absent, but preview had an untracked locally generated lockfile. All other expected hashes matched the supplied base.
3. Inspected the lockfile difference, preserved the local file privately, used the reviewed frozen dependency lock, and reran the supplied check. All 58 file checks passed before application.
4. Applied the supplied overlay with `--apply`. Immediate post-application check: **58 files checked, zero changes remaining**. No newer tracked implementation was force-overwritten.
5. Ran `yarn install --frozen-lockfile` and an optimized frontend build successfully.

Persistent artifacts (outside Git): `/root/daleel-reviewed/package/`, `/root/daleel-reviewed/daleel-reviewed-fixes.zip`, `/root/daleel-reviewed/daleel-lock-reconciliation/`, and captured source HTML under `/root/daleel-reviewed/daleel-reviewed-samples/`. The original archive is unchanged. Test source fixtures without secrets are checked in under `backend/tests/fixtures/reviewed_beso_sources.json`.

## Reviewed regressions
All **19 supplied review gates pass**: startup index preservation; external variant identity; incomplete pagination; supplemented-barcode persistence; event replay repair; GTIN precedence; grouped denominators; null movement; stale own prices; foreign-currency own prices; ambiguous own variants; store credential redaction; build-secret configuration; availability denominators; excessive money values; truthful failed-cron status; reviewed metadata; current seller cohorts; and removal of unsupported “floor” claims.

## Follow-up defects fixed during acceptance
- Stale own prices leaked as zero in Price Intel details and as bare currency/ranges in the product panel. Current prices now stay null/dash; historical prices remain separate.
- Excluded legacy offers displayed invented 99% confidence and current “In Stock” badges. They now show no current verified offer and unknown stock. Confirmation of an unverified/missing offer is disabled.
- Restored the pack-count guard on specific source offer names; shared GTIN cannot turn a carton into a single unit.
- Added explicit credentialed CORS configuration and rejection of untrusted-origin cookie mutations. Preview origin configured locally; no passwords/tokens rotated.
- Fixed mobile product-detail overflow; added clear fallback for unavailable product imagery and validated GTIN display instead of the invalid vendor barcode `2048`.
- Full Comparison silently showed only the first 100 products. Added search and paging so the actual Beso product can be opened. Missing prices are dashes.
- Corrected detail confirm/reject callbacks to include the own SKU alongside the specific offer identity.
- Removed two historical credential literals missed by the overlay, without disclosing or rotating them. Current configured-secret scan over tracked/pending files returns **no matches**.

Only three files originally included in the reviewed overlay intentionally differ from its post-apply hashes: `backend/server.py` (CORS), `backend/price_cohort.py` (pack-count guard), and `backend/tests/test_refactor_regression.py` (remaining literal removed). Other follow-up changes are in files not replaced by the package.

## Final test results
Reproducible command: `python scripts/run_reviewed_tests.py`

| Group | Passed | Failed / errors / skipped |
|---|---:|---:|
| Reviewed core: existing 24 + real-Mongo 9 + supplied 19 gates | 52 | 0 / 0 / 0 |
| Isolated authentication, CORS, and password-preservation tests | 10 | 0 / 0 / 0 |
| Captured real-source variants, Beso, stale offers, filters | 6 | 0 / 0 / 0 |
| Relevant pack, ledger, and VAT contract tests | 36 | 0 / 0 / 0 |
| **Total selected tests** | **104** | **0 / 0 / 0** |

Final JUnit artifacts: `test_reports/pytest/reviewed-core-final.xml`, `isolated-auth-final.xml`, `real-source-final.xml`, `related-contracts-final.xml`.

Also passed: `python -m compileall -q backend`, `python scripts/validate_crons.py`, `yarn --cwd frontend install --frozen-lockfile`, and `yarn --cwd frontend build`. Full historical repository test suite was **not** claimed or run indiscriminately.

Some old tests asserted guessed VAT, storefront absence implying hidden prices, old direct route wiring, or resetting admin passwords at startup. Those expectations were reconciled with the reviewed contract; wrong behavior was NOT restored. A real pack identity gap was fixed rather than dismissed as an old assertion. An early generated fixture used the wrong async event loop and was corrected; this was a harness error, not a deployed application error.

Safety: final mutation tests use generated UUID databases on loopback Mongo and delete them afterward. The initial verification agent ran six auth/session tests against preview before the stronger harness was added; the final auth verification uses isolated TestClient/Mongo only. Preview browsing creates ordinary login sessions; catalogue and production data were not changed. No persistent credentials were created or rotated.

## October 8 evidence and UI (historical; superseded by targeted refresh below)
- Captured native `window.productObj` for Pets Houses Beso Hair & Skin: **2 kg = SAR 46 / quantity 15**, **4 kg = SAR 85 / quantity 2**, with distinct actual variant IDs/SKUs. Tests retain those exact observed values; parent price is never assigned to both children. The unresolved parent itself remains quarantined.
- Captured Beso baby-powder 20 kg source values: Pets Houses **SAR 79.35**, Zarafa **SAR 83.95**, Petsy **SAR 87**. The comparison test uses source-specific identity, not only a title or an unrelated marketing number. Captures are evidence fixtures in disposable DBs, not a catalogue refresh or live-price guarantee.
- Preview still contains legacy/stale observations. Real SKU **8699245859829** therefore correctly shows current own/competitor prices and sales as **unavailable**. No old dates were freshened, no legacy rows promoted, and no historical backfill run.
- Selected **Petsy** in the actual Market Share UI; confirmed matching request parameter, retained selection, HTTP200, zero eligible rows, and null sales totals. A populated isolated test separately verifies A-only/B-only/shared membership. The store selector is a row-membership filter; it does not rebase a Saudi-wide market-share denominator.
- Verified desktop **1920×800** and mobile **390×844** with the real catalogue and actual Beso details. Final screenshots showed no horizontal overflow. Verified product-panel and Price Intel sheets, search/paging, Market Share, Scanner, Discounts, unavailable states, and disabled unsupported confirmations. Earlier invalid 1920×1080 captures were not accepted; they were replaced.
- An old Beso image URL is unavailable; a clear fallback is shown, not a broken image or substituted stock image.

Tests use **MOCKED provider responses only inside explicitly isolated fixtures** and a TestClient transport for isolated auth. Preview application APIs are not mocked. Existing email simulation remains **MOCKED**; Zid exact orders remain unavailable pending partner approval and complete coverage. Exact competitor sales or Saudi market share are not claimed.

## October 9 — final six-finding acceptance

**Result: verified for the approved preview-only fix scope and ready for the Save to GitHub handoff. This is NOT a production-readiness certification.**

| Finding | Implemented and verified |
|---|---|
| 1. Ambiguous parents / variant separation | Empty variants with options, identity-less children, duplicate native child IDs and remembered multi-variant parents remain quarantined. Existing child-only price/stock/identifier inheritance protection remains intact. Native Hair & Skin 2kg and 4kg identities are distinct. Quarantined parent shows no current price or stock. |
| 2. Historical quantity vs current stock | `own_stock` and comparison adapters withhold unknown, removed, quarantined or stale current quantities. Historical quantities carry their original observation timestamp, not the latest sync time. Real parent displays **Last observed quantity: 17**, October 8 timestamp, **not current stock**, never “17 in stock”. Details and Market Share distinguish unknown from OOS. |
| 3. Matcher failure + real refreshed evidence | Original October 8 failure was the deliberate zero-current-verified-offers guard, not a matcher crash. Guard retains previous matches. Latest invalid offers cannot resurrect older eligible prices; nullable original price is safe; identity-specific rejection does not reject siblings. Targeted October 9 refresh produced two valid Beso litter matches; no unsupported matches invented for Hair & Skin children. |
| 4. Market Share semantics | Overview, product tables, breakdown, methodology and CSV identify inventory movement and shelf-value proxies; removed sale-floor/measured-exact claims. Exact share remains withheld without complete compatible transaction evidence. Fresh prices alone do not establish units sold. |
| 5. Errors vs empty results | Every Market Share data tab, Price Intel dashboard/detail, Scanner and My Products has a visible failure + Retry state. Old product details are cleared and stale responses ignored. Failed Price Intel core requests do not render an empty comparison table. HTTP503 browser injections and restored-transport retries verified. |
| 6. Membership vs comparison scope | Separate “Membership” filter and “Competitor comparison” control. `all`, selected IDs, and selected-none supported. Scope carried through cohort, Price Intel table/detail, Scanner, Market Share dataset/detail/CSV/cache keys. Membership derives independently from the all-tracked-store evidence. Real UI retained Beso when **membership=Zarafa, comparison=Petsy**, and showed **87–87**, not Zarafa's 83.95. |

### Scanner and crawler correctness included
- Scanner ranks only current, eligible same-product offers with available own stock. Selected competitors govern minimum, average, gap and offer lists; well-positioned rows now also expose minimum/maximum and cohort identity. Excluded/OOS/hidden/stale/low-confidence offers do not drive recommendations.
- `crawl_persistence.py` checkpoints raw captures **before** Salla detail enrichment in the successful Tier 1/2/3/bulk persistence paths; enriched evidence is separate from immutable raw evidence. Interrupted captures are replayed before the next store crawl.
- Original ISO observation timestamp is preserved through BSON's millisecond truncation so replay cannot duplicate events. Snapshot/event/ledger replay is idempotent; a failed daily-ledger write is surfaced, not logged as a full success. Quarantined-only or failed persistence work cannot be marked successful. Job failure is no longer demoted to degraded by a second status condition.
- Preserved prior 19 review gates and earlier data-integrity fixes. No broad route extraction or optional performance work.

### Preview-only refresh audit
- Executed `/app/scripts/refresh_preview_beso.py` after a successful capture-only dry run. Guard refuses non-loopback Mongo and requires the exact configured `.preview.emergentagent.com` origin.
- Database: local preview `daleel_pets`; host `localhost`. No production endpoint, backfill, full-store crawl, or production secret was used.
- Audit: `/app/test_reports/targeted_preview_refresh.json`, run **53c5cd7b214b4223b3ab3b39e149e6f3**, completed **2026-10-09T05:52:48Z**. Includes public source URLs, SHA256 response hashes, raw allowlisted source captures and real capture timestamps.
- Only source pages for own Beso litter, own Hair & Skin variants, Petsy litter and Zarafa litter were fetched. Matching restricted to the four approved own identifiers.
- Fresh source values: own litter **79.35 SAR**, Petsy **87 SAR**, Zarafa **83.95 SAR**. Hair & Skin **2kg/5065023629268 = 46 SAR, quantity 15**; **4kg/5065023629848 = 85 SAR, quantity 2**.
- Unrelated `my_products`, `product_snapshots`, and `product_matches` fingerprints are identical before/after. Target observations are appended; historical snapshots were not rewritten or re-dated. The preview audit collection records the targeted run separately.
- The old full-catalogue sync failure/freshness warning is intentionally **not rewritten as a global success**. The targeted match succeeded; other stores/catalogue items were not refreshed under this authorization.

### Verification results
- **104 original selected tests passed**: reviewed-core 52, isolated auth 10, real-source 6, related contracts 36.
- **22 new isolated acceptance regressions passed**: quarantine, history, latest-invalid precedence, offer-specific matching, scope parity, durable capture, real interrupted-ledger replay, cancelled enrichment, permissions and parent/child search.
- **7 live-preview read-only API checks passed**: all/A/B/none scopes; detail and Scanner parity; Market Share filtered product/detail; CSV scope; invalid IDs; refreshed children visible.
- **Total: 133 passed; 0 failures/errors.** XML results: `test_reports/pytest/*-final.xml`. Runner: `python scripts/run_reviewed_tests.py` (126 isolated checks); live suite: `backend/tests/test_iter40_preview_scope_checks.py` using existing documented credentials.
- `python -m compileall -q backend scripts`, `python scripts/validate_crons.py`, and `yarn --cwd frontend build` passed. Five existing authenticated schedules validated; none changed.
- Desktop **1920×800**, mobile **390×844**: actual variants, Market Share membership/comparison, Price Intel selected-offer detail, Scanner scope. Final overflow checks **[]**. Wrapped the wide Market Share table rather than hiding trailing columns.
- Fault-injection retries verified for all six Market Share data tabs and Price Intel dashboard; testing-agent checks also covered Scanner/My Products, filter-options and detail failures. **MOCKED HTTP failures only in tests**; comparison prices were live source observations, not mocked.
- Authenticated layout now waits for session verification and only mounts notification polling for alert-authorized users. Follow-up browser navigation produced **no 401 requests**; credentials and JWT validation remain unchanged.

### Testing-agent findings reconciliation
Initial report `iteration_40.json` is retained as history; see `iteration_40_followup.json` for final closure.
1. Scanner's live row existed in `well_positioned`, but lacked the test's expected `market_lowest`; added it from the same cohort rather than modifying eligibility.
2. Market Share test searched only the first 50 unfiltered rows and expected a nonexistent `competitors` root. Corrected test to filter by SKU and assert `product.sellers` / `product.competitor_price_min`. Live scope data was already correct.
3. Child SKU search worked; English parent search did not include the Arabic-named children. Search now follows explicit parent listing identity without merging children.
4. Notification polling mounted before auth resolution; authenticated layout gating resolved the observed 401 loop. No password reset, seed rotation or token-validation relaxation.

## Deferred work and readiness impact

| Deferred item | Correctness / readiness impact |
|---|---|
| Full-catalogue refresh and production provenance/data hygiene | **Blocks claiming whole-catalogue freshness or production data readiness.** Outside authorized writes. Stale/unverified records remain excluded or unavailable; targeted acceptance does not imply all stores are fresh. Production TEST_Regression_Store/Test Store cleanup was not performed. |
| Webshare billing/config and broad crawl coverage | Existing external 402 limitation not exercised/resolved. **Blocks reliable full-store coverage**, not correctness of the verified native public-source comparisons. |
| Zid partner OAuth approval and complete order coverage | **Blocks exact own revenue/units claims**. Exact figures remain unavailable rather than estimated as fact. Competitor transaction evidence is also required for exact market shares. |
| Email integration, Slack/Telegram alerts, alert history, watchlists | Email remains **MOCKED** pending credentials; these features are not completed by this task. Do not claim working email delivery. Non-blocking for this acceptance scope. |
| New-store activation | Remains deferred until dashboards/data are clean. More coverage would not repair missing evidence; no activation performed. |
| Salla supplement time budgets, sitemap discovery, other optional performance improvements | Deferred; raw captures before enrichment are now durable. Slow acquisition can still reduce freshness, so current-offer filters remain essential. No claim of complete crawl throughput or graceful recovery of a response never captured to the database. |
| Broad `server.py` routes refactor | Deferred **until user gives the final green light**. Maintainability debt, not a failure of the 133 verified checks. |
| Legacy broad test suites outside the selected gate set | Not a blanket certification of every historic test or feature. Selected gates plus new invariants are the acceptance basis; stale magic-number suites require separate re-baselining. |

## Save to GitHub handoff — pending user action
Use the chat's **Save to GitHub** control. Verify repository **DC90-90/Pet-Crawler** and intended branch **conflict_130726_1244** against the selected UI destination; local branch is still `main`. Include this acceptance report and final regressions. Record the resulting remote commit ID after save; **none is claimed yet**. No deployment action is authorized.

Potential enhancement: an exportable per-offer evidence panel linking price, timestamp and source would make comparison review faster.

## October 9 — continuation validation against commit `daa86dfbe95230df8165c83230a4e574f2290d14` scope

Implementation and testing were preview-only. Live catalogue/evidence checks were read-only; mutation tests used disposable local UUID databases. Preserved newer working changes; no deployment, no live refresh/sync/crawl invocation, no backfill, no credential rotation, no production writes. `git cat-file -t`, `git show --stat --oneline` and `git log` confirmed the saved reference locally; no checkout/reset/revert/push occurred.

### Commands run
- `python /app/scripts/run_reviewed_tests.py`
- `pytest -q /app/backend/tests/test_iter40_preview_scope_checks.py --junitxml=/app/test_reports/pytest/iter41_preview_scope_checks.xml`
- Preview UI checks via browser automation (desktop `1920x800`, mobile `390x844`) using existing preview credentials.

### Results
- `run_reviewed_tests.py` groups passed:
  - reviewed-core: **52 passed**
  - isolated-auth: **10 passed**
  - real-source: **6 passed**
  - related-contracts: **36 passed**
  - six-acceptance: **22 passed**
  - four-correctness: **10 passed**
- Live preview API suite (`test_iter40_preview_scope_checks.py`): **7 passed**
- Combined target set this continuation: **143 passed, 0 failed**.

### Focus checks completed for four remaining correctness gaps
1. Parent identity persistence independent of `my_products` materialization: validated by `test_first_seen_parent_without_catalog_row_survives_flagless_own_response` and related competitor/read-through checks (pass).
2. Root-first then children-later exclusion from current comparisons while preserving historical evidence: validated by `test_root_first_children_later_excludes_root_without_editing_history` (pass).
3. Daily-ledger replay idempotence by immutable observation identity (including counters and stale replay protection): validated by interruption + old/new replay tests (pass).
4. Row-level `OperationFailure` propagation and checkpoint non-success on partial batches; successful idempotent recovery without duplicates: validated by validator-code-121 test path (pass).

### Preview UI read-only verification
- My Products search confirms parent + children are separately retrievable (`Hair & Skin`, `5065023629268`, `5065023629848`) and parent detail shows unavailable current price with historical quantity context.
- Price Intel/Market Share selected-competitor scope toggles were exercised successfully.
- No desktop/mobile horizontal overflow observed (`overflow=0` on both 1920x800 and 390x844 runs).

### Remaining limitations (explicit)
- Price Intel detail exclusion chips depend on product/scope state; in this run, tested parent detail rendered as unavailable with zero sellers rather than showing exclusion-chip variants.
- UI checks were read-only against existing preview data; synthetic root-first live chronology was not injected into preview (covered by isolated backend regressions).

### Final implementation details and evidence

| Gap | Fix and evidence |
|---|---|
| First-seen parent without a catalogue row | New monotonic `listing_identities` collection remembers store/listing identity and parent-SKU aliases before own-row filtering or competitor normalization. It does not depend on a successful `my_products` update. A flagless/SKU-only reappearance stays unavailable. Two-pass batch registration protects roots that precede children in the same batch. Valid native children stay separate. |
| Previously accepted root superseded by children | `parent_identity.py` annotates current views and cohorts using the identity registry plus read-through existing child/quarantine evidence. Historical root snapshots/events are **not updated or re-timestamped**. `parent_listing_not_an_offer` excludes the root from current price cohorts, match resolution, own prices and Market Share. Price policy version changes to `offers-v3-parent-aware-current-7d`. |
| Idempotent daily replay / stale closings | `ledger_receipts.py` applies each immutable event ID atomically with the row observation counter. Store-day first-seen counters are derived, not incremented again on retry. Duplicate receipts do not rewrite row fields; older new observations cannot replace a newer closing value or timestamp. Original microsecond ISO time is retained through checkpoint replay. |
| Per-row failure cannot become success | The actual Mongo validator code **121 OperationFailure** test permits one row and rejects another. Batch returns incomplete; crawler propagates it; checkpoint is `recovery_required`, not `persisted`, and store-day status is partial. Removing the validator lets recovery finish without duplicate observations, snapshots, events, or first-seen counts. |

- Interrupted **after successful ledger materialization but before checkpoint completion**: replay leaves both ledger row and store-day document identical. This is distinct from the prior iteration's pre-ledger interruption test.
- Shared store/day leases serialize ledger writes and sealing. Seal resumes only pending row seals; it does not replace closing evidence. A lock conflict is an explicit unresolved operation, not success.
- Recovery records structured checkpoint errors and raises `RecoveryIncomplete`; job failures retain recovery details. A failed recovery does not proceed to a new store crawl and pretend the previous work succeeded.
- Own-store ledger results are also checked; unsuccessful outcomes are no longer hidden by a fail-soft log-and-success path.
- A proven duplicate already applied to a sealed day can be acknowledged **without writing the sealed documents**. An unapplied sealed observation remains unresolved and requires separately authorized reconciliation.
- Receipt-less legacy rows cannot prove old event membership. Replays at or before their stored timestamp—including the same BSON-truncated millisecond—are explicitly `legacy_observation_identity_unresolved`; no counters are guessed, receipts invented or history backfilled.

### Final commands and artifacts
- `python scripts/run_reviewed_tests.py` → **136 passed** = the previous126 isolated checks +10 new follow-up regressions.
- `python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=test_reports/pytest/preview-scope-final.xml` → **7 passed**. Environment values were loaded from existing preview configuration; passwords were not printed or changed.
- Final main-agent re-run after the same-millisecond legacy guard: **143 passed, 0 failures**. Independent report `test_reports/iteration_41.json` also records143 passed before that additional conservative assertion; the full final suite was rerun afterward.
- `python -m compileall -q backend scripts` → passed.
- `yarn --cwd frontend build` → passed; no frontend source changes needed for these four backend corrections.
- `python scripts/validate_crons.py` → five existing authenticated schedules valid; no schedules changed.
- New tests: `backend/tests/test_four_correctness_regressions.py`; machine-readable output: `test_reports/pytest/four-correctness-final.xml` and the other six `*-final.xml` files.
- Desktop/mobile smoke logs: `/root/.emergent/automation_output/20261009_112506/console_20261009_112506.log`. Parent remains unavailable with original historical17 and timestamp; 2kg46SAR/15 and4kg85SAR/2 remain distinct. Independent checks additionally exercised selected competitor views; both exact viewport sizes had no horizontal overflow.
- `test_reports/four_fixes_preview_evidence_audit.json`: before/after independent-testing SHA256 fingerprints identical for **all eight** checked preview collections (`my_products`, `products`, `product_snapshots`, `observation_events`, `daily_ledger`, `daily_ledger_store`, `crawl_checkpoints`, `listing_identities`). New identity registry remains empty in live preview because no new ingest/backfill was authorized; existing evidence is protected by read-through classification.

### Unresolved failures and operational limits
- **No unresolved failure in the approved acceptance checks.**143/143 passed, plus build/compile and desktop/mobile checks.
- Legacy receipt-less or unapplied sealed recovery is intentionally blocked, not silently repaired. These explicit states require separate authorized reconciliation; this continuation does not certify an old production ledger as reconciled.
- Interrupted process leases expire after five minutes; recovery may report a lock conflict until expiry. No in-process retry timer, scheduler change, or production recovery job was introduced.
- Per-row applied-ID arrays grow with genuine observations within that store/offer/day; exceptional high-volume receipt compaction is not implemented. Existing tests do not constitute load/chaos certification.
- Browser verification did not manufacture a root-first chronology or new source evidence in the live preview. That chronology and real row-level failure/recovery are verified in isolated Mongo tests. Preview APIs were **not mocked**.
- Existing external limitations remain: Zid approval/complete order coverage, Webshare billing/coverage, and **MOCKED email delivery**. Optional performance work, broader reconciliation, new-store activation, and the large server refactor remain deferred. No production readiness or full-catalogue freshness claim.

### GitHub handoff status
Save these changes using **Save to GitHub → `DC90-90/Pet-Crawler` → `conflict_130726_1244`**. Saved reference `daa86dfbe95230df8165c83230a4e574f2290d14` is the comparison baseline, **not a claimed new fix commit**. The resulting remote commit is **pending the user's save and verification**. No deployment is authorized.

## October 9 — matcher integration follow-up against saved `aa2c442`

**Result: existing143 checks +1 new regression =144 passed; zero unresolved test failures.** This narrow continuation preserves the previous parent-identity and ledger-recovery changes.

### Reproduction and correction
- Before correction, `run_matching_for_all` checked ordinary offer eligibility before its empty-pool guard, but parent-registry annotation was applied later inside individual product matching. A pool containing only a formerly valid, now-superseded root therefore passed the guard, matched nothing, deleted automatic matches and returned normal unmatched statistics.
- Added shared `verified_matching.prepare_candidates`: applies brand review, parent-registry/read-through annotations, own-store/offer-ID checks and current-offer exclusion at one evaluation time.
- Batch matching prepares this pool **before** the existing no-eligible-offers safeguard. The exact prepared pool is reused during actual matching via `candidates_prepared=True`; standalone matching defaults to the same preparation path. This avoids a different guard-versus-match eligibility policy within a run.
- Existing error text remains unchanged: `Refusing to rebuild product_matches: 0 current verified competitor offers (missing, stale, quarantined, hidden or out of stock). Existing matches left untouched.`
- No schema, auth, UI, ledger, source ingestion or historical data changes were needed. Changed runtime files: `backend/matcher.py`, `backend/verified_matching.py`. Test runner includes the new dedicated regression group.

### New regression: `test_parent_registry_only_pool_aborts_and_preserves_unrelated_automatic_matches`
File: `backend/tests/test_matcher_parent_pool_regression.py`.
1. Disposable local Mongo contains an owned product, a formerly valid root snapshot and two automatic matches: the root match and an unrelated offer.
2. Parent registry marks that root's listing as a parent. The raw candidate passes ordinary exclusion; no eligible child observations exist; individual parent-aware matching produces no matches.
3. Batch matching must raise the exact existing RuntimeError **before** individual matching/progress callbacks. Both automatic matches remain identical.
4. The durable matching job must be **failed**, not completed, with no successful result payload. Both matches and the historical root snapshot remain unchanged afterward.

### Actual commands and results
- `git log -4 --oneline`, `git cat-file -t aa2c44225430e65650deaf37608789c22d117503`, `git show --stat --oneline aa2c44225430e65650deaf37608789c22d117503`: reference verified locally; no reset/checkout/revert or Git write.
- **Red reproduction:** `python scripts/run_reviewed_tests.py` → existing136 isolated checks passed, new regression failed with **DID NOT RAISE RuntimeError**. Log: `/tmp/matcher-pool-before.log`.
- **Final main run:** `python scripts/run_reviewed_tests.py` → **137 passed** (52 core +10 auth +6 real-source +36 related +22 six-acceptance +10 four-correctness +1 matcher-parent-pool). Log: `/tmp/matcher-pool-final.log`.
- `python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=test_reports/pytest/preview-scope-final.xml` → **7 passed**, using existing environment-backed preview credentials. No password changes or credential values printed.
- `python -m compileall -q backend` → passed.
- Independent testing repeated137 isolated +7 read-only preview API checks and compilation: **144/144 passed**, report `test_reports/iteration_42.json`, live XML `test_reports/pytest/iter42_preview_scope_checks.xml`.
- Machine-readable new regression result: `test_reports/pytest/matcher-parent-pool-final.xml`. Existing selected test assertions were not relaxed or removed.
- Read-only desktop preview smoke: authenticated My Products/Beso search loaded successfully; no matcher, sync or refresh action triggered. Log: `/root/.emergent/automation_output/20261009_121943/console_20261009_121943.log`. No frontend source changes; this narrow task did not repeat the previous full desktop/mobile design suite or claim a new frontend build.

### Interrupted verification run and remaining limitations
- One initial post-patch verification run encountered local MongoDB `AutoReconnect: localhost:27017: connection closed` failures during unrelated tests/teardown (`/tmp/matcher-pool-after.log`). These were not matcher assertion failures. Read-only investigation found Mongo responding normally afterward; the subsequent complete main-agent run and independent rerun both passed.
- The transient disconnect's underlying cause was **not conclusively established**. No database reset, credential/configuration changes, fixture weakening, or production action was used to obtain the clean runs. There is no unresolved failure in the final144 checks.
- Eligibility is evaluated once for the batch; per-product blacklist/confirmation and identity matching remain separate. This guard does not invent child offers or promise a match for every own product when other eligible candidates exist.
- Mutation tests used disposable loopback UUID databases. No live matcher/refresh/crawl/sync/backfill endpoint or source-refresh script was invoked. Prior source snapshots and preview matching data were not rewritten by this task.
- Existing unrelated limitations remain documented above: full-catalogue freshness/reconciliation, sealed or legacy recovery requiring authorization, Zid order approval, Webshare coverage/billing, and **MOCKED email delivery**. Broad refactoring and optional performance improvements remain deferred. This is not production-readiness certification.

### Latest Save to GitHub handoff
Use **Save to GitHub → `DC90-90/Pet-Crawler` → `conflict_130726_1244`**. `aa2c44225430e65650deaf37608789c22d117503` is the supplied saved reference, **not the resulting commit for this matcher correction**. New remote commit: **pending user save and confirmation**; no hash is invented or claimed pushed. No deployment.

## October 9 — release-safety remediation: final evidence reconciliation

**Accepted for documentation and Save to GitHub handoff only. Production: NO-GO.** The inherited remediation is preserved; this continuation reconciled saved results, not a new application implementation or test execution. Starting local checkpoint: `642854c` on `main`. Original read-only assessment: `afc2d162a144fd3f4b942b694b072637ae6c645c`. Neither is asserted to be the resulting remote remediation commit.

### Exact count and provenance

| Saved JUnit filename under `test_reports/pytest/` | Cases passed | Suite start UTC, 2026-10-09 |
|---|---:|---|
| `reviewed-core-final.xml` | 52 | 15:53:07.456244 |
| `isolated-auth-final.xml` | 10 | 15:53:11.811717 |
| `real-source-final.xml` | 6 | 15:53:15.140307 |
| `related-contracts-final.xml` | 36 | 15:53:16.907482 |
| `six-acceptance-final.xml` | 22 | 15:53:19.058790 |
| `four-correctness-final.xml` | 10 | 15:53:21.857265 |
| `matcher-parent-pool-final.xml` | 1 | 15:53:24.713077 |
| `release-safety-final.xml` | 19 | 15:53:26.208499 |
| **Isolated subtotal** | **156** | Eight groups |
| `preview-scope-final.xml` | 7 | 15:53:46.951958 |
| **Combined** | **163** | **0 failures / 0 errors / 0 skipped** |

Commands represented by these results: `python scripts/run_reviewed_tests.py` (eight isolated groups) and `python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=test_reports/pytest/preview-scope-final.xml` (preview API scope). The runner refuses non-loopback Mongo and supplies disposable test databases/secrets. Preview API checks concern existing comparison data; they are not production checks or integration delivery tests.

Count reconciliation: **137 previous isolated + 19 new = 156; +7 preview =163**. The safety file has 12 test functions yielding19 cases through an eight-value write-operation parametrization. No build, screenshot, earlier rerun or repeated assertion is counted again. The final preview cases cover table/detail/Scanner scope, Market Share detail/export scope, invalid store IDs and Hair & Skin search.

`iteration_41.json` records136+7=143 and `iteration_42.json` records137+7=144. They are historical independent verification, **not an independent certification of the new19 cases**. Common `*-final.xml` filenames have newer15:53 contents. No new independent163-check report was found. Artifact hashes and retained failure excerpts are in `test_reports/release_safety_reconciliation.json` so future overwrites can be detected.

### Failed attempts and final rerun

| Attempt | Actual result | Failure / correction evidenced by saved log and current fixture |
|---|---|---|
| `/tmp/release-existing-tests.log` | 136 passed, 1 failed | Cron protocol test reached an unbound server Mongo client: `RuntimeError: Event loop is closed`. The fixture now explicitly monkeypatches `server.db` to its disposable DB. The subsequent core52 and other prior85 cases pass. This is distinct from the earlier matcher task's transient Mongo disconnect. |
| `/tmp/release-all-tests.log` | 150 passed, 3 failed (137 existing +13/16 new safety cases) | Three fixture `AttributeError`s: module-level `_self_heal_playwright`, `zid_orders.get_zid_headers`, `server.create_token`. Corrected spies to actual boot/credentials paths and used `make_token` with actual Mongo user IDs. These failures occurred before the intended safety assertions; they are not successful safety evidence. |
| `/tmp/release-all-tests-2.log` and eight final XMLs | 156 passed, zero failed/errors/skipped | Full rerun after fixture corrections; safety suite expanded16→19 with manual HTTP mutation drain/block, schema-preparation gate and uncommitted-candidate readiness tests. No tests were skipped to obtain the green result. |
| Latest `preview-scope-final.xml` | 7 passed, zero failed/errors/skipped | Separate preview run after the final isolated run, bringing the selected total to163. |

The temporary logs are not assumed durable across environments: key result/error excerpts and SHA256 fingerprints have been preserved in the reconciliation JSON. Raw original logs remain at the paths above in this workspace. No application rerun was necessary to verify these saved counts in this documentation-only continuation. Deprecation/peer-dependency warnings remain; the selected final set has no unresolved test failure, but this is not full legacy-suite, load, chaos or security certification.

### Verified release-safety work and limits

- **Startup / business writes:** `release_database.py`, `release_control.py`, `release_runtime.py` and server wiring default to observer/no business writes; startup does not seed, migrate, build indexes, warm write caches or probe integrations. Eight write-operation cases reject direct/GET-side mutations. Auth security writes in observer mode and authorized control/maintenance writes are explicit exceptions; this is not a storage-level read-only guarantee.
- **Freeze / maintenance:** tested draining admitted work, refusing new writers, retaining crashed-writer permits instead of claiming quiescence, and requiring frozen matching ownership/approval/unchanged plan hash for the tested index operation. It does not stop legacy unfenced processes or establish production DB privileges. Maintenance plan counts/indexes/stores are not an exact production document-impact audit.
- **Scheduling / identity:** all five `.emergent/crons.yml` entries are OFF in source; owner/epoch protocol prevents stale queued execution across synthetic A→B→A transitions. Uncommitted candidate is not ready. This is **not** proof of production scheduler ownership, deployed build identity, actual image rollback, backup restoration or old-worker shutdown.
- **Unavailable features:** selected tests prove disabled orders return before credential lookup, disabled refresh helpers refuse work, invalid cron auth is denied, and disabled own-sync acknowledges without queueing. Email/digests cannot be enabled as implemented delivery. Frontend source now uses `ReleaseContext`, `ReleaseBoundary`, observed-price comparison and release-status pages; automatic-refresh OFF and as-of language replace live-price promises in limited mode. No retained release-specific desktop/mobile browser artifact was located; earlier screenshots certify earlier UI only. Full restricted-customer and egress acceptance remains outstanding.
- **Existing correctness:** parent/variant identity, empty-pool match preservation, ledger idempotency/recovery, unknown-value handling and comparison-scope checks remain green in the final rerun. No production data cleanup or full-catalogue freshness is inferred.

### Clean-build evidence — frontend only, not a saved production artifact

`test_reports/release_build/result.json` and its install/build logs record **Node20.20.2 / Yarn1.22.22**, fresh dependency installation with `--frozen-lockfile`, compiled frontend, unchanged lock and matching generated frontend/backend manifest at that build time. Run: **15:46:59–15:48:06 UTC**. Lock SHA256: `2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0` (also matches current lock).

The result explicitly says `source=uncommitted-candidate`, `production_pipeline_verified=false`, `container_image_verified=false`. Clean frontend/deploy inputs still match the retained clean tree, but backend files `release_control.py`, `release_runtime.py`, `release_api.py`, `zid_orders.py`, the safety test, and `scripts/stamp_release.py` changed afterward; `backend/release_preflight.py` was also added after the build. Therefore do **not** claim a final complete-candidate/image build, immutable saved SHA proof, or reuse that earlier content ID as final release identity. Frozen install emitted peer/workspace warnings; build nevertheless compiled successfully. No saved failed clean-build result was located; the earlier commit's missing lock was an inspection blocker, not a claimed executed Docker failure.

### Documentation validation completed

Offline validation passed for all nine XML hashes/timestamps, **163 distinct case identities**, zero final failure/error/skip counts, three source-log fingerprints/excerpts, build/lock hashes and report/PRD consistency. The first documentation check found a newly added post-build file (`release_preflight.py`) missing from the initial difference list; corrected both reports and the reconciliation JSON, then reran the complete offline check successfully. This documentary check is **not an additional app test** and does not alter the163 total. No app import, DB connection or network call was used.

### Outstanding production gates and handoff

All **B1–B7 remain open for release approval**; detailed closure evidence is in the latest section of `PRODUCTION_READINESS_AFC2D16.md` and the updated rollback runbook:
1. **B1:** saved exact-source/lock inclusion, final candidate build and immutable image provenance.
2. **B2/B3:** production-consistent isolated startup/maintenance impact plus limited-mode restricted-customer and disabled-egress acceptance.
3. **B4:** deployed SHA/deployment ID/digests and actual single scheduler authority; historical15-job discrepancy unresolved.
4. **B5:** approved per-store/SKU eligible coverage, source timestamps and freshness/expiry at release time; no freshening of stale history.
5. **B6:** authorized backup/PITR, successful isolated restoration/integrity checks, compatible fallback image and real rollback rehearsal, agreed RPO/RTO. **No authorized production backup supplied.**
6. **B7:** monitored capacity/readiness/customer-role acceptance, operator ownership and abort/recovery evidence. API readiness alone cannot approve production.

**Save to GitHub — user action pending:** open the chat's Save to GitHub control; verify repository **`DC90-90/Pet-Crawler`** and branch **`conflict_130726_1244`** before confirmation. Local `main` is not the authorized remote destination. Include all remediation source/UI/scripts, `frontend/yarn.lock`, disabled cron manifest, new tests, JUnit/build evidence and updated memory reports; exclude `.env` and secret values. If the exact destination cannot be selected/verified, stop. After save, verify remote files and record the resulting commit SHA; none is claimed here. **No direct push, deployment or production action.**

External limitations remain: Zid orders unavailable pending partner approval and coverage; Webshare402/broad crawl reliability unresolved; email **MOCKED/unavailable**. New stores and broad server refactor stay deferred. Potential later enhancement: exportable per-offer source/as-of evidence for faster comparison signoff.