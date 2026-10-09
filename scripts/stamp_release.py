"""Create non-secret content-addressed backend/frontend release manifests."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from release_identity import backend_files


def stamp(root, commit=None):
    lock = root / "frontend/yarn.lock"
    if not lock.is_file():
        raise SystemExit("Missing required frontend/yarn.lock")
    back = backend_files(root / "backend")
    files = {"backend/"+k: v for k, v in back.items()}
    for folder in (root / "frontend/src", root / "frontend/public", root / "deploy"):
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.name not in {"release.json", ".env", ".env.example"}:
                files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("frontend/package.json", "frontend/yarn.lock", "frontend/craco.config.js", "frontend/tailwind.config.js", "frontend/postcss.config.js", ".emergent/crons.yml"):
        path = root / name
        if path.exists(): files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    release_id = "sha256:" + hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    manifest = {"release_id": release_id, "git_commit": commit, "source_state": "committed-export" if commit else "uncommitted-candidate",
                "backend_files": back, "source_files": files, "lock_sha256": files["frontend/yarn.lock"]}
    (root / "backend/release_build.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)+"\n")
    (root / "frontend/public/release.json").write_text(json.dumps({k: manifest[k] for k in ("release_id", "git_commit", "source_state", "lock_sha256")}, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--commit", help="Only for an immutable clean Git export; never a dirty workspace HEAD")
    args = p.parse_args()
    if args.commit:
        raise SystemExit("Use verify_clean_release.py --commit REF for immutable Git export stamping; never label a workspace as committed")
    result = stamp(args.root, args.commit)
    print(json.dumps({k: result[k] for k in ("release_id", "git_commit", "source_state", "lock_sha256")}))