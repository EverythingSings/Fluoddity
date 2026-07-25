"""Run every exported Trial Dish contract through the native Rust/wgpu runtime."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from compare_native_visual_metrics import image_metrics
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_trial_matrix.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_trial_matrix.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke all Trial Dish contracts through the native runtime.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH, help="Exported trial definitions JSON.")
    parser.add_argument("--config", type=Path, default=ROOT / "physics_configs/Core/Bubbles.json", help="Physics config path.")
    parser.add_argument("--frames", type=int, default=24, help="Frames per trial capture.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def load_trials(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "fluoddity.trial_definitions.v1":
        raise RuntimeError(f"unexpected trial schema in {path}")
    trials = payload.get("trials", [])
    if not isinstance(trials, list) or not trials:
        raise RuntimeError(f"no trials in {path}")
    return trials


def run_trial(binary: Path, trial_path: Path, config_path: Path, trial: dict, frames: int) -> dict:
    trial_id = trial["trial_id"]
    output = ROOT / "artifacts" / "native-wgpu" / f"trial_matrix_{trial_id}.ppm"
    output.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(binary),
            "--trial",
            str(trial_path),
            "--trial-id",
            trial_id,
            "--config",
            str(config_path),
            "--frames",
            str(frames),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    stdout = proc.stdout + proc.stderr
    result = {
        "trial_id": trial_id,
        "title": trial["title"],
        "expected_zone_count": len(trial["zones"]),
        "expected_hazard_enabled": bool(trial.get("hazard_enabled")),
        "expected_rival_enabled": bool(trial.get("rival_enabled")),
        "returncode": proc.returncode,
        "output": output.relative_to(ROOT).as_posix(),
        "failures": [],
    }
    failures: list[str] = result["failures"]
    if proc.returncode != 0:
        failures.append(f"native runtime exited {proc.returncode}")
        result["stdout_tail"] = "\n".join(stdout.splitlines()[-20:])
        return result

    contract = re.search(
        r'trial_contract_result id=(?P<id>\S+) title="(?P<title>[^"]+)" objective="(?P<objective>[^"]+)" zones=(?P<zones>\d+) first_zone=\((?P<x>[0-9.]+),(?P<y>[0-9.]+),r=(?P<radius>[0-9.]+)\)',
        stdout,
    )
    if not contract:
        failures.append("missing trial_contract_result")
    else:
        if contract.group("id") != trial_id:
            failures.append(f"trial id mismatch: {contract.group('id')}")
        if contract.group("title") != trial["title"]:
            failures.append(f"title mismatch: {contract.group('title')}")
        if int(contract.group("zones")) != len(trial["zones"]):
            failures.append(f"zone count mismatch: {contract.group('zones')}")
        first_zone = trial["zones"][0]
        expected_x = float(first_zone[1][0])
        expected_y = float(first_zone[1][1])
        expected_radius = float(first_zone[2])
        if abs(float(contract.group("x")) - expected_x) > 0.001:
            failures.append("first zone x mismatch")
        if abs(float(contract.group("y")) - expected_y) > 0.001:
            failures.append("first zone y mismatch")
        if abs(float(contract.group("radius")) - expected_radius) > 0.001:
            failures.append("first zone radius mismatch")

    runtime_state = re.search(
        r"trial_runtime_state status=(?P<status>\d+) progress=(?P<progress>[0-9.]+) active_zones=(?P<active>\d+) rival_zones=(?P<rival>\d+) elapsed_seconds=(?P<elapsed>[0-9.]+)",
        stdout,
    )
    if not runtime_state:
        failures.append("missing trial_runtime_state")
    else:
        result["runtime_state"] = {
            "status": int(runtime_state.group("status")),
            "progress": float(runtime_state.group("progress")),
            "active_zones": int(runtime_state.group("active")),
            "rival_zones": int(runtime_state.group("rival")),
            "elapsed_seconds": float(runtime_state.group("elapsed")),
        }
        if result["runtime_state"]["status"] != 1:
            failures.append(f"trial state not running: {result['runtime_state']['status']}")

    frame = re.search(
        r"wgpu_spike_result trials=(?P<trials>\d+) frames=(?P<frames>\d+) "
        r"width=(?P<width>\d+) height=(?P<height>\d+) particles=(?P<particles>\d+) "
        r"avg_fps=(?P<fps>[0-9.]+) avg_frame_ms=(?P<ms>[0-9.]+) "
        r"nonblank_pixels=(?P<nonblank>\d+) output=(?P<output>.+)",
        stdout,
    )
    if not frame:
        failures.append("missing wgpu_spike_result")
    else:
        result["frame_result"] = {
            "trial_count": int(frame.group("trials")),
            "frames": int(frame.group("frames")),
            "width": int(frame.group("width")),
            "height": int(frame.group("height")),
            "particle_count": int(frame.group("particles")),
            "avg_fps": float(frame.group("fps")),
            "avg_frame_ms": float(frame.group("ms")),
            "nonblank_pixels": int(frame.group("nonblank")),
        }
        if result["frame_result"]["trial_count"] < 3:
            failures.append("trial count should include all exported trials")
        if result["frame_result"]["frames"] != frames:
            failures.append("frame count mismatch")
        if result["frame_result"]["width"] != 1280 or result["frame_result"]["height"] != 800:
            failures.append("default native render dimensions should be 1280x800")
        if result["frame_result"]["particle_count"] <= 0:
            failures.append("native particle count should be positive")
        if result["frame_result"]["nonblank_pixels"] <= 0:
            failures.append("blank native frame")

    if not output.exists():
        failures.append("missing output frame")
    else:
        metrics = image_metrics(output)
        result["metrics"] = {
            "mean_luma": metrics["mean_luma"],
            "luma_std": metrics["luma_std"],
            "nonblack_ratio": metrics["nonblack_ratio"],
            "sampled_color_count": metrics["sampled_color_count"],
        }
        if float(metrics["mean_luma"]) < 2.0:
            failures.append("frame is too dark")
        if float(metrics["luma_std"]) < 2.0:
            failures.append("frame lacks variation")
        if int(metrics["sampled_color_count"]) < 8:
            failures.append("frame has too few sampled colors")

    return result


def write_reports(results: list[dict], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    passed = [result for result in results if not result["failures"]]
    payload = {
        "schema": "fluoddity.native_trial_matrix.v1",
        "status": "pass" if len(passed) == len(results) else "fail",
        "trial_count": len(results),
        "passed_trial_count": len(passed),
        "results": results,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Trial Matrix",
        "",
        f"- Status: {payload['status']}",
        f"- Trials checked: {len(results)}",
        f"- Trials passed: {len(passed)}",
        "",
        "## Results",
        "",
    ]
    for result in results:
        status = "pass" if not result["failures"] else "fail"
        state = result.get("runtime_state", {})
        metrics = result.get("metrics", {})
        lines.append(f"- `{result['trial_id']}` ({result['title']}): {status}")
        if state:
            lines.append(
                f"  - state status={state['status']} active_zones={state['active_zones']} "
                f"rival_zones={state['rival_zones']} progress={state['progress']:.3f}"
            )
        if metrics:
            lines.append(
                f"  - metrics mean_luma={float(metrics['mean_luma']):.2f} "
                f"luma_std={float(metrics['luma_std']):.2f} "
                f"nonblack={float(metrics['nonblack_ratio']):.4f} "
                f"colors={metrics['sampled_color_count']}"
            )
        for failure in result["failures"]:
            lines.append(f"  - failure: {failure}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    trial_path = resolve(args.trial_definitions)
    config_path = resolve(args.config)
    if not args.no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    if not binary.exists():
        raise SystemExit(f"native runtime binary not found: {binary}")
    trials = load_trials(trial_path)
    results = [run_trial(binary, trial_path, config_path, trial, args.frames) for trial in trials]
    write_reports(results, args.json_output, args.markdown)
    passed = sum(1 for result in results if not result["failures"])
    print(f"native_trial_matrix_status={'pass' if passed == len(results) else 'fail'}")
    print(f"native_trial_matrix_checked={len(results)}")
    print(f"native_trial_matrix_passed={passed}")
    print(f"native_trial_matrix_markdown={resolve(args.markdown)}")
    print(f"native_trial_matrix_json={resolve(args.json_output)}")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
