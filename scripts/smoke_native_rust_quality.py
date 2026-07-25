"""Run Rust formatting and lint checks for the native Rust/wgpu runtime."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from native_runtime_tools import RUNTIME_MANIFEST


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_rust_quality.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_rust_quality.md"

CHECKS = [
    {
        "id": "rustfmt",
        "command": ["cargo", "fmt", "--manifest-path", str(RUNTIME_MANIFEST), "--", "--check"],
    },
    {
        "id": "clippy",
        "command": ["cargo", "clippy", "--manifest-path", str(RUNTIME_MANIFEST), "--", "-D", "warnings"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run native Rust/wgpu format and lint checks.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def run_check(check: dict[str, object]) -> dict[str, object]:
    command = check["command"]
    assert isinstance(command, list)
    started = time.perf_counter()
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.perf_counter() - started
    return {
        "id": check["id"],
        "command": subprocess.list2cmdline(command),
        "status": "pass" if proc.returncode == 0 else "fail",
        "returncode": proc.returncode,
        "seconds": elapsed,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-60:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-60:]),
    }


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Rust Quality",
        "",
        f"- Status: {payload['status']}",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        lines.append(
            f"- `{check['id']}`: {check['status']} "
            f"(returncode={check['returncode']}, seconds={float(check['seconds']):.2f})"
        )
        if check["status"] != "pass":
            if check.get("stdout_tail"):
                lines.extend(["", "```text", str(check["stdout_tail"]), "```"])
            if check.get("stderr_tail"):
                lines.extend(["", "```text", str(check["stderr_tail"]), "```"])
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    checks = [run_check(check) for check in CHECKS]
    passed = [check for check in checks if check["status"] == "pass"]
    payload = {
        "schema": "fluoddity.native_rust_quality.v1",
        "status": "pass" if len(passed) == len(checks) else "fail",
        "check_count": len(checks),
        "passed_check_count": len(passed),
        "checks": checks,
        "note": "Rust formatting and clippy checks for native replacement runtime quality.",
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_rust_quality_status={payload['status']}")
    print(f"native_rust_quality_markdown={resolve(args.markdown)}")
    print(f"native_rust_quality_json={resolve(args.json_output)}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
