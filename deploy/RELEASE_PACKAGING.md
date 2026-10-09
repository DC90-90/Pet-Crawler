# Isolated release packaging — no production authorization

## Status and evidence boundaries

Reference: `dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc`, repository `DC90-90/Pet-Crawler`, branch `conflict_130726_1244`.

The reference's **actual public remote tree** omits `frontend/yarn.lock` and contains outdated generated manifests. Local Git also omitted the lock before save, despite its presence on disk. Root/frontend ignore files, `.git/info/exclude`, and global excludes did not explain the omission. Thus the missing input predates the saved Git snapshot; evidence does not establish an internal Save-to-GitHub filter/root cause. Explicit inclusion/export attributes are now present, but **only a subsequent actual remote blob check can establish closure**. No direct Git add/commit/push is used.

Compatible lock bytes are unchanged: SHA256 `2348d43b12d72db4d7752db08aa23c9efd54f734d6ab913e1763c8c1cb24edf0`. The corrected saved-source build must use this actual remote blob, not silently inject the local lock or resolve new dependencies.

**Production remains NO-GO.** Backup/restore, deployed identity, scheduler ownership, data quality/freshness and other acceptance gates remain open. This procedure never calls production or stops writers. An isolated readiness200 is an application-artifact check only, not production signoff.

## One build path, two explicit evidence classes

1. **Before save:** `--candidate` copies current packaging inputs to a new `/tmp` directory, stamps `git_commit=null`, and runs a clean frozen frontend build/backend compile/import check. Actual exported-app `/api/ready` must return **503**; generated identity is a candidate, never a saved commit.
2. **After user Save to GitHub:** `--commit SHA --repository DC90-90/Pet-Crawler --branch conflict_130726_1244` requires that exact branch SHA, an untruncated remote tree and an actual lock blob. It downloads the SHA archive and verifies every included source file against its Git blob. No overlay or branch switch is permitted. The **export's own** `scripts/build_release.py` generates both manifests, builds, verifies and tests the export. `/api/ready` must return **200** only if the committed artifact actually verifies.
3. Local `--commit` without `--repository` verifies a Git archive but explicitly records `remote_verified=false`. This is not a substitute for step2's remote proof.

The source receipt is generated from the verified export. `stamp_release.py` has no workspace-stamping CLI and does not accept a user-entered release identifier. Both manifests contain the same generated schema2 payload and identity; compiled `frontend/build/release.json` must equal them. The identity includes the exact source SHA (or explicit candidate null), all declared source inputs and public build context/API origin.

## Input and output contract

- Input roots: **all files** under `backend`, `frontend`, `scripts`, `deploy`, `.github`; plus `.dockerignore`, `.gitignore`, `.gitattributes`, `.emergent/crons.yml`. Backend non-Python resources, frontend plugins and build scripts count, including newly added inputs.
- Explicit non-inputs: generated manifests, dependencies, build outputs, caches, bytecode, private env/credential files and logs. Root `memory`, `test_reports`, investigation archives and generated `.emergent/cron` state are evidence/runtime metadata, not compiler/runtime inputs. These exclusions are not proof of production configuration.
- Generated outputs live only in the exported tree: `backend/release_build.json`, `frontend/public/release.json`, `frontend/build/*`, `artifacts/release-build.json`. Tracked stale manifests were removed. Save source, not these outputs.
- Frontend production preflight rejects missing/stale/different manifests, changed/added/deleted input inventory, unexpected public environment, and wrong API origin. Candidate builds require explicit build-only opt-in and still have no saved SHA. Preview `craco start` is unchanged.
- Runtime backend recomputes actual backend file hashes and checks manifest schema/content-derived identity. It no longer trusts unchanged manifest mtime when code/data changes. Broken/old manifests fail closed.
- `verify_release_artifact.py` verifies prepared source, identical manifests, compiled asset hashes and the API origin's presence in emitted JavaScript. The existing API client's same-origin runtime fallback is unchanged; this check records compiled configuration, not a network request to that origin.
- Node20 / Yarn1.22.22 frozen frontend install is checked. Backend compile and import/readiness run on the existing preview Python environment; **clean backend dependency installation and container runtime are unverified unless separately performed**.

## Commands and private configuration

The commands below require the existing preview environment to be loaded into the child process: `MONGO_URL` must be loopback for readiness testing, existing backend configuration remains unchanged, and `REACT_APP_BACKEND_URL` must come from `frontend/.env`. Do not print/copy secrets into reports, source or artifacts. The API origin used for the isolated rehearsal is the preview origin; it must never be described as a production origin.

```bash
python scripts/run_reviewed_tests.py
python -m pytest -q backend/tests/test_iter40_preview_scope_checks.py --junitxml=test_reports/pytest/packaging-preview-scope.xml
python -m pytest -q backend/tests/test_release_packaging.py --junitxml=test_reports/pytest/packaging-regressions.xml

# Before Save to GitHub (candidate only):
python scripts/verify_clean_release.py --candidate --containers --output /tmp/daleel-candidate-evidence-NEW

# After Save to GitHub; replace SAVED_SHA with the actually verified remote SHA:
python scripts/verify_clean_release.py --commit SAVED_SHA --repository DC90-90/Pet-Crawler --branch conflict_130726_1244 --containers --output /tmp/daleel-saved-evidence-NEW
```

Output directory must be new; failures are never overwritten by a retry. Configure the existing preview values privately before invoking these commands. The ready check imports the exported FastAPI app, uses ASGI transport (no additional listening server), runs real read-only startup against a disposable local DB, checks capabilities OFF and verifies **zero collections created**. It creates no test login users and changes no credentials.

## Artifact consumers and managed-pipeline limit

Repository Dockerfiles now consume **only prepared exports**. A Python verification stage validates all source/manifests/compiled assets with `--require-committed`; backend copies verified backend files, frontend copies the verified compiled bundle rather than rebuilding with an unrelated API origin. The compose health check uses `/api/ready`. Building directly from an unstamped working tree deliberately fails.

These repository checks **do not establish which recipe the managed platform uses**. General platform guidance says managed packaging may use preview state and rewrite dependency inputs rather than consume these repository Dockerfiles. That guidance is not app-specific pipeline evidence. No supported exact-artifact hook or actual production build trace was verified here. If managed packaging bypasses the exporter, frontend production preflight must refuse missing/stale inputs rather than ship the old manifest. **Managed pipeline/artifact consumption stays UNVERIFIED.**

Without Docker/Podman, `--containers` records `unverified-no-container-engine`; it does not invent image digests or claim an image build. Even successful future image builds would not establish deployed production identity or scheduler ownership.

## Save to GitHub and follow-up

Use the chat's **Save to GitHub** control, confirming **DC90-90/Pet-Crawler → conflict_130726_1244**. Include `frontend/yarn.lock`, inclusion attributes, new/changed packaging source/tests/docs and manifest deletions. Exclude secrets, generated manifests/build outputs and dependency caches. If destination/file inclusion cannot be confirmed, stop rather than push directly or save to another branch.

After save, record the remote SHA and run the remote command above. Require exact lock hash, all source blob matches, matching generated manifests, clean build and committed-artifact readiness result. If the lock is again missing, retain the failed report and escalate the unexplained save omission; do not patch the exported commit with a local lock and label it exact-source.