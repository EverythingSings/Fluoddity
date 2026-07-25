"""Small helpers for stamping generated validation artifacts."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str | None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes | None:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _dirty_fingerprint(root: Path) -> str:
    """Fingerprint tracked diffs plus every non-ignored untracked file."""
    digest = hashlib.sha256()
    tracked_diff = _git_bytes(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--")
    digest.update(b"tracked\0")
    digest.update(tracked_diff or b"")

    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z") or b""
    for encoded_path in sorted(path for path in untracked.split(b"\0") if path):
        digest.update(b"\0untracked\0")
        digest.update(encoded_path)
        digest.update(b"\0")
        path = root / encoded_path.decode("utf-8", errors="surrogateescape")
        try:
            digest.update(path.read_bytes())
        except OSError as exc:
            digest.update(f"<unreadable:{type(exc).__name__}>".encode("ascii"))
    return digest.hexdigest()[:12]


def current_build_id(root: Path) -> str:
    """Return a compact git build label for hardware/test reports."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return "not-a-git-worktree"

    branch = _git(root, "branch", "--show-current") or "detached"
    commit = _git(root, "rev-parse", "--short=12", "HEAD") or "unknown"
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all") or ""
    tree_state = "dirty" if status else "clean"
    changed_count = len(status.splitlines()) if status else 0
    suffix = (
        f"; {changed_count} changed paths; content {_dirty_fingerprint(root)}"
        if changed_count
        else ""
    )
    return f"{branch}@{commit} ({tree_state}{suffix})"
