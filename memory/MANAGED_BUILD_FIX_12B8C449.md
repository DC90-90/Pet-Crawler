# Native managed frontend build failure — code-only repair

**Historical first-stage repair.** The subsequent native build exposed a separate blank-URL validation regression, now repaired and verified in `memory/SAME_ORIGIN_BUILD_FIX_DED49A10.md`. Earlier claims here that a missing frontend origin must fail are superseded for the managed path: blank/unset legitimately means same-origin, without relaxing nonempty-origin or release/readiness validation.

**2026-10-09 UTC. Build blocker reproduced and repaired in isolation; no redeployment performed. Production-readiness gates remain open.**

## Confirmed root cause

Failed build: `12b8c449-f2ea-469b-a59a-d9bb52009693`, Cloud Build step8 `frontend-build-push`.

```text
Error: ENOENT: no such file or directory, open '/workspace/backend/release_build.json'
    at Object.verify (/workspace/frontend/release-build/verify.cjs:33:34)
    at Object.<anonymous> (/workspace/frontend/craco.config.js:10:57)
```

The production CRACO config unconditionally required a paired export manifest. The native pipeline stages a Git-less working tree and runs `yarn install --prefer-offline` / `yarn build`; it does not run the application's isolated exporter. Both generated manifests are intentionally absent/ignored. The full tree, including backend/scripts, is present in the actual step8 context; the missing **generated file**, not a missing backend directory, is the actual failure. A narrower frontend-only context fails the old gate too.

Deployer investigation confirmed this independently from full build logs and the failed source snapshot: `deployer-agent-docs/RCA_6e7507bf-5cd2-42d4-a396-cd856806baa5.MD`. DEPLOY, HEALTH_CHECK, MANAGE_SECRETS and MONGODB_MIGRATE did not run. The deployer reports the prior healthy production run remains live. Main-agent work used preview/local evidence only; no new deployment or production action was initiated.

This failure is **not evidence of an Atlas MongoDB fault**: it occurs before deployment/database migration. No MongoDB configuration, URL/port, database name, credential or migration behavior was changed.

## Code-only changes

| File | Change |
|---|---|
| `frontend/craco.config.js` | Selects a build-validation path and installs a build-receipt plugin instead of unconditionally demanding absent export manifests. Development/preview startup is unchanged. |
| `frontend/release-build/prepare.cjs` | When both manifests are absent, permits frontend compilation with an explicit logged **UNVERIFIED** source state. Any existing/partial manifest pair, or strict requirement flag, still invokes strict validation and cannot silently downgrade. |
| `frontend/release-build/receipt.cjs` | Validates required frontend inputs/API origin and fingerprints frontend bytes/build context. It produces a frontend-only receipt with `git_commit=null`, `release_id=null`, `manifest_verified=false`, `production_readiness_verified=false` for raw managed workspaces. Arbitrary Git environment strings are not trusted as source proof. |
| `frontend/release-build/build-plugin.cjs` | Rejects input mutations during compilation and mismatch with Webpack's compiled API-origin definition; emits **only** `build/build-provenance.json`. |
| `scripts/build_release.py` | Sets `DALEEL_REQUIRE_VERIFIED_RELEASE_BUILD=true` inside isolated export builds so missing manifests cannot fall back to the managed path. |
| `backend/tests/test_managed_frontend_build.py` | Adds20 regression cases for native/strict selection, missing/partial/stale manifests, input/origin validation, deterministic/private-context receipt handling and plugin invariants. |

**Not changed:** `verify.cjs`'s strict verification rules, backend release identity, `/api/ready`, writer/maintenance guards, scheduler ownership, auth logic, dependency manifests, approved lockfile, `.dockerignore`, every file under `deploy/` (including Dockerfiles/compose/docs), cron configuration and `.env` files. No Docker-related edits were made. Protected-file before/after hashes and direct comparisons against starting HEAD `f3ee2c14ae05186632a3ee23fe0c2943f461fb3d` verify the relevant unchanged sources.

## Provenance and readiness are deliberately separate from compilation

### Raw managed build (the previously failing path)

- No Git/exporter/backend manifest required to compile the frontend.
- Actual API origin is required from environment; missing/invalid/credential-bearing origins still fail.
- Receipt state: **`unverified-managed-workspace`**, null commit and release ID, false manifest/production-readiness verification. It is **not** a backend/public release manifest and does not grant write permissions or fake a40-character SHA.
- A frontend receipt cannot establish backend-image provenance or production scheduler ownership.
- The backend remains `unstamped-workspace` without its own valid source attestation. **`/api/ready` remains503**; this was not weakened to make a health gate green. `/api/health` remains200 in the verified preview with Mongo connected.

### Prepared exact-source or explicit candidate export

- Both generated manifests must be present and validate. Partial, stale or corrupt manifests fail even if the raw managed path would otherwise be available.
- Exporter always requires strict validation. Explicit candidate opt-in still applies and cannot invent a saved SHA.
- The historical exact commit2faa51c has its own previously verified identity/readiness evidence, but that does **not** certify these newer modified sources or bind them to the failed native build.

## Tests and build results

| Check | Actual result |
|---|---|
| Original error reproduction | Before repair, isolated frontend-only/Git-less `yarn build` exited1 with the same missing backend manifest error. This red reproduction reused existing dependencies by symlink; it is not clean-install proof. |
| Native-like frontend-only build | **Fresh install** using `yarn install --prefer-offline`, then `yarn build`: both exit0. No Git, backend or generated manifests present. |
| Native-like full-tree build | `yarn build` exit0 with backend/scripts present but no Git/generated manifests. Reused only the prior isolated install's node_modules; not a second independent dependency installation. |
| Managed output | Both builds produced69 assets, including a truthful receipt; no backend/public release manifests fabricated. Preview API origin verified in emitted build configuration/assets. |
| Existing regression suites | **185 passed =156 isolated +22 packaging +7 preview API** |
| New regression suite | **20 passed** |
| **Combined current tests** | **205 passed, zero failures/errors/skips** |
| Strict candidate exporter | Clean frozen build and real exported-app ASGI startup/readiness check passed; expected503, manifest verified, null sourceSHA, capabilitiesOFF, zero DB collections created. |
| Protected inputs | Approved lock, `.dockerignore`, all `deploy/*` and cron manifest hashes unchanged. |
| Current source inventory | All325 declared inputs match the final strict candidate's source receipt; no post-build application/test edits. |
| Preview smoke | Existing login loads at1920×800; no UI/layout change was made. |

The first eight suite XMLs are from20:17:53–20:18:14UTC; packaging20:18:20, preview API20:18:43, new managed tests20:19:01. Only these205 distinct cases count, not inherited reports or asset assertions. The seven API cases test the existing preview, not production. Unit compiler/manifest fixtures are synthetic; the actual managed builds and strict-candidate ASGI check are not mocked.

There were **no unexpected post-fix failures or failed-run retries**. The original red failure is retained in `before-build.log`/`before-result.json`; successful after-runs occupy separate directories. Non-fatal dependency/deprecation warnings remain. No failed evidence was overwritten to obtain a green total.

### Fingerprints and scope

- Approved lock SHA256, unchanged before/after install/build: **`2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`**.
- Raw managed receipt SHA256 (both layouts): **`584546f02953610c1b8ad07adc4d56a4a1d786d85a90a2306ba11725dacab935`**. This is a **receipt file hash**, not an attested release ID.
- Test build API origin: **`https://price-intel-dev.preview.emergentagent.com`**, from existing preview configuration; not a verified production-origin build.
- Strict candidate identity: **`sha256:c306ec4f7b9c15e8b75997b923130d1a7a72fb378bd7572541e0b1b55a708d9a`**, sourceSHA null, `uncommitted-candidate`. It is not a saved release or the raw managed receipt's identity.
- Strict candidate interval: **20:19:10–20:20:12UTC**. Node20.20.2 / Yarn1.22.22 / Python3.11.17. Clean frontend install/compile verified; backend uses existing preview dependencies. Container check remains `unverified-no-container-engine`.
- Candidate export: `/tmp/daleel-packaging-ohbyjtq8`; frontend-only build: `/tmp/daleel-frontend-only-IYmsiy`; full-tree build: `/tmp/daleel-fulltree-gitless-YY7mEf`.

## Static deployment scan

The requested post-fix static scanner returned **PASS**, with no source compilation/configuration blocker identified. This is **code-level evidence only**, not a native pipeline rerun or production approval.

The scanner's generic summary also described APScheduler/background Playwright self-healing and called the application deployment-ready. Those broad statements are **not adopted as current operational evidence**: the tested observer boot leaves zero active scheduler jobs and does not run the retired mutation/probe sequence, while `/api/ready` still requires verified identity. No production configuration or workload was inspected by the static scan. Existing source/image, restoration, scheduling, freshness and operational gates remain open regardless of that label.

## Remaining limits and next action

The **confirmed missing-manifest compilation failure is fixed and independently verified in isolation**. A fresh actual native build has **not** been run. No claim is made that every later pipeline/runtime stage has succeeded.

Production approval remains **NO-GO**: actual managed source/image/artifact provenance and approved production build context, production-consistent startup/maintenance and restricted-user/egress acceptance, deployed identity and scheduler ownership, data quality/freshness, authorized backup restoration/real rollback and operational capacity/monitoring remain open. Current unverified-workspace `/api/ready`503 is an intentional outstanding attestation gate, not concealed as healthy release readiness.

Next: review/save the code-only repair, then obtain separately authorized native build/image/provenance verification. Do not initiate another production deployment or activate writers from this report. If the eventual platform readiness probe requires `/api/ready`, its attestation prerequisites must be satisfied—not bypassed.

External features are unchanged: email **MOCKED/unavailable**, Zid partner approval and Webshare402/coverage unresolved. Broad refactor/new-store rollout remain deferred. Potential safeguard: include this Git-less managed-build check in future release verification.

## Evidence

- Independent testing: `/app/test_reports/iteration_45.json`.
- All current evidence: `/app/test_reports/managed_build_fix/`.
- Original failure: `before-result.json`, `before-build.log`.
- Native builds: `frontend_only_gitless_attempt01/`, `fulltree_gitless_reuse_node_modules_attempt01/`.
- Original185 checks: `original185_attempt01/` (including copied eight runner XMLs).
- New20: `test_managed_frontend_build.{log,xml}`.
- Strict candidate: `strict-candidate-attempt-01/{result,source-receipt,build-evidence,artifact-ready}.json` and logs.
- API status: `ready_health_check.json`. Preservation: `protected-inputs-{before,after,compare}.json`.