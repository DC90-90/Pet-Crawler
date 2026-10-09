"""Stamp only a verified exported source, never label a working tree with a SHA."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from release_contract import source_files, make_manifest


def stamp(export, context):
    # The exporter owns commit provenance. A source mutation invalidates its receipt.
    files = source_files(export.root)
    if files != export.files:
        raise ValueError("Export changed before stamping; refusing source SHA attribution")
    manifest = make_manifest(files, export.commit, context)
    for name in ("backend/release_build.json", "frontend/public/release.json"):
        path = export.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


if __name__ == "__main__":
    raise SystemExit("Use scripts/verify_clean_release.py --commit REF (or --candidate). Direct workspace stamping is forbidden.")