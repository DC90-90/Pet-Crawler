# Same-origin managed-build regression — code-only repair

**2026-10-09 UTC. Confirmed source error fixed and tested in isolation. No automatic redeployment or production changes. Production-readiness gates remain open.**

## Root cause and scope

Deployer-confirmed run: `9ad0c83e-d740-44a0-bb93-2aaf5ba59448`; Cloud Build **`ded49a10-0b9b-4111-b241-8cd071f4a88b`**, step2 frontend-build.

```text
Error: REACT_APP_BACKEND_URL must be an explicit HTTP(S) origin
    at apiOrigin (.../release-build/receipt.cjs:16:51)
    at makeReceipt (.../release-build/receipt.cjs:52:17)
```

The native Cloudflare build intentionally replaces the preview backend URL with an empty build argument, producing `REACT_APP_BACKEND_URL=`. This is **valid same-origin configuration**, not a missing secret: the unchanged API client already resolves empty/unset values to `window.location.origin + '/api'` (or `/api` without a browser). The new build validator contradicted that existing runtime behavior. Its second compiled-value guard also needed the same normalization to avoid moving the failure to a later step.

Main reproduced the original error in both empty-dotenv and fully-unset isolated frontend builds. Deployer independently confirmed the native build mechanics in `deployer-agent-docs/RCA_9ad0c83e-d740-44a0-bb93-2aaf5ba59448.MD`. Neither diagnosis nor repair resumed the pipeline. No MongoDB/Atlas, DNS, tier, credential, Docker or manifest configuration change was needed.

## Changes

- **`frontend/release-build/receipt.cjs`:** undefined/empty/whitespace-only values return a null origin before URL parsing. Receipt schema2 explicitly records `api_mode=same-origin`, `api_origin=null`; nonempty supplied values still undergo strict HTTP(S)/origin checks. No hostname or Git identity is invented.
- **`frontend/release-build/build-plugin.cjs`:** absent DefinePlugin keys and compiled blank values normalize to the same null sentinel. Duplicate definitions, explicit-versus-same-origin mismatches and input mutation remain errors.
- **Tests:** corrected the prior erroneous empty-is-invalid assertion to reject the nonempty relative value `/api` instead. Added33 cases in `backend/tests/test_same_origin_build.py` for receipt modes, validation, compiled-value agreement and the actual unchanged API resolver executed in a VM fixture.
- Six one-off verification helper scripts were added under `/app/tests/`; they are test harnesses, not application/runtime code. They are outside the declared release input roots. Setup failures and their evidence limitations are recorded below.

**Unchanged and hash-checked:** `frontend/src/lib/api.js`, auth/runtime behavior, backend readiness/identity/writer guards, environment files, approved lockfile, dependency manifests, `.dockerignore`, every `deploy/*` file and cron configuration. No key was generated or rotated. No data refresh/backfill, writer shutdown or production action occurred.

## Build matrix and final tests

| Isolated native-like build | Result | Receipt |
|---|---|---|
| Frontend-only, empty temporary `.env` value, no inherited URL | **Pass**; fresh `yarn install --prefer-offline` then `yarn build` | schema2, same-origin, origin null |
| Frontend-only, environment key absent and no `.env*` files | **Pass**; reuses only the first isolated dependency tree | schema2, same-origin, origin null |
| Frontend-only, valid explicit preview origin | **Pass**; same isolated dependency reuse | schema2, explicit-origin, configured value |
| Full tree/backend/scripts present, no Git/manifests, empty origin | **Pass**; separate fresh install/build | schema2, same-origin, origin null |

All four emitted69 assets. Every managed receipt retains null commit/release ID and false manifest verification; no backend/public release manifest was fabricated. Original `.env` files were not copied to the build trees or edited; empty `.env` files were generated **only as isolated test fixtures**.

**Final current-run totals:238 passed, zero failures/errors/skips.** Breakdown:156 reviewed isolated +22 packaging +7 existing preview API +20 managed-build +33 new same-origin tests. All238 testcase identities and their current XML timestamps were independently reconciled. The seven API cases remain live-preview checks; VM/compiler fixtures are unit tests, not production routing/Cloudflare E2E.

The API resolver fixtures confirm browser same-origin `/api` for blank/unset, server-side relative `/api`, configured origin when it matches, and same-origin fallback for a mismatched configured hostname. The API client itself was not changed.

### Strict release path preserved

The existing strict candidate exporter passed after test environment correction, using its **explicit preview build context** and requiring valid paired manifests. Its contract was not broadened to accept a missing strict-export context; this fix addresses the native managed build path. Partial/stale/corrupt manifests still cannot fall back to an unverified build.

- Candidate identity: **`sha256:944c801c3f91be174ef6b5d40276cf063effadc14ab3b26e199940616e8553f0`**; sourceSHA null, uncommitted candidate—not a saved or production release.
- Real exported ASGI `/api/ready`: **503 expected**, manifest verified, boot done, all capabilities OFF, zero collections created.
- Current preview `/api/health`: **200**; unstamped preview `/api/ready`: **503**. No readiness guard was bypassed.
- All **326** declared current source inputs match the final candidate export. The main agent re-ran artifact verification successfully after testing.

## Failures and reruns — retained versus unavailable evidence

1. **Original red reproductions:** empty and unset builds each exited1 with the original URL-validation error. Complete before logs/results retained; linked existing dependencies were used only for these red reproductions, not clean-install proof.
2. **Matrix attempt01:** saved install log completed; saved build log says `Compiled successfully` but has no complete exit/result record. It is **incomplete evidence**, not counted as a successful full matrix and not labeled a new source failure. Attempt02 contains the four complete passing cases.
3. **Initial preview API setup:** testing agent reports a401 when `DALEEL_TEST_PASSWORD` was unset. Existing saved credentials were supplied to the child process and the seven tests passed. The wrapper overwrote its shared log/XML filenames, so the **original raw failed trace/count is unavailable**. This limitation is recorded rather than claiming complete before/after preservation. No application auth change, credential rotation or skipped test was used.
4. **Strict candidate attempt01:** frontend build/compilation completed, but actual app import failed because its wrapper passed only Mongo/origin and omitted existing `ENCRYPTION_KEY` and other backend environment values. Original failed result and traceback retained. **No new encryption key was generated.**
5. **Strict candidate attempt02:** wrapper loaded the existing backend environment privately; the same source passed. No source repair/restamping workaround or relaxed readiness rule was needed for this setup correction.

Final successes do not erase those setup failures or evidence gaps. Non-fatal peer-dependency/deprecation warnings remain. Tests were not skipped to produce the green total; no unresolved application assertion/build error remains in the tested matrix.

## Artifact fingerprints

Approved lock SHA256 remained **`2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`** in every successful build.

| Artifact | SHA256 |
|---|---|
| Empty/full-tree managed receipt | `4d44ce2169d0156e01b20bfe7c0f9d7af7814c8f7dca4661a751d6931c9ec4ad` |
| Unset managed receipt | `192bee09c6a37241dad212503e00ae54132a29fef58cb7ada237439618d883b0` |
| Explicit-origin managed receipt | `c04edc426fc25f6d312feb0c395eeb7ba79ae1a546d31db8c4c4cb5cb25dcb96` |
| Same-origin `static/js/main.802d74b4.js` (empty/unset/full-tree) | `2a0081066550981b6c92e86eed2db71fb124ce199c860635427361c7196a2b92` |
| Explicit-origin `static/js/main.337532de.js` | `28f213cbfbf1378adde40735f7fab4b5fcefd223e23e7d7143f0b70f44497aa4` |

All per-case asset hashes are recorded in the matrix result. Cases A/B/C reused the same frontend directory, so C overwrote the earlier A/B asset trees; their emitted hashes/logs were captured during testing, not reconstructed afterward. Main independently rehashed the still-retained C and D trees. Receipt differences between empty/unset preserve input differences even though their compiled main JavaScript is identical.

## Static scan and remaining gates

Post-fix static deployment scan returned **PASS**, with no additional source blocker identified. This concerns code-level compatibility only: the scanner's generic deployment-ready/CORS-update notes are not evidence of an actual native pipeline, production configuration, image or deployed runtime. No production gate is closed by that label.

**Production remains NO-GO** under the existing release-approval gates: actual managed source/image provenance and runtime consumption; production-consistent startup/maintenance and restricted-user/egress acceptance; deployed identity and scheduler ownership; data quality/freshness; authorized backup restoration/rollback; operational capacity and recovery signoff. Unverified-build `/api/ready`503 remains intentional. No actual native build retry/deployment was initiated by this repair.

**Next concrete action:** save/review the code-only fix, then obtain separately authorized native build verification using its intentional same-origin configuration, while retaining the other production gates. Do not inject a hardcoded production URL or weaken readiness to make a check green. Future safeguard: include empty/unset/explicit origin configurations in every build-compatibility check.

Email remains **MOCKED/unavailable**; Zid approval and Webshare coverage issues are unchanged. New-store rollout and broad refactoring remain deferred.

## Evidence

- Independent testing report: `/app/test_reports/iteration_46.json`.
- Main evidence root: `/app/test_reports/same_origin_build_fix/`.
- Before failures: `before-results.json`, `empty-before-build.log`, `unset-before-build.log`.
- Build matrix: `matrix-attempt-01/` (incomplete), `matrix-attempt-02/result.json` and per-case logs.
- Final238 XMLs: `baseline205-attempt-01/xml-copies/` (directory name predates the new33 tests).
- Strict exports: `strict-candidate-attempt-01/`, `strict-candidate-attempt-02/`.
- API status/preservation: `ready_health_check_attempt01.json`, `protected-inputs-compare-attempt01.json`.
- Reconciled counts, hashes and failure-evidence limits: `main-evidence-validation.json`.