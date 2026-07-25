"""Validate scripted native Rust/wgpu controller input state transitions."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from native_runtime_tools import build_native_runtime
from smoke_native_input_contract import prepare_binary


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_input_runtime.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_input_runtime.md"
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
CONFIG_PATH = ROOT / "physics_configs" / "Core" / "Bubbles.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke scripted native input behavior.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH, help="Exported trial definitions JSON.")
    parser.add_argument("--trial-id", default="rival_bloom", help="Trial id for the smoke.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="Native config path.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
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


def write_markdown(payload: dict, failures: list[str], output: Path) -> None:
    output = resolve(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Native Input Runtime Smoke",
        "",
        f"- Status: {'pass' if not failures else 'fail'}",
        f"- Runtime: {payload.get('runtime', '')}",
        f"- Trial: {payload.get('trial_id', '')}",
        f"- Cursor delta X: {payload.get('cursor_delta', {}).get('x', '')}",
        f"- Cursor delta Y: {payload.get('cursor_delta', {}).get('y', '')}",
        "",
        "## Checks",
        "",
    ]
    checks = payload.get("checks", {})
    for name, passed in checks.items():
        lines.append(f"- `{name}`: {'pass' if passed else 'fail'}")
    lines.extend(["", "## Snapshots", ""])
    for snapshot in payload.get("snapshots", []):
        params = snapshot.get("params", {})
        input_state = snapshot.get("input", {})
        actions = snapshot.get("overlay", {}).get("prompt_actions", [])
        action_text = ", ".join(action.get("steam_action", "") for action in actions)
        lines.append(
            f"- `{snapshot.get('label', '')}`: trial={snapshot.get('trial_id', '')} status={snapshot.get('status')} "
            f"params.paused={params.get('paused')} params.applying={params.get('applying')} "
            f"cursor=({input_state.get('cursor_x')}, {input_state.get('cursor_y')}) "
            f"overlay.status=\"{snapshot.get('overlay', {}).get('status', '')}\" "
            f"overlay.prompt=\"{snapshot.get('overlay', {}).get('prompt', '')}\" "
            f"actions=[{action_text}]"
        )
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in failures)
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def validate(payload: dict) -> list[str]:
    failures = []
    if payload.get("schema") != "fluoddity.native_input_runtime_smoke.v1":
        failures.append("schema mismatch")
    checks = payload.get("checks", {})
    for expected in [
        "briefing_starts_paused",
        "south_starts_running",
        "r2_applies_when_running",
        "pause_suppresses_apply",
        "resume_restores_running",
        "right_stick_moves_cursor",
        "result_state_reached",
        "south_next_returns_to_briefing",
        "south_next_advances_trial",
        "final_result_state_reached",
        "final_next_restarts_sequence",
        "result_overlay_names_next_assay",
        "final_overlay_names_sequence_complete",
        "result_overlay_uses_view_exit",
        "prompt_actions_are_structured",
    ]:
        if checks.get(expected) is not True:
            failures.append(f"check failed: {expected}")
    snapshots = {snapshot.get("label"): snapshot for snapshot in payload.get("snapshots", [])}
    if snapshots.get("start_pause_suppresses_apply", {}).get("params", {}).get("applying") != 0:
        failures.append("paused state did not suppress apply param")
    if float(payload.get("cursor_delta", {}).get("x", 0.0)) <= 0.0:
        failures.append("cursor X did not move")
    if float(payload.get("cursor_delta", {}).get("y", 0.0)) <= 0.0:
        failures.append("cursor Y did not move")
    if snapshots.get("result_won", {}).get("params", {}).get("run_status") != 2:
        failures.append("result snapshot did not reach won status")
    result_overlay = snapshots.get("result_won", {}).get("overlay", {})
    if "Next assay unlocked" not in result_overlay.get("status", ""):
        failures.append("result overlay did not name next assay progression")
    if "A NEXT ASSAY" not in result_overlay.get("prompt", ""):
        failures.append("result overlay prompt did not name next assay action")
    if "VIEW EXIT" not in result_overlay.get("prompt", ""):
        failures.append("result overlay prompt did not name View exit action")
    result_actions = {action.get("steam_action") for action in result_overlay.get("prompt_actions", [])}
    for action in ["StartExperiment", "ExitExperiment"]:
        if action not in result_actions:
            failures.append(f"result overlay missing structured action: {action}")
    next_snapshot = snapshots.get("south_next_briefing", {})
    if next_snapshot.get("params", {}).get("run_status") != 0:
        failures.append("A/next result transition did not reset to briefing")
    if next_snapshot.get("params", {}).get("applying") != 0:
        failures.append("A/next result transition did not clear apply param")
    if next_snapshot.get("trial_id") == snapshots.get("result_won", {}).get("trial_id"):
        failures.append("A/next result transition did not advance to the next exported trial")
    final_snapshot = snapshots.get("final_result_won", {})
    restart_snapshot = snapshots.get("final_next_restarts_sequence", {})
    if final_snapshot.get("params", {}).get("run_status") != 2:
        failures.append("final result snapshot did not reach won status")
    final_overlay = final_snapshot.get("overlay", {})
    if "Sequence complete" not in final_overlay.get("status", ""):
        failures.append("final result overlay did not name sequence completion")
    if "A RESTART TRIAL 1" not in final_overlay.get("prompt", ""):
        failures.append("final result overlay prompt did not name sequence restart")
    if "VIEW EXIT" not in final_overlay.get("prompt", ""):
        failures.append("final result overlay prompt did not name View exit action")
    final_actions = {action.get("steam_action") for action in final_overlay.get("prompt_actions", [])}
    for action in ["StartExperiment", "ExitExperiment"]:
        if action not in final_actions:
            failures.append(f"final overlay missing structured action: {action}")
    for label, snapshot in snapshots.items():
        prompt_actions = snapshot.get("overlay", {}).get("prompt_actions", [])
        if not prompt_actions:
            failures.append(f"snapshot missing prompt action metadata: {label}")
        for action in prompt_actions:
            if not action.get("steam_action") or not action.get("fallback_label"):
                failures.append(f"snapshot has incomplete prompt action metadata: {label}")
    if restart_snapshot.get("trial_index") != 0:
        failures.append("final A/next transition did not restart at the first exported trial")
    if restart_snapshot.get("params", {}).get("run_status") != 0:
        failures.append("final A/next transition did not land in briefing")
    return failures


def main() -> int:
    args = parse_args()
    if not args.no_build:
        build_native_runtime()
    binary = prepare_binary(args.binary_output, args.no_sign)
    output = resolve(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(binary),
            "--trial",
            str(resolve(args.trial_definitions)),
            "--trial-id",
            args.trial_id,
            "--config",
            str(resolve(args.config)),
            "--dump-input-smoke",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"native input runtime smoke failed: {proc.stdout}\n{proc.stderr}")
    payload = json.loads(output.read_text(encoding="utf-8"))
    failures = validate(payload)
    write_markdown(payload, failures, args.markdown)
    print(f"native_input_runtime_status={'pass' if not failures else 'fail'}")
    print(f"native_input_runtime_markdown={resolve(args.markdown)}")
    print(f"native_input_runtime_json={output}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
