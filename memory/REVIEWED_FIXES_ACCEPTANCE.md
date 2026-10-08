# Independently reviewed Daleel fixes — preview acceptance

Date: 2026-10-08. Scope: preview only. This document supersedes the earlier 39-test closure claims for the reviewed work.

## Checkout and Git handoff
- Requested repository: `DC90-90/Pet-Crawler`.
- Requested destination branch: `conflict_130726_1244`.
- Actual local checkout: `/app`, branch **`main`**.
- Actual current HEAD: **`558861e59fce42a605d909108998a61e7e02f60a`**.
- That HEAD is the supplied **pre-change base**, NOT a commit containing these fixes. No direct commit/push or branch switch was performed. The user approved completing preview verification before the platform's **Save to GitHub** handoff. A resulting remote fix commit is pending that action; none is invented here.
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

## Real-product evidence and UI
- Captured native `window.productObj` for Pets Houses Beso Hair & Skin: **2 kg = SAR 46 / quantity 15**, **4 kg = SAR 85 / quantity 2**, with distinct actual variant IDs/SKUs. Tests retain those exact observed values; parent price is never assigned to both children. The unresolved parent itself remains quarantined.
- Captured Beso baby-powder 20 kg source values: Pets Houses **SAR 79.35**, Zarafa **SAR 83.95**, Petsy **SAR 87**. The comparison test uses source-specific identity, not only a title or an unrelated marketing number. Captures are evidence fixtures in disposable DBs, not a catalogue refresh or live-price guarantee.
- Preview still contains legacy/stale observations. Real SKU **8699245859829** therefore correctly shows current own/competitor prices and sales as **unavailable**. No old dates were freshened, no legacy rows promoted, and no historical backfill run.
- Selected **Petsy** in the actual Market Share UI; confirmed matching request parameter, retained selection, HTTP200, zero eligible rows, and null sales totals. A populated isolated test separately verifies A-only/B-only/shared membership. The store selector is a row-membership filter; it does not rebase a Saudi-wide market-share denominator.
- Verified desktop **1920×800** and mobile **390×844** with the real catalogue and actual Beso details. Final screenshots showed no horizontal overflow. Verified product-panel and Price Intel sheets, search/paging, Market Share, Scanner, Discounts, unavailable states, and disabled unsupported confirmations. Earlier invalid 1920×1080 captures were not accepted; they were replaced.
- An old Beso image URL is unavailable; a clear fallback is shown, not a broken image or substituted stock image.

Tests use **MOCKED provider responses only inside explicitly isolated fixtures** and a TestClient transport for isolated auth. Preview application APIs are not mocked. Existing email simulation remains **MOCKED**; Zid exact orders remain unavailable pending partner approval and complete coverage. Exact competitor sales or Saudi market share are not claimed.

## Remaining work — not executed here
1. **Save to GitHub** for the requested repository/branch, then record/verify the resulting commit ID. Current HEAD above is not the fix commit.
2. Production data/provenance reconciliation, live credential rotation/history exposure response, and live build/config verification remain separate authorized work.
3. Zid partner approval and complete order-window evidence are required before exact own-order totals; competitor transaction evidence is required before exact competitor-sales/share claims.
4. Existing Webshare billing/config issue and mocked email delivery remain unrelated external limitations. This step neither deployed nor exercised production.

Potential follow-up: expose the already-recorded observation provenance in an exportable evidence panel, after the separate reconciliation is approved. Broad `server.py` refactoring remains deferred as requested.