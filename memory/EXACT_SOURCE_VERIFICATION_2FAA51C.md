# Exact-source release verification — 2faa51c

**2026-10-09 UTC · Verification only · Production remains NO-GO.**

## Decision

The actual remote lockfile inclusion and clean saved-source build/readiness blockers are now **verified for this commit and preview build context**. This does **not** close image, managed-pipeline or production-readiness gates. No application/packaging/test/configuration source was changed, no local checkout was replaced, no uncommitted files were overlaid, and no production action or credential rotation occurred.

| Requested result | Actual evidence |
|---|---|
| Repository / branch | `DC90-90/Pet-Crawler` / `conflict_130726_1244` |
| Exact verified remote source SHA | **`2faa51c3ac21ef1d7fae97558bf666a7674bbd7e`** |
| Remote lockfile | Actual Git tree and downloaded raw bytes verified: **518152 bytes**, blob `603e2c6d1a8ee82be74311c3672d832fc8f389a3` |
| Lock SHA256 | **`2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`** before/after build; never regenerated |
| Existing remote verifier | **`passed-saved-source-build`**, `candidate=false`, `remote_verified=true` |
| Generated release identity | **`sha256:7c6d8146f2c7c9000d8e5df11ba7172d8caec105e81642e683aaeb8229789adc`** |
| Source state | `committed-export`; manifest source SHA equals the requested commit |
| Build context | Node **20.20.2**, Yarn **1.22.22**, Python **3.11.17** |
| Frontend | Clean dependency install with frozen lock; compiled successfully; all **43** emitted asset hashes verified |
| Backend | Compilation plus real exported-app import/startup/readiness passed using existing preview Python dependencies; **not a clean dependency/image build** |
| Manifest agreement | Backend, frontend public, and compiled frontend manifests are identical; their SHA256 is below |
| Compiled API origin | **`https://price-intel-dev.preview.emergentagent.com`**, found in emitted `static/js/main.272217b9.js`; from existing preview environment, **not a production-origin proof** |
| Isolated artifact `/api/ready` | **HTTP 200**, expected200, verified identity, boot `done`, all capabilities OFF, **zero collections created** |
| Readiness transport | Real exported FastAPI app over ASGI with a disposable loopback Mongo database; no mocked identity/boot and no extra listening server |
| Build attempt interval | **18:17:50.897015–18:19:08.676827 UTC** |

The clean export is `/tmp/daleel-packaging-gduk3tv6`. The verifier checked saved Git blobs before invoking **that export's own** build driver. All **320 declared source inputs** still matched the source receipt after compilation and tests. No local lockfile or newer source was injected into the export.

## Actual test totals and scope

| Current-run suite | Passed | Failed / errors / skipped |
|---|---:|---:|
| Reviewed core | 52 | 0 / 0 / 0 |
| Isolated auth | 10 | 0 / 0 / 0 |
| Real-source fixtures | 6 | 0 / 0 / 0 |
| Related contracts | 36 | 0 / 0 / 0 |
| Six acceptance regressions | 22 | 0 / 0 / 0 |
| Four correctness regressions | 10 | 0 / 0 / 0 |
| Matcher parent pool | 1 | 0 / 0 / 0 |
| Release safety | 19 | 0 / 0 / 0 |
| **Original isolated subtotal** | **156** | **0 / 0 / 0** |
| Packaging regressions | **22** | **0 / 0 / 0** |
| Existing preview API scope | **7** | **0 / 0 / 0** |
| **Requested total** | **185** | **0 / 0 / 0** |

All test definitions and isolated runs came from the saved export. The **seven API cases still target the existing preview endpoint**, as designed; they are **not exported-image E2E tests**. Preview backend source hashes also match the exported backend sources, but this does not substitute for container/runtime or customer-role acceptance. The exported-artifact `/api/ready`200 proof is separate from those seven checks. Unit fixtures remain synthetic where originally designed; they are not external-integration delivery evidence.

Current reviewed XML start times are **18:19:25–18:19:44 UTC**; packaging starts **18:19:52**, preview API **18:19:59**. There are **185 distinct testcase identities**. An old carried `reviewed-tests-attempt-01/preview-scope-final.xml` has timestamp **15:53:46** and is explicitly **excluded** from the current count. Do not glob every XML in the exported archive and count inherited results again.

### Failures, reruns and warnings

- **No build or test failure occurred in this exact-commit run.** One clean source build attempt; each requested suite passed its first execution; **zero failed-test/build reruns**.
- Existing artifact verification was repeated after tests and by the main agent; both checks passed without rebuilding or restamping. These checks are not additional pytest cases.
- Attempt01 logs/XMLs are preserved under a new evidence directory; earlier candidate builds and missing-lock failures were neither overwritten nor relabeled as this commit's results.
- Non-fatal peer-dependency/workspace and FastAPI/multipart/test-client deprecation warnings remain. This is not full legacy-suite, load, security, browser-role or production acceptance.
- **Unavailable checks remain unavailable**, not counted as passed: no Docker/Podman, no image build/digest/runtime proof, no clean backend dependency install, and no actual managed-pipeline artifact-consumption proof.

## Commands and configuration boundary

Existing preview configuration was loaded privately into child environment variables, never copied as `.env` files into the export. `DALEEL_TEST_MONGO_URL` was explicitly loopback. Existing preview credentials were used for the seven API cases; isolated runner-created test identities were disposable, not credential rotations. No secrets are included in this report.

```text
python /app/scripts/verify_clean_release.py \
  --commit 2faa51c3ac21ef1d7fae97558bf666a7674bbd7e \
  --repository DC90-90/Pet-Crawler --branch conflict_130726_1244 \
  --containers --output /app/test_reports/exact_source_2faa51c/build-attempt-01

# Executed from /tmp/daleel-packaging-gduk3tv6, using exported scripts/tests:
python scripts/run_reviewed_tests.py
python -m pytest -q backend/tests/test_release_packaging.py --junitxml=.../packaging-attempt-01.xml
python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=.../preview-scope-attempt-01.xml
python scripts/verify_release_artifact.py --require-committed
```

The exported build driver executed `yarn install --frozen-lockfile --non-interactive --production=false --cache-folder <evidence>/yarn-cache`, `yarn build`, `python -m compileall -q backend scripts`, compiled-artifact verification and `scripts/check_artifact_ready.py`. Exact argv/build context are recorded in `build-attempt-01/build-evidence.json`.

## Artifact fingerprints

All values below are SHA256, calculated from actual artifact bytes. The generated release identity is distinct from the byte hash of the JSON manifest.

| Artifact | SHA256 |
|---|---|
| Backend / public frontend / compiled frontend manifest (each) | `c9bcd194ececfcc72ae331b6c784fc5a3ac47eb040f3fccc8dfa62754f8e8bee` |
| `static/js/main.272217b9.js` | `fe07a3102b513f9171da7f46e2e2ecebc45118bb76dfcb0a6fb5f97e1234052e` |
| Compiled `asset-manifest.json` | `b0c47ebea32d6c37cff902eeb0154373888d7811b2d2d6685bbe3c5b8662e956` |
| Build evidence / exported build receipt | `91af9564ed4db5873cc2909f9b597aa55a81df689597e46663f52ce21e66f8a4` |
| `source-receipt.json` | `97522e4f2429fdc89c17930e9df5a09fb7b281f20b202ef0e3dc009be4fcba20` |
| `artifact-ready.json` | `5b69f3dfe59012f108f2ca4f2e9216b45f4acc76d8f6c9d51ab520f052dbcb39` |
| Verifier `result.json` | `580b55a861a85bd615f06fc36db339eccbf6331b52bd95b187d551e4ce83d583` |

Copies of all three generated manifests, the asset manifest and build receipt are retained under **`test_reports/exact_source_2faa51c/retained-artifacts/`**. All43 output hashes are in `build-attempt-01/build-evidence.json`. Current-run XML hashes and the main agent's independent evidence reconciliation are in **`main-evidence-validation.json`**. No generated manifest was copied back into application source.

## Workspace preservation and evidence limitation

- The newer workspace remained at **`a1256aa9623610096a7f2df06367d0b89ec8c05d`**, local branch `main`; it was not reset to the requested remote SHA.
- All **321 workspace source-input hashes** match the before snapshot. The extra local download ZIP was preserved and was not overlaid into the saved export's320 inputs. No source/dependency/config/test edits were made. Only new reports and memory documentation were added.
- Staged-content checks remained empty against unchanged HEAD/tree `b7ecce494a2e9b1c9f33ed3e47d8c2177ab72fb2`; no staging/commit/push/reset was requested or executed by the main agent.
- **Raw index checksum limitation:** the main initial index checksum (`97e746f0…`) differs from the testing agent interval's checksum (`e6718788…`), and a later main read observed `9b3574e0…`. The agent's own interval has matching before/after bytes, but **byte-for-byte index preservation across the whole session is not claimed**. HEAD, staged content and application-input hashes are unchanged; the cause of the index metadata/checksum changes was not established. Full values are retained in `main-evidence-validation.json` rather than concealed by the narrower preservation report.

## Production gates still open

| Gate | What this run establishes | Still required before release approval |
|---|---|---|
| **B1 Artifact/build provenance** | Remote lock inclusion/hash, exact remote-source export, source build, matching identities and isolated ASGI readiness are verified for this SHA and preview API origin. | Clean backend dependency install; actual frontend/backend container builds and runtime checks; immutable image identities; proof of the real managed pipeline consuming approved source/generated artifacts and approved API-origin configuration. Docker/Podman was unavailable; no pipeline was run. |
| **B2 Startup / maintenance effects** | Disposable empty-DB boot is read-only, all capabilities OFF. | Production-consistent isolated data/index/registry/migration-impact and controlled maintenance evidence. Empty DB is not a production clone. |
| **B3 Restricted-mode acceptance** | Existing selected safety/regression checks and compiled assets pass. | Restricted-customer desktop/mobile end-to-end flows and complete disabled-integration/egress checks against the intended runtime. |
| **B4 Deployed identity / scheduling** | Artifact identity/protocol is verifiable in isolation. | Actual production commit/deployment/image IDs; complete scheduler/worker inventory, single authority and absence of overlapping legacy writers. No production status was read or changed. |
| **B5 Data quality / freshness** | Seven existing preview-scope assertions pass. | Approved production store/SKU coverage, eligible-offer provenance, timestamps and freshness/expiry. These tests do not establish whole-catalogue freshness. |
| **B6 Backup / restore / rollback** | Existing isolated protocol/recovery regressions pass. | Authorized backup/PITR ID and retention, successful isolated restoration/integrity comparison, compatible fallback image, real rollback rehearsal and agreed RPO/RTO. No authorized restoration evidence supplied. |
| **B7 Operational acceptance** | Selected tests and lightweight isolated readiness pass. | Capacity/load, monitoring/on-call ownership, abort/recovery procedures and supported-runtime signoff. `/api/ready`200 alone is not operational approval. |

**Next concrete action:** take this exact saved SHA into a **Docker/Podman-capable isolated verification runner**, rerun the existing remote verifier with `--containers` and a new evidence directory, and capture backend/frontend image IDs plus container-level startup/readiness **without deploying**. The current build uses a preview API origin; any different approved build context must generate and record its own identity. Then obtain actual managed-pipeline provenance and the remaining authorized B2–B7 evidence. Do not mark production ready or initiate production actions from this report.

Email remains **MOCKED/unavailable**; Zid partner-order approval and Webshare402/broad crawl coverage remain unresolved and were not activated/tested. New-store rollout and broad refactoring stay deferred. Optional future improvement: an immutable release/evidence bundle linking comparison results to source/as-of provenance.

## Evidence index

- Independent report: `/app/test_reports/iteration_44.json`.
- Main evidence root: `/app/test_reports/exact_source_2faa51c/`.
- Primary summaries: `verification-summary.json`, `main-evidence-validation.json`.
- Exact build/lock/ready: `build-attempt-01/{result,source-receipt,build-evidence,artifact-ready}.json`, `remote-lock-evidence.json`, retained unchanged `remote-lock-yarn.lock`.
- Logs/XMLs: `verify_clean_release_attempt01.log`, `reviewed-tests-attempt-01/`, `packaging-attempt-01.{log,xml}`, `preview-scope-attempt-01.{log,xml}`, `verify-release-artifact-after-tests.log`.
- Preservation: `workspace-baseline-{before,after}.json`, `workspace-preservation-compare.json`, `export-source-integrity-after-tests.json`; broader index caveat above takes precedence over any whole-session byte-preservation inference.