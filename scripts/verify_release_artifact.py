"""Verify prepared source + compiled assets before any container consumes them."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from release_contract import digest, load_and_verify


def asset_hashes(root):
    base = root / "frontend/build"
    return {p.relative_to(base).as_posix(): digest(p.read_bytes()) for p in sorted(base.rglob("*")) if p.is_file()}


def compiled_origin(root, origin):
    matches = []
    for p in (root / "frontend/build/static/js").glob("*.js"):
        if origin in p.read_text():
            matches.append(p.relative_to(root / "frontend/build").as_posix())
    if not matches:
        raise ValueError("Expected API origin not found in emitted JavaScript")
    return matches


def verify(root=ROOT, require_committed=False, compiled=True):
    manifest = load_and_verify(root, require_committed)
    if compiled:
        build = json.loads((root / "artifacts/release-build.json").read_text())
        for key in ("release_id", "git_commit", "lock_sha256", "build_context"):
            if build[key] != manifest[key]:
                raise ValueError(f"Build receipt differs from source manifest: {key}")
        if asset_hashes(root) != build["frontend_assets"]:
            raise ValueError("Compiled artifact hashes changed")
        if json.loads((root / "frontend/build/release.json").read_text()) != manifest:
            raise ValueError("Compiled frontend manifest differs from backend")
        compiled_origin(root, manifest["build_context"]["REACT_APP_BACKEND_URL"])
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-committed", action="store_true")
    args = parser.parse_args()
    result = verify(require_committed=args.require_committed)
    print(json.dumps({k: result[k] for k in ("release_id", "git_commit", "lock_sha256", "source_state")}))