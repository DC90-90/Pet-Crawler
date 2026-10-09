"""Runs INSIDE the exported source using that export's own build implementation."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from release_source import Export
from stamp_release import stamp
from release_contract import build_context, load_and_verify
from verify_release_artifact import asset_hashes, compiled_origin, verify

ROOT = Path(__file__).resolve().parents[1]


def build(receipt_path, output):
    source = json.loads(receipt_path.read_text())
    context = build_context(os.environ["REACT_APP_BACKEND_URL"])
    export = Export(ROOT, source["commit"], source["files"], source["evidence"])
    manifest = stamp(export, context)
    env = {k: v for k, v in os.environ.items() if not k.startswith("REACT_APP_") and k not in {"PUBLIC_URL", "BUILD_PATH", "NODE_ENV", "CI", "GENERATE_SOURCEMAP", "ENABLE_HEALTH_CHECK"}}
    env.update(context)
    # Build-only opt-in: candidate status remains null-SHA/not-ready.
    env["DALEEL_ALLOW_CANDIDATE_BUILD"] = "true" if export.commit is None else "false"
    versions = {k: subprocess.check_output(command, text=True).strip() for k, command in {
        "node": ["node", "--version"], "yarn": ["yarn", "--version"], "python": [sys.executable, "--version"]}.items()}
    if not versions["node"].startswith("v20.") or versions["yarn"] != "1.22.22":
        raise RuntimeError("Use Node20 and Yarn1.22.22, the reviewed build toolchain")
    commands = [(["yarn", "install", "--frozen-lockfile", "--non-interactive", "--production=false", "--cache-folder", str(output / "yarn-cache")], ROOT / "frontend", "frontend-install"),
                (["yarn", "build"], ROOT / "frontend", "frontend-build"),
                ([sys.executable, "-m", "compileall", "-q", "backend", "scripts"], ROOT, "backend-compile")]
    for command, cwd, name in commands:
        with (output / (name + ".log")).open("w") as log:
            subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    load_and_verify(ROOT, require_committed=export.commit is not None)
    record = {k: manifest[k] for k in ("release_id", "git_commit", "lock_sha256", "build_context", "source_state")}
    record.update(versions=versions, commands=[c for c, _, _ in commands], frontend_assets=asset_hashes(ROOT),
                  compiled_api_origin_files=compiled_origin(ROOT, context["REACT_APP_BACKEND_URL"]),
                  frontend_manifest_equal=json.loads((ROOT / "frontend/build/release.json").read_text()) == manifest,
                  backend_dependency_install_verified=False, backend_runtime="existing-preview-Python-not-a-new-image")
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts/release-build.json").write_text(json.dumps(record, indent=2) + "\n")
    verify(ROOT, require_committed=export.commit is not None)
    with (output / "artifact-ready.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/check_artifact_ready.py"), str(output / "artifact-ready.json")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    (output / "build-evidence.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.receipt, args.output)