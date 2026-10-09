"""Read-only Git/remote export, with blob-level verification; never git add/push."""
import io
import json
import re
import shutil
import subprocess
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from hashlib import sha1

from stamp_release import source_files


@dataclass(frozen=True)
class Export:
    root: Path
    commit: str | None
    files: dict
    evidence: dict


def extract(data, destination, strip_prefix=False):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts[1:] if strip_prefix else Path(member.name).parts
            if not parts:
                continue
            rel = Path(*parts)
            if rel.is_absolute() or ".." in rel.parts or member.issym() or member.islnk():
                raise ValueError("Unsafe source archive member")
            if member.isdir():
                (destination / rel).mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path = destination / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.extractfile(member).read())
                path.chmod(member.mode & 0o777)
            else:
                raise ValueError("Unsupported source archive member")


def export_local(repo, ref, destination):
    commit = subprocess.check_output(["git", "rev-parse", "--verify", ref + "^{commit}"], cwd=repo, text=True).strip()
    data = subprocess.check_output(["git", "archive", "--format=tar", commit], cwd=repo)
    extract(data, destination)
    # Reject missing lock before generating any manifest. Do not copy it from workspace.
    files = source_files(destination)
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", commit], cwd=repo).split(b"\0")
    blobs = {entry.split(b"\t", 1)[1].decode(): entry.split(b"\t", 1)[0].split()[2].decode() for entry in tree if entry}
    verify_blobs(destination, files, blobs)
    return Export(destination, commit, files, {"method": "local-git-archive", "remote_verified": False})


def verify_blobs(root, files, blobs):
    for name in files:
        data = (root / name).read_bytes()
        actual = sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if blobs.get(name) != actual:
            raise ValueError(f"Saved Git blob mismatch or missing input: {name}")


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Daleel-read-only-release-verifier", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def export_remote(repository, branch, commit, destination):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Exact repository and 40-character saved SHA required")
    refs = subprocess.check_output(["git", "ls-remote", "https://github.com/" + repository + ".git", "refs/heads/" + branch], text=True).split()
    if not refs or refs[0] != commit:
        raise ValueError("Requested remote branch is not at the supplied saved SHA; stop and reconcile newer changes")
    base = "https://api.github.com/repos/" + repository
    tree = json.loads(get(base + "/git/trees/" + commit + "?recursive=1"))
    if tree.get("truncated"):
        raise ValueError("Truncated remote tree is insufficient evidence")
    blobs = {item["path"]: item["sha"] for item in tree["tree"] if item["type"] == "blob"}
    if "frontend/yarn.lock" not in blobs:
        raise ValueError("Actual remote commit omits frontend/yarn.lock; Save to GitHub inclusion gate FAILED")
    extract(get("https://codeload.github.com/" + repository + "/tar.gz/" + commit), destination, True)
    files = source_files(destination)
    verify_blobs(destination, files, blobs)
    return Export(destination, commit, files, {"method": "remote-commit-archive", "remote_verified": True,
                  "repository": repository, "branch": branch, "lock_git_blob": blobs["frontend/yarn.lock"],
                  "lock_sha256": files["frontend/yarn.lock"], "remote_tree_truncated": False})


def export_candidate(repo, destination):
    from release_contract import INPUT_ROOTS, ROOT_INPUTS, excluded
    for folder in INPUT_ROOTS:
        for p in (repo / folder).rglob("*"):
            rel = p.relative_to(repo)
            if excluded(rel):
                continue
            if p.is_symlink():
                raise ValueError("Symlink in candidate inputs")
            if p.is_file():
                target = destination / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, target)
    for name in ROOT_INPUTS:
        if (repo / name).is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(repo / name, target)
    return Export(destination, None, source_files(destination), {"method": "candidate-copy", "remote_verified": False})