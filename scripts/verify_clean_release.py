"""Clean-source rehearsal without starting the application or accessing Mongo.

--commit REF exports EXACT Git contents (and fails if lockfile was not saved).
Without --commit this verifies an uncommitted candidate, not a Git release.
Docker/managed pipeline proof is recorded separately, never inferred from yarn.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from stamp_release import stamp

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    output = ROOT / "test_reports/release_build"
    output.mkdir(parents=True, exist_ok=True)
    clean = Path(tempfile.mkdtemp(prefix="daleel-clean-release-"))
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "source": args.commit or "uncommitted-candidate",
              "production_pipeline_verified": False, "container_image_verified": False, "clean_root": str(clean)}
    try:
        if args.commit:
            sha = subprocess.check_output(["git", "rev-parse", args.commit], cwd=ROOT, text=True).strip()
            archive = subprocess.Popen(["git", "archive", sha], cwd=ROOT, stdout=subprocess.PIPE)
            subprocess.run(["tar", "-x", "-C", str(clean)], stdin=archive.stdout, check=True)
            archive.stdout.close()
            if archive.wait(): raise RuntimeError("Git archive failed")
            result["source"] = sha
        else:
            for folder in ("backend", "frontend", "deploy", "scripts", ".emergent"):
                shutil.copytree(ROOT / folder, clean / folder, ignore=shutil.ignore_patterns(
                    "node_modules", "build", ".env", ".env.*", "__pycache__", ".cache", ".venv", "venv", "*.log", "release_build.json", "release.json", "cron"))
        if not (clean / "frontend/yarn.lock").is_file():
            raise RuntimeError("Release source has no frontend/yarn.lock; save it before claiming committed-build proof")
        manifest = stamp(clean, result["source"] if args.commit else None)
        result.update({k: manifest[k] for k in ("release_id", "lock_sha256")})
        result["node"] = subprocess.check_output(["node", "--version"], text=True).strip()
        result["yarn"] = subprocess.check_output(["yarn", "--version"], text=True).strip()
        if not result["node"].startswith("v20."):
            raise RuntimeError("Use Node20, matching deploy/frontend.Dockerfile; refusing different-major proof")
        env = dict(os.environ)
        from dotenv import dotenv_values
        env["REACT_APP_BACKEND_URL"] = dotenv_values(ROOT / "frontend/.env")["REACT_APP_BACKEND_URL"]
        env.pop("CI", None)  # The committed Docker build does not set CI/Werror.
        env["NODE_OPTIONS"] = "--max-old-space-size=4096"
        before = hashlib.sha256((clean / "frontend/yarn.lock").read_bytes()).hexdigest()
        with (output / "frontend-install.log").open("w") as log:
            subprocess.run(["yarn", "install", "--frozen-lockfile", "--non-interactive", "--cache-folder", str(clean / "yarn-cache")], cwd=clean / "frontend", env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (output / "frontend-build.log").open("w") as log:
            subprocess.run(["yarn", "build"], cwd=clean / "frontend", env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        assert before == hashlib.sha256((clean / "frontend/yarn.lock").read_bytes()).hexdigest()
        artifact = json.loads((clean / "frontend/build/release.json").read_text())
        assert artifact["release_id"] == manifest["release_id"]
        result.update(frontend_clean_build="passed", frozen_lock_unchanged=True, frontend_backend_manifest_match=True)
        engine = shutil.which("docker") or shutil.which("podman")
        if args.containers:
            if not engine: raise RuntimeError("No container engine: production-container gate is unverified")
            with (output / "container-build.log").open("w") as log:
                for name in ("backend", "frontend"):
                    command = [engine, "build", "-f", f"deploy/{name}.Dockerfile", "-t", f"daleel-rehearsal-{name}:{manifest['release_id'][7:19]}"]
                    if name == "frontend": command += ["--build-arg", "REACT_APP_BACKEND_URL="+env["REACT_APP_BACKEND_URL"]]
                    subprocess.run(command+["."], cwd=clean, stdout=log, stderr=subprocess.STDOUT, check=True)
            result["container_image_verified"] = True
        result["status"] = "passed-clean-source-build"
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(result, indent=2)+"\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit")
    parser.add_argument("--containers", action="store_true")
    run(parser.parse_args())