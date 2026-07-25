"""Run the Rust/wgpu native validation gates in a safe sequential order."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_validation_suite.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_validation_suite.md"


GATES = [
    {
        "id": "rust_quality",
        "command": [
            "scripts/smoke_native_rust_quality.py",
            "--json-output",
            "artifacts/native_rust_quality.json",
            "--markdown",
            "artifacts/native_rust_quality.md",
        ],
        "json": "artifacts/native_rust_quality.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "rust_unit_tests",
        "command": [
            "scripts/smoke_native_rust_tests.py",
            "--json-output",
            "artifacts/native_rust_tests.json",
            "--markdown",
            "artifacts/native_rust_tests.md",
        ],
        "json": "artifacts/native_rust_tests.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "shader_parity",
        "command": [
            "scripts/audit_native_shader_parity.py",
            "--markdown",
            "artifacts/native_shader_parity.md",
            "--json-output",
            "artifacts/native_shader_parity.json",
        ],
        "json": "artifacts/native_shader_parity.json",
        "allowed_statuses": {"incomplete", "complete"},
        "note": "Incomplete is accepted while explicit Python/GLSL parity gaps remain; complete must also remain a passing state.",
    },
    {
        "id": "config_contract",
        "command": [
            "scripts/check_native_config_contract.py",
            "--no-build",
            "--json-output",
            "artifacts/native_config_contract.json",
            "--markdown",
            "artifacts/native_config_contract.md",
        ],
        "json": "artifacts/native_config_contract.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "input_contract",
        "command": [
            "scripts/smoke_native_input_contract.py",
            "--no-build",
            "--json-output",
            "artifacts/native_input_contract.json",
            "--markdown",
            "artifacts/native_input_contract.md",
        ],
        "json": "artifacts/native_input_contract.json",
        "allowed_statuses": {None, "pass"},
    },
    {
        "id": "input_runtime",
        "command": [
            "scripts/smoke_native_input_runtime.py",
            "--no-build",
            "--json-output",
            "artifacts/native_input_runtime.json",
            "--markdown",
            "artifacts/native_input_runtime.md",
        ],
        "json": "artifacts/native_input_runtime.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "trial_matrix",
        "command": [
            "scripts/smoke_native_trial_matrix.py",
            "--no-build",
            "--json-output",
            "artifacts/native_trial_matrix.json",
            "--markdown",
            "artifacts/native_trial_matrix.md",
        ],
        "json": "artifacts/native_trial_matrix.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "preset_matrix",
        "command": [
            "scripts/smoke_native_preset_matrix.py",
            "--no-build",
            "--json-output",
            "artifacts/native_preset_matrix.json",
            "--markdown",
            "artifacts/native_preset_matrix.md",
        ],
        "json": "artifacts/native_preset_matrix.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "rule_sensitivity",
        "command": [
            "scripts/smoke_native_rule_sensitivity.py",
            "--no-build",
            "--json-output",
            "artifacts/native_rule_sensitivity.json",
            "--markdown",
            "artifacts/native_rule_sensitivity.md",
        ],
        "json": "artifacts/native_rule_sensitivity.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "parameter_sensitivity",
        "command": [
            "scripts/smoke_native_parameter_sensitivity.py",
            "--no-build",
            "--json-output",
            "artifacts/native_parameter_sensitivity.json",
            "--markdown",
            "artifacts/native_parameter_sensitivity.md",
        ],
        "json": "artifacts/native_parameter_sensitivity.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "visual_metrics",
        "command": [
            "scripts/compare_native_visual_metrics.py",
            "--run-native",
            "--no-build",
            "--json-output",
            "artifacts/native_visual_metrics.json",
            "--markdown",
            "artifacts/native_visual_metrics.md",
        ],
        "json": "artifacts/native_visual_metrics.json",
        "allowed_statuses": {"compared", "reference-missing"},
    },
    {
        "id": "python_visual_parity",
        "command": [
            "scripts/smoke_native_python_visual_parity.py",
            "--no-build",
            "--json-output",
            "artifacts/native_python_visual_parity.json",
            "--markdown",
            "artifacts/native_python_visual_parity.md",
        ],
        "json": "artifacts/native_python_visual_parity.json",
        "allowed_statuses": {"within-threshold", "measured-drift"},
        "note": "Measured drift is allowed here because exact parity is explicitly not yet claimed.",
    },
    {
        "id": "replay_determinism",
        "command": [
            "scripts/smoke_native_replay_determinism.py",
            "--no-build",
            "--json-output",
            "artifacts/native_replay_determinism.json",
            "--markdown",
            "artifacts/native_replay_determinism.md",
        ],
        "json": "artifacts/native_replay_determinism.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "video_export",
        "command": [
            "scripts/smoke_native_video_export.py",
            "--no-build",
            "--json-output",
            "artifacts/native_video_export_smoke.json",
            "--markdown",
            "artifacts/native_video_export_smoke.md",
        ],
        "json": "artifacts/native_video_export_smoke.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "package_smoke",
        "command": [
            "scripts/smoke_native_package.py",
            "--json-output",
            "artifacts/native_package_smoke.json",
            "--markdown",
            "artifacts/native_package_smoke.md",
            "--package-manifest-json",
            "artifacts/native_package_manifest.json",
            "--package-manifest-markdown",
            "artifacts/native_package_manifest.md",
        ],
        "json": "artifacts/native_package_smoke.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "timing_budget",
        "command": [
            "scripts/smoke_native_timing_budget.py",
            "--timing-report",
            "dist/FluoddityNative/artifacts/wgpu_deck_timing.json",
            "--json-output",
            "artifacts/native_timing_budget.json",
            "--markdown",
            "artifacts/native_timing_budget.md",
        ],
        "json": "artifacts/native_timing_budget.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "steam_input_alignment",
        "command": [
            "scripts/smoke_native_steam_input_alignment.py",
            "--json-output",
            "artifacts/native_steam_input_alignment.json",
            "--markdown",
            "artifacts/native_steam_input_alignment.md",
        ],
        "json": "artifacts/native_steam_input_alignment.json",
        "allowed_statuses": {"pass"},
    },
    {
        "id": "steam_launch_contract",
        "command": [
            "scripts/smoke_native_steam_launch_contract.py",
            "--json-output",
            "artifacts/native_steam_launch_contract.json",
            "--markdown",
            "artifacts/native_steam_launch_contract.md",
        ],
        "json": "artifacts/native_steam_launch_contract.json",
        "allowed_statuses": {"pass"},
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run native Rust/wgpu validation gates sequentially.")
    parser.add_argument("--python", default=sys.executable, help="Python executable for child scripts.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--skip-build", action="store_true", help="Skip the initial native release build.")
    parser.add_argument("--skip-package", action="store_true", help="Skip package-local smoke and dependent package checks.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return resolve(path).relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def run_gate(python: str, gate: dict) -> dict[str, object]:
    started = time.perf_counter()
    command = [python, *gate["command"]]
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    elapsed = time.perf_counter() - started
    json_path = ROOT / gate["json"]
    payload = json.loads(json_path.read_text(encoding="utf-8")) if json_path.exists() else {}
    observed_status = payload.get("status")
    allowed_statuses = gate["allowed_statuses"]
    valid_status = observed_status in allowed_statuses
    passed = proc.returncode == 0 and valid_status
    return {
        "id": gate["id"],
        "command": subprocess.list2cmdline(command),
        "returncode": proc.returncode,
        "seconds": elapsed,
        "json": gate["json"],
        "observed_status": observed_status,
        "allowed_statuses": sorted("missing" if status is None else str(status) for status in allowed_statuses),
        "passed": passed,
        "note": gate.get("note", ""),
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
    }


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Validation Suite",
        "",
        f"- Status: {payload['status']}",
        f"- Native binary: `{payload['native_binary']}`",
        f"- Gates passed: {payload['passed_gate_count']}/{payload['gate_count']}",
        f"- Package gates skipped: {'yes' if payload['package_gates_skipped'] else 'no'}",
        "",
        "## Gates",
        "",
    ]
    for gate in payload["gates"]:
        status = "pass" if gate["passed"] else "fail"
        observed = gate.get("observed_status")
        lines.append(
            f"- `{gate['id']}`: {status} "
            f"(returncode={gate['returncode']}, status={observed}, seconds={float(gate['seconds']):.2f})"
        )
        if gate.get("note"):
            lines.append(f"  - note: {gate['note']}")
        if not gate["passed"]:
            if gate.get("stdout_tail"):
                lines.append(f"  - stdout tail: `{str(gate['stdout_tail']).splitlines()[-1]}`")
            if gate.get("stderr_tail"):
                lines.append(f"  - stderr tail: `{str(gate['stderr_tail']).splitlines()[-1]}`")
    lines.extend(
        [
            "",
            "This suite is local native-runtime evidence. It does not replace Steam Deck hardware validation, Steamworks Steam Input import, or exact Python/GLSL parity work.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.skip_build:
        build_native_runtime()
    gates = [
        gate
        for gate in GATES
        if not args.skip_package
        or gate["id"]
        not in {
            "package_smoke",
            "timing_budget",
            "steam_input_alignment",
            "steam_launch_contract",
        }
    ]
    results = [run_gate(args.python, gate) for gate in gates]
    passed = [result for result in results if result["passed"]]
    payload = {
        "schema": "fluoddity.native_validation_suite.v1",
        "status": "pass" if len(passed) == len(results) else "fail",
        "native_binary": rel(native_runtime_binary()),
        "gate_count": len(results),
        "passed_gate_count": len(passed),
        "package_gates_skipped": args.skip_package,
        "gates": results,
        "note": "Local native validation suite; external Steam Deck and Steamworks gates remain required.",
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_validation_suite_status={payload['status']}")
    print(f"native_validation_suite_passed={payload['passed_gate_count']}/{payload['gate_count']}")
    print(f"native_validation_suite_markdown={resolve(args.markdown)}")
    print(f"native_validation_suite_json={resolve(args.json_output)}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
