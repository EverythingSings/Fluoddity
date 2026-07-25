"""Check that saved Fourier rule coefficients materially affect native output."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from compare_native_visual_metrics import image_metrics, read_image
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
DEFAULT_CONFIG = ROOT / "physics_configs" / "Core" / "LavaLamp.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_rule_sensitivity.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_rule_sensitivity.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify that saved rules affect native Rust/wgpu fluid output.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH, help="Exported trial definitions JSON.")
    parser.add_argument("--trial-id", default="rival_bloom", help="Trial contract to use for captures.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Saved config with an 80-float rule.")
    parser.add_argument("--frames", type=int, default=72, help="Frames per capture.")
    parser.add_argument("--min-distance", type=float, default=0.0, help="Minimum coarse metric distance between saved and zero-rule captures.")
    parser.add_argument("--min-pixel-mean-abs", type=float, default=1.0, help="Minimum mean absolute channel delta between captures.")
    parser.add_argument("--min-pixel-changed-ratio", type=float, default=0.05, help="Minimum ratio of color channels changed by more than 2 values.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def write_zero_rule_config(source: Path) -> Path:
    payload = json.loads(source.read_text(encoding="utf-8"))
    rule = payload.get("rule")
    if not isinstance(rule, list) or len(rule) != 80:
        raise RuntimeError(f"{source} does not contain an 80-float saved rule")
    output = ROOT / "artifacts" / "native-wgpu" / f"rule_sensitivity_{source.stem}_zero_rule.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload["rule"] = [0.0] * 80
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def capture_variant(binary: Path, trial_path: Path, trial_id: str, config_path: Path, label: str, frames: int) -> dict:
    output = ROOT / "artifacts" / "native-wgpu" / f"rule_sensitivity_{label}.ppm"
    contract_output = ROOT / "artifacts" / "native-wgpu" / f"rule_sensitivity_{label}_contract.json"
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
        "config": config_path.relative_to(ROOT).as_posix() if config_path.is_relative_to(ROOT) else str(config_path),
        "output": output.relative_to(ROOT).as_posix(),
        "contract_output": contract_output.relative_to(ROOT).as_posix(),
        "contract_returncode": contract_proc.returncode,
        "capture_returncode": capture_proc.returncode,
        "failures": [],
    }
    failures: list[str] = result["failures"]
    if contract_proc.returncode != 0:
        failures.append(f"contract dump exited {contract_proc.returncode}")
        result["contract_stdout_tail"] = "\n".join((contract_proc.stdout + contract_proc.stderr).splitlines()[-20:])
    if capture_proc.returncode != 0:
        failures.append(f"capture exited {capture_proc.returncode}")
        result["capture_stdout_tail"] = "\n".join((capture_proc.stdout + capture_proc.stderr).splitlines()[-20:])
    if contract_output.exists():
        contract = json.loads(contract_output.read_text(encoding="utf-8"))
        result["contract"] = {
            "has_saved_rule": bool(contract.get("has_saved_rule")),
            "rule_float_count": contract.get("rule_float_count"),
            "rule_seed": contract.get("rule_seed"),
            "rule_seed_value": contract.get("rule_seed_value"),
        }
    else:
        failures.append("missing contract output")
    if output.exists():
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
    else:
        failures.append("missing output frame")
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


def pixel_difference(left_path: Path, right_path: Path) -> dict[str, float | int]:
    left_width, left_height, left_pixels = read_image(left_path)
    right_width, right_height, right_pixels = read_image(right_path)
    if (left_width, left_height) != (right_width, right_height):
        raise RuntimeError(
            f"image size mismatch: {left_path} is {left_width}x{left_height}, "
            f"{right_path} is {right_width}x{right_height}"
        )
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


def write_reports(
    saved: dict,
    zero: dict,
    distance: float,
    pixel_delta: dict[str, float | int],
    status: str,
    min_distance: float,
    min_pixel_mean_abs: float,
    min_pixel_changed_ratio: float,
    json_path: Path,
    markdown_path: Path,
) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "fluoddity.native_rule_sensitivity.v1",
        "status": status,
        "min_distance": min_distance,
        "distance": distance,
        "min_pixel_mean_abs": min_pixel_mean_abs,
        "min_pixel_changed_ratio": min_pixel_changed_ratio,
        "pixel_delta": pixel_delta,
        "saved_rule": saved,
        "zero_rule": zero,
        "note": "Rule sensitivity is isolated native regression evidence, not exact Python/GLSL parity.",
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Rule Sensitivity",
        "",
        f"- Status: {status}",
        f"- Coarse metric distance: {distance:.4f}",
        f"- Required coarse distance: {min_distance:.4f}",
        f"- Mean absolute channel delta: {float(pixel_delta['mean_abs_channel_delta']):.4f}",
        f"- Required mean absolute channel delta: {min_pixel_mean_abs:.4f}",
        f"- Changed channel ratio: {float(pixel_delta['changed_channel_ratio']):.4f}",
        f"- Required changed channel ratio: {min_pixel_changed_ratio:.4f}",
        "- Scope: saved Fourier rule influence in the native Rust/wgpu path, not pixel parity",
        "",
        "## Variants",
        "",
    ]
    for variant in (saved, zero):
        contract = variant.get("contract", {})
        metrics = variant.get("metrics", {})
        variant_status = "pass" if not variant["failures"] else "fail"
        lines.append(f"- `{variant['label']}` ({variant['config']}): {variant_status}")
        if contract:
            lines.append(
                f"  - contract has_saved_rule={str(contract['has_saved_rule']).lower()} "
                f"rule_float_count={contract['rule_float_count']} rule_seed={contract['rule_seed']}"
            )
        if metrics:
            lines.append(
                f"  - metrics mean_luma={float(metrics['mean_luma']):.2f} "
                f"luma_std={float(metrics['luma_std']):.2f} "
                f"nonblack={float(metrics['nonblack_ratio']):.4f} "
                f"saturated={float(metrics['saturated_ratio']):.4f} "
                f"edge={float(metrics['horizontal_edge_mean']):.2f} "
                f"colors={metrics['sampled_color_count']}"
            )
        for failure in variant["failures"]:
            lines.append(f"  - failure: {failure}")
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
    zero_config = write_zero_rule_config(config_path)
    saved = capture_variant(binary, trial_path, args.trial_id, config_path, f"{config_path.stem}_saved_rule", args.frames)
    zero = capture_variant(binary, trial_path, args.trial_id, zero_config, f"{config_path.stem}_zero_rule", args.frames)
    distance = metric_distance(saved, zero)
    pixel_delta = pixel_difference(ROOT / saved["output"], ROOT / zero["output"])

    saved_contract = saved.get("contract", {})
    zero_contract = zero.get("contract", {})
    if saved_contract and not saved_contract.get("has_saved_rule"):
        saved["failures"].append("source config did not load as a saved rule")
    if zero_contract and zero_contract.get("has_saved_rule"):
        zero["failures"].append("zero-rule variant still loaded as a saved rule")
    if distance < args.min_distance:
        saved["failures"].append(f"saved-rule coarse metrics too close to zero-rule capture ({distance:.4f})")
    if float(pixel_delta["mean_abs_channel_delta"]) < args.min_pixel_mean_abs:
        saved["failures"].append(
            f"saved-rule mean absolute channel delta too low ({float(pixel_delta['mean_abs_channel_delta']):.4f})"
        )
    if float(pixel_delta["changed_channel_ratio"]) < args.min_pixel_changed_ratio:
        saved["failures"].append(
            f"saved-rule changed channel ratio too low ({float(pixel_delta['changed_channel_ratio']):.4f})"
        )

    status = "pass" if not saved["failures"] and not zero["failures"] else "fail"
    write_reports(
        saved,
        zero,
        distance,
        pixel_delta,
        status,
        args.min_distance,
        args.min_pixel_mean_abs,
        args.min_pixel_changed_ratio,
        args.json_output,
        args.markdown,
    )
    print(f"native_rule_sensitivity_status={status}")
    print(f"native_rule_sensitivity_distance={distance:.4f}")
    print(f"native_rule_sensitivity_pixel_mean_abs={float(pixel_delta['mean_abs_channel_delta']):.4f}")
    print(f"native_rule_sensitivity_pixel_changed_ratio={float(pixel_delta['changed_channel_ratio']):.4f}")
    print(f"native_rule_sensitivity_markdown={resolve(args.markdown)}")
    print(f"native_rule_sensitivity_json={resolve(args.json_output)}")
    return 0 if status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
