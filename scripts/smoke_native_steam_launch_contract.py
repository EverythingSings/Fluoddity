"""Validate the native package's Steam launch target contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE_DIR = ROOT / "dist" / "FluoddityNative"
DEFAULT_JSON = ROOT / "artifacts" / "native_steam_launch_contract.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_steam_launch_contract.md"
WINDOWS_EXE = "XenocultureTrialDish.exe"
LINUX_EXE = "XenocultureTrialDish"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate native Steam launch target contract.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR, help="Native package directory.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def shell_command_block(text: str, command: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith(command):
            continue
        block = [line]
        while block[-1].rstrip().endswith("\\") and index + len(block) < len(lines):
            block.append(lines[index + len(block)])
        return "\n".join(block)
    return ""


def validate_package_contract(package_dir: Path) -> tuple[list[dict], list[str]]:
    failures: list[str] = []
    targets: list[dict] = []
    windows_exe = package_dir / WINDOWS_EXE
    windows_wrapper = package_dir / "run_steam_deck.ps1"
    deck_wrapper = package_dir / "run_steam_deck.sh"
    package_deck_script = ROOT / "runtime" / "rust-wgpu-spike" / "scripts" / "package-deck.sh"
    package_windows_script = ROOT / "runtime" / "rust-wgpu-spike" / "scripts" / "package-windows.ps1"

    windows_wrapper_text = read_text(windows_wrapper)
    deck_wrapper_text = read_text(deck_wrapper)
    deck_script_text = read_text(package_deck_script)
    windows_script_text = read_text(package_windows_script)
    deck_copy_command = (
        "cp runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike "
        f'"$PACKAGE_ROOT/{LINUX_EXE}"'
    )
    deck_chmod_block = shell_command_block(deck_script_text, "chmod +x")
    deck_script_creates_target = deck_copy_command in deck_script_text
    deck_script_marks_executable = f'"$PACKAGE_ROOT/{LINUX_EXE}"' in deck_chmod_block

    require(package_dir.exists(), f"missing package directory: {package_dir}", failures)
    require(windows_exe.exists() and windows_exe.stat().st_size > 0, f"missing Steam-facing Windows executable: {WINDOWS_EXE}", failures)
    require(windows_wrapper.exists(), "missing Windows Steam launch wrapper", failures)
    require(deck_wrapper.exists(), "missing Deck/Linux Steam launch wrapper", failures)
    require(WINDOWS_EXE in windows_wrapper_text, "Windows launch wrapper should call XenocultureTrialDish.exe", failures)
    require("--window" in windows_wrapper_text, "Windows launch wrapper should open the native window", failures)
    require("--deck-profile" not in windows_wrapper_text, "Windows launch wrapper should not use deck-profile timing mode", failures)
    require("--max-window-frames" not in windows_wrapper_text, "Windows launch wrapper should not have a bounded frame count", failures)
    require("python" not in windows_wrapper_text.lower(), "Windows launch wrapper should not call Python", failures)

    require(LINUX_EXE in deck_wrapper_text, "Deck/Linux launch wrapper should prefer XenocultureTrialDish", failures)
    require("--window" in deck_wrapper_text, "Deck/Linux launch wrapper should open the native window", failures)
    require("--deck-profile" not in deck_wrapper_text, "Deck/Linux launch wrapper should not use deck-profile timing mode", failures)
    require("--max-window-frames" not in deck_wrapper_text, "Deck/Linux launch wrapper should not have a bounded frame count", failures)
    require("python" not in deck_wrapper_text.lower(), "Deck/Linux launch wrapper should not call Python", failures)
    require("fluoddity-wgpu-spike" not in deck_wrapper_text, "Deck/Linux launch wrapper should not fall back to the compatibility binary", failures)
    require("package-deck.sh" in deck_wrapper_text, "Deck/Linux launch wrapper should tell testers to build the Deck package when the product alias is missing", failures)

    require(deck_script_creates_target, "Deck package script should copy XenocultureTrialDish", failures)
    require("exec ./XenocultureTrialDish" in deck_script_text, "Deck package script should launch XenocultureTrialDish", failures)
    require(
        deck_script_marks_executable,
        "Deck package script should mark XenocultureTrialDish executable",
        failures,
    )
    require(f'$steamExeName = "{WINDOWS_EXE}"' in windows_script_text, "Windows package script should define Steam-facing exe alias", failures)

    targets.append(
        {
            "platform": "windows_or_proton",
            "working_directory": rel(package_dir),
            "steam_launch_target": WINDOWS_EXE,
            "steam_launch_arguments": "--trial artifacts/trial_definitions.json --trial-id rival_bloom --config physics_configs/Core/Bubbles.json --window",
            "wrapper": "run_steam_deck.ps1",
            "wrapper_uses_target": WINDOWS_EXE in windows_wrapper_text,
            "python_free": "python" not in windows_wrapper_text.lower(),
            "bounded_smoke": "--max-window-frames" in windows_wrapper_text or "--deck-profile" in windows_wrapper_text,
        }
    )
    targets.append(
        {
            "platform": "steam_deck_linux",
            "working_directory": rel(package_dir),
            "steam_launch_target": f"./{LINUX_EXE}",
            "steam_launch_arguments": "--trial artifacts/trial_definitions.json --trial-id rival_bloom --config physics_configs/Core/Bubbles.json --window",
            "wrapper": "run_steam_deck.sh",
            "wrapper_uses_target": LINUX_EXE in deck_wrapper_text and "exec" in deck_wrapper_text,
            "python_free": "python" not in deck_wrapper_text.lower(),
            "bounded_smoke": "--max-window-frames" in deck_wrapper_text or "--deck-profile" in deck_wrapper_text,
            "compatibility_fallback": "fluoddity-wgpu-spike" in deck_wrapper_text,
            "package_contains_target": (package_dir / LINUX_EXE).exists(),
            "package_script_creates_target": deck_script_creates_target,
            "package_script_marks_executable": deck_script_marks_executable,
        }
    )
    return targets, failures


def write_reports(payload: dict, json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Native Steam Launch Contract",
        "",
        f"- Status: {payload['status']}",
        f"- Package: `{payload['package_dir']}`",
        "- Scope: package-local native Steam launch target, not Steamworks upload confirmation",
        "",
        "## Targets",
        "",
        "| Platform | Working directory | Target | Arguments | Wrapper | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for target in payload["targets"]:
        status = (
            "pass"
            if target["wrapper_uses_target"]
            and target["python_free"]
            and not target["bounded_smoke"]
            and not target.get("compatibility_fallback", False)
            else "fail"
        )
        lines.append(
            f"| {target['platform']} | `{target['working_directory']}` | `{target['steam_launch_target']}` | "
            f"`{target['steam_launch_arguments']}` | `{target['wrapper']}` | {status} |"
        )
        if target["platform"] == "steam_deck_linux" and not target.get("package_contains_target"):
            lines.append(
                "- Deck/Linux target binary is not present in this Windows-built package; "
                "build with `runtime/rust-wgpu-spike/scripts/package-deck.sh` on Linux/Steam Deck for the actual Deck artifact."
            )
    if payload["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in payload["failures"])
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = resolve(args.package_dir)
    targets, failures = validate_package_contract(package_dir)
    payload = {
        "schema": "fluoddity.native_steam_launch_contract.v1",
        "status": "pass" if not failures else "fail",
        "package_dir": rel(package_dir),
        "targets": targets,
        "failures": failures,
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_steam_launch_contract_status={payload['status']}")
    print(f"native_steam_launch_contract_markdown={resolve(args.markdown)}")
    print(f"native_steam_launch_contract_json={resolve(args.json_output)}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
