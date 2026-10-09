# Daleel gated deployment and rollback runbook

**Current prerequisite update (2026-10-09):** actual remote commit`2faa51c3ac21ef1d7fae97558bf666a7674bbd7e` has verified lock inclusion, matching generated manifests,185 passing checks and isolated committed-artifact `/api/ready`200. See `memory/EXACT_SOURCE_VERIFICATION_2FAA51C.md`. This closes only those saved-source/preview-context subgates: image/managed-pipeline evidence, production-consistent startup/egress, deployed identity, scheduler ownership, data freshness, authorized backup restoration/rollback and ops gates remain open. **Production NO-GO.** Next action is isolated exact-SHA image verification on a Docker/Podman-capable runner, not executing this production runbook. Prior pending-lock statements below are historical.

**Latest packaging prerequisite (2026-10-09):** see `deploy/RELEASE_PACKAGING.md` and `memory/PACKAGING_CORRECTIONS_DC22D72.md`. Candidate packaging and185 checks pass, but actual reference remote lacks the lock; corrected remote save/exact-source build/committed readiness remain pending. Repository container consumers require generated verified exports. Managed-pipeline/image consumption, backup restoration, deployed identity, actual scheduler ownership and data quality remain unverified. **No step here is authorized for production execution.**

**Baseline assessed:** `afc2d162a144fd3f4b942b694b072637ae6c645c`  
**Status:** Future production procedure only. **Current NO-GO. No production step below was executed.** Isolated protocol rehearsals are recorded separately and do not constitute production restoration or image rollback.  
**Companion assessment:** `PRODUCTION_READINESS_AFC2D16.md`.

This runbook deliberately favors an approved maintenance window over an unproven zero-downtime/mixed-writer rollout. Do not assume traffic splitting, image pinning, database restore or scheduler suspension is available in the current platform UI; confirm the supported mechanism before the window.

## Remediation update — 2026-10-09; documentation only

- Reconciled saved checks: **156 isolated +7 preview API =163 passed**, zero final failures/errors/skips. Previous attempts had one cron-fixture closed-loop failure, then three incorrect safety-fixture targets; full final rerun passed. See `test_reports/release_safety_reconciliation.json` and the latest acceptance section. No new application run or production operation was performed to finalize these docs.
- Source now includes observer/default-deny business writes, drain-to-freeze control, explicit maintenance operations, release/epoch job fencing, identity/readiness routes, unavailable-feature UI boundaries, and **all five source cron entries OFF**. Code-level controls do not prove deployed-state ownership or stop old unfenced code.
- Clean Node20 frontend build/unchanged lock is saved, **not** an image build or final saved-commit attestation. Backend/control/stamping files changed after that build; final exact-source artifact verification remains required.
- **No authorized production backup was supplied; no restore or production-consistent clone rehearsal occurred.** A synthetic A→B→A protocol test is not an image rollback. Deployed identity, actual scheduler authority, current eligible-offer freshness, restricted-customer acceptance and B1–B7 closure remain required.
- Requested next action is only **Save to GitHub → `DC90-90/Pet-Crawler` → `conflict_130726_1244`**. Verify inclusion of new files/lock/evidence and record the remote SHA afterward. No direct Git push, production writer shutdown or deployment is authorized.

### Control protocol for a separately authorized future rehearsal

1. Read `/api/release` and authenticated `/api/admin/release-control`; compare manifest/commit with the saved build and actual running images. A declared `scheduler_authority=platform-cron` is not an inventory of real schedules.
2. Under separate authorization, freeze uses `/api/admin/release-control` with `action=freeze`, the observed `expected_revision` and an approval reference. `freezing` permits already admitted work to finish; wait for `frozen` and zero tracked writers. Do not expire/erase a crashed permit to force a green state. Confirm external and old processes separately.
3. Observer mode blocks business writes but permits scoped auth-security writes. Frozen mode and maintenance still allow the authorized control plane. Do not call this a Mongo-wide read-only account or a complete production writer stop.
4. Named maintenance requires frozen/drained state, matching release ownership (`claim-maintenance`), explicit approval and a fresh plan hash from `/api/admin/maintenance/plan/{operation}` before `/api/admin/maintenance/apply`. The current plan summarizes stores/counts/indexes; obtain an additional exact impact assessment for production. No migration/backfill is implicitly approved.
5. Observer/active ownership transitions require a frozen/drained state, expected release and revision; capability activation also requires a verified committed build and prepared integrity indexes. Epoch changes invalidate old queued work even on a compatible-code rollback. Keep unavailable capabilities OFF; email/digests cannot be enabled.
6. `/api/ready` deliberately rejects uncommitted candidate identity. A future200 is not proof of backup restoration, current data coverage, deployed image provenance or exclusive scheduler authority; release-owner B1–B7 signoff is still mandatory.

These descriptions are **not commands to execute now**. None of these control-plane mutations were called during this documentation continuation.

## A. Named owners and change record — mandatory before scheduling

Assign release owner, app engineer, platform operator, data owner and incident lead. Record:

- Approved release SHA (**a successor if fixes are needed**), source repository/branch, dependency-lock hash and build-input manifest.
- Candidate frontend/backend image digests, build results, test report IDs and configuration references (names/versions only, **never secret values**).
- Current production deployment ID/SHA/image digests and the intended compatible fallback deployment. An older Git commit alone is not a usable rollback artifact.
- Actual production database/cluster identifier and binding; all scheduler authorities and active workers.
- Approved pilot stores/SKUs, audience, freshness requirements, disabled capabilities and end/renewal date.
- Backup/PITR ID and timestamp, restore owner/method, restore rehearsal results, authorized data-loss boundary and communications contacts.
- Proposed targets to validate: **RPO0 for immutable evidence during the frozen comparison-only rollout; RTO≤30 minutes**. These are planning targets, not achieved guarantees. Agree alternatives before release if rehearsal cannot meet them.

**Stop:** any missing owner, unverified artifact, unsupported restore procedure, or unaccepted RPO/RTO means no window begins.

## B. Close release gates on a clone/staging environment

1. Resolve B1: include the reviewed `frontend/yarn.lock` in the release inputs and verify it is actually in the saved release commit. Do not rely on the local untracked copy or opportunistic dependency re-resolution.
2. Build from a clean source tree with approved frozen dependencies and production-like configuration **without production credentials**. Record immutable image digests. Do not treat previous workspace `yarn build` as this proof.
3. Run the current selected **163 checks (156 isolated +7 preview API)** against the exact saved candidate in isolated/preview scope, plus any new regressions, clean container/import checks and desktop/mobile restricted-customer flows. Preserve separate failed-run and final artifacts; do not relabel the historical144-check independent report as163.
4. Implement or prove the limited-mode boundaries from the assessment: disable unsupported UI controls and API/job paths; prevent orders calls; preserve explicit unavailable data states; prove comparisons do not need mocked integrations.
5. On a production-consistent isolated clone, boot the candidate and measure every seed/index/registry/classification/rollup side effect. Approve each required change or gate it OFF. Preserve historical observations and sealed rows. Do not insert migration markers just to make boot appear ready.
6. Exercise read-only comparisons with the proposed restricted user permissions. In particular verify the merged Price Intel background requests, not only a super-admin session. No hidden403 storms or unavailable integrations presented as active.
7. Rehearse known-empty matcher protection, parent-first/root-first identity, checkpoint failures and ledger replays with synthetic fixtures **only in the isolated clone/test DB**.
8. Rehearse the actual image rollback mechanism against the post-candidate clone schema. Verify shared SKU variants, offer/event indexes, listing identities, v2 ledger receipts and sealed-history handling are compatible with fallback code.
9. Verify no code-only rollback pretends to restore Mongo data, secrets, indexes, cron application state or external storage.

**Stop:** any failed test, unexpected boot mutation, rollback incompatibility or dependency/artifact drift.

## C. Read-only production preflight packet

Obtain the following using an operator-approved **read-only** connection. Never reuse preview `MONGO_URL` as a production address, print a connection URI, or run the full regression suite against production.

Illustrative `mongosh` reads below run only after an operator confirms the database binding; **they were not executed by this assessment**:

```javascript
db.getName();
db.products.getIndexes();
db.product_snapshots.getIndexes();
db.daily_ledger.getIndexes();
db.migrations.find(
  {_id: {$in: ["legacy_admin_removed", "legacy_name_matches_purged_v4"]}},
  {_id: 1, applied_at: 1, deleted: 1}
);
db.metric_rollup_meta.find(
  {_id: {$in: ["schema", "classifier"]}}, {_id: 1, version: 1}
);
db.products.aggregate([
  {$match: {offer_id: {$type: "string"}}},
  {$group: {_id: "$offer_id", count: {$sum: 1}}},
  {$match: {count: {$gt: 1}}}, {$limit: 20}
]);
db.product_snapshots.aggregate([
  {$match: {event_id: {$type: "string"}}},
  {$group: {_id: "$event_id", count: {$sum: 1}}},
  {$match: {count: {$gt: 1}}}, {$limit: 20}
]);
db.crawl_checkpoints.aggregate([
  {$group: {_id: "$state", count: {$sum: 1}}}
]);
db.job_runs.find(
  {status: {$in: ["queued", "running", "interrupted", "deferred", "failed"]}},
  {_id: 0, id: 1, kind: 1, status: 1, created_at: 1, started_at: 1, finished_at: 1}
).sort({created_at: -1}).limit(50);
db.daily_ledger_store.countDocuments({status: "partial"});
```

Large aggregations should be reviewed for production cost and run off-peak/on an approved consistent clone where appropriate. A truncated sample is not proof of whole-catalogue cleanliness. These reads are diagnostics, **not instructions to delete duplicates or recover/backfill rows**.

Additionally collect:
- Scope-specific eligible-offer evidence and comparison responses with observation timestamps and exclusions.
- Exact deployed build and per-replica health evidence. `/api/health` must have Mongo connected, `boot.status=done`, `boot.errors=[]`; also verify indexes and background work separately. The historically observed build did not report a Git SHA. Candidate `/api/release` and `/api/ready` add manifest/commit information; corroborate this with actual deployment/image identifiers rather than assuming those routes are live.
- Explain the observed15 in-process jobs and prove which scheduler will be authoritative after rollout. Export platform schedule state as well; `scheduler_active_jobs=0` alone cannot prove platform crons are disabled or working.
- Verify required configuration by reference/presence: Mongo binding, `DB_NAME`, stable `JWT_SECRET` and `ENCRYPTION_KEY`, intended admin identity, exact allowed HTTPS origins, frontend API origin and cron secret when crons are enabled. **Do not rotate or replace existing values as part of this rollout.**
- Confirm backup restore includes catalogue, stores/settings, observations/quarantine/parent identities, matches/blacklists, all ledger/receipt state, orders/evidence, migrations/index definitions, auth users/session revocation state and job/checkpoint state. Keep encryption-key references available to both current and fallback images.

**Stop:** unresolved duplicate index keys, unexplained schema/marker state, incorrect own-store identity, inadequate eligible coverage, unknown backup, or missing deployment identity.

## D. Freeze all writers before backup and cutover

Future actions in this section require explicit deployment/operations authorization:

1. Announce the maintenance/read-only window; block customer/operator mutation routes at an approved control boundary, while retaining safe health/maintenance visibility.
2. Suspend **every** scheduler and manual ingestion path: legacy in-process jobs, platform `crawl-stores`, `own-catalog`, `seal-ledger`, `archive-prices`, `weekly-digest`, external ingest/imports, explicit matching, admin repair/backfill and ongoing tasks.
3. Do **not** rely on `/api/scheduler/toggle-pause`: it is a toggle, is not a global writer stop and the persisted pause only gates the crawl cron. Do not call it blindly in an automated runbook.
4. All five candidate manifest entries now have `enabled: false`; verify these reach the saved release and confirm how **already active production schedules** will be suspended before cutover. Old rendered configuration may persist until reconciliation. The new application fence covers only participating code; it does not stop the previously observed legacy scheduler. If a safe suspension mechanism is unavailable, stop and obtain platform-operator assistance.
5. Let in-flight work finish or document interruption and captured checkpoint state. Terminate old writer processes using the approved platform operation, not an assumed UI undeploy/reset. Do not erase active leases or mark checkpoints complete by hand.
6. Confirm no old/new writers can overlap. Ledger-day leases last5 minutes and generic job leases3 hours; expiration is not proof an old process stopped. Known unapplied sealed/legacy recoveries stay explicitly unresolved.
7. Record stable counts/checksums and latest timestamps for immutable evidence, matches, ledger receipts/seals and checkpoints. Take the approved consistent backup/PITR checkpoint and verify accessibility and manifest.

**Stop:** writes continue, backup is incomplete, a lease owner is still running, or the available platform operation would copy preview data into production/change the DB binding unexpectedly.

## E. Candidate activation — after all approvals, not now

1. Release operator verifies the exact approved code/dependency snapshot in the platform's publishing workflow. General platform guidance identifies **Manage Publishes / Republish**; confirm current controls and selected source before acting. No assumption of arbitrary SHA/image pinning.
2. Retain the compatible previous deployment ID/digest and backup record outside the candidate pod. Confirm the platform's actual rollback retention before starting.
3. Review planned pipeline data/secret steps. **Do not import/reseed preview data into the existing production DB.** Stop if an unapproved migration, secret replacement or DB rebinding is proposed.
4. Activate only the approved artifact/configuration with writers still disabled. Use an operator-only validation window; use traffic canaries only if the platform's support is confirmed. Otherwise use the approved maintenance cutover, not an invented percentage rollout.
5. Verify runtime image/commit identity, environment references and all replicas. Do not accept frontend200 or `/api/health` HTTP200 alone. Observe at least five consecutive successful content-aware checks over several minutes, plus explicit index/boot/background-state confirmation.
6. Authenticate only with an existing approved account as part of the separately authorized release smoke. Verify the real restricted customer role, not only super-admin. Check login/session/CORS, My Products, intended price-comparison path, detail and export.
7. On approved existing data, compare all/A/B/none scopes, membership independence, separate2kg/4kg identities, unknown/historical stock, parent exclusion and selected-offer minimum. Do not trigger a live refresh merely to make a smoke test populate.
8. Verify OFF integrations are visibly unavailable and produce **no** orders/email/proxy/digest/archive calls or job executions. Verify zero demo seed use and no unexpected startup data modifications against the pre-cutover evidence packet.
9. Review logs and metrics before exposing the pilot. Proposed acceptance budgets, to sign in advance: zero incorrect reference comparisons, zero unexplained5xx on ten requests per critical read path; warmed P95≤5s under the agreed pilot load; no memory/connection exhaustion. These are targets, not previously measured production guarantees.
10. Release owner signs the observer-pilot go decision and publishes the scope/as-of limitation. Keep jobs OFF. Set pilot expiry before the earliest included offer crosses the approved freshness limit.

## F. Optional later refresh activation — separate approval

Do not enable all five jobs merely because HTTP health is green.

| Job | Committed UTC cadence | Initial observer pilot | Condition for later enablement |
|---|---|---|---|
| crawl-stores | daily01:00 (04:00 KSA) | OFF | Approved direct-source allowlist; complete/partial behavior and checkpoint recovery measured |
| own-catalog | 00:15/06:15/12:15/18:15 UTC | OFF | Verified price-only path; unavailable orders integration actually skipped, not repeatedly failing |
| seal-ledger | daily21:30 (00:30 next KSA day) | OFF | Approved ledger scope, seal/recovery policy and one scheduler authority |
| archive-prices | daily03:00 (06:00 KSA) | OFF | Storage configured and retrieval verified; not a substitute for full DB backup |
| weekly-digest | Sunday05:00 (08:00 KSA) | OFF | Feature and delivery behavior intentionally supported and clearly described |

Verify cron authentication and stable run IDs on staging; require immediate acknowledgments and separately verify job **completion**, not only accepted200. Current implementation records jobs durably but executes via process-local background tasks: a crash after queueing can leave a queued run, and a duplicate delivery does not automatically re-enqueue it. Have an approved recovery procedure/owner before promising unattended refresh reliability. Do not manually fabricate a new completed status.

## G. Monitoring and abort criteria

Monitor deployment identity, per-replica boot/errors, Mongo connectivity, read latency/5xx, replica restarts and resources, eligible-price freshness/coverage, variant-root exclusions, scope parity and authentication403/401 rates.

When jobs are separately enabled, also monitor last terminal result per schedule, queued/running age, failed/degraded/interrupted jobs, `recovery_required`, leases and unresolved sealed/legacy evidence. Suggested alert: queued work unclaimed for10 minutes, or no successful authorized cycle within one scheduled interval plus agreed grace. A successful HTTP dispatch is not a completed crawl.

**Immediate abort / keep writers stopped** for:
- Wrong source/image, preview DB binding, unexpected secret change or unapproved boot mutation.
- Ambiguous root price used, variants merged, unrelated matches deleted by an empty pool, false current stock or a wrong selected-competitor minimum.
- Receipt/first-seen counts change on a duplicate, an older observation replaces a newer close, sealed evidence changes, or an incomplete checkpoint reports success.
- Disabled integration calls still occur, mixed scheduling authorities remain, or old/new writers overlap.
- Sustained production health/auth/read failures, resource exhaustion, or breached approved latency/error budgets.

An unavailable value caused by deliberate freshness/identity exclusion is not by itself a reason to restore unsafe legacy calculations; assess loss of advertised coverage against the signed pilot scope.

## H. Rollback decision tree

### H1 — code/config issue; data remains valid

1. Incident lead closes access/mutations and stops all writers first. Preserve incident logs, deployment IDs and evidence hashes. Do not rerun sync/matching to hide the failure.
2. Confirm the saved fallback artifact can read the **current** offer/parent/receipt/index schema. Do not roll back to code that ignores parent exclusions or v2 ledger receipts while allowing writers to run.
3. Use the **supported deployment rollback workflow**, after confirming exact previous deployment ID/image in the current UI (general guidance: Manage Publishes → Overview → rollback action). No Git reset/revert and no blind old-workspace publish.
4. Keep the current production DB and stable secret references. Code rollback is **not** data/index/secret restoration. Verify actual scheduling configuration separately; do not assume its applied state tracks the UI rollback.
5. Repeat content-aware health, auth, parent/variant, scope and evidence-integrity checks. Reopen only the approved read-only mode after owner signoff; keep ingestion OFF until compatible recovery is proven.
6. If no safe fallback image exists or rollback is unavailable, remain in maintenance and prepare a separately approved forward fix. **Do not improvise an unsafe downgrade.**

### H2 — unintended data/index/history change suspected

1. Freeze writers, preserve the current production state as incident evidence and involve the data owner. Code rollback alone cannot undo database changes.
2. Restore the approved backup/PITR point into an **isolated recovery database first**, never directly over live data as a first action. Verify counts/checksums, indexes, parent identities, event/receipt IDs, sealed timestamps, migrations and offer scope.
3. Determine the exact post-backup loss interval and preserve later immutable observations/checkpoints. Any merge, replay, quarantine correction or backfill requires a separate scoped reconciliation approval; do not re-date evidence or blindly replay sealed rows.
4. Include authentication/revocation state in the recovery decision: an old DB restore must not silently resurrect revoked sessions. Preserve current secret references; do not rotate credentials as a rollback shortcut.
5. Obtain explicit incident-owner authorization for any production restore or DB rebind, with the proven restore procedure and communicated RPO impact. Keep writes disabled through the switch and revalidation.
6. Reopen only after the restored/reconciled DB and a compatible image pass the same data and comparison gates. Re-enable jobs one at a time only under the separate refresh-activation approval.

## I. Completion record

Record actual release or rollback deployment ID/SHA/digests, time, operator, config references, DB binding, backup/restore ID, scheduler state, validation evidence, remaining exclusions and customer communication. Never record “rollback successful” merely because the old page loads.

**Current assessment outcome:** No deployment/rollback was initiated. No release SHA or production state has been changed. This plan becomes executable only after B1–B7 close and the user explicitly authorizes the operational change.