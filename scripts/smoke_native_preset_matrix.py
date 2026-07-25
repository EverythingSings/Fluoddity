"""Run representative saved Core presets through the native Rust/wgpu runtime.

This complements the Trial Dish matrix. The trial matrix proves exported game
contracts load; this preset matrix checks that multiple saved fluid presets
produce nonblank, textured, and measurably distinct native captures.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from itertools import combinations
from pathlib import Path

from compare_native_visual_metrics import image_metrics
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_preset_matrix.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_preset_matrix.md"
DEFAULT_PRESETS = [
    ROOT / "physics_configs" / "Core" / "Bubbles.json",
    ROOT / "physics_configs" / "Core" / "LavaLamp.json",
    ROOT / "physics_configs" / "Core" / "Streamers.json",
    ROOT / "physics_configs" / "Core" / "Veins.json",
    ROOT / "physics_configs" / "Core" / "Wreath.json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke representative saved Core presets through the native runtime.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH, help="Exported trial definitions JSON.")
    parser.add_argument("--trial-id", default="rival_bloom", help="Trial contract to use for every preset capture.")
    parser.add_argument("--preset", type=Path, action="append", default=[], help="Preset JSON path. Repeatable.")
    parser.add_argument("--frames", type=int, default=36, help="Frames per preset capture.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--min-distinct-distance", type=float, default=0.010, help="Minimum metric distance from another preset.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def preset_name(path: Path) -> str:
    return path.stem


def run_preset(binary: Path, trial_path: Path, trial_id: str, config_path: Path, frames: int) -> dict:
    name = preset_name(config_path)
    output = ROOT / "artifacts" / "native-wgpu" / f"preset_matrix_{name}.ppm"
    contract_output = ROOT / "artifacts" / "native-wgpu" / f"preset_matrix_{name}_contract.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    contract_proc = subprocess.run(
        [
            str(binary),
            "--config",
            str(config_path),
            "--dump-config-contract",
            str(contract_output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
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
    result = {
        "preset": name,
        "config": config_path.relative_to(ROOT).as_posix(),
        "trial_id": trial_id,
        "frames": frames,
        "contract_returncode": contract_proc.returncode,
        "capture_returncode": proc.returncode,
        "output": output.relative_to(ROOT).as_posix(),
        "contract_output": contract_output.relative_to(ROOT).as_posix(),
        "failures": [],
    }
    failures: list[str] = result["failures"]
    if contract_proc.returncode != 0:
        failures.append(f"native contract dump exited {contract_proc.returncode}")
        result["contract_stdout_tail"] = "\n".join((contract_proc.stdout + contract_proc.stderr).splitlines()[-20:])
    if proc.returncode != 0:
        failures.append(f"native capture exited {proc.returncode}")
        result["capture_stdout_tail"] = "\n".join((proc.stdout + proc.stderr).splitlines()[-20:])
    if not output.exists():
        failures.append("missing output frame")
    else:
        metrics = image_metrics(output)
        result["metrics"] = {
            "mean_luma": metrics["mean_luma"],
            "luma_std": metrics["luma_std"],
            "nonblack_ratio": metrics["nonblack_ratio"],
            "bright_ratio": metrics["bright_ratio"],
            "saturated_ratio": metrics["saturated_ratio"],
            "sampled_color_count": metrics["sampled_color_count"],
            "horizontal_edge_mean": metrics["horizontal_edge_mean"],
        }
        if float(metrics["mean_luma"]) < 2.0:
            failures.append("frame is too dark")
        if float(metrics["luma_std"]) < 2.0:
            failures.append("frame lacks variation")
        if int(metrics["sampled_color_count"]) < 8:
            failures.append("frame has too few sampled colors")
    if not contract_output.exists():
        failures.append("missing config contract output")
    else:
        contract = json.loads(contract_output.read_text(encoding="utf-8"))
        result["contract"] = {
            "source": contract.get("source", ""),
            "rule_seed": contract.get("rule_seed"),
            "num_cohorts": contract.get("num_cohorts"),
            "notes_present": bool(str(contract.get("notes", ""))),
            "ink_weight": contract.get("ink_weight"),
            "watercolor_mode": contract.get("watercolor_mode"),
            "emboss_mode": contract.get("emboss_mode"),
        }
        expected_source = config_path.relative_to(ROOT).as_posix()
        actual_source_path = Path(str(contract.get("source", "")))
        if actual_source_path.is_absolute():
            try:
                actual_source = actual_source_path.relative_to(ROOT).as_posix()
            except ValueError:
                actual_source = actual_source_path.as_posix()
        else:
            actual_source = actual_source_path.as_posix()
        if actual_source != expected_source:
            failures.append(f"contract source mismatch: {contract.get('source')}")
    return result


def metric_distance(left: dict, right: dict) -> float:
    left_metrics = left.get("metrics", {})
    right_metrics = right.get("metrics", {})
    if not left_metrics or not right_metrics:
        return 0.0
    return (
        abs(float(left_metrics["mean_luma"]) - float(right_metrics["mean_luma"])) / 255.0
        + abs(float(left_metrics["luma_std"]) - float(right_metrics["luma_std"])) / 128.0
        + abs(float(left_metrics["nonblack_ratio"]) - float(right_metrics["nonblack_ratio"]))
        + abs(float(left_metrics["saturated_ratio"]) - float(right_metrics["saturated_ratio"]))
        + abs(float(left_metrics["horizontal_edge_mean"]) - float(right_metrics["horizontal_edge_mean"])) / 32.0
    )


def add_distinctness_failures(results: list[dict], min_distance: float) -> list[dict]:
    comparisons: list[dict] = []
    for left, right in combinations(results, 2):
        distance = metric_distance(left, right)
        comparisons.append(
            {
                "left": left["preset"],
                "right": right["preset"],
                "distance": distance,
            }
        )
    for result in results:
        distances = [
            comparison["distance"]
            for comparison in comparisons
            if comparison["left"] == result["preset"] or comparison["right"] == result["preset"]
        ]
        result["nearest_distance"] = min(distances) if distances else 0.0
        if result["nearest_distance"] < min_distance:
            result["failures"].append(
                f"preset capture is not distinct enough from its nearest neighbor ({result['nearest_distance']:.4f})"
            )
    return comparisons


def write_reports(results: list[dict], comparisons: list[dict], json_path: Path, markdown_path: Path, min_distance: float) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    passed = [result for result in results if not result["failures"]]
    payload = {
        "schema": "fluoddity.native_preset_matrix.v1",
        "status": "pass" if len(passed) == len(results) else "fail",
        "preset_count": len(results),
        "passed_preset_count": len(passed),
        "min_distinct_distance": min_distance,
        "results": results,
        "comparisons": comparisons,
        "note": "Preset distances are coarse regression evidence, not proof of exact Python/GLSL visual parity.",
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Preset Matrix",
        "",
        f"- Status: {payload['status']}",
        f"- Presets checked: {len(results)}",
        f"- Presets passed: {len(passed)}",
        f"- Minimum distinctness distance: {min_distance:.3f}",
        "- Scope: saved-preset response and rendered-output diversity, not pixel parity",
        "",
        "## Results",
        "",
    ]
    for result in results:
        status = "pass" if not result["failures"] else "fail"
        metrics = result.get("metrics", {})
        contract = result.get("contract", {})
        lines.append(f"- `{result['preset']}` ({result['config']}): {status}")
        if metrics:
            lines.append(
                f"  - metrics mean_luma={float(metrics['mean_luma']):.2f} "
                f"luma_std={float(metrics['luma_std']):.2f} "
                f"nonblack={float(metrics['nonblack_ratio']):.4f} "
                f"saturated={float(metrics['saturated_ratio']):.4f} "
                f"edge={float(metrics['horizontal_edge_mean']):.2f} "
                f"colors={metrics['sampled_color_count']}"
            )
            lines.append(f"  - nearest distance={float(result.get('nearest_distance', 0.0)):.4f}")
        if contract:
            lines.append(
                f"  - contract rule_seed={contract['rule_seed']} cohorts={contract['num_cohorts']} "
                f"notes_present={str(contract['notes_present']).lower()} "
                f"ink_weight={contract['ink_weight']} watercolor={str(contract['watercolor_mode']).lower()} "
                f"emboss_mode={contract['emboss_mode']}"
            )
        for failure in result["failures"]:
            lines.append(f"  - failure: {failure}")
    lines.extend(["", "## Pairwise Distances", ""])
    for comparison in sorted(comparisons, key=lambda item: (item["left"], item["right"])):
        lines.append(f"- `{comparison['left']}` vs `{comparison['right']}`: {comparison['distance']:.4f}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    trial_path = resolve(args.trial_definitions)
    presets = [resolve(path) for path in (args.preset or DEFAULT_PRESETS)]
    for preset in presets:
        if not preset.exists():
            raise SystemExit(f"preset missing: {preset}")
    if not args.no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    if not binary.exists():
        raise SystemExit(f"native runtime binary not found: {binary}")
    results = [run_preset(binary, trial_path, args.trial_id, preset, args.frames) for preset in presets]
    comparisons = add_distinctness_failures(results, args.min_distinct_distance)
    write_reports(results, comparisons, args.json_output, args.markdown, args.min_distinct_distance)
    passed = sum(1 for result in results if not result["failures"])
    print(f"native_preset_matrix_status={'pass' if passed == len(results) else 'fail'}")
    print(f"native_preset_matrix_checked={len(results)}")
    print(f"native_preset_matrix_passed={passed}")
    print(f"native_preset_matrix_markdown={resolve(args.markdown)}")
    print(f"native_preset_matrix_json={resolve(args.json_output)}")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
