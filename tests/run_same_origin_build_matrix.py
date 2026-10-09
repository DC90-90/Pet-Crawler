from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/app")
FRONTEND = ROOT / "frontend"
OUT = ROOT / "test_reports" / "same_origin_build_fix" / "matrix-attempt-02"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def build_assets_hash(frontend_root: Path) -> dict:
    build = frontend_root / "build"
    files = {}
    for p in sorted(build.rglob("*")):
        if p.is_file():
            files[p.relative_to(build).as_posix()] = file_sha(p)
    digest = sha256_bytes(json.dumps(files, sort_keys=True).encode())
    return {"count": len(files), "digest": digest, "files": files}


def read_origin_from_frontend_env() -> str:
    for line in (FRONTEND / ".env").read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise RuntimeError("Missing non-empty REACT_APP_BACKEND_URL in frontend/.env")


def copy_frontend_without_dotenv(dst: Path) -> Path:
    target = dst / "frontend"
    shutil.copytree(
        FRONTEND,
        target,
        ignore=shutil.ignore_patterns(".env", ".env.*", "build", "node_modules", "*.log"),
    )
    return target


def run_cmd(cmd: list[str], cwd: Path, env: dict[str, str], log_file: Path) -> int:
    with log_file.open("w") as log:
        process = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    return process.returncode


def assert_no_generated_manifests(frontend_root: Path) -> dict:
    checks = {
        "frontend_public_release_json_exists": (frontend_root / "public/release.json").exists(),
        "root_backend_release_build_json_exists": (frontend_root.parent / "backend/release_build.json").exists(),
    }
    return checks


def run_case(case_name: str, workspace_root: Path, configure, install: bool, reuse: str | None, explicit_origin: str | None) -> dict:
    case_dir = OUT / case_name
    case_dir.mkdir(parents=True, exist_ok=False)
    frontend_root = workspace_root / "frontend"
    env = dict(os.environ)
    env.pop("REACT_APP_BACKEND_URL", None)
    if explicit_origin is not None:
        env["REACT_APP_BACKEND_URL"] = explicit_origin
    configure(frontend_root)

    commands = []
    if install:
        install_cmd = ["yarn", "install", "--prefer-offline"]
        commands.append(install_cmd)
        install_rc = run_cmd(install_cmd, frontend_root, env, case_dir / "yarn-install.log")
        if install_rc != 0:
            return {"name": case_name, "status": "failed", "failed_step": "install", "returncode": install_rc, "commands": commands}

    build_cmd = ["yarn", "build"]
    commands.append(build_cmd)
    build_rc = run_cmd(build_cmd, frontend_root, env, case_dir / "yarn-build.log")
    result = {
        "name": case_name,
        "status": "passed" if build_rc == 0 else "failed",
        "returncode": build_rc,
        "commands": commands,
        "cwd": str(frontend_root),
        "dependency_tree_reuse": reuse,
    }
    if build_rc == 0:
        receipt = json.loads((frontend_root / "build/build-provenance.json").read_text())
        result.update(
            receipt_schema=receipt.get("receipt_schema"),
            api_mode=receipt.get("api_mode"),
            api_origin=receipt.get("api_origin"),
            manifest_verified=receipt.get("manifest_verified"),
            git_commit=receipt.get("git_commit"),
            release_id=receipt.get("release_id"),
            lock_sha256=receipt.get("lock_sha256"),
            frontend_content_sha256=receipt.get("frontend_content_sha256"),
            assets=build_assets_hash(frontend_root),
            generated_manifest_checks=assert_no_generated_manifests(frontend_root),
        )
    return result


def main():
    if OUT.exists():
        raise RuntimeError(f"Output already exists: {OUT}")
    OUT.mkdir(parents=True, exist_ok=False)
    explicit_origin = read_origin_from_frontend_env()
    approved_lock = json.loads((ROOT / "test_reports/same_origin_build_fix/protected-inputs-before.json").read_text())["frontend/yarn.lock"]

    matrix_root = Path(tempfile.mkdtemp(prefix="same-origin-matrix-"))
    matrix_frontend = copy_frontend_without_dotenv(matrix_root)

    def cfg_a(frontend_root: Path):
        for p in frontend_root.glob(".env*"):
            p.unlink()
        (frontend_root / ".env").write_text("REACT_APP_BACKEND_URL=\n")

    def cfg_b(frontend_root: Path):
        for p in frontend_root.glob(".env*"):
            p.unlink()

    def cfg_c(frontend_root: Path):
        for p in frontend_root.glob(".env*"):
            p.unlink()

    case_a = run_case("case_a_empty_dotenv", matrix_root, cfg_a, install=True, reuse=None, explicit_origin=None)
    case_b = run_case("case_b_unset_no_dotenv", matrix_root, cfg_b, install=False, reuse="case_a_empty_dotenv/node_modules", explicit_origin=None)
    case_c = run_case("case_c_explicit_origin", matrix_root, cfg_c, install=False, reuse="case_a_empty_dotenv/node_modules", explicit_origin=explicit_origin)

    # Full-tree managed empty-origin build (backend/scripts present; no release manifests)
    full_root = Path(tempfile.mkdtemp(prefix="same-origin-fulltree-"))
    copy_frontend_without_dotenv(full_root)
    shutil.copytree(ROOT / "backend", full_root / "backend", ignore=shutil.ignore_patterns(".env", "release_build.json", "__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "scripts", full_root / "scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    def cfg_full(frontend_root: Path):
        for p in frontend_root.glob(".env*"):
            p.unlink()
        (frontend_root / ".env").write_text("REACT_APP_BACKEND_URL=\n")
        release_json = frontend_root / "public/release.json"
        if release_json.exists():
            release_json.unlink()
        backend_manifest = frontend_root.parent / "backend/release_build.json"
        if backend_manifest.exists():
            backend_manifest.unlink()

    full_case = run_case("case_d_fulltree_empty_dotenv", full_root, cfg_full, install=True, reuse=None, explicit_origin=None)

    report = {
        "at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(ROOT),
        "source_dotenv_copied": False,
        "matrix_workspace": str(matrix_root),
        "fulltree_workspace": str(full_root),
        "explicit_origin_source": "/app/frontend/.env",
        "approved_lock_sha256": approved_lock,
        "cases": [case_a, case_b, case_c, full_case],
        "all_passed": all(c.get("returncode") == 0 for c in [case_a, case_b, case_c, full_case]),
        "lock_hash_unchanged": all(c.get("lock_sha256") == approved_lock for c in [case_a, case_b, case_c, full_case] if c.get("returncode") == 0),
    }
    (OUT / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"all_passed": report["all_passed"], "output": str(OUT / 'result.json')}, indent=2))


if __name__ == "__main__":
    main()
