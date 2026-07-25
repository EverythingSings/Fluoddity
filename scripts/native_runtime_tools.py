"""Shared helpers for Rust/wgpu native runtime smoke scripts."""
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MANIFEST = ROOT / "runtime" / "rust-wgpu-spike" / "Cargo.toml"


def native_runtime_candidates() -> list[Path]:
    return [
        ROOT / "runtime" / "rust-wgpu-spike" / "target" / "release" / "fluoddity-wgpu-spike.exe",
        ROOT / "runtime" / "rust-wgpu-spike" / "target" / "release" / "fluoddity-wgpu-spike",
        ROOT / "artifacts" / "native-wgpu" / "fluoddity-wgpu-spike.exe",
    ]


def native_runtime_binary() -> Path:
    existing = [path for path in native_runtime_candidates() if path.exists()]
    if not existing:
        return native_runtime_candidates()[0]
    return max(existing, key=lambda path: path.stat().st_mtime)


def build_native_runtime() -> None:
    subprocess.run(
        ["cargo", "build", "--manifest-path", str(RUNTIME_MANIFEST), "--release"],
        cwd=ROOT,
        check=True,
    )
