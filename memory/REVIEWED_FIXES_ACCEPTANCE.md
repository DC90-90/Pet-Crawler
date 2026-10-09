# Independently reviewed Daleel fixes — preview acceptance

Updated: **2026-10-09**. Scope: **preview only, six final acceptance findings plus Scanner/crawler correctness**. The October 9 section below supersedes earlier stale-data/test-count statements. No production changes, credential rotation, direct Git writes, or deployment occurred.

## Checkout and Git handoff
- Requested repository: `DC90-90/Pet-Crawler`.
- Requested destination branch: `conflict_130726_1244`.
- Actual local checkout: `/app`, branch **`main`**.
- Actual current HEAD verified October 9: **`65f6474399bbb89d37b25cd98a8d8062f804be98`**.
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