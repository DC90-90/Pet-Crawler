"""Managed frontend build regressions: unverified path, strict path, and receipt plugin checks."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from release_contract import build_context, make_manifest, source_files


def _run_node(cwd: Path, script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    runner = cwd / "node_runner.cjs"
    runner.write_text(script)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(["node", str(runner)], cwd=cwd, env=merged_env, text=True, capture_output=True)


def _seed_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    for rel, content in {
        "frontend/release-build/prepare.cjs": (ROOT / "frontend/release-build/prepare.cjs").read_text(),
        "frontend/release-build/receipt.cjs": (ROOT / "frontend/release-build/receipt.cjs").read_text(),
        "frontend/release-build/build-plugin.cjs": (ROOT / "frontend/release-build/build-plugin.cjs").read_text(),
        "frontend/release-build/verify.cjs": (ROOT / "frontend/release-build/verify.cjs").read_text(),
        "frontend/yarn.lock": "left-pad@1.3.0:\n  version \"1.3.0\"\n",
        "frontend/package.json": "{\"name\":\"fixture\",\"version\":\"1.0.0\",\"private\":true}",
        "frontend/craco.config.js": "module.exports = {};\n",
        "frontend/src/index.js": "console.log('fixture');\n",
        "frontend/public/index.html": "<html><body>fixture</body></html>\n",
        "backend/server.py": "APP = 'ok'\n",
        "scripts/helper.py": "print('ok')\n",
        "deploy/backend.Dockerfile": "FROM python:3.11-slim\n",
        ".github/workflows/ci.yml": "name: ci\n",
        ".dockerignore": "node_modules\n",
        ".gitignore": "__pycache__/\n",
        ".gitattributes": "* text=auto\n",
        ".emergent/crons.yml": "jobs: []\n",
    }.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return ws


def _write_manifests(ws: Path, *, origin: str, commit: str | None):
    files = source_files(ws)
    manifest = make_manifest(files, commit, build_context(origin))
    for rel in ("backend/release_build.json", "frontend/public/release.json"):
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(manifest, sort_keys=True))
    return manifest


def _prepare(ws: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    script = """
const out = require('./frontend/release-build/prepare.cjs').prepareBuild();
console.log(JSON.stringify(out.receipt));
"""
    return _run_node(ws, script, env)


# managed path behavior
def test_unmanifested_frontend_only_workspace_returns_unverified_receipt(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    (ws / "backend").rename(ws / "backend_absent")
    env = {
        "REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com",
        "NODE_ENV": "production",
        "GIT_COMMIT": "f" * 40,
    }
    result = _prepare(ws, env)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["source_state"] == "unverified-managed-workspace"
    assert receipt["git_commit"] is None
    assert receipt["release_id"] is None
    assert receipt["manifest_verified"] is False
    assert not (ws / "backend/release_build.json").exists()
    assert not (ws / "frontend/public/release.json").exists()


def test_unmanifested_full_tree_workspace_also_returns_unverified_receipt(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    env = {
        "REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com",
        "NODE_ENV": "production",
    }
    result = _prepare(ws, env)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["source_state"] == "unverified-managed-workspace"
    assert receipt["manifest_verified"] is False
    assert receipt["git_commit"] is None


# strict mode and manifest validation behavior
def test_require_verified_true_with_missing_manifests_fails(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _prepare(ws, {
        "REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com",
        "DALEEL_REQUIRE_VERIFIED_RELEASE_BUILD": "true",
    })
    assert result.returncode != 0
    assert "Strict release build requires both generated manifests" in result.stderr


@pytest.mark.parametrize("missing_rel", ["backend/release_build.json", "frontend/public/release.json"])
def test_partial_manifest_pair_fails_without_unverified_fallback(tmp_path: Path, missing_rel: str):
    ws = _seed_workspace(tmp_path)
    _write_manifests(ws, origin="https://price-intel-dev.preview.emergentagent.com", commit=None)
    (ws / missing_rel).unlink()
    result = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com"})
    assert result.returncode != 0
    assert "Strict release build requires both generated manifests" in result.stderr


def test_stale_manifest_pair_fails_strict_verification(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    _write_manifests(ws, origin="https://price-intel-dev.preview.emergentagent.com", commit="a" * 40)
    (ws / "scripts/helper.py").write_text("print('changed')\n")
    result = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com"})
    assert result.returncode != 0
    assert "Release input inventory changed, added or removed" in result.stderr or "Release input changed" in result.stderr


def test_corrupt_manifest_pair_fails(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    _write_manifests(ws, origin="https://price-intel-dev.preview.emergentagent.com", commit="b" * 40)
    (ws / "backend/release_build.json").write_text("{broken")
    result = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com"})
    assert result.returncode != 0


def test_valid_candidate_manifest_requires_explicit_optin_and_remains_null_sha(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    manifest = _write_manifests(ws, origin="https://price-intel-dev.preview.emergentagent.com", commit=None)
    ctx = {k: v for k, v in manifest["build_context"].items() if v is not None}
    without_optin = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com", **ctx})
    assert without_optin.returncode != 0
    assert "Saved-source manifest required for production build" in without_optin.stderr

    with_optin = _prepare(ws, {
        "REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com",
        **ctx,
        "DALEEL_ALLOW_CANDIDATE_BUILD": "true",
    })
    assert with_optin.returncode == 0, with_optin.stderr
    receipt = json.loads(with_optin.stdout.strip().splitlines()[-1])
    assert receipt["git_commit"] is None
    assert receipt["manifest_verified"] is True


def test_valid_committed_fixture_accepts_synthetic_sha_invariants(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    synthetic = "c" * 40
    manifest = _write_manifests(ws, origin="https://price-intel-dev.preview.emergentagent.com", commit=synthetic)
    ctx = {k: v for k, v in manifest["build_context"].items() if v is not None}
    result = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com", **ctx})
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["git_commit"] == synthetic
    assert receipt["source_state"] == "committed-export"
    assert receipt["manifest_verified"] is True


# receipt input validation and hashing behavior
def test_required_frontend_inputs_missing_are_rejected(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    for rel in ("frontend/yarn.lock", "frontend/package.json", "frontend/craco.config.js"):
        fresh = _seed_workspace(tmp_path / rel.replace("/", "_"))
        (fresh / rel).unlink()
        result = _prepare(fresh, {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com"})
        assert result.returncode != 0
        assert "Missing required frontend input" in result.stderr


@pytest.mark.parametrize(
    "origin",
    [
        "/api",
        "ftp://example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=1",
    ],
)
def test_invalid_api_origin_rejected(origin: str, tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    result = _prepare(ws, {"REACT_APP_BACKEND_URL": origin})
    assert result.returncode != 0
    assert "REACT_APP_BACKEND_URL must be" in result.stderr


def test_receipt_is_deterministic_and_changes_on_input_or_origin_change(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    env = {"REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com"}
    first = _prepare(ws, env)
    second = _prepare(ws, env)
    assert first.returncode == 0 and second.returncode == 0
    r1 = json.loads(first.stdout.strip().splitlines()[-1])
    r2 = json.loads(second.stdout.strip().splitlines()[-1])
    assert r1["frontend_content_sha256"] == r2["frontend_content_sha256"]

    (ws / "frontend/src/new-file.js").write_text("console.log('new')\n")
    third = _prepare(ws, env)
    r3 = json.loads(third.stdout.strip().splitlines()[-1])
    assert r3["frontend_content_sha256"] != r1["frontend_content_sha256"]

    fourth = _prepare(ws, {"REACT_APP_BACKEND_URL": "https://another.preview.emergentagent.com"})
    r4 = json.loads(fourth.stdout.strip().splitlines()[-1])
    assert r4["frontend_content_sha256"] != r3["frontend_content_sha256"]


def test_public_environment_hash_updates_without_disclosing_non_public_values(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    env_a = {
        "REACT_APP_BACKEND_URL": "https://price-intel-dev.preview.emergentagent.com",
        "REACT_APP_FEATURE_X": "on",
        "SECRET_TOKEN": "top-secret",
    }
    env_b = dict(env_a)
    env_b["REACT_APP_FEATURE_X"] = "off"
    a = _prepare(ws, env_a)
    b = _prepare(ws, env_b)
    ra = json.loads(a.stdout.strip().splitlines()[-1])
    rb = json.loads(b.stdout.strip().splitlines()[-1])
    assert ra["public_environment_sha256"] != rb["public_environment_sha256"]
    payload = json.dumps(ra)
    assert "SECRET_TOKEN" not in payload and "top-secret" not in payload


# BuildReceiptPlugin behavior with fake compiler hooks
def test_build_receipt_plugin_detects_source_mutation_during_compilation(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = """
const { BuildReceiptPlugin } = require('./frontend/release-build/build-plugin.cjs');
const receipt = { api_origin: 'https://price-intel-dev.preview.emergentagent.com', x: 1 };
const plugin = new BuildReceiptPlugin(receipt, () => ({ api_origin: 'https://price-intel-dev.preview.emergentagent.com', x: 2 }));
let processAssets;
const compiler = {
  webpack: { Compilation: { PROCESS_ASSETS_STAGE_REPORT: 1 }, sources: { RawSource: class { constructor(v){ this.value=v; } } } },
  options: { plugins: [{ definitions: { 'process.env': { REACT_APP_BACKEND_URL: JSON.stringify('https://price-intel-dev.preview.emergentagent.com') } } }] },
  hooks: { thisCompilation: { tap: (_n, cb) => cb({ hooks: { processAssets: { tap: (_o, fn) => { processAssets = fn; } } }, emitAsset: () => {} }) } }
};
plugin.apply(compiler);
try { processAssets(); console.log('NO_ERROR'); } catch (e) { console.error(e.message); process.exit(2); }
"""
    result = _run_node(ws, script)
    assert result.returncode != 0
    assert "Frontend inputs changed during compilation" in result.stderr


def test_build_receipt_plugin_detects_defineplugin_api_origin_mismatch(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = """
const { BuildReceiptPlugin } = require('./frontend/release-build/build-plugin.cjs');
const receipt = { api_origin: 'https://price-intel-dev.preview.emergentagent.com', x: 1 };
const plugin = new BuildReceiptPlugin(receipt, () => receipt);
let processAssets;
const compiler = {
  webpack: { Compilation: { PROCESS_ASSETS_STAGE_REPORT: 1 }, sources: { RawSource: class { constructor(v){ this.value=v; } } } },
  options: { plugins: [{ definitions: { 'process.env': { REACT_APP_BACKEND_URL: JSON.stringify('https://wrong.preview.emergentagent.com') } } }] },
  hooks: { thisCompilation: { tap: (_n, cb) => cb({ hooks: { processAssets: { tap: (_o, fn) => { processAssets = fn; } } }, emitAsset: () => {} }) } }
};
plugin.apply(compiler);
try { processAssets(); console.log('NO_ERROR'); } catch (e) { console.error(e.message); process.exit(2); }
"""
    result = _run_node(ws, script)
    assert result.returncode != 0
    assert "Compiled API origin differs from frontend build receipt" in result.stderr


def test_build_receipt_plugin_emits_only_build_provenance_asset(tmp_path: Path):
    ws = _seed_workspace(tmp_path)
    script = """
const { BuildReceiptPlugin } = require('./frontend/release-build/build-plugin.cjs');
const receipt = { api_origin: 'https://price-intel-dev.preview.emergentagent.com', source_state: 'unverified-managed-workspace' };
const plugin = new BuildReceiptPlugin(receipt, () => receipt);
let processAssets;
const emitted = {};
const compiler = {
  webpack: { Compilation: { PROCESS_ASSETS_STAGE_REPORT: 1 }, sources: { RawSource: class { constructor(v){ this.value=v; } } } },
  options: { plugins: [{ definitions: { 'process.env': { REACT_APP_BACKEND_URL: JSON.stringify('https://price-intel-dev.preview.emergentagent.com') } } }] },
  hooks: { thisCompilation: { tap: (_n, cb) => cb({ hooks: { processAssets: { tap: (_o, fn) => { processAssets = fn; } } }, emitAsset: (name, src) => { emitted[name] = src.value; } }) } }
};
plugin.apply(compiler);
processAssets();
console.log(JSON.stringify(Object.keys(emitted)));
"""
    result = _run_node(ws, script)
    assert result.returncode == 0, result.stderr
    emitted = json.loads(result.stdout.strip().splitlines()[-1])
    assert emitted == ["build-provenance.json"]
