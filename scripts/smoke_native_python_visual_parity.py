"""Measure native-vs-Python visual parity for the same Trial Dish scenario.

This is deliberately stricter than the coarse native visual metrics report, but
it is still not a completion claim. The native runtime is a replacement-track
wgpu player path, while the Python path includes the current game shell and
OpenGL renderer. This script makes that gap measurable instead of implicit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from compare_native_visual_metrics import image_metrics, read_image
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NATIVE_IMAGE = ROOT / "artifacts" / "native-wgpu" / "python_parity_rival_bloom.ppm"
DEFAULT_PYTHON_IMAGE = ROOT / "artifacts" / "visual_smoke" / "native_parity_trial3_running.png"
DEFAULT_JSON = ROOT / "artifacts" / "native_python_visual_parity.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_python_visual_parity.md"
DEFAULT_CHILD_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if (ROOT / ".venv" / "Scripts" / "python.exe").exists()
    else Path(sys.executable)
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure native-vs-Python Trial Dish visual parity.")
    parser.add_argument("--trial-definitions", type=Path, default=ROOT / "artifacts" / "trial_definitions.json")
    parser.add_argument("--native-trial-id", default="rival_bloom")
    parser.add_argument("--python-trial", type=int, default=3, choices=(1, 2, 3))
    parser.add_argument("--config", type=Path, default=ROOT / "physics_configs" / "Core" / "Bubbles.json")
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--native-image", type=Path, default=DEFAULT_NATIVE_IMAGE)
    parser.add_argument("--python-image", type=Path, default=DEFAULT_PYTHON_IMAGE)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--python", default=str(DEFAULT_CHILD_PYTHON))
    parser.add_argument("--no-build", action="store_true", help="Skip native release build.")
    parser.add_argument("--skip-native-capture", action="store_true")
    parser.add_argument("--skip-python-capture", action="store_true")
    parser.add_argument("--max-mean-abs-delta", type=float, default=28.0)
    parser.add_argument("--max-rmse-delta", type=float, default=52.0)
    parser.add_argument("--max-changed-channel-ratio", type=float, default=0.72)
    parser.add_argument(
        "--require-within-threshold",
        action="store_true",
        help="Exit non-zero when the measured image delta exceeds the loose parity threshold.",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def repo_path(path: Path) -> str:
    path = resolve(path)
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def run_command(command: list[str], label: str) -> dict[str, object]:
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=90)
    return {
        "label": label,
        "command": command,
        "returncode": proc.returncode,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-25:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-25:]),
    }


def build_runtime() -> dict[str, object]:
    try:
        build_native_runtime()
    except subprocess.CalledProcessError as error:
        return {
            "label": "native_build",
            "command": error.cmd,
            "returncode": error.returncode,
            "stdout_tail": "",
            "stderr_tail": str(error),
        }
    return {
        "label": "native_build",
        "command": ["cargo", "build", "--manifest-path", str(ROOT / "runtime" / "rust-wgpu-spike" / "Cargo.toml"), "--release"],
        "returncode": 0,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def capture_native(args: argparse.Namespace) -> dict[str, object]:
    output = resolve(args.native_image)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    command = [
        str(native_runtime_binary()),
        "--trial",
        str(resolve(args.trial_definitions)),
        "--trial-id",
        args.native_trial_id,
        "--config",
        str(resolve(args.config)),
        "--frames",
        str(args.frames),
        "--out",
        str(output),
    ]
    result = run_command(command, "native_capture")
    result["output"] = repo_path(output)
    result["exists"] = output.exists()
    return result


def capture_python(args: argparse.Namespace) -> dict[str, object]:
    output = resolve(args.python_image)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    command = [
        args.python,
        "scripts/smoke_game_visual.py",
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--frame",
        str(args.frames),
        "--trial",
        str(args.python_trial),
        "--start",
        "--feed",
        "--output",
        str(output),
    ]
    result = run_command(command, "python_capture")
    result["output"] = repo_path(output)
    result["exists"] = output.exists()
    return result


def pixel_difference(left_path: Path, right_path: Path) -> dict[str, float | int | bool]:
    left_width, left_height, left_pixels = read_image(left_path)
    right_width, right_height, right_pixels = read_image(right_path)
    if (left_width, left_height) != (right_width, right_height):
        return {
            "same_size": False,
            "left_width": left_width,
            "left_height": left_height,
            "right_width": right_width,
            "right_height": right_height,
        }
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
        "same_size": True,
        "width": left_width,
        "height": left_height,
        "channel_count": channel_count,
        "mean_abs_channel_delta": abs_sum / channel_count,
        "rmse_channel_delta": (square_sum / channel_count) ** 0.5,
        "changed_channel_ratio": changed_channels / channel_count,
    }


def threshold_pass(diff: dict[str, object], args: argparse.Namespace) -> bool:
    if not diff.get("same_size"):
        return False
    return (
        float(diff["mean_abs_channel_delta"]) <= args.max_mean_abs_delta
        and float(diff["rmse_channel_delta"]) <= args.max_rmse_delta
        and float(diff["changed_channel_ratio"]) <= args.max_changed_channel_ratio
    )


def metric_subset(metrics: dict[str, object]) -> dict[str, object]:
    return {
        "path": metrics["path"],
        "width": metrics["width"],
        "height": metrics["height"],
        "mean_luma": metrics["mean_luma"],
        "luma_std": metrics["luma_std"],
        "nonblack_ratio": metrics["nonblack_ratio"],
        "bright_ratio": metrics["bright_ratio"],
        "saturated_ratio": metrics["saturated_ratio"],
        "sampled_color_count": metrics["sampled_color_count"],
        "horizontal_edge_mean": metrics["horizontal_edge_mean"],
    }


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    commands: list[dict[str, object]] = []
    if not args.no_build and not args.skip_native_capture:
        commands.append(build_runtime())
    if not args.skip_native_capture:
        commands.append(capture_native(args))
    if not args.skip_python_capture:
        commands.append(capture_python(args))

    native_path = resolve(args.native_image)
    python_path = resolve(args.python_image)
    failures: list[str] = []
    for command in commands:
        if command.get("returncode") != 0:
            failures.append(f"{command['label']} exited {command['returncode']}")
    if not native_path.exists():
        failures.append(f"native image missing: {repo_path(native_path)}")
    if not python_path.exists():
        failures.append(f"python image missing: {repo_path(python_path)}")

    native_metrics = metric_subset(image_metrics(native_path)) if native_path.exists() else None
    python_metrics = metric_subset(image_metrics(python_path)) if python_path.exists() else None
    diff = pixel_difference(native_path, python_path) if native_path.exists() and python_path.exists() else None
    within_threshold = threshold_pass(diff, args) if diff else False
    if failures:
        status = "failed"
    elif within_threshold:
        status = "within-threshold"
    else:
        status = "measured-drift"

    return {
        "schema": "fluoddity.native_python_visual_parity.v1",
        "status": status,
        "within_loose_threshold": within_threshold,
        "exact_parity_claimed": False,
        "scope": "same Trial Dish scenario image-level comparison between Python/OpenGL game smoke and Rust/wgpu native player capture",
        "scenario": {
            "native_trial_id": args.native_trial_id,
            "python_trial": args.python_trial,
            "config": repo_path(resolve(args.config)),
            "frames": args.frames,
            "width": args.width,
            "height": args.height,
        },
        "thresholds": {
            "max_mean_abs_channel_delta": args.max_mean_abs_delta,
            "max_rmse_channel_delta": args.max_rmse_delta,
            "max_changed_channel_ratio": args.max_changed_channel_ratio,
        },
        "commands": commands,
        "native": native_metrics,
        "python": python_metrics,
        "pixel_difference": diff,
        "failures": failures,
        "note": "This is stronger than nonblank smoke, but it is not proof that the Rust/wgpu engine fully replicates the Python/GLSL fluid engine.",
    }


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    diff = payload.get("pixel_difference") or {}
    native = payload.get("native") or {}
    python = payload.get("python") or {}
    lines = [
        "# Native Python Visual Parity",
        "",
        f"- Status: {payload['status']}",
        f"- Within loose threshold: {'yes' if payload['within_loose_threshold'] else 'no'}",
        "- Exact parity claimed: no",
        f"- Scope: {payload['scope']}",
        "",
        "## Scenario",
        "",
    ]
    scenario = payload["scenario"]
    assert isinstance(scenario, dict)
    for key, value in scenario.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Captures", ""])
    if native:
        lines.append(f"- Native: `{native['path']}` mean_luma={float(native['mean_luma']):.2f} luma_std={float(native['luma_std']):.2f} nonblack={float(native['nonblack_ratio']):.4f}")
    if python:
        lines.append(f"- Python: `{python['path']}` mean_luma={float(python['mean_luma']):.2f} luma_std={float(python['luma_std']):.2f} nonblack={float(python['nonblack_ratio']):.4f}")
    lines.extend(["", "## Pixel Difference", ""])
    if diff:
        if diff.get("same_size"):
            lines.extend(
                [
                    f"- Size: {diff['width']}x{diff['height']}",
                    f"- Mean abs channel delta: {float(diff['mean_abs_channel_delta']):.3f}",
                    f"- RMSE channel delta: {float(diff['rmse_channel_delta']):.3f}",
                    f"- Changed channel ratio: {float(diff['changed_channel_ratio']):.4f}",
                ]
            )
        else:
            lines.append(f"- Size mismatch: native {diff['left_width']}x{diff['left_height']} vs Python {diff['right_width']}x{diff['right_height']}")
    else:
        lines.append("- No pixel difference computed.")
    failures = payload.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure}")
    lines.extend(
        [
            "",
            "This report keeps native fluid replacement work honest: it measures visual drift, but the native shader parity audit remains the authority for unmapped engine features.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_python_visual_parity_status={payload['status']}")
    print(f"native_python_visual_parity_within_threshold={payload['within_loose_threshold']}")
    print(f"native_python_visual_parity_markdown={resolve(args.markdown)}")
    print(f"native_python_visual_parity_json={resolve(args.json_output)}")
    if payload["status"] == "failed":
        return 1
    if args.require_within_threshold and not payload["within_loose_threshold"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
