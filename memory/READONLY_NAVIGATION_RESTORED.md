# Authorized read-only navigation restored; production cohort timeout still open

**Later correction:** Nav restoration subsequently went live in run1970e575, but data reads still time out. Missing-store-leading-index claim below is WITHDRAWN (metadata-tool dict sorting); do not create duplicates based on the earlier key-order interpretation. See `CURRENT_DATA_READ_INCIDENT.md` and `READ_PATH_CANDIDATE_VERIFICATION.md` for current findings/unpublished candidate and185final checks.

Date: 2026-10-10 (final verification around08:06 UTC).

## User request and scope

User: “where are the other tabs such as market share tab, price intel, etc..? still there is error (Request failed. Results are unavailable, not empty.)”

Confirmed choice: **“Yes, keep all authorized tabs visible in read-only mode”** and **“i'm using super admin account, all tabs should be visible”**.

Authorized work: read-only live diagnosis and targeted preview code changes/testing. Existing prohibitions remain: no production data/index/config changes, writer enablement, additional deployment or broad server refactor. No shortening the180-day history, loosening7-day freshness, changing variant matching, silent truncation or empty-success fallback.

## Two distinct causes

### 1. Missing tabs — fixed and verified in preview, NOT newly deployed

`Sidebar.jsx` hid every page except My Products/Intel whenever `release.price_comparison_only` was true, and hid Alerts when email was disabled. It also hid Users from super admins. `ReleaseBoundary.jsx` independently blocked direct URLs. These were release-mode presentation restrictions, **not a loss of super-admin permissions**.

Implemented:
- All **10 role-authorized sidebar links** remain available: My Products, Price & Market Intel, Market Share, Price Scanner, Discounts, Alerts, Stores, Import, Users, Settings. Non-admin restrictions remain enforced by unchanged `canAccessPage`, `ProtectedRoute`, `SuperAdminRoute`, backend auth/access policy.
- Price-Intel-only accounts link to `/price-intel` rather than an unauthorized `/insights` destination. Existing merged Intel page restored with its read-only tabs; exact evidence/capability limitations remain disclosed, not enabled.
- Release boundary now displays a read-only notice without replacing authorized pages with an unavailable screen.
- Individual source refresh/import/matching/store-edit/scheduling/alert actions disabled; handler guards added where relevant. User-management inputs/create form are disabled fieldsets, destructive control disabled, search and row expansion still work. Existing backend admin-maintenance restriction is unchanged, so these admin writes remain disabled even if other release capabilities become active.
- Narrow backend release exception: **only GET `/api/alerts` and GET `/api/alerts/feed`** may read already-authorized user-owned history. All alert mutations, notification/digest families, delivery and default-deny DB guard remain blocked. No JWT/login/password/role policy changes or credentials created/rotated.
- Imports can read status without uploading. Alerts, Stores, Users and Coverage now show request failure rather than fake empty content when their read fails.
- Request errors retain actual Axios context and distinguish timeout, source change, freshness expiry, database unavailable and generic HTTP failure. My Products no longer assigns an empty dataset on failure. Market Share overview/filter options/products/missing/brands/categories/methodology/product-breakdown now pass through typed errors; retry is available.
- Existing responsive layout preserved; added wrapping in newly exposed controls/rows. No dependencies, styling system, database schema, scheduled jobs or protected environment keys changed.

### 2. Live My Products failure — NOT fixed

Read-only current production diagnostic: `deployer-agent-docs/RCA_d57077e1-e621-4eef-a92a-5ee60b1a55ed.MD`.

- Platform-initiated deployment **already completed**, serving run `d57077e1-e621-4eef-a92a-5ee60b1a55ed`, Oct10 06:58:49→07:06:01 UTC. Frontend/backend both from this run; no mixed/old image explanation.
- This run contains the **previous P0 mitigation** (local cache/deadline/compact projection). It does **not** contain this newer navigation restoration. No new deploy was initiated here.
- Authenticated requests in live logs return **503 `price_query_timeout`**, not the old500 and not source/freshness race codes. Diagnostic did not log into a production account; authenticated failure evidence comes from production request logs.
- Actual stack: `price_read_limits.bounded_read` → `my_products_cache` → `_my_products_dataset` → `catalog_views.dataset` → `comparison_views.context` → `price_cohort.build_cohorts` aggregate/getMore → **`pymongo.errors.NetworkTimeout: ...mongodb.net:27017: The read operation timed out`**.
- Even a diagnostic collection count timed out. Actual reported indexes are time-leading; the index NAMED `store_id_1_crawled_at_-1` actually has `{crawled_at:-1, store_id:1}` key order. No store-leading index observed. **Index names alone cannot establish coverage.**
- Previous changes bounded/reclassified the error; they did not make the cold180-day aggregate finish. Shared cohort consumers may also fail; only My Products authenticated5xx was observed in current live logs, so separate production tab success/failure is not claimed.
- Additional read-only code investigation did not establish a safe code-only replacement preserving complete latest/variant/historical-discount semantics under existing constraints. Its categorical claim that the index alone resolves it is **not accepted as verified evidence**: the live diagnostic explicitly says supporting index may not be sufficient, and local fixtures still examined the same100k records. No representative production post-index explain/performance proof exists.

## Verification and limitations of evidence

### Backend
- **180 checks passed** across selected suites:156 safe reviewed regressions +24 final targeted/P0 checks (7 navigation/alert guard checks +17 original P0/temporal/full-match checks). Final XML has zero errors/failures/skips.
- Targeted checks: actual preview super-admin role/release, alerts/history200, unauth401, real existing restricted account403; release exact-path exception and broader-deny unit/isolated checks. Intentional denial probes called protected mutation APIs and received4xx; this is distinct from frontend read navigation, which issued no business mutation requests.
- Existing observer/variant/freshness/cache/failure/no-truncation regressions rerun. Final P0 includes the fully matched2,832-product/101,952-snapshot fixture, not just sparse/invalid-barcode baseline data.
- Disposable DB helper now explicitly rejects non-loopback URLs. Restricted-user credentials are read from test-process environment, not embedded in the test source; login failure cannot be skipped. No persistent account/password changed.

### Browser
- Real preview super-admin:10/10 nav links, direct routes, read filters, Intel and Market Share views, read-only actions, Users search/expand and disabled fields verified by tester.
- Restricted-account navigation check used **MOCKED `/auth/me` role response**; real restricted-account API403 separately verified. No fake role response is presented as actual authorization proof.
- Initial tester found Market Share dropping typed errors. Fixed all affected components. **Nine final browser checks passed**: overview+filter source race; five tab timeout messages; real methodology retry recovery; product breakdown freshness error and retry-error removal.
- Those failure responses are **MOCKED/INJECTED HTTP500/503**; successful recovery reads actual preview APIs. Breakdown recovery check proves error removed/dialog present; it is not an exhaustive monetary-content validation.
- Desktop1920×800 and mobile390×844 explicit viewport checks: **zero overflow offenders**, both navigation and final long error banners. No production visual verification of this unpublished fix.
- Babel syntax parsing and preview compilation/browser execution passed. Standalone ESLint could not run: installed ESLint9 has no project configuration or react-app config package. Three attempted invocations/logs retained; no lint-pass claim or dependency/config migration bundled into this scope.

### Artifacts
- Independent report: `test_reports/iteration_50.json` (original typed-error issue retained, superseded by final self-retest).
- Targeted tests: `backend/tests/test_iter50_readonly_navigation_and_alerts.py`.
- Final24: `test_reports/pytest/iteration_50_final_backend.xml`, `test_reports/iteration_50_final_backend.log`.
- Safe156: `test_reports/iteration_50_run_reviewed_tests.log` plus selected reviewed JUnit files. Earlier iteration50 P0 run was16 checks and omitted the fully-matched module; final24 explicitly includes it.
- Final9 UI checks: `test_reports/iteration_50_ui_retest.json`; screenshots/logs under `/root/.emergent/automation_output/20261010_075448/` and `/root/.emergent/automation_output/20261010_080646/`.
- Lint attempts: `test_reports/iteration_50_frontend_lint*.log`.

## Next actions / backlog

**P0:** Review/accept this unpublished navigation fix. Separately authorize a representative cold-path query/index investigation before any production change. Evaluate actual index key order/size/plans and complete-results performance; a store-leading index is a candidate, not a proven cure. Its default generated name would collide with the reported misleading existing index name, so any separately approved plan must use an explicit non-conflicting name and must not silently drop/rebuild the existing index. Do not enable writes for caching or shorten price history as a shortcut. No automatic rollout.

**P1/P2:** Existing Zid partner approval, proxy billing, data hygiene, alert/watchlist/crawler work unchanged. Broad server refactor remains LAST/on explicit instruction. Email delivery remains **MOCKED/unavailable** and disabled; restoring Alerts history is not delivery integration.

Potential improvement after authorization: a small cold-query latency/timeout diagnostic so cache hits cannot conceal the production bottleneck.