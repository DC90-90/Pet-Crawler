# Daleel production-readiness assessment

## Latest packaging continuation — 2026-10-09

**NO-GO remains.** Packaging corrections against `dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc` and final **185 checks (163 existing +22 packaging)** passed in isolated/preview scope. Full evidence: **`memory/PACKAGING_CORRECTIONS_DC22D72.md`**; reproducible workflow: **`deploy/RELEASE_PACKAGING.md`**.

The actual remote reference omits the lockfile; its underlying save-omission mechanism remains unknown. Explicit inclusion rules and fail-closed export/build checks are implemented, but **corrected remote lock inclusion, saved source SHA/build and committed-artifact readiness remain pending user Save to GitHub**. Candidate02 generates matching manifests for all320 declared inputs and the preview API origin; its SHA is deliberately null and `/api/ready`503 is expected. This is not a positive saved-source release test.

Repository Dockerfiles now verify/consume prepared artifacts, but **actual managed-pipeline consumption, image builds/digests and clean backend dependency installation are unverified**. Existing core fixes were byte-preserved; no production action or credential change occurred. All B1–B7 require separate closure evidence, particularly backup restoration, deployed-version identity, actual scheduler ownership and current data quality/freshness. The older sections below retain their original evidence/totals; newer XML files may replace shared historical paths.

## Historical decision — release-safety remediation evidence reconciled, 2026-10-09

**Production remains NO-GO.** Preview/disposable-database safety fixes are verified within the scope below; no blocking production gate is declared closed. This update finalizes documentation only. It did **not** deploy, access production, stop production writers, restore a backup, backfill data, rotate credentials, or push to GitHub.

The original assessment of immutable commit `afc2d162a144fd3f4b942b694b072637ae6c645c` is preserved below as **historical evidence**, not a description of the remediated workspace. Documentation-continuation starting HEAD was `642854c` on local `main`; it is not a claimed commit containing the remediation or a remote-save result. Save destination: **`DC90-90/Pet-Crawler` → `conflict_130726_1244`**. Resulting remote SHA is **pending user save and verification**.

### Reconciled checks: 163, not 144 and not 163 additional checks

| Latest saved JUnit group (`test_reports/pytest/`) | Passed | Failures / errors / skipped |
|---|---:|---:|
| `reviewed-core-final.xml` | 52 | 0 / 0 / 0 |
| `isolated-auth-final.xml` | 10 | 0 / 0 / 0 |
| `real-source-final.xml` | 6 | 0 / 0 / 0 |
| `related-contracts-final.xml` | 36 | 0 / 0 / 0 |
| `six-acceptance-final.xml` | 22 | 0 / 0 / 0 |
| `four-correctness-final.xml` | 10 | 0 / 0 / 0 |
| `matcher-parent-pool-final.xml` | 1 | 0 / 0 / 0 |
| `release-safety-final.xml` | 19 | 0 / 0 / 0 |
| **Isolated subtotal** | **156** | **0 / 0 / 0** |
| `preview-scope-final.xml` | 7 | 0 / 0 / 0 |
| **Combined selected checks** | **163** | **0 / 0 / 0** |

The eight isolated XML suites started between **15:53:07 and 15:53:26 UTC** on October 9; the preview suite started **15:53:46 UTC**. Actual testcase counts agree with suite totals. Arithmetic: prior **137 isolated + 7 preview = 144**; add **19** release-safety cases to obtain **156 + 7 = 163**. Builds, UI observations, parameter assertions within a case, and repeated runs are not extra checks. The eight parametrized write-operation cases count as eight pytest cases, not eight additional suites.

`iteration_41.json` independently covers **143** historical checks; `iteration_42.json` independently covers **144**, not 163. Their shared `*-final.xml` paths were subsequently overwritten by the release-safety run. There is **no saved independent 163-check testing-agent report**. The latest claim is supported by the later JUnit files and main-run log, not by relabeling iteration 42. This documentation continuation parsed and cross-checked saved evidence; it did **not rerun application tests/builds**.

Durable reconciliation, hashes and failed-run excerpts: **`test_reports/release_safety_reconciliation.json`**. Detailed acceptance: final release-safety section in **`memory/REVIEWED_FIXES_ACCEPTANCE.md`**.

### Failures and reruns are retained, not hidden by the green total

1. Initial existing-suite run: **136 passed, 1 failed**. `test_cron_dispatch_auth_payload_and_duplicate_queue` raised `RuntimeError: Event loop is closed` after the new runtime path reached a server Mongo client not bound to that fixture. Current fixture explicitly binds `server.db` to its disposable DB. Subsequent existing suites passed. Source log: `/tmp/release-existing-tests.log`.
2. First expanded run: existing **137 passed**, then release-safety **13 passed, 3 failed** (**150 passed / 3 failed**, 153 cases at that point). The three failures were invalid test references: `_self_heal_playwright`, `zid_orders.get_zid_headers`, and `server.create_token` did not exist at those module locations. Fixture targets were corrected to the retired-boot guard, `zid_oauth.credentials`, and actual `make_token`/Mongo user identities. Source log: `/tmp/release-all-tests.log`.
3. Final full isolated rerun: **156 passed**, including the corrected cases and three additional manual-write/schema-preparation/uncommitted-readiness regressions, with no failures/errors/skips. Source log: `/tmp/release-all-tests-2.log`; eight final XMLs. Separate latest preview API XML: **7 passed**. No unresolved failure in this selected final set.
4. Non-fatal warnings remain: FastAPI `on_event`, multipart import and test-client cookie deprecations; frozen frontend install reports peer/workspace warnings. Successful build is not a warning-free dependency certification. The older matcher reproduction failure and transient Mongo disconnect are separately preserved in the historical acceptance section; they are not failures in the 15:53 final set.

### Verified remediation versus gates still open

| Gate | Verified in source / isolated or preview evidence | Outstanding production evidence — still blocking |
|---|---|---|
| **B1 Build artifact** | `frontend/yarn.lock` exists and its SHA256 matches the frozen Node **20.20.2** / Yarn **1.22.22** clean frontend build. `release_build/result.json` records success at **15:48:06 UTC** and an unchanged lock. | Lock/new files were not tracked in the inspected starting Git index. Verify inclusion in the resulting saved remote commit; build the exact saved source and record immutable frontend/backend image digests. Saved build explicitly says `uncommitted-candidate`, `production_pipeline_verified=false`, `container_image_verified=false`. |
| **B2 Startup / maintenance** | Startup read-only test; default-deny business write wrapper; freeze drains admitted writers and rejects new work; crashed permit is not silently expired; maintenance index operation requires frozen ownership, approval and matching plan hash. | No authorized production backup/clone supplied. Production-specific seed/index/registry impact, data binding and maintenance plan remain unverified. The plan lists counts/indexes/stores, not a complete per-document production impact proof. |
| **B3 Limited-mode isolation** | All five source cron entries `enabled: false`; capability gates block refresh/orders/manual writes; disabled own-sync cron returns `accepted=false` without queueing. Source UI offers observed-price comparison/status pages and disabled unavailable features; email/digests cannot be enabled as if implemented. | Verify exact saved artifact and restricted-customer desktop/mobile flows, all disabled-path egress and actual production capability configuration. The 19 tests cover selected paths, not every integration or route. No retained release-specific desktop/mobile screenshot/log was located in this continuation; older screenshots do not certify the newly changed UI. |
| **B4 Deployed version / scheduler ownership** | Build identity/status routes and protocol-level release owner/epoch fencing exist. Synthetic A→B→A handoff rejects stale queued jobs; no new in-process scheduling is intended. | Identify deployed Git SHA, deployment ID and image digests for all replicas. Reconcile every actual platform/legacy schedule and worker; prove one authority and no old/new overlap. Historical production health reported **15** in-process jobs. No new production observation was made and no scheduler was stopped. Source OFF flags cannot stop an already deployed legacy writer. |
| **B5 Data freshness / coverage** | Existing selected-offer/variant/cohort checks pass; stale evidence stays excluded; UI source states observed prices, not live quotes, and a seven-day maximum age. | Approve store/SKU scope and current per-offer source timestamps, eligibility and expiry; prove sufficient comparable coverage at release time. Seven passing preview checks and October 9 targeted source fixtures do not prove whole-catalogue or production freshness. No refresh/re-timestamp/backfill authorized. |
| **B6 Backup restoration / rollback** | Synthetic protocol handoff/rollback and interrupted-ledger recovery are tested on disposable databases. | **No authorized production backup is available for restoration rehearsal.** Need backup/PITR ID, completeness/retention, successful isolated restore with integrity/index/history comparison, compatible fallback image, supported image rollback rehearsal and signed RPO/RTO. A→B→A identity simulation is not an image rollback or backup restore. |
| **B7 Operational acceptance** | Uncommitted candidate readiness is deliberately **503/not ready** in the new regression; boot/readiness/capability information is exposed. | Production customer-role, capacity, monitoring/on-call and abort/recovery evidence are absent. Even a future `/api/ready` 200 checks only application conditions; it cannot sign off B1–B7, freshness, backup restoration or external scheduler ownership. |

**Build-provenance limit discovered during reconciliation:** the retained clean build tree has unchanged frontend/deploy sources and the same lockfile as this workspace, but later differences exist in `backend/release_control.py`, `release_runtime.py`, `release_api.py`, `zid_orders.py`, `backend/tests/test_release_safety.py` and `scripts/stamp_release.py`; `backend/release_preflight.py` was also added after that build. Thus the 15:48 frontend build remains valid evidence for those frontend inputs, **not a complete final backend/frontend candidate build or final manifest attestation**. Do not reuse its content ID as the final saved release identity.

**Freeze boundary:** observer mode denies business mutations but deliberately permits narrowly scoped login/logout/refresh security writes. `freezing` drains existing admitted work; `frozen` is not declared until tracked permits drain. The control plane still records authorized transitions/maintenance. This is not a claim of a storage-level read-only database, and it cannot fence old code/direct DB clients that do not use the protocol.

### Current handoff and next decision

Save the preview fixes and evidence using the chat's **Save to GitHub** control, verifying **`DC90-90/Pet-Crawler` / `conflict_130726_1244`** before confirmation. Include the lockfile, new release modules/UI/tests/scripts, source cron disablement and reports; exclude `.env`/secrets. If the destination cannot be matched, stop rather than saving `main` or using a direct push. Verify the remote branch contents and record its resulting SHA. **Saving is not deployment or production approval.**

Next: obtain the missing gate evidence under separately authorized scope. Zid exact orders remain unavailable pending partner approval/complete transaction evidence; Webshare 402/broad coverage is unresolved; email remains **MOCKED/unavailable**. Optional alerts, watchlists, new-store expansion and broad `server.py` refactor remain deferred. Suggested later enhancement: export a timestamped per-offer evidence packet for comparison acceptance.

---

## Historical baseline assessment — immutable `afc2d16`, before remediation

The sections below record what was true during the earlier read-only assessment. Missing-controls/build-input statements here are **baseline findings**, not claims that no remediation now exists; current gate status is above. Production observations retain their original dates and were not repeated for this update.

**Assessed commit:** `afc2d162a144fd3f4b942b694b072637ae6c645c`  
**Assessment date:** 2026-10-09 UTC  
**Recommendation:** **NO-GO for this release as-is, including a customer-facing limited price-comparison release today.**  
**Conditional path:** A limited, explicitly scoped price-comparison release is technically viable after the gates below are closed. Restoring unavailable integrations is **not** a prerequisite if they are verifiably disabled, excluded from the product promise, and cannot run in the background.

This is an assessment, **not authorization to deploy or repair production**. Only assessment documentation was authored. No application/configuration changes, deployment, credential rotation, production login, production database connection, live refresh, backfill, or mutation endpoint invocation was performed. Two unauthenticated HTTPS GETs to the previously documented production `/api/health` were the only production requests made by this assessment.

## 1. Executive decision

The matcher, parent identity and ledger fixes have substantial **preview/test evidence**: 144 recorded checks pass, including the formerly-valid-root-only matcher abort and interrupted ledger recovery. That does **not** establish production readiness.

The remaining release gates are concrete:

1. **Committed build input missing:** `frontend/yarn.lock` exists locally but is absent from this commit. The committed frontend Dockerfile explicitly copies it; that Docker build cannot be reproduced from a clean checkout. A successful workspace build is not evidence of a reproducible commit-only release.
2. **Uncontrolled startup writes:** startup can delete/retag stores and matches, create/change indexes and rebuild classifications/rollups. There is no verified no-migration/read-only startup switch. Whether production would be changed depends on unverified data and markers.
3. **Limited-mode controls are not proven end-to-end:** the crawl pause does not pause own-sync/orders, sealing, archives or digests. Price Intel is a merged price/insights page; page permissions alone are not evidence that unavailable functionality is disabled.
4. **Production build/scheduler identity is unresolved:** the live origin reported **15 in-process scheduler jobs**, whereas the assessed code disables in-process registration in favor of five platform crons. The public endpoint exposes no commit/image identifier. Do not assume this candidate or its safety fixes are live.
5. **Production data and rollback prerequisites are unverified:** eligible offer coverage, required indexes, migration markers, unresolved recoveries, backup completeness, restore capability and a compatible last-known-good image have not been demonstrated.

**Go/no-go rule:** No launch until a release owner signs the closure evidence for every blocking gate. If the lockfile/control changes require a successor commit, assess and record that new SHA; do not relabel this immutable commit as corrected.

## 2. Evidence classes and scope

- **S — source verified:** read directly from the assessed Git object/current matching source.
- **T — recorded test evidence:** committed reports of prior preview/disposable-database tests; not newly executed in this read-only assessment.
- **P — public production observation:** a timestamped unauthenticated health response. Proves only what the endpoint returned.
- **U — unverified production prerequisite:** requires an authorized operator's read-only evidence or a separately approved rehearsal/action.
- **G — general platform guidance:** not evidence about this app's deployed state or backups; conflicting/general assertions are not release gates.

### Source identity

`git rev-parse HEAD` and `git cat-file -t` confirmed the requested commit locally. `git diff --name-only afc2d16 -- backend frontend scripts deploy` showed no application differences. Comparison with the tested parent `5c1f891` showed no changes in backend/frontend/scripts/deploy or `.emergent/crons.yml`. The target commit itself changes platform metadata only.

Two generated workspace cron files already differed before assessment: `.emergent/cron/applied.hash` and `.emergent/cron/webhook-crons`. They were not edited or treated as production schedule evidence. No reset, checkout, Git write or publish was performed.

### Recorded verification

| Recorded suite | Passed | Failures/errors |
|---|---:|---:|
| Reviewed core | 52 | 0 |
| Isolated auth | 10 | 0 |
| Real source contracts | 6 | 0 |
| Related contracts | 36 | 0 |
| Six acceptance fixes | 22 | 0 |
| Four correctness follow-ups | 10 | 0 |
| Matcher parent-pool guard | 1 | 0 |
| Live-preview scope checks | 7 | 0 |
| **Total** | **144** | **0** |

Evidence: `test_reports/iteration_42.json`, the eight relevant `test_reports/pytest/*-final.xml` files and `memory/REVIEWED_FIXES_ACCEPTANCE.md`. XML timestamps are October 9, 2026, approximately 12:19–12:20 UTC. The isolated suites used disposable loopback databases; the seven API checks were preview checks, **not production tests**.

Previous frontend builds and desktop/mobile checks are documented in the acceptance report. They used the workspace, including its local lockfile. A clean source-only image build, production-scale load test, and production rollback rehearsal are **not evidenced**. No tests, builds or app imports that could write data/start boot tasks were rerun for this assessment.

### New non-mutating checks

- Parsed **165 Python source files** using `ast.parse`; no syntax errors. This does not execute imports, prove dependency installation or build a container.
- Read and parsed the committed five-entry cron manifest. All entries omit `enabled`, hence default to enabled under the platform cron contract; schedules use UTC by default.
- Verified committed presence of package manifest, requirements, Dockerfiles and ignore files, and absence of both frontend lockfiles. `.env` files are not committed, as expected.
- A generic static configuration scan returned PASS for stack/ports/env wiring. Its broad conclusion is **not adopted as an overall release verdict**: commit-level lockfile inspection and source-level startup/operational checks identified blockers it did not establish. Its production CORS/resource/readiness assertions were not independently verified.

## 3. Production observations: what is actually known

Origin: `https://saudi-pets-monitor.emergent.host`, sourced from existing project documentation. Its current binding to a specific deployment ID/image/commit was not accessible in this assessment.

| UTC capture | HTTP/TLS | Health response | Boot | In-process scheduler jobs |
|---|---|---|---|---:|
| 2026-10-09 14:57:09.389397Z | 200; normal TLS certificate verification enabled | healthy; MongoDB connected; Playwright available; uptime92.0s | running / indexes / zero reported errors | 0 |
| 2026-10-09 14:58:00.395642Z | 200; normal TLS certificate verification enabled | healthy; MongoDB connected; Playwright available; uptime142.7s | done / scheduler / zero reported errors | **15** |

Both returned `last_successful_crawl=2026-10-09T08:58:46.686967+00:00`.

**Interpretation limits:**
- These observations establish endpoint reachability and self-reported state at two instants, not a production SLO or fleet-wide readiness.
- The first response demonstrates that HTTP200/`healthy` can precede boot completion. Source `backend/server.py:266–329` determines health chiefly from a Mongo ping, not successful migrations/indexes/background jobs.
- `last_successful_crawl` is selected by presence of `tier_used`, not an explicit completed-success predicate (`server.py:294–312`). It does not prove comparable product coverage or crawl completeness.
- `playwright_available` is a filesystem/executable check, not proof of successful storefront crawling.
- The source's `register_crawl_job` immediately returns (`server.py:1739–1740`), and boot declares platform-only scheduling (`11792–11822`). The observed15 in-process jobs are a **verified discrepancy requiring deployment/scheduler reconciliation**. They do not identify which old build, worker or configuration is running.
- No restart or deployment was initiated here. The reported uptime does not establish why the process recently started.

### Production facts still unverified

Current deployment/image digest and Git SHA; replica/resource configuration; platform cron registrations/last delivery/result; absence of legacy schedulers; secrets presence and continuity; actual CORS/cookie behavior; MongoDB database binding, privileges and indexes; migration markers; current allowlist and data quality; pending jobs/checkpoints; backup ID/retention/restore procedure and rehearsal; object-storage integrity; customer-role access; Zid approval, proxy billing and notification delivery.

No preview `.env`, local database, source comment, generic platform claim or historical report is used as proof of these production facts.

## 4. Blocking gates versus optional work

| ID / class | Evidence and blocker | Closure evidence / owner |
|---|---|---|
| **B1 Release artifact — BLOCKER** | `git cat-file -e afc2d16:frontend/yarn.lock` fails; file exists only locally. `deploy/frontend.Dockerfile:10–11` requires COPY+frozen install. No clean image/artifact provenance recorded. | Release engineer: successor commit includes the reviewed lockfile, or an explicitly approved fully attested build-input manifest; clean image build and tests from those exact inputs; immutable frontend/backend image digests. Merely rebuilding the current workspace does not close this. |
| **B2 Startup/data boundary — BLOCKER until impact is approved or safely gated** | Boot invokes seeds/registry/index changes (`server.py:11719–11779`). Registry can reactivate Caty, delete reserved-domain/old-domain stores and retag own catalogue (`store_registry.py:150–212`). Background warm-up can backfill category/metrics (`server.py:11824–11857`). `SEED_DEMO_DATA=false` does not disable these. | Data/release owners: read-only preflight on a production-consistent clone, exact marker/index/update/delete impact list, and tested boot controls or explicit approval for the identified changes with backup/rollback coverage. No first-boot surprises. |
| **B3 Limited release isolation — BLOCKER for the requested limited scope until proven** | Only crawl cron checks persisted pause (`server.py:11631–11642`); own-sync also calls orders (`7431–7440`). Manifest enables all five jobs. No verified end-to-end price-only release recipe. | App/operations owners: explicit OFF states for unavailable integrations in server behavior and customer UI; verify API permissions, scheduled calls, manual/admin paths and egress. All out-of-scope cron entries disabled in the approved release configuration. Customer-role smoke must pass without hidden403/error loops. |
| **B4 Deployed identity and scheduling — BLOCKER** | Public health reports15 jobs versus source platform-only design; commit/digest not returned. Existing platform schedules persist until reconciliation; a code change alone is not evidence of their state. | Platform/release operator: export actual deployment ID/SHA/digests and every active schedule/worker; demonstrate one scheduling authority, no overlapping old/new writers, correct cron secret delivery without exposing values, and verified disablement during rollout. |
| **B5 Eligible production data — BLOCKER for commercial comparison claims** | Preview fixtures prove algorithms, not production provenance. Legacy rows are intentionally excluded. Current production eligible coverage, ambiguous parent roots, VAT/currency certainty and recoveries are unknown. | Data owner: approved store/SKU scope; dated source provenance; at least one actual eligible competitor per advertised comparison; zero known variant/cohort errors; exclusions and freshness visible; approved handling of unavailable rows. No synthetic/re-timestamped promotion/backfill to fill gaps. |
| **B6 Recoverability — BLOCKER** | Code-only rollback cannot undo startup writes, removed indexes, receipts, orders or migrations. Backup/restore capability and compatible fallback artifact not evidenced. | Operations/data owners: current backup/PITR identifier and retention, successful isolated restore and integrity comparison, compatible fallback image, rehearsed data-loss boundary and signed RPO/RTO. App price archives alone are not a complete DB backup. |
| **B7 Operational acceptance — BLOCKER until evidenced for the chosen mode** | Health200 is insufficient; background jobs can be queued then interrupted; load/resource limits and alert ownership unknown. | Operator: content-aware readiness and monitored limits, named on-call, staged-mode smoke/load results, and tested abort procedure. For all-jobs-OFF pilot, demonstrate no job execution; for refreshed mode, demonstrate one approved cycle completes and recovery is observable. |

### Optional/deferred, not blanket blockers to a correctly isolated price pilot

- Zid Partner OAuth approval and exact order analytics: **defer if OFF**. Do not present exact revenue/unit/share claims or run orders calls while disabled.
- Webshare subscription renewal: **not required for proven direct-source comparisons**. `PROXY_ENABLED` defaults false (`store_registry.py:29–41`). Production setting is unverified; startup proxy smoke separately checks configured usernames (`server.py:11983–12009`) and must be accounted for.
- Resend/email delivery, digests and outbound alert channels: **MOCKED/unavailable**, defer with clearly disabled controls and no delivery promises. `server.py:6337–6340` logs rather than sends email.
- App-specific historical price archive: can be OFF if full database backup/restore is separately proven. `archive.py` archives selected collections, not complete application recovery state.
- Broad `server.py` refactor, alerts-history UI, share watchlists, new-store expansion, sitemap acceleration and a richer recovery dashboard: optional after release-critical gates.
- Receipt-array compaction, optimized parent-index scans and a separate durable worker: optional for the small all-jobs-OFF observer pilot; revisit before high-volume or automatic refresh promises. Do not confuse optional architecture work with the mandatory measured capacity/recovery gates.

## 5. Limited price-comparison release: viability

### Permitted promise

“Compare the latest verified observed prices for the approved stores and exact product variants, in SAR with known price basis, with source timestamps and explicit unavailable/excluded states.” Not real-time checkout guarantees, market-wide coverage, exact sales/revenue/market share, or working email notifications.

| Capability | Limited release treatment |
|---|---|
| Own-product search, exact variant detail, selected-competitor prices/ranges | ON only for verified eligible data and tested customer-role paths |
| Historical prices/quantities | Clearly historical with original timestamps, never substituted for current stock |
| Unknown/removed/superseded parent | Unavailable/excluded, never promoted from historical values |
| My Products-only observer pilot | Potentially feasible after B1–B7; verify no out-of-scope controls/calls. Short-lived snapshot experience, not continuous monitoring. |
| Full Price Intel screen | Requires additional isolation verification: it eagerly requests12 mixed price/insight endpoints (`IntelPage.jsx:84–99`). `/api/insights` and digests share page permissions (`access_policy.py:7–8,20`). `/baseline/catalog-gaps` has no matching non-admin read rule, so customer-role behavior must be validated. |
| Zid exact orders/revenue, market share and sales-derived recommendations | OFF unless separately approved, connected and supported by complete transaction evidence. Source gates withhold incompatible exact shares (`market_share.py:762–765`); absence is not zero. |
| Proxy-dependent collection | OFF; optionally allow proven direct-source stores after explicit authorization and fresh-cycle acceptance |
| Alerts/email/digest/archive jobs | OFF until independently available, authorized and tested; do not describe log-only delivery as sent email |
| Bulk import, manual sync/matching, backfill, repair, store activation | Not available to pilot users; operator actions require separate authorization |

**A missing token or recurring401/402 is not “disabled.”** OFF must prevent calls and make product state clear. Existing page permissions help with audience restriction, but do not stop background work or separate all merged panels. Removing credentials to force failures is not a release-control strategy.

### Two stages, not a premature monitoring promise

1. **Observer pilot:** approved current observations only; all write schedules and operator mutations held; no new source refresh promised. Show as-of times. Code excludes offers at7 days (`price_cohort.py:60–80`; own price `server.py:8065–8082`; stock `stock_evidence.py:7–27`). End or renew the pilot **before the earliest included evidence expires**, not “seven days after launch.” A business freshness target of24 hours is recommended for launch samples, subject to owner approval.
2. **Renewable comparison service:** enable only an approved price-catalogue refresh path and approved direct sources. Current combined own-sync includes orders, so prove a genuine orders-OFF path first. Check checkpoint/ledger outcomes, current-store allowlist and monitoring. This stage needs separate authorization for production ingestion.

**Conclusion:** unavailable integrations need not block the concept. Missing build inputs, unsafe/unverified boot effects, incomplete isolation, production scheduler drift and absent data/restore evidence **do block release approval today**.

## 6. Data evidence required before go

Read-only operator evidence must identify the actual production database/cluster without exposing its URI/password and record:

- One intended own store; store allowlist, active/test/deprecated stores and expected registry boot effects.
- Existing index definitions and duplicate string `products.offer_id` / `product_snapshots.event_id` groups. `integrity_indexes.py:3–9` drops a unique SKU index and adds unique partial indexes; duplicates could stop boot after an index was already removed.
- Migration markers `legacy_admin_removed`, `legacy_name_matches_purged_v4`; `metric_rollup_meta` classifier version3 and schema version34. Counts of documents each pending operation would affect. Do not fabricate markers to skip work.
- Per-store eligible coverage: version2, non-synthetic, comparable, positive known-basis SAR price, confidence≥85, present/in-stock, timestamp within the current policy, exact product/pack/variant agreement. Missing or excluded values must not enter rank/minimum/Scanner opportunities.
- Superseded root remains in history but not current cohorts; Hair & Skin 2kg/4kg stay independent. The prior46/85SAR and15/2 quantities are **historical preview evidence**, not asserted current production values.
- Scope parity for all/A/B/none and independent membership filter, including detail and export. Production acceptance uses approved existing evidence; it must not refresh sources implicitly.
- Counts of `recovery_required`/captured/enriched checkpoints; queued/running/interrupted/deferred/failed jobs; leases and age; partial/unsealed daily rows; receipt-less legacy rows and unapplied sealed observations. Explain each exception in the selected slice.
- Archive availability if advertised; full DB backup manifest regardless of whether the archive feature is advertised.

The companion runbook includes safe query examples and explicit evidence/approval gates. No production queries were executed here beyond the two public health GETs.

## 7. Deployment and rollback plan

See **`memory/DEPLOYMENT_ROLLBACK_RUNBOOK_AFC2D16.md`** for the gate-by-gate future procedure, owners, abort conditions and rollback branches. It is a plan only; **not an instruction to deploy now**.

General platform guidance is preserved separately in `memory/PLATFORM_WORKFLOW_REFERENCE_AFC2D16.md`. Its statements about in-process scheduling conflict with this release's platform-cron contract; timings, backup policies, retained-version counts and zero-downtime claims are **unverified for this app**. The runbook does not rely on those claims.

### Final decision record

- Full release: **NO-GO**.
- Exact commit, limited customer price release today: **NO-GO**.
- Limited price release after verified isolation and B1–B7 closure: **conditionally viable**, without waiting for optional unavailable integrations.
- Changes made during assessment: documentation only.
- Next decision: approve a narrowly scoped remediation/rehearsal task, or supply the missing operator evidence. No deployment, data repair or credential change is implicitly authorized.