"""Release packaging regressions for isolated export/build safety contracts."""
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from release_contract import build_context, digest, load_and_verify, make_manifest, source_files
from release_source import Export, export_remote, extract
from stamp_release import stamp
from verify_release_artifact import asset_hashes, verify


def _seed_minimal_release_tree(base: Path, origin: str = "https://preview.example.test"):
    # release_contract inputs + root configs
    for rel, content in {
        "backend/server.py": "APP = 'ok'\n",
        "backend/module.txt": "backend-bytes\n",
        "frontend/src/index.js": "console.log('app');\n",
        "frontend/release-build/verify.cjs": (ROOT / "frontend/release-build/verify.cjs").read_text(),
        "frontend/yarn.lock": "# frozen\nleft-pad@1.3.0:\n  version \"1.3.0\"\n",
        "scripts/helper.py": "print('helper')\n",
        "deploy/backend.Dockerfile": "FROM python:3.11-slim\n",
        ".github/workflows/ci.yml": "name: ci\n",
        ".dockerignore": "node_modules\n",
        ".gitignore": "__pycache__/\n",
        ".gitattributes": "* text=auto\n",
        ".emergent/crons.yml": "jobs: []\n",
    }.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    files = source_files(base)
    context = build_context(origin)
    return files, context


def _write_dual_manifests(base: Path, manifest: dict):
    for rel in ("backend/release_build.json", "frontend/public/release.json"):
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, sort_keys=True))


def _run_js_verify(base: Path, context: dict, *, allow_candidate: bool = False, extra_env: dict | None = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("REACT_APP_")}
    env.update(context)
    if allow_candidate:
        env["DALEEL_ALLOW_CANDIDATE_BUILD"] = "true"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["node", "frontend/release-build/verify.cjs"], cwd=base, env=env, capture_output=True, text=True)


# release_contract hashing/inventory rules
def test_source_files_include_all_roots_and_lock(tmp_path: Path):
    files, _ = _seed_minimal_release_tree(tmp_path)
    for expected in (
        "backend/server.py",
        "frontend/src/index.js",
        "frontend/release-build/verify.cjs",
        "frontend/yarn.lock",
        "scripts/helper.py",
        "deploy/backend.Dockerfile",
        ".github/workflows/ci.yml",
        ".dockerignore",
        ".gitignore",
        ".gitattributes",
        ".emergent/crons.yml",
    ):
        assert expected in files
    assert files["frontend/yarn.lock"] == digest((tmp_path / "frontend/yarn.lock").read_bytes())


def test_source_files_exclude_secrets_caches_and_generated(tmp_path: Path):
    _seed_minimal_release_tree(tmp_path)
    for rel in (
        "backend/.env",
        "backend/debug.log",
        "backend/secrets.pem",
        "frontend/build/app.js",
        "backend/release_build.json",
        "frontend/public/release.json",
        "frontend/node_modules/pkg/index.js",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    files = source_files(tmp_path)
    assert "backend/.env" not in files
    assert "backend/debug.log" not in files
    assert "backend/secrets.pem" not in files
    assert "frontend/build/app.js" not in files
    assert "backend/release_build.json" not in files
    assert "frontend/public/release.json" not in files
    assert "frontend/node_modules/pkg/index.js" not in files


def test_source_files_requires_frontend_lock(tmp_path: Path):
    _seed_minimal_release_tree(tmp_path)
    (tmp_path / "frontend/yarn.lock").unlink()
    with pytest.raises(ValueError, match="Missing saved frontend/yarn.lock"):
        source_files(tmp_path)


def test_manifest_identity_is_deterministic_and_sensitive_to_commit_and_origin(tmp_path: Path):
    files, context_a = _seed_minimal_release_tree(tmp_path, "https://a.example.test")
    m1 = make_manifest(files, "a" * 40, context_a)
    m2 = make_manifest(files, "a" * 40, context_a)
    m3 = make_manifest(files, "b" * 40, context_a)
    context_b = build_context("https://b.example.test")
    m4 = make_manifest(files, "a" * 40, context_b)
    assert m1 == m2
    assert m1["release_id"] != m3["release_id"]
    assert m1["release_id"] != m4["release_id"]


def test_make_manifest_rejects_non_sha_commit_label(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    with pytest.raises(ValueError, match="Expected resolved source commit"):
        make_manifest(files, "release-123", context)


# stamp/load verification mutation guards
def test_stamp_rejects_mutation_before_attribution(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    export = Export(root=tmp_path, commit="c" * 40, files=files, evidence={"method": "test"})
    (tmp_path / "backend/module.txt").write_text("changed-after-export\n")
    with pytest.raises(ValueError, match="Export changed before stamping"):
        stamp(export, context)


def test_load_and_verify_rejects_source_change_even_if_manifest_mtime_unchanged(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, "d" * 40, context)
    _write_dual_manifests(tmp_path, manifest)
    manifest_path = tmp_path / "backend/release_build.json"
    before_stat = manifest_path.stat()
    (tmp_path / "backend/server.py").write_text("APP = 'mutated'\n")
    os.utime(manifest_path, (before_stat.st_atime, before_stat.st_mtime))
    with pytest.raises(ValueError, match="Source changed after export/stamping"):
        load_and_verify(tmp_path, require_committed=True)


def test_load_and_verify_rejects_backend_frontend_manifest_disagreement(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    backend_manifest = make_manifest(files, "e" * 40, context)
    front_manifest = dict(backend_manifest)
    front_manifest["release_id"] = "sha256:" + "0" * 64
    _write_dual_manifests(tmp_path, backend_manifest)
    (tmp_path / "frontend/public/release.json").write_text(json.dumps(front_manifest))
    with pytest.raises(ValueError, match="Backend/frontend generated manifests disagree"):
        load_and_verify(tmp_path, require_committed=True)


# frontend production preflight (verify.cjs)
def test_js_preflight_rejects_uncommitted_without_explicit_candidate_opt_in(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, None, context)
    _write_dual_manifests(tmp_path, manifest)
    result = _run_js_verify(tmp_path, context, allow_candidate=False)
    assert result.returncode != 0
    assert "Saved-source manifest required for production build" in result.stderr


def test_js_preflight_candidate_optin_allows_null_sha(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, None, context)
    _write_dual_manifests(tmp_path, manifest)
    result = _run_js_verify(tmp_path, context, allow_candidate=True)
    assert result.returncode == 0
    assert manifest["git_commit"] is None


def test_js_preflight_rejects_changed_missing_or_added_inputs_and_context_mismatch(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, "f" * 40, context)
    _write_dual_manifests(tmp_path, manifest)

    (tmp_path / "scripts/helper.py").write_text("changed\n")
    changed = _run_js_verify(tmp_path, context)
    assert changed.returncode != 0
    assert "Release input" in changed.stderr

    (tmp_path / "scripts/helper.py").write_text("print('helper')\n")
    (tmp_path / "deploy/backend.Dockerfile").unlink()
    missing = _run_js_verify(tmp_path, context)
    assert missing.returncode != 0 and "Release input inventory changed, added or removed" in missing.stderr

    (tmp_path / "deploy/backend.Dockerfile").write_text("FROM python:3.11-slim\n")
    (tmp_path / "deploy/extra.cfg").write_text("new\n")
    added = _run_js_verify(tmp_path, context)
    assert added.returncode != 0 and "Release input inventory changed, added or removed" in added.stderr

    (tmp_path / "deploy/extra.cfg").unlink()
    wrong_context = _run_js_verify(tmp_path, context, extra_env={"REACT_APP_BACKEND_URL": "https://wrong.example.test"})
    assert wrong_context.returncode != 0 and "Build context mismatch: REACT_APP_BACKEND_URL" in wrong_context.stderr


def test_js_preflight_rejects_unrecorded_public_env(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, "1" * 40, context)
    _write_dual_manifests(tmp_path, manifest)
    result = _run_js_verify(tmp_path, context, extra_env={"REACT_APP_UNTRACKED": "1"})
    assert result.returncode != 0
    assert "Unrecorded public build environment" in result.stderr


# compiled artifact verification
def test_verify_release_artifact_rejects_asset_manifest_and_origin_drift(tmp_path: Path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, "2" * 40, context)
    _write_dual_manifests(tmp_path, manifest)

    js = tmp_path / "frontend/build/static/js/main.js"
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(f"window.API='{context['REACT_APP_BACKEND_URL']}';")
    (tmp_path / "frontend/build/release.json").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend/build/release.json").write_text(json.dumps(manifest))
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    build = {
        "release_id": manifest["release_id"],
        "git_commit": manifest["git_commit"],
        "lock_sha256": manifest["lock_sha256"],
        "build_context": manifest["build_context"],
        "frontend_assets": asset_hashes(tmp_path),
    }
    (tmp_path / "artifacts/release-build.json").write_text(json.dumps(build))

    verify(root=tmp_path, require_committed=True, compiled=True)

    js.write_text("window.API='https://other.example.test';")
    with pytest.raises(ValueError, match="Compiled artifact hashes changed"):
        verify(root=tmp_path, require_committed=True, compiled=True)

    js.write_text("window.API='https://other.example.test';")
    build["frontend_assets"] = asset_hashes(tmp_path)
    (tmp_path / "artifacts/release-build.json").write_text(json.dumps(build))
    with pytest.raises(ValueError, match="Expected API origin not found"):
        verify(root=tmp_path, require_committed=True, compiled=True)

    js.write_text(f"window.API='{context['REACT_APP_BACKEND_URL']}';")
    build["frontend_assets"] = asset_hashes(tmp_path)
    (tmp_path / "artifacts/release-build.json").write_text(json.dumps(build))
    bad_front = dict(manifest)
    bad_front["release_id"] = "sha256:" + "f" * 64
    (tmp_path / "frontend/build/release.json").write_text(json.dumps(bad_front))
    build["frontend_assets"] = asset_hashes(tmp_path)
    (tmp_path / "artifacts/release-build.json").write_text(json.dumps(build))
    with pytest.raises(ValueError, match="Compiled frontend manifest differs from backend"):
        verify(root=tmp_path, require_committed=True, compiled=True)


# packaging scripts and Docker recipe policy assertions
def test_packaging_scripts_do_not_perform_git_writes_or_workspace_stamping():
    stamp_text = (ROOT / "scripts/stamp_release.py").read_text()
    source_text = (ROOT / "scripts/release_source.py").read_text()
    verify_text = (ROOT / "scripts/verify_clean_release.py").read_text()
    for forbidden in ("git commit", "git push", "git init"):
        assert forbidden not in stamp_text
        assert forbidden not in source_text
        assert forbidden not in verify_text
    assert "Direct workspace stamping is forbidden." in stamp_text


def test_dockerfiles_consume_verified_outputs_from_verified_stage():
    backend = (ROOT / "deploy/backend.Dockerfile").read_text()
    frontend = (ROOT / "deploy/frontend.Dockerfile").read_text()
    assert "RUN python scripts/verify_release_artifact.py --require-committed" in backend
    assert "COPY --from=verified /source/backend/ ./" in backend
    assert "RUN python scripts/verify_release_artifact.py --require-committed" in frontend
    assert "COPY --from=verified /source/frontend/build /usr/share/nginx/html" in frontend


# archive/export safety and remote lock gate
def test_extract_rejects_traversal_and_symlink_members(tmp_path: Path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        bad = tarfile.TarInfo(name="root/../escape.txt")
        payload = b"oops"
        bad.size = len(payload)
        tar.addfile(bad, io.BytesIO(payload))
    with pytest.raises(ValueError, match="Unsafe source archive member"):
        extract(data.getvalue(), tmp_path, strip_prefix=True)

    data2 = io.BytesIO()
    with tarfile.open(fileobj=data2, mode="w") as tar:
        sym = tarfile.TarInfo(name="root/link")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "target"
        tar.addfile(sym)
    with pytest.raises(ValueError, match="Unsafe source archive member"):
        extract(data2.getvalue(), tmp_path, strip_prefix=True)


def test_export_remote_fails_explicitly_when_reference_commit_omits_lock(tmp_path: Path, monkeypatch):
    commit = "dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc"

    def fake_check_output(cmd, *args, **kwargs):
        if cmd[:2] == ["git", "ls-remote"]:
            return f"{commit}\trefs/heads/conflict_130726_1244\n"
        raise AssertionError(f"Unexpected command: {cmd}")

    def fake_get(url):
        if "/git/trees/" in url:
            return json.dumps({"truncated": False, "tree": [{"path": "frontend/package.json", "type": "blob", "sha": "1"}]}).encode()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("release_source.subprocess.check_output", fake_check_output)
    monkeypatch.setattr("release_source.get", fake_get)
    with pytest.raises(ValueError, match="omits frontend/yarn.lock"):
        export_remote("DC90-90/Pet-Crawler", "conflict_130726_1244", commit, tmp_path)


def test_runtime_identity_detects_same_mtime_input_change(tmp_path, monkeypatch):
    import release_identity
    files, context = _seed_minimal_release_tree(tmp_path)
    _write_dual_manifests(tmp_path, make_manifest(files, None, context))
    monkeypatch.setattr(release_identity, "ROOT", tmp_path / "backend")
    assert release_identity.identity()["manifest_verified"] is True
    source = tmp_path / "backend/module.txt"
    before = source.stat()
    source.write_text("modified-data\n")
    os.utime(source, (before.st_atime, before.st_mtime))
    assert release_identity.identity()["manifest_verified"] is False


def test_runtime_identity_rejects_malformed_and_legacy_manifests(tmp_path, monkeypatch):
    import release_identity
    _seed_minimal_release_tree(tmp_path)
    monkeypatch.setattr(release_identity, "ROOT", tmp_path / "backend")
    target = tmp_path / "backend/release_build.json"
    for content in ("{broken", json.dumps({"release_id": "legacy", "backend_files": {}})):
        target.write_text(content)
        identity = release_identity.identity()
        assert identity["manifest_verified"] is False and identity["git_commit"] is None


def test_runtime_identity_detects_new_non_python_input(tmp_path, monkeypatch):
    import release_identity
    files, context = _seed_minimal_release_tree(tmp_path)
    _write_dual_manifests(tmp_path, make_manifest(files, None, context))
    monkeypatch.setattr(release_identity, "ROOT", tmp_path / "backend")
    assert release_identity.identity()["manifest_verified"] is True
    (tmp_path / "backend/new-data.csv").write_text("key,value\nx,1\n")
    assert release_identity.identity()["manifest_verified"] is False


def test_direct_stamp_cli_refuses_workspace_attribution():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/stamp_release.py"), "--commit", "dc22d72a51f6d35dd40e4ee469c22f57f5d3d9dc"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "Direct workspace stamping is forbidden" in result.stderr


def test_js_preflight_rejects_derived_lock_hash_tampering(tmp_path):
    files, context = _seed_minimal_release_tree(tmp_path)
    manifest = make_manifest(files, None, context)
    manifest["lock_sha256"] = "invalid"
    _write_dual_manifests(tmp_path, manifest)
    result = _run_js_verify(tmp_path, context, allow_candidate=True)
    assert result.returncode != 0 and "Invalid lock hash" in result.stderr
