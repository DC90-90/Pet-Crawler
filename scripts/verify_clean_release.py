"""Isolated packaging entrypoint. Remote mode proves actual saved blob inclusion.

No source overlay, Git writes, production calls, or working-tree manifests. A
candidate rehearsal is explicit and MUST remain null-SHA/not-ready. Container
checks and managed-pipeline evidence are independent from a clean source build.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from release_source import export_candidate, export_local, export_remote

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    clean = Path(tempfile.mkdtemp(prefix="daleel-packaging-"))
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "clean_root": str(clean),
              "production_pipeline_verified": False, "container_image_verified": False,
              "requested_commit": args.commit, "candidate": args.candidate, "status": "started"}
    try:
        if args.candidate:
            source = export_candidate(ROOT, clean)
        elif args.repository:
            source = export_remote(args.repository, args.branch, args.commit, clean)
        else:
            source = export_local(ROOT, args.commit, clean)
        result.update(source_sha=source.commit, source_evidence=source.evidence, lock_sha256=source.files["frontend/yarn.lock"])
        receipt = output / "source-receipt.json"
        receipt.write_text(json.dumps({"commit": source.commit, "files": source.files, "evidence": source.evidence}, indent=2) + "\n")
        driver = clean / "scripts/build_release.py"
        if not driver.is_file():
            raise RuntimeError("Saved commit has no corrected build driver; cannot overlay newer build code onto saved source")
        # No fallback to workspace build code. Even scripts come from the saved export.
        with (output / "build-driver.log").open("w") as log:
            subprocess.run([sys.executable, str(driver), "--receipt", str(receipt), "--output", str(output)], cwd=clean, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, check=True)
        evidence = json.loads((output / "build-evidence.json").read_text())
        result.update(release_id=evidence["release_id"], versions=evidence["versions"], build_context=evidence["build_context"],
                      source_build="passed", ready=json.loads((output / "artifact-ready.json").read_text()))
        if args.containers:
            engine = shutil.which("docker") or shutil.which("podman")
            if not engine:
                result["container_check"] = "unverified-no-container-engine"
            elif not source.commit:
                result["container_check"] = "blocked-uncommitted-candidate"
            else:
                with (output / "container-build.log").open("w") as log:
                    for name in ("backend", "frontend"):
                        subprocess.run([engine, "build", "--iidfile", str(output / (name + "-image-id.txt")), "-f", "deploy/" + name + ".Dockerfile", "."], cwd=clean, stdout=log, stderr=subprocess.STDOUT, check=True)
                result["container_image_verified"] = True
        result["status"] = "passed-candidate-rehearsal" if args.candidate else "passed-saved-source-build"
    except Exception as exc:
        result.update(status="failed", error=str(exc))
        raise
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--commit")
    mode.add_argument("--candidate", action="store_true")
    parser.add_argument("--repository", help="Public GitHub owner/repo; require exact branch/SHA and blob verification")
    parser.add_argument("--branch")
    parser.add_argument("--output", type=Path, required=True, help="New directory, never overwrite earlier failed evidence")
    parser.add_argument("--containers", action="store_true")
    args = parser.parse_args()
    if args.repository and (not args.commit or not args.branch):
        parser.error("Remote verification requires --commit and --branch")
    run(args)