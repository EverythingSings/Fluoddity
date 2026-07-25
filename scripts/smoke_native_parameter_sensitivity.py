"""Check that mapped native fluid parameters have measurable rendered effect."""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
from pathlib import Path

from compare_native_visual_metrics import image_metrics, read_image
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
DEFAULT_CONFIG = ROOT / "physics_configs" / "Core" / "Bubbles.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_parameter_sensitivity.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_parameter_sensitivity.md"

VARIANTS = [
    {
        "name": "sensor_gain_low",
        "field": "physics.sensor_gain",
        "updates": [("physics", "sensor_gain", 0.25)],
    },
    {
        "name": "sensor_distance_short",
        "field": "physics.sensor_distance",
        "updates": [("physics", "sensor_distance", 0.20)],
    },
    {
        "name": "sensor_angle_wide",
        "field": "physics.sensor_angle",
        "updates": [("physics", "sensor_angle", 0.90)],
    },
    {
        "name": "drag_low",
        "field": "physics.drag",
        "updates": [("physics", "drag", 0.20)],
    },
    {
        "name": "trail_persistence_low",
        "field": "physics.trail_persistence",
        "updates": [("physics", "trail_persistence", 0.25)],
    },
    {
        "name": "symmetry_disabled",
        "field": "settings.disable_symmetry",
        "updates": [("settings", "disable_symmetry", True)],
    },
    {
        "name": "orientation_radial",
        "field": "settings.absolute_orientation",
        "updates": [
            ("settings", "absolute_orientation", 2),
            ("settings", "orientation_mix", 1.0),
        ],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke mapped native parameter influence on rendered output.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH, help="Exported trial definitions JSON.")
    parser.add_argument("--trial-id", default="rival_bloom", help="Trial contract to use for captures.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Base saved Core config.")
    parser.add_argument("--frames", type=int, default=48, help="Frames per capture.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--min-pixel-mean-abs", type=float, default=0.35, help="Minimum mean absolute channel delta per variant.")
    parser.add_argument("--min-pixel-changed-ratio", type=float, default=0.015, help="Minimum changed channel ratio per variant.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_variant_config(source: dict, name: str, updates: list[tuple[str, str, object]]) -> Path:
    payload = copy.deepcopy(source)
    for section, key, value in updates:
        payload.setdefault(section, {})[key] = value
    output = ROOT / "artifacts" / "native-wgpu" / f"parameter_sensitivity_{name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def capture(binary: Path, trial_path: Path, trial_id: str, config_path: Path, label: str, frames: int) -> dict:
    output = ROOT / "artifacts" / "native-wgpu" / f"parameter_sensitivity_{label}.ppm"
    contract_output = ROOT / "artifacts" / "native-wgpu" / f"parameter_sensitivity_{label}_contract.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    contract_proc = subprocess.run(
        [str(binary), "--config", str(config_path), "--dump-config-contract", str(contract_output)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    capture_proc = subprocess.run(
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
        "label": label,
        "config": repo_path(config_path),
        "output": repo_path(output),
        "contract_output": repo_path(contract_output),
        "contract_returncode": contract_proc.returncode,
        "capture_returncode": capture_proc.returncode,
        "failures": [],
    }
    failures: list[str] = result["failures"]
    if contract_proc.returncode != 0:
        failures.append(f"contract dump exited {contract_proc.returncode}")
        result["contract_tail"] = "\n".join((contract_proc.stdout + contract_proc.stderr).splitlines()[-20:])
    if capture_proc.returncode != 0:
        failures.append(f"capture exited {capture_proc.returncode}")
        result["capture_tail"] = "\n".join((capture_proc.stdout + capture_proc.stderr).splitlines()[-20:])
    if contract_output.exists():
        result["contract"] = json.loads(contract_output.read_text(encoding="utf-8"))
    else:
        failures.append("missing contract output")
    if output.exists():
        metrics = image_metrics(output)
        result["metrics"] = {
            "mean_luma": metrics["mean_luma"],
            "luma_std": metrics["luma_std"],
            "nonblack_ratio": metrics["nonblack_ratio"],
            "sampled_color_count": metrics["sampled_color_count"],
            "horizontal_edge_mean": metrics["horizontal_edge_mean"],
        }
        if float(metrics["mean_luma"]) < 2.0:
            failures.append("frame is too dark")
        if float(metrics["luma_std"]) < 2.0:
            failures.append("frame lacks variation")
        if int(metrics["sampled_color_count"]) < 8:
            failures.append("frame has too few sampled colors")
    else:
        failures.append("missing output frame")
    return result


def pixel_difference(left_path: Path, right_path: Path) -> dict[str, float | int]:
    left_width, left_height, left_pixels = read_image(left_path)
    right_width, right_height, right_pixels = read_image(right_path)
    if (left_width, left_height) != (right_width, right_height):
        raise RuntimeError(f"image size mismatch: {left_path} vs {right_path}")
    abs_sum = 0
    square_sum = 0
    changed_channels = 0
    for left, right in zip(left_pixels, right_pixels):
        delta = abs(left - right)
        abs_sum += delta
        square_sum += delta * delta
        if delta > 2:
            changed_channels += 1
    channel_count = len(left_pixels)
    return {
        "width": left_width,
        "height": left_height,
        "channel_count": channel_count,
        "mean_abs_channel_delta": abs_sum / channel_count,
        "rmse_channel_delta": (square_sum / channel_count) ** 0.5,
        "changed_channel_ratio": changed_channels / channel_count,
    }


def contract_value(contract: dict, field: str) -> object:
    return contract.get(field.split(".", 1)[1])


def write_reports(payload: dict, json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Native Parameter Sensitivity",
        "",
        f"- Status: {payload['status']}",
        f"- Base config: `{payload['base']['config']}`",
        f"- Variants checked: {len(payload['variants'])}",
        f"- Variants passed: {payload['passed_variant_count']}",
        f"- Required mean absolute channel delta: {payload['min_pixel_mean_abs']:.3f}",
        f"- Required changed channel ratio: {payload['min_pixel_changed_ratio']:.3f}",
        "- Scope: mapped native fluid parameter influence, not exact Python pixel parity",
        "",
        "## Variants",
        "",
        "| Variant | Field | Contract value | Mean abs delta | Changed ratio | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for variant in payload["variants"]:
        delta = variant.get("pixel_delta", {})
        status = "pass" if not variant["failures"] else "fail"
        lines.append(
            f"| `{variant['name']}` | `{variant['field']}` | `{variant.get('contract_value', '')}` | "
            f"{float(delta.get('mean_abs_channel_delta', 0.0)):.3f} | "
            f"{float(delta.get('changed_channel_ratio', 0.0)):.3f} | {status} |"
        )
    failures = [failure for variant in payload["variants"] for failure in variant["failures"]]
    if failures:
        lines.extend(["", "## Failures", ""])
        for variant in payload["variants"]:
            for failure in variant["failures"]:
                lines.append(f"- `{variant['name']}`: {failure}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    trial_path = resolve(args.trial_definitions)
    config_path = resolve(args.config)
    if not config_path.exists():
        raise SystemExit(f"config missing: {config_path}")
    if not args.no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    if not binary.exists():
        raise SystemExit(f"native runtime binary not found: {binary}")

    base_config = json.loads(config_path.read_text(encoding="utf-8"))
    base = capture(binary, trial_path, args.trial_id, config_path, "base", args.frames)
    variants: list[dict] = []
    for variant in VARIANTS:
        variant_config = write_variant_config(base_config, variant["name"], variant["updates"])
        result = capture(binary, trial_path, args.trial_id, variant_config, variant["name"], args.frames)
        result["name"] = variant["name"]
        result["field"] = variant["field"]
        result["updates"] = [
            {"section": section, "key": key, "value": value} for section, key, value in variant["updates"]
        ]
        if not base["failures"] and not result["failures"]:
            delta = pixel_difference(ROOT / base["output"], ROOT / result["output"])
            result["pixel_delta"] = delta
            if float(delta["mean_abs_channel_delta"]) < args.min_pixel_mean_abs:
                result["failures"].append(
                    f"mean absolute channel delta too low ({float(delta['mean_abs_channel_delta']):.3f})"
                )
            if float(delta["changed_channel_ratio"]) < args.min_pixel_changed_ratio:
                result["failures"].append(
                    f"changed channel ratio too low ({float(delta['changed_channel_ratio']):.3f})"
                )
        contract = result.get("contract", {})
        if contract:
            result["contract_value"] = contract_value(contract, variant["field"])
        variants.append(result)

    passed = [variant for variant in variants if not variant["failures"]]
    payload = {
        "schema": "fluoddity.native_parameter_sensitivity.v1",
        "status": "pass" if not base["failures"] and len(passed) == len(variants) else "fail",
        "frames": args.frames,
        "trial_id": args.trial_id,
        "min_pixel_mean_abs": args.min_pixel_mean_abs,
        "min_pixel_changed_ratio": args.min_pixel_changed_ratio,
        "base": base,
        "variants": variants,
        "passed_variant_count": len(passed),
        "note": "This catches mapped native parameters that do not materially affect output; it is not exact Python/GLSL parity.",
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_parameter_sensitivity_status={payload['status']}")
    print(f"native_parameter_sensitivity_checked={len(variants)}")
    print(f"native_parameter_sensitivity_passed={len(passed)}")
    print(f"native_parameter_sensitivity_markdown={resolve(args.markdown)}")
    print(f"native_parameter_sensitivity_json={resolve(args.json_output)}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
