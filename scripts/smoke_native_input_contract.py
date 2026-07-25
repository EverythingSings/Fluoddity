"""Validate the Rust/wgpu native runtime's controller input contract."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from native_runtime_tools import build_native_runtime, native_runtime_binary

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_input_contract.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_input_contract.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke the native Rust/wgpu controller input contract.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON contract path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument(
        "--binary-output",
        type=Path,
        default=ROOT / "artifacts" / "native-wgpu" / "fluoddity-wgpu-spike.exe",
        help="Runnable copied/signed binary path.",
    )
    parser.add_argument("--no-sign", action="store_true", help="Skip local Windows code signing.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def prepare_binary(output: Path, no_sign: bool) -> Path:
    source = native_runtime_binary()
    if not source.exists():
        raise RuntimeError(f"native runtime binary not found: {source}")
    output = resolve(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == output.resolve():
        return output
    if output.suffix.lower() == ".exe":
        copy_and_sign = (
            "$ErrorActionPreference='Stop';"
            "$source=$env:FLUODDITY_SOURCE_PATH;"
            "$path=$env:FLUODDITY_SIGN_PATH;"
            "Copy-Item -Force -LiteralPath $source -Destination $path;"
        )
        if not no_sign:
            copy_and_sign += (
                "$cert=Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | "
                "Where-Object { $_.Subject -eq 'CN=Dissipa Local Developer Code Signing' } | "
                "Select-Object -First 1;"
                "if ($null -eq $cert) { "
                "$cert=Get-ChildItem Cert:\\CurrentUser\\My -CodeSigningCert | Select-Object -First 1 "
                "};"
                "if ($null -ne $cert) { "
                "Set-AuthenticodeSignature -FilePath $path -Certificate $cert "
                "-TimestampServer 'http://timestamp.digicert.com' | Out-Null "
                "}"
            )
        sign_proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                copy_and_sign,
            ],
            cwd=ROOT,
            env={
                **os.environ,
                "FLUODDITY_SOURCE_PATH": str(source),
                "FLUODDITY_SIGN_PATH": str(output),
            },
            text=True,
            capture_output=True,
        )
        if sign_proc.returncode != 0:
            raise RuntimeError(f"binary copy/sign failed: {sign_proc.stdout}\n{sign_proc.stderr}")
    else:
        shutil.copyfile(source, output)
    return output


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def validate(payload: dict) -> list[str]:
    failures: list[str] = []
    require(payload.get("schema") == "fluoddity.native_input_contract.v1", "schema mismatch", failures)
    require(payload.get("input_backend") == "gilrs", "input backend should be gilrs", failures)
    cursor = payload.get("cursor", {})
    require(cursor.get("axis_x") == "RightStickX", "right stick X axis missing", failures)
    require(cursor.get("axis_y") == "RightStickY", "right stick Y axis missing", failures)
    require(float(cursor.get("deadzone", 0.0)) > 0.0, "deadzone should be explicit", failures)
    require(float(cursor.get("speed_per_frame", 0.0)) > 0.0, "cursor speed should be explicit", failures)

    actions = {action.get("action"): action for action in payload.get("actions", [])}
    require("StartOrResume" in actions, "StartOrResume action missing", failures)
    require("PauseToggle" in actions, "PauseToggle action missing", failures)
    require("ApplyNutrientGel" in actions, "ApplyNutrientGel action missing", failures)
    require("South" in actions.get("StartOrResume", {}).get("buttons", []), "South/A start binding missing", failures)
    pause_buttons = set(actions.get("PauseToggle", {}).get("buttons", []))
    require({"Start", "Mode"}.issubset(pause_buttons), "Start/Menu pause bindings missing", failures)
    apply_buttons = set(actions.get("ApplyNutrientGel", {}).get("buttons", []))
    require(
        {"RightTrigger2", "RightTrigger"}.issubset(apply_buttons),
        "R2/trigger apply bindings missing",
        failures,
    )
    requirements = "\n".join(payload.get("deck_requirements", []))
    for expected in ["Right stick", "R2", "A starts", "Start/Menu", "No text entry"]:
        require(expected in requirements, f"Deck requirement missing: {expected}", failures)
    return failures


def write_markdown(payload: dict, failures: list[str], output: Path) -> None:
    output = resolve(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    actions = payload.get("actions", [])
    cursor = payload.get("cursor", {})
    lines = [
        "# Native Input Contract",
        "",
        f"- Status: {'pass' if not failures else 'fail'}",
        f"- Runtime: {payload.get('runtime', '')}",
        f"- Input backend: {payload.get('input_backend', '')}",
        f"- Cursor axes: {cursor.get('axis_x', '')}, {cursor.get('axis_y', '')}",
        f"- Cursor deadzone: {cursor.get('deadzone', '')}",
        f"- Cursor speed per frame: {cursor.get('speed_per_frame', '')}",
        "",
        "## Actions",
        "",
    ]
    for action in actions:
        lines.append(
            f"- `{action.get('action', '')}`: {', '.join(action.get('buttons', []))} - {action.get('effect', '')}"
        )
    lines.extend(["", "## Deck Requirements", ""])
    lines.extend(f"- {requirement}" for requirement in payload.get("deck_requirements", []))
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    json_output = resolve(args.json_output)
    if not args.no_build:
        build_native_runtime()
    try:
        binary = prepare_binary(args.binary_output, args.no_sign)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    json_output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(binary), "--dump-input-contract", str(json_output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"native input contract dump failed: {proc.stdout}\n{proc.stderr}")
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    failures = validate(payload)
    write_markdown(payload, failures, args.markdown)
    print(f"native_input_contract_status={'pass' if not failures else 'fail'}")
    print(f"native_input_contract_markdown={resolve(args.markdown)}")
    print(f"native_input_contract_json={json_output}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
