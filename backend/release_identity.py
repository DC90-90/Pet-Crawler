"""Content identity is never inferred from a possibly dirty Git HEAD."""
import json
from pathlib import Path
from release_contract import canonical, digest, tree_files, validate_manifest

ROOT = Path(__file__).resolve().parent


def backend_files(root=None):
    return tree_files(ROOT if root is None else root, "backend/")


def identity():
    # No manifest-mtime-only cache: code/data/requirements may change independently.
    return _identity()


def _identity():
    actual = backend_files()
    path = ROOT / "release_build.json"
    if path.exists():
        try:
            stamp = validate_manifest(json.loads(path.read_text()))
            return {"release_id": stamp["release_id"], "git_commit": stamp["git_commit"],
                    "source_state": stamp["source_state"], "manifest_verified": stamp["backend_files"] == actual,
                    "scheduler_protocol": "fenced-platform-cron-v1", "schema_protocol": "offers-v2-ledger-receipts-v2"}
        except (ValueError, KeyError, TypeError):
            pass  # Malformed/stale manifests must never grant readiness or writer ownership.
    return {"release_id": "workspace-" + digest(canonical(actual)), "git_commit": None, "source_state": "unstamped-workspace",
            "manifest_verified": False, "scheduler_protocol": "fenced-platform-cron-v1", "schema_protocol": "offers-v2-ledger-receipts-v2"}