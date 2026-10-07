DALEEL — ENGINEERING HANDOFF — 7 OCTOBER 2026

STATUS: local containment only; NOT deployed. Read Daleel-investigation.html.
Target repository: https://github.com/DC90-90/Pet-Crawler.git
Target branch: conflict_130726_1244
Exact base commit: 62a1a7261ae181ca51c65283b137109a9d02df93
Do not apply blindly to main (which is older) or an unverified deployment.

APPLY IN AN ISOLATED CHECKOUT/STAGING ENVIRONMENT
1. Check out the exact base commit; preserve local work first.
2. Run: python verify_base.py PATH_TO_CHECKOUT
3. From checkout: git apply --check PATH_TO_HANDOFF/containment.patch
4. From checkout: git apply PATH_TO_HANDOFF/containment.patch
5. Run: python -m unittest discover -s backend/tests -p test_audit_containment.py -v
6. Review the diff, run FastAPI/Mongo integration and a full frontend build,
   then stage against a scrubbed backup. Do not run the existing whole test
   suite with production URLs/credentials: some supplied tests call services.

PATCHED FILES
backend/core/utils.py
backend/market_share.py
backend/server.py
backend/tests/test_audit_containment.py
frontend/src/components/marketShare/Methodology.jsx
frontend/src/components/marketShare/ShareOverview.jsx
frontend/src/components/marketShare/SourceChip.jsx
frontend/src/pages/MarketSharePage.jsx
frontend/src/pages/MyProductsPage.jsx
frontend/src/pages/ScannerPage.jsx

VALIDATION
30 new offline regression tests pass. Six changed JSX files parse successfully
with Babel parser 7.28.5. Changed Python files compile. No live DB writes.
Full integration/build/browser regression for the application NOT performed.
The report itself was inspected separately as a standalone deliverable.

INTENTIONAL BEHAVIOR CHANGES
Demo seed requires SEED_DEMO_DATA=true AND APP_ENV=development/test;
default environment is production. Development demo snapshots are marked.
Gaps and implausible signal jumps are withheld rather than assigned clipped sales.
Legacy My Products share is unavailable until denominator migration.
Market Share missing product evidence is unavailable, not fabricated zero.
The scanner metric is price-gap exposure, not an uplift prediction. Existing
revenue_uplift/total_uplift_sar keys remain deprecated aliases for compatibility;
new explicit fields are added. Do not treat those old names as forecasts.

RELEASE BLOCKERS
Variants/store-scoped identities, source provenance, all legacy analytics paths,
zero coercion in extractors, old cached data, KSA/UTC boundaries, ledger replay,
order completeness, RBAC, build packaging and historical quarantine remain.
No stored data was repaired. Do not interpret this package as production ready.
Thresholds inherited from the existing estimator are conservative heuristics,
not validated sales limits. Withheld anomalies need source review.

REPRODUCTIONS
The before/ directory captures the UNPATCHED Oct 7 commit with synthetic fixtures.
These demonstrate bugs, not production contents. Run scripts against an isolated
unpatched checkout with: python SCRIPT.py PATH_TO_CHECKOUT
The reproductions assert old behavior; they are not acceptance tests.

DEPLOYMENT / ROLLBACK
Confirm deployed SHA, take a restore-tested backup, and version/rebuild caches
in staging. Do not overwrite historic evidence or mass-delete suspected rows.
Promote only after report acceptance gates. Roll back code and derived-dataset
version together if needed. No production deployment commands are included.
