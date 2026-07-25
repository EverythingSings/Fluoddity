"""Check native Rust/wgpu replay determinism for a saved Trial Dish scenario."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from compare_native_visual_metrics import image_metrics, read_image
from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
TRIALS_PATH = ROOT / "artifacts" / "trial_definitions.json"
DEFAULT_CONFIG = ROOT / "physics_configs" / "Core" / "Bubbles.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_replay_determinism.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_replay_determinism.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify deterministic native headless captures.")
    parser.add_argument("--trial-definitions", type=Path, default=TRIALS_PATH)
    parser.add_argument("--trial-id", default="rival_bloom")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--frames", type=int, default=64)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--no-build", action="store_true")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def repo_path(path: Path) -> str:
    try:
        return resolve(path).relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture(binary: Path, args: argparse.Namespace, label: str) -> dict[str, object]:
    output = ROOT / "artifacts" / "native-wgpu" / f"replay_determinism_{label}.ppm"
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    proc = subprocess.run(
        [
            str(binary),
            "--trial",
            str(resolve(args.trial_definitions)),
            "--trial-id",
            args.trial_id,
            "--config",
            str(resolve(args.config)),
            "--frames",
            str(args.frames),
            "--out",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    result: dict[str, object] = {
        "label": label,
        "output": repo_path(output),
        "returncode": proc.returncode,
        "failures": [],
    }
    failures: list[str] = result["failures"]  # type: ignore[assignment]
    if proc.returncode != 0:
        failures.append(f"native capture exited {proc.returncode}")
        result["stdout_tail"] = "\n".join((proc.stdout + proc.stderr).splitlines()[-25:])
    if not output.exists():
        failures.append("missing output frame")
        return result

    metrics = image_metrics(output)
    result["sha256"] = sha256_file(output)
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
    max_delta = 0
    for left, right in zip(left_pixels, right_pixels):
        delta = abs(left - right)
        abs_sum += delta
        square_sum += delta * delta
        max_delta = max(max_delta, delta)
        if delta > 0:
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
        "max_channel_delta": max_delta,
    }


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    captures = payload["captures"]
    assert isinstance(captures, list)
    diff = payload.get("pixel_difference") or {}
    lines = [
        "# Native Replay Determinism",
        "",
        f"- Status: {payload['status']}",
        f"- Bit exact: {'yes' if payload['bit_exact'] else 'no'}",
        f"- Trial id: `{payload['trial_id']}`",
        f"- Config: `{payload['config']}`",
        f"- Frames: {payload['frames']}",
        "",
        "## Captures",
        "",
    ]
    for capture_result in captures:
        metrics = capture_result.get("metrics", {})
        lines.append(
            f"- `{capture_result['label']}`: `{capture_result['output']}` "
            f"sha256=`{capture_result.get('sha256', '-')}` "
            f"mean_luma={float(metrics.get('mean_luma', 0.0)):.2f} "
            f"luma_std={float(metrics.get('luma_std', 0.0)):.2f}"
        )
    lines.extend(["", "## Difference", ""])
    if diff:
        if diff.get("same_size"):
            lines.extend(
                [
                    f"- Size: {diff['width']}x{diff['height']}",
                    f"- Mean abs channel delta: {float(diff['mean_abs_channel_delta']):.6f}",
                    f"- RMSE channel delta: {float(diff['rmse_channel_delta']):.6f}",
                    f"- Changed channel ratio: {float(diff['changed_channel_ratio']):.6f}",
                    f"- Max channel delta: {int(diff['max_channel_delta'])}",
                ]
            )
        else:
            lines.append("- Size mismatch; no pixel-level determinism result.")
    failures = payload.get("failures") or []
    if failures:
        lines.extend(["", "## Failures", ""])
        for failure in failures:
            lines.append(f"- {failure}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    first = capture(binary, args, "first")
    second = capture(binary, args, "second")
    failures = [*first.get("failures", []), *second.get("failures", [])]
    first_path = ROOT / str(first.get("output", ""))
    second_path = ROOT / str(second.get("output", ""))
    diff = pixel_difference(first_path, second_path) if first_path.exists() and second_path.exists() else None
    bit_exact = bool(
        not failures
        and first.get("sha256")
        and first.get("sha256") == second.get("sha256")
        and diff
        and diff.get("same_size")
        and float(diff.get("mean_abs_channel_delta", 1.0)) == 0.0
    )
    if not diff:
        failures.append("missing pixel comparison")
    elif not bit_exact:
        failures.append("replay captures are not bit-exact")

    payload = {
        "schema": "fluoddity.native_replay_determinism.v1",
        "status": "pass" if bit_exact else "fail",
        "bit_exact": bit_exact,
        "trial_id": args.trial_id,
        "config": repo_path(resolve(args.config)),
        "frames": args.frames,
        "captures": [first, second],
        "pixel_difference": diff,
        "failures": failures,
        "note": "Native replay determinism is local headless stability evidence, not Python/GLSL parity or Steam Deck hardware proof.",
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_replay_determinism_status={payload['status']}")
    print(f"native_replay_determinism_bit_exact={payload['bit_exact']}")
    print(f"native_replay_determinism_markdown={resolve(args.markdown)}")
    print(f"native_replay_determinism_json={resolve(args.json_output)}")
    return 0 if bit_exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
