# Release packaging corrections — isolated handoff

**Date:** 2026-10-09 UTC. **Status: candidate verified; corrected remote save/exact-source build pending. Production NO-GO.**

User reference: `dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc`. Authorized destination: **`DC90-90/Pet-Crawler` → `conflict_130726_1244`**. No direct Git add/commit/push, branch switch/reset, production deployment/access/write/backfill/writer shutdown, or credential rotation was performed. All DB mutation tests used disposable loopback databases; preview API checks used existing data/credentials.

## 1. Missing-lock diagnosis: what is proved, and what is not

- Read-only `git ls-remote` found the actual destination branch at the exact reference SHA. Public GitHub API returned its untruncated Git tree. **`frontend/yarn.lock` is absent remotely**, while `backend/release_build.json` and `frontend/public/release.json` are present with obsolete candidate metadata.
- The local reference/index also omits the lock; the compatible file exists on disk with SHA256 **`2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`**. It has no local Git history. Root/frontend ignores, `.git/info/exclude` and global excludes did not account for the omission. This places the omission before the saved Git snapshot; it does **not** prove a particular hidden Save-to-GitHub filter or internal failure mechanism.
- Kept the lock bytes unchanged. Added explicit `.gitignore` inclusion and `.gitattributes` text/LF/`-export-ignore` intent. These rules are **not evidence that a platform exporter now includes it**. In the pre-save local index it remains untracked; actual inclusion must be verified after the user-operated save.
- New remote verification reads exact branch/SHA/tree, requires the actual lock blob, downloads that SHA's archive and checks all declared source files against their Git blob hashes. A missing lock fails before manifest generation/build; no workspace lock overlay or dependency re-resolution is permitted.
- Executed real remote reproduction: `test_reports/packaging/reference-remote-01/result.json`, **16:35:50–16:35:51 UTC**. Expected failure: `Actual remote commit omits frontend/yarn.lock; Save to GitHub inclusion gate FAILED`. This is an **open release gate**, not a passed saved-source build.

## 2. Corrections implemented

- Removed tracked stale manifests. New generated manifests are ignored as source and produced only inside isolated exports. Source archives are never mixed with newer working-tree code.
- `release_source.py` exports either a verified local commit, a verified actual remote branch/SHA, or an explicitly uncommitted candidate. Remote export verifies each included blob; archive extraction rejects path traversal/symlinks. The exporter provides the source receipt; the **export's own build driver** is executed.
- `release_contract.py` hashes every file under declared input roots, including non-Python backend data, frontend plugins, tests, scripts and deployment files, plus root ignore/attribute/cron controls. Explicit generated/private/cache exclusions are documented in `deploy/RELEASE_PACKAGING.md`.
- Generated schema2 identity covers source SHA/state, input hashes and public build context including API origin. Backend, public frontend and compiled frontend manifests must agree. No user-supplied release ID or workspace-to-commit stamping is supported.
- Backend runtime verifies manifest structure/content and all backend bytes on each identity evaluation. Changes cannot hide behind unchanged manifest mtime. Malformed/old manifests fail closed.
- Frontend production builds reject missing/stale/mismatched manifests, changed/added/deleted input inventory, inconsistent derived lock/backend fields, unknown public build variables and wrong origin. Candidate opt-in remains null-SHA/not-ready. Preview development startup is unchanged.
- Prepared-artifact verification checks source/manifests, compiled output hashes and API-origin presence in emitted JS. Repository Dockerfiles consume only this verified exported backend/compiled frontend; they reject an uncommitted candidate. Compose readiness now checks `/api/ready`.
- Reviewed application fixes are preserved: direct byte comparisons against the reference passed for `server.py`, ledger/receipts, matcher/verified matching, crawlers, parent identity, release control/runtime/API/maintenance, Zid orders, freshness/release boundaries, comparison and My Products pages. No application route refactor, auth changes or data-policy changes were made.

## 3. Final evidence: 185 selected checks

| Verification | Final result | Evidence |
|---|---|---|
| Original isolated groups | **156 passed**, zero failed/errors/skipped | Eight `test_reports/pytest/*-final.xml` groups; final runner log below |
| Original preview API scope | **7 passed**, zero failed/errors/skipped | `test_reports/packaging/final-verification/preview-scope.xml` |
| Packaging regressions | **22 passed**, zero failed/errors/skipped | `test_reports/packaging/final-verification/packaging.xml` |
| **Total** | **185 = original163 +22 packaging** | `test_reports/packaging/final-verification/run.log` |
| Final frozen frontend build | Passed; lock unchanged | `test_reports/packaging/candidate-02/frontend-install.log`, `frontend-build.log` |
| Backend compilation/import/real boot | Passed in existing preview Python environment | `candidate-02/backend-compile.log`, `artifact-ready.log` |
| Actual isolated artifact `/api/ready` | **503, expected for null-SHA candidate**; manifest verifies, boot done, all capabilities OFF, zero DB collections created | `candidate-02/artifact-ready.json` |
| Complete final input comparison | **320 inputs**, candidate export equals current declared source inventory | Main-agent bidirectional input-hash comparison after build |
| Raw workspace production build | **Rejected as expected (exit1)** because generated export manifest is absent; no stale-manifest fallback | `test_reports/packaging/final-verification/raw-workspace-build.log` |
| UI smoke | Existing preview login loads, desktop1920×800 | `/root/.emergent/automation_output/20261009_163109/console_20261009_163109.log`; no UI-layout changes |

Independent report `test_reports/iteration_43.json` initially verified **163 +17 =180** and candidate01. Main then added five runtime/CLI/derived-lock regressions, dependency-cache exclusions and the packaging guide, and reran **all163 +22** plus a new clean candidate02 build. Candidate01 is retained as earlier-source evidence, not relabeled as final. Initial independent JUnit copies are under `test_reports/packaging/iteration43-junit/`; older15:53 release-safety evidence remains historical and is superseded by these current checks.

There were **no unexpected failing assertions/builds** in these two packaging verification passes. The intentionally failed actual reference-remote check and raw-workspace production-build rejection are retained, not hidden. A final invocation of the exported `verify_release_artifact.py` also passed. These build/gate probes are not additional pytest cases in the185 total. Earlier one/three failures from the preceding release-safety task remain documented in the earlier acceptance report. Non-fatal dependency peer warnings and FastAPI/multipart/test-client deprecations remain. The testing report's unresolved “critical” is the genuine remote missing-lock gate; its container item is unavailable evidence, not a code fix falsely declared complete.

### Final candidate provenance (generated, not a saved release)

- Source SHA: **`null`**, `source_state=uncommitted-candidate`; remote inclusion **not verified for corrections**.
- Reference remote SHA: `dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc` (missing lock).
- Generated candidate identity: **`sha256:0797580df25eb68948713d3bab90bf674affdb88e815f65edcb42de5daded592`**.
- Lock SHA256: **`2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`**.
- Build interval: **2026-10-09T16:39:43.137911Z–16:40:46.078507Z**. Node **v20.20.2**, Yarn **1.22.22**, Python **3.11.17**.
- Compiled API origin: **`https://price-intel-dev.preview.emergentagent.com`**, taken from existing `frontend/.env`. Build receipt records the emitted JS file carrying it and compiled asset hashes. The client's existing same-origin fallback behavior is unchanged. This is not a production-origin proof.
- Authoritative generated records: `test_reports/packaging/candidate-02/result.json`, `build-evidence.json`, `source-receipt.json`, `artifact-ready.json`.
- Export directory: `/tmp/daleel-packaging-rdt8txs_`; generated manifests/assets stay there, not in source. Candidate02 input equality was checked after all code/tests/deploy-guide changes. Later `memory`/`test_reports` documentation is outside the declared build input roots.

### Commands actually executed

Existing env values were loaded privately into child processes from `.env` files; no values were rotated or printed. Commands/results are preserved in `final-verification/run.log` and build receipts:

```text
python -m pytest -q backend/tests/test_release_packaging.py --junitxml=test_reports/packaging/final-verification/packaging.xml
python scripts/run_reviewed_tests.py
python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=test_reports/packaging/final-verification/preview-scope.xml
python scripts/verify_clean_release.py --candidate --containers --output /app/test_reports/packaging/candidate-02
```

The export's driver then executed frozen Yarn install (`--frozen-lockfile --non-interactive --production=false`), `yarn build`, Python compilation, compiled-artifact verification and the real exported-app readiness check. No separate Uvicorn server was started; the last check uses ASGI transport and an empty disposable local Mongo database without mocked identity/boot.

## 4. Explicitly unverified / not completed

1. **Corrected remote lock inclusion and source SHA:** pending user Save to GitHub and remote blob verification. No new SHA is invented. Exact saved-source corrected build and committed-artifact `/api/ready=200` are likewise pending, not claimed from the candidate's expected503.
2. **Container images / clean backend dependency installation:** Docker/Podman unavailable; no image digests, full image build or clean backend dependency-install proof. Source compile/import/readiness uses installed preview Python dependencies.
3. **Actual managed-pipeline consumption:** repository consumer wiring and fail-closed build guard are tested, but no managed pipeline invocation/build trace/artifact handoff was observed. General platform guidance says it may package preview state and rewrite dependency inputs rather than consume repository Dockerfiles. That guidance is not app-specific verification. Actual managed image/source/compiled-origin consumption remains **UNVERIFIED**; no production action is authorized to obtain it now.
4. **Production B1–B7 remain open for signoff**, including authorized backup/PITR and restoration, deployed SHA/image identity, actual single scheduling authority/legacy writers, current eligible data quality/freshness, restricted-customer acceptance and operational capacity/recovery. No production reads were needed for this task.
5. No whole legacy-suite certification; fixtures with artificial manifest SHAs are unit tests only and are **not** saved-source provenance. Email remains **MOCKED/unavailable**; Zid order approval and Webshare402/coverage are unchanged.

## 5. Save to GitHub handoff — next required user action

1. Open **Save to GitHub** in the chat. Confirm **`DC90-90/Pet-Crawler` → `conflict_130726_1244`**. Do not save to `main` or use a direct push.
2. Include the unchanged **`frontend/yarn.lock`**, `.gitattributes`/ignore changes, all packaging source/tests, Docker/compose/build-guard updates and documentation/evidence. Include removal of the obsolete tracked backend/frontend manifests. Exclude `.env`, credential notes, dependency caches and generated artifacts.
3. Provide the resulting remote commit SHA. The next authorized continuation will inspect that actual branch/commit, require the compatible remote lock hash, export **that exact source**, rerun packaging/build/readiness and record its newly generated identity. The candidate ID above is **not** that future release ID.
4. If the lock remains missing or the branch has advanced unexpectedly, stop and preserve failure evidence. Do not overlay workspace inputs, overwrite newer changes, or claim the platform-save omission is fixed without remote proof.

Potential later enhancement: a downloadable comparison-evidence packet tying observed prices/as-of times to the verified release identity. Broader refactoring/new-store rollout remains deferred.