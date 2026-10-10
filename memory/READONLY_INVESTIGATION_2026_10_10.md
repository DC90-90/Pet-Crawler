# Daleel — read-only production investigation

## Authorization and outcome
User approved: “Yes, start the investigation” for read-only production investigation.
**Outcome: investigation blocked on live diagnostic availability; analytics recovery NOT verified.**
No application, auth, environment or production configuration changes were made. No deployment, restart, business-data/index writes, backfill, materialization or crawler enablement was performed. The production investigator later used one ordinary existing-super-admin login (security bookkeeping only) for authenticated GET diagnostics. No credentials created/changed. Only verification/evidence/memory artifacts were added or updated.

## Direct live HTTP evidence — 2026-10-10
Origin: `https://daleel.hrm-sa.com`. Two sequential bounded public requests, no redirects to other hosts, no retries; stopped on diagnostic404.

| Time UTC | Request | Result | Duration |
|---|---|---|---|
| 11:49:51.769551 | GET `/api/health` | 200; healthy/Mongo connected; boot done, phase ready-observer | 407.39ms |
| 11:49:51.839280 | GET `/api/admin/analytics-read-plan?pipeline=cohort` (unauthenticated) | 404 JSON `{"detail":"Not Found"}` | 69.64ms |

Health also reported zero in-process scheduler jobs and last successful crawl2026-10-09T21:00:55.256337Z. These health fields do not establish current scheduled-task ownership, source SHA, run identity, database integrity or analytics recovery.

Evidence: `/app/test_reports/iteration_55.json`, `/app/test_reports/iteration_55_live_http_artifact.json`.

## Preview verification — NOT production evidence
- Existing `test_iteration53_read_recovery_preview.py`:8passed,0failed. Normal login/security bookkeeping is separate from business-data mutations; no credentials created/changed.
- Sequential cohort/latest/ranking diagnostic GETs: allHTTP200/status available; queryPlanner, manual trigger, selected_hint null; ordered installed-index key arrays; sensitive query/server/filter fields absent.
- Desktop1920x800 login smoke returned200/nonblank. No UI or layout modifications; no responsive-change claim.
- No integrations mocked in this verification. Existing email integration remains MOCKED/unavailable; OAuth/order data coverage remains a separate external blocker, not a tested integration here.
- Artifacts: `iteration_54.json`, `iteration_54_analytics_read_plan_capture.json`, `pytest/iteration_54_read_recovery.xml`; screenshot `/tmp/daleel-investigation-smoke.jpg` and automation log directory `/root/.emergent/automation_output/20261010_114711/`.

## Source/handoff reconciliation
- Current source `server.py:1648` registers the diagnostic. `read_diagnostics.py` fixes its pipelines and uses2s Mongo planning/5s total collection deadlines; `read_plan_policy.py` sanitizes output.
- Manual diagnostic does not select a hint. Inherited timeout diagnostics may select an existing exact store/time index in worker memory; `snapshot_strategy.py` and bounded `snapshot_reads.py` exist beyond the simplified handoff description. No changes to these were made here.
- Handoff says diagnostic deployed; older PRD says not implemented. Updated verified truth: implemented/tested in preview, **absent from deployed source** per production investigator, with authenticated404s for all three selectors.
- Historical RCA withdrew the missing store-leading index claim because JSON property sorting obscured key order. Latest RCA section4 again labels JSON key objects as ordered without order-preserving arrays or new method proof. This conflicts with the prior correction: **main agent treats index order as unresolved**, not proven time-leading. No duplicate/missing-index recommendation accepted.
- QueryPlanner bypasses the plan cache and does not provide execution latency or documents/keys examined. Even a successful future live plan cannot alone prove a performance cure.

## Runtime investigation status
**Result received after initial investigation summary.** Active newest successful run confirmed by investigator: `1970e575-b7af-48b5-95e6-318ac726f897`, completed2026-10-10T08:27:12Z. Exact deployed source inspection reports zero diagnostic markers and no read_diagnostics module; server.py:1648 is seed_super_admin. One valid existing-super-admin login200 followed by sequential authenticated cohort/latest/ranking404s. No diagnostic/alternative-hint markers in24h logs. No code/config/index mutations or deployment.

Live logs confirm MyProducts503 (bounded) and MarketShare overview500 (unbounded Mongo NetworkTimeout). Indexed newest snapshot check returns2026-10-09T20:57:11.09Z. These establish real observations and failing heavy reads, not complete dataset quality or a specific winning-plan cause. Production tool supports find/count/distinct/list_indexes, not aggregate/explain. Therefore no actual production plan captured. Updated report: `/app/deployer-agent-docs/RCA_1970e575-b7af-48b5-95e6-318ac726f897.MD`; see index-order caveat above. Exact GitSHA still not established.

## Prioritized next actions
1. P0: diagnostic absence from active build confirmed; obtain approval for the next code/release step rather than repeating inaccessible live explains.
2. P0: **subsequently approved** testing, deploying after verification, then bounded live plans. Candidate includes read-path/retry/timeout/existing-index-fallback changes, not diagnostic-only. Full206-check acceptance now passes and deployment dispatched once/queued. Completion and production plans still pending. See `ANALYTICS_RELEASE_2026_10_10.md` for authoritative rollout progress.
3. P0: capture bounded live cohort/latest/ranking plans and ordered index metadata; choose a remedy from evidence. Seek separate explicit approval before production index builds, materialization or other data changes.
4. P0: verify real My Products and Market Share results/latency after an authorized fix. No new heavy endpoint loads or full scans were run in this investigation.
5. P1/P2: Zid owner OAuth, proxy coverage/billing, data hygiene, alerts/watchlists, new stores only after dashboard recovery; broad server refactor LAST/on approval.

Preserve180-day history,7-day eligibility, strict Barcode/SKU identity and truthful unavailable data. No stale-cache fallback, artificial zero success, fabricated sales or freshness relaxation. Potential later enhancement: cold-query latency/timeout monitoring to distinguish genuine recovery from warm-cache success.