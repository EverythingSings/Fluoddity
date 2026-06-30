"""Small helpers for stamping generated validation artifacts."""
from __future__ import annotations

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


def current_build_id(root: Path) -> str:
    """Return a compact git build label for hardware/test reports."""
    inside = _git(root, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return "not-a-git-worktree"

    branch = _git(root, "branch", "--show-current") or "detached"
    commit = _git(root, "rev-parse", "--short=12", "HEAD") or "unknown"
    status = _git(root, "status", "--porcelain") or ""
    tree_state = "dirty" if status else "clean"
    changed_count = len(status.splitlines()) if status else 0
    suffix = f"; {changed_count} changed paths" if changed_count else ""
    return f"{branch}@{commit} ({tree_state}{suffix})"
