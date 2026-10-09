"""Content identity is never inferred from a possibly dirty Git HEAD."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def backend_files(root=ROOT):
    files = [p for p in root.rglob("*.py") if not any(x in p.parts for x in ("tests", "__pycache__", ".venv", "venv"))]
    files += [root / "requirements.txt"]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.is_file()}


def identity():
    path = ROOT / "release_build.json"
    return _identity(path.stat().st_mtime_ns if path.exists() else None)


@lru_cache(maxsize=1)
def _identity(stamp_mtime):
    actual = backend_files()
    path = ROOT / "release_build.json"
    if path.exists():
        stamp = json.loads(path.read_text())
        valid = stamp.get("backend_files") == actual
        return {"release_id": stamp["release_id"], "git_commit": stamp.get("git_commit"),
                "source_state": stamp.get("source_state"), "manifest_verified": valid,
                "scheduler_protocol": "fenced-platform-cron-v1", "schema_protocol": "offers-v2-ledger-receipts-v2"}
    digest = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
    return {"release_id": "workspace-" + digest, "git_commit": None, "source_state": "unstamped-workspace",
            "manifest_verified": False, "scheduler_protocol": "fenced-platform-cron-v1", "schema_protocol": "offers-v2-ledger-receipts-v2"}