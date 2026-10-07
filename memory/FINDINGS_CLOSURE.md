# Daleel investigation — implementation and verification record

Date: 2026-10-07. Source: user-uploaded Daleel-findings.json (15 findings), investigation HTML and engineering handoff ZIP. User authorized fixing all findings; production changes still require separate authorization. This is NOT a statement that the existing production deployment has been repaired.

## Implemented controls

| ID | Resolution in this checkout | Verification / remaining live work |
|---|---|---|
| F01 Variant prices | Specific store/listing/variant offer IDs; child prices/stock never inherit parent values; unresolved parent offers quarantined. | Real-Mongo test creates two differently priced variants sharing a local SKU. Historical prices cannot be repaired without original variant evidence: fresh production crawl required. |
| F02 Synthetic history | Demo seeding defaults off and requires development/test environment. Synthetic observations marked; legacy/unverified observations excluded from actionable cohorts. No historical rows deleted. | Core APIs tested with 40,089 legacy preview observations safely excluded. Production provenance reconciliation/recrawl pending authorization. |
| F03 Phantom sales | Null remains unknown. One interval estimator rejects missing/capped/reset/anomalous/low-confidence observations and long gaps. | Unit and immutable-fact tests. No false restock-to-zero transition. |
| F04 False measured zeros | Store-wide capability no longer proves SKU-level zero. Only repeated valid evidence or a complete empty order window supplies zero. | Regression tests and complete-empty order-window Mongo tests. |
| F05 SKU / manual scope leaks | Metadata keyed by offer and store. GTIN checksum and leading-zero normalization; suffixes are not GTIN aliases. Confirm/reject decisions require scoped offers; contradictory barcodes/pack/verified brands cannot be overridden. | Real cross-store/local-SKU isolation; permission tests. Old match documents cannot authorize v2 prices. |
| F06 Price divergence | Shared versioned cohort powers catalogue, Scanner, Price Intel, details, Market Share price statistics and market-position summary. Latest reading is selected before eligibility; invalid/OOS readings cannot resurrect older prices. | Populated multi-store test asserts matching cohort IDs and lows across adapters. Fresh/in-stock/confidence/currency/tax/pack requirements shared. |
| F07 Overstated sales/share | Proxy labels; no mixed invoice/proxy percentage denominator; summary numerator/denominator aligned; display caps removed before aggregation; own orders require complete coverage. Profiles/ranking no longer extrapolate sparse observations into monthly revenue. | Exactness projection bug fixed; proxy/profile/ranking parity test. Live Zid order permission remains external. |
| F08 Uplift mismeaning | Scanner displays historical price-gap exposure, explicitly not a forecast. Unavailable/hidden own products excluded; unknown own units remain unknown. | Scanner API/UI and populated cohort tests. |
| F09 Incomplete crawls | Metadata-driven pagination; duplicate/error/cap/count-mismatch detection; explicit completion state; checkpoints precede optional enrichment. Partial catalogues never authorize archival. Attempt time and successful completion time separated. | Fixture pagination tests; own-tax/public-overlay guards. Full source-specific production recrawl still pending. |
| F10 Money/tax/aliases | Decimal validation, Arabic digits, finite/nonnegative values, currency/tax provenance, GTIN checksum, ambiguous alias rejection. Unknown tax never triggers automatic VAT addition. | Contract and own-price tests. Unsupported observations are quarantined, not guessed. |
| F11 Unstable history | Immutable observed/ingested events, idempotent versioned interval facts, offer-specific deltas, KSA-day windows, sealed cutoff, out-of-order records withheld pending explicit rebuild. | Real-Mongo duplicate, KSA 21:00 UTC boundary, late-after-seal tests. Existing legacy rollups retained but not used by v2 sales readers. |
| F12 False freshness/status | Cache keys include policy/build/day and source revision; five-minute max age. Persistent job IDs, status polling, leases and explicit failed/degraded outcomes replace the frontend timer. | Job/lease/concurrency tests; frontend timer removed; manual refresh remains available. |
| F13 Permissions | Server-side page reads and admin mutations; registration off by default; auth-v2 tokens, logout/password revocation; startup never restores an old password over a rotation. | Live auth/RBAC tests pass. **Production credential rotation and session verification are NOT performed.** |
| F14 Release/process | Correct package context, complete backend module copying, no baked .env, strict compose settings, build digest diagnostics, platform cron manifest, authenticated/idempotent cron routes and persisted leases. | Python compilation, frontend build, cron validator; isolated route/job tests. **Production image/build identity and new cron secret configuration are not yet verified.** |
| F15 Taxonomy | Removed generic leading-token brands, store/offer-scoped metadata, explicit inferred/reviewed provenance, admin metadata review with audit record. | Canonical/generic-name tests. Existing inferred categories are labelled unverified rather than silently promoted. Manual review of real catalogue exceptions remains an operational task. |

## Tests
- `/app/backend/tests/test_findings_v2_regression.py`: 24 contract tests.
- `/app/backend/tests/test_findings_auth_live.py`: 6 live auth/RBAC tests.
- `/app/backend/tests/test_iteration37_integration_real_mongo.py`: 9 populated integration tests, isolated disposable Mongo database.
- Combined: **39 passed** at the final full run; final results recorded in `test_reports/pytest/investigation_verified.xml`. Concurrent partial-ingest replay tested three additional times; all passed after under-lock idempotency recheck.
- Reports iteration_36 and iteration_37 preserve initial failures, not current final status. Summary null gating, order projections and mobile layout were corrected after those reports.
- One iteration37 cohort failure was a fixture-clock mismatch (fixed February timestamp vs current-price adapters using October). The fixture now uses one current clock and additionally asserts actual lows and Scanner cohort parity; freshness was NOT weakened.
- Desktop 1920×800 and mobile 390×844 checked with the real 2,303-product preview catalogue. Final mobile checks for `/`, `/insights`, `/market-share`, `/scanner`, `/discounts` ALL returned empty overflow lists. Store profile also verified. Catalogue and Price Intel desktop screenshots returned empty overflow lists. Earlier screenshot-script wrong routes/test IDs were corrected; they were automation errors, not app failures.
- Additional paths hardened: verified-offer discounts and discount history, no aggression badge without observations, offer-specific alerts/digests, proxy-based store leaderboard, trending, gaps, price wars/restock, null subtotal rendering and reviewed-only category conclusions.
- Final external API smoke: `/api/health`, `/api/insights/summary`, `/api/market-share/my-products?limit=1`, `/api/discounts/aggression` all 200. Boot errors empty, unavailable sales totals null, no fake discount leaderboard entries.
- The cron integration test uses **MOCKED test actions** to avoid running a real crawl/archive. Application price/sales APIs are not mocked. Existing email simulation and unapproved Zid-order integration remain outside verified live functionality.

## Required production closure steps — not executed
1. Authorize applying the verified code to the existing live Daleel instance; validate code digest and cron secret there.
2. Authorize a controlled fresh catalogue backfill (retain historical evidence; do not label legacy rows verified). Deactivate known test stores only with approval.
3. Rotate exposed live credentials and invalidate old sessions; check provider tokens and crawler secret. Do not put replacements into a downloadable report.
4. Complete Zid partner approval and verify full order-window coverage. Until then exact sales/shares remain unavailable.
5. Recheck the actual investigation sample products on live endpoints after backfill, including unavailable products and multi-variant packs.

## Intentionally deferred
- Broad server.py route extraction remains last, per the user's earlier instruction. Retired implementations are named `_retired_*`; current routes delegate to the new modules. No broad architecture rewrite was performed.
- Alert history, notifications, watchlists and new-store rollout remain unrelated backlog.