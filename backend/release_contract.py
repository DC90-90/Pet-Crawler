"""Standard-library release contract shared by packager and runtime verification.

All files under the input roots count, including plugins, data files, scripts,
tests and Docker/cron configuration. Exclusions are explicit generated/private
content, not an extension allowlist that can silently miss a new input type.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = 2
INPUT_ROOTS = ("backend", "frontend", "scripts", "deploy", ".github")
ROOT_INPUTS = (".dockerignore", ".gitignore", ".gitattributes", ".emergent/crons.yml")
IGNORED_PARTS = {"node_modules", "build", "__pycache__", ".pytest_cache", ".cache", ".venv", "venv", "coverage"}
GENERATED = {"backend/release_build.json", "frontend/public/release.json"}
PAYLOAD_KEYS = ("schema_version", "git_commit", "source_state", "source_files", "build_context")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def excluded(relative):
    p = Path(relative)
    return (bool(set(p.parts) & IGNORED_PARTS) or p.name.startswith(".env")
            or p.suffix in {".pyc", ".log", ".pem", ".key"}
            or p.name in {"credentials.json", "test_credentials.md"}
            or p.as_posix() in GENERATED)


def tree_files(root, prefix=""):
    root = Path(root)
    result = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        qualified = prefix + rel
        if excluded(qualified):
            continue
        if p.is_symlink():
            raise ValueError(f"Symlink not permitted as release input: {qualified}")
        if p.is_file():
            result[rel] = digest(p.read_bytes())
    return result


def source_files(root):
    root = Path(root)
    files = {}
    for folder in INPUT_ROOTS:
        files.update({folder + "/" + k: v for k, v in tree_files(root / folder, folder + "/").items()})
    for name in ROOT_INPUTS:
        p = root / name
        if p.is_symlink():
            raise ValueError(f"Symlink not permitted: {name}")
        if p.is_file():
            files[name] = digest(p.read_bytes())
    if "frontend/yarn.lock" not in files:
        raise ValueError("Missing saved frontend/yarn.lock; dependency re-resolution is forbidden")
    return dict(sorted(files.items()))


def build_context(origin):
    value = urlsplit(origin)
    if value.scheme not in {"http", "https"} or not value.hostname or value.username or value.password or value.query or value.fragment or value.path not in {"", "/"}:
        raise ValueError("REACT_APP_BACKEND_URL must be an explicit HTTP(S) origin without credentials/path/query")
    # These exact public build values are passed to Yarn; ambient REACT_APP_* are removed.
    return {"REACT_APP_BACKEND_URL": origin.rstrip("/"), "REACT_APP_ALLOW_PUBLIC_REGISTRATION": "false",
            "NODE_ENV": "production", "GENERATE_SOURCEMAP": "false", "ENABLE_HEALTH_CHECK": "false", "CI": "false"}


def make_manifest(files, commit, context):
    if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected resolved source commit, not an arbitrary label")
    payload = {"schema_version": SCHEMA, "git_commit": commit,
               "source_state": "committed-export" if commit else "uncommitted-candidate",
               "source_files": files, "build_context": context}
    return {**payload, "release_id": "sha256:" + digest(canonical(payload)),
            "lock_sha256": files["frontend/yarn.lock"],
            "backend_files": {k[8:]: v for k, v in files.items() if k.startswith("backend/")}}


def validate_manifest(manifest, require_committed=False):
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("Missing/current release manifest schema required")
    expected = make_manifest(manifest["source_files"], manifest["git_commit"], manifest["build_context"])
    if manifest != expected:
        raise ValueError("Release manifest identity/content mismatch")
    if require_committed and not manifest["git_commit"]:
        raise ValueError("Committed-export artifact required; candidate cannot be released")
    return manifest


def load_and_verify(root, require_committed=False):
    root = Path(root)
    manifest = validate_manifest(json.loads((root / "backend/release_build.json").read_text()), require_committed)
    if source_files(root) != manifest["source_files"]:
        raise ValueError("Source changed after export/stamping")
    if json.loads((root / "frontend/public/release.json").read_text()) != manifest:
        raise ValueError("Backend/frontend generated manifests disagree")
    return manifest