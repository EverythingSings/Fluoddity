"""Run Rust unit tests for the native Rust/wgpu runtime and write reports."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from native_runtime_tools import RUNTIME_MANIFEST


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_rust_tests.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_rust_tests.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run native Rust/wgpu unit tests.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Rust Tests",
        "",
        f"- Status: {payload['status']}",
        f"- Command: `{payload['command']}`",
        f"- Seconds: {float(payload['seconds']):.2f}",
        "",
        "## Output",
        "",
    ]
    stdout_tail = str(payload.get("stdout_tail", ""))
    stderr_tail = str(payload.get("stderr_tail", ""))
    if stdout_tail:
        lines.extend(["```text", stdout_tail, "```", ""])
    if stderr_tail:
        lines.extend(["## Stderr", "", "```text", stderr_tail, "```", ""])
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    command = ["cargo", "test", "--manifest-path", str(RUNTIME_MANIFEST)]
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.perf_counter() - started
    payload = {
        "schema": "fluoddity.native_rust_tests.v1",
        "status": "pass" if proc.returncode == 0 else "fail",
        "command": subprocess.list2cmdline(command),
        "returncode": proc.returncode,
        "seconds": elapsed,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-80:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-80:]),
        "note": "Rust unit tests cover native parser/contract behavior inside the replacement runtime crate.",
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_rust_tests_status={payload['status']}")
    print(f"native_rust_tests_markdown={resolve(args.markdown)}")
    print(f"native_rust_tests_json={resolve(args.json_output)}")
    return 0 if proc.returncode == 0 else proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
