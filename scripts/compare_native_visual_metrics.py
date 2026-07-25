"""Compare coarse visual metrics between Python and native renderer captures.

This is not a pixel-parity test. It is a repeatable evidence artifact that
keeps native renderer work from being judged only by "it opened a window".
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import zlib
from pathlib import Path

from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NATIVE = ROOT / "artifacts" / "native-wgpu" / "wgpu_spike_text_overlay.ppm"
DEFAULT_PYTHON = ROOT / "artifacts" / "visual_smoke" / "trial3_running.png"
DEFAULT_JSON = ROOT / "artifacts" / "native_visual_metrics.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_visual_metrics.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare native renderer and Python visual smoke metrics.")
    parser.add_argument("--native-image", type=Path, default=DEFAULT_NATIVE, help="Native PPM image path.")
    parser.add_argument("--python-image", type=Path, default=DEFAULT_PYTHON, help="Python visual smoke PNG path.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--run-native", action="store_true", help="Refresh the native PPM capture before comparing.")
    parser.add_argument("--no-build", action="store_true", help="Skip building before --run-native.")
    parser.add_argument("--require-reference", action="store_true", help="Fail if the Python reference image is missing.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def run_native_capture(path: Path, no_build: bool) -> None:
    if not no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    subprocess.run(
        [
            str(binary),
            "--trial",
            "artifacts/trial_definitions.json",
            "--trial-id",
            "rival_bloom",
            "--config",
            "physics_configs/Core/Bubbles.json",
            "--frames",
            "24",
            "--out",
            str(path),
        ],
        cwd=ROOT,
        check=True,
    )


def read_image(path: Path) -> tuple[int, int, bytes]:
    suffix = path.suffix.lower()
    if suffix == ".ppm":
        return read_ppm(path)
    if suffix == ".png":
        return read_png(path)
    raise ValueError(f"unsupported image type: {path}")


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    cursor = 0

    def token() -> bytes:
        nonlocal cursor
        while cursor < len(data) and data[cursor] in b" \t\r\n":
            cursor += 1
        if cursor < len(data) and data[cursor] == ord("#"):
            while cursor < len(data) and data[cursor] not in b"\r\n":
                cursor += 1
            return token()
        start = cursor
        while cursor < len(data) and data[cursor] not in b" \t\r\n":
            cursor += 1
        return data[start:cursor]

    magic = token()
    if magic != b"P6":
        raise ValueError(f"unsupported PPM magic in {path}: {magic!r}")
    width = int(token())
    height = int(token())
    max_value = int(token())
    if max_value != 255:
        raise ValueError(f"unsupported PPM max value in {path}: {max_value}")
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    pixels = data[cursor:]
    expected = width * height * 3
    if len(pixels) != expected:
        raise ValueError(f"PPM payload size mismatch in {path}: expected {expected}, got {len(pixels)}")
    return width, height, pixels


def read_png(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"not a PNG file: {path}")
    offset = 8
    width = height = color_type = bit_depth = None
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break
    if width is None or height is None or bit_depth is None or color_type is None:
        raise ValueError(f"PNG missing IHDR: {path}")
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError(f"unsupported PNG format in {path}: bit_depth={bit_depth} color_type={color_type}")
    channels = 3 if color_type == 2 else 4
    stride = width * channels
    raw = zlib.decompress(bytes(compressed))
    rows: list[bytearray] = []
    cursor = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[cursor]
        cursor += 1
        row = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        unfilter(row, previous, filter_type, channels)
        rows.append(row)
        previous = row
    rgb = bytearray(width * height * 3)
    out = 0
    for row in rows:
        for index in range(0, len(row), channels):
            rgb[out : out + 3] = row[index : index + 3]
            out += 3
    return width, height, bytes(rgb)


def unfilter(row: bytearray, previous: bytearray, filter_type: int, bpp: int) -> None:
    for index in range(len(row)):
        left = row[index - bpp] if index >= bpp else 0
        up = previous[index]
        upper_left = previous[index - bpp] if index >= bpp else 0
        if filter_type == 0:
            value = row[index]
        elif filter_type == 1:
            value = row[index] + left
        elif filter_type == 2:
            value = row[index] + up
        elif filter_type == 3:
            value = row[index] + ((left + up) // 2)
        elif filter_type == 4:
            value = row[index] + paeth(left, up, upper_left)
        else:
            raise ValueError(f"unsupported PNG filter type: {filter_type}")
        row[index] = value & 0xFF


def paeth(left: int, up: int, upper_left: int) -> int:
    estimate = left + up - upper_left
    distances = (
        abs(estimate - left),
        abs(estimate - up),
        abs(estimate - upper_left),
    )
    if distances[0] <= distances[1] and distances[0] <= distances[2]:
        return left
    if distances[1] <= distances[2]:
        return up
    return upper_left


def image_metrics(path: Path) -> dict[str, object]:
    width, height, pixels = read_image(path)
    pixel_count = width * height
    sum_r = sum_g = sum_b = 0
    sum_luma = 0.0
    sum_luma2 = 0.0
    nonblack = 0
    bright = 0
    saturated = 0
    sample_colors: set[tuple[int, int, int]] = set()
    edge_total = 0.0
    edge_count = 0
    previous_luma = None
    for pixel_index in range(pixel_count):
        offset = pixel_index * 3
        r = pixels[offset]
        g = pixels[offset + 1]
        b = pixels[offset + 2]
        luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
        sum_r += r
        sum_g += g
        sum_b += b
        sum_luma += luma
        sum_luma2 += luma * luma
        if r > 3 or g > 3 or b > 3:
            nonblack += 1
        if luma > 96:
            bright += 1
        if max(r, g, b) - min(r, g, b) > 48:
            saturated += 1
        if pixel_index % max(1, pixel_count // 4096) == 0:
            sample_colors.add((r, g, b))
        if previous_luma is not None and pixel_index % width != 0:
            edge_total += abs(luma - previous_luma)
            edge_count += 1
        previous_luma = luma
    mean_luma = sum_luma / pixel_count
    variance = max(0.0, (sum_luma2 / pixel_count) - mean_luma * mean_luma)
    return {
        "path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "modified_utc": modified_utc(path),
        "width": width,
        "height": height,
        "pixel_count": pixel_count,
        "mean_rgb": [sum_r / pixel_count, sum_g / pixel_count, sum_b / pixel_count],
        "mean_luma": mean_luma,
        "luma_std": math.sqrt(variance),
        "nonblack_ratio": nonblack / pixel_count,
        "bright_ratio": bright / pixel_count,
        "saturated_ratio": saturated / pixel_count,
        "sampled_color_count": len(sample_colors),
        "horizontal_edge_mean": edge_total / max(1, edge_count),
    }


def modified_utc(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")


def compare_metrics(native: dict[str, object], reference: dict[str, object] | None) -> dict[str, object] | None:
    if reference is None:
        return None
    keys = [
        "mean_luma",
        "luma_std",
        "nonblack_ratio",
        "bright_ratio",
        "saturated_ratio",
        "horizontal_edge_mean",
    ]
    return {
        key: abs(float(native[key]) - float(reference[key]))
        for key in keys
    }


def write_reports(
    native: dict[str, object] | None,
    reference: dict[str, object] | None,
    comparison: dict[str, object] | None,
    json_path: Path,
    markdown_path: Path,
    status: str,
) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "fluoddity.native_visual_metrics.v1",
        "status": status,
        "native": native,
        "python_reference": reference,
        "comparison": comparison,
        "note": "Coarse image metrics are regression evidence, not proof of exact visual parity.",
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Visual Metrics",
        "",
        f"- Status: {status}",
        "- Scope: coarse image metrics, not pixel parity",
        "",
    ]
    if native:
        lines.extend(metric_lines("Native", native))
    if reference:
        lines.extend(metric_lines("Python Reference", reference))
    else:
        lines.extend(
            [
                "## Python Reference",
                "",
                "- Missing. Run `python scripts/smoke_game_visual.py --trial 3 --start --feed --frame 90 --output artifacts/visual_smoke/trial3_running.png` in an environment with the visual-smoke dependencies installed.",
                "",
            ]
        )
    if comparison:
        lines.extend(["## Difference", ""])
        for key, value in comparison.items():
            lines.append(f"- `{key}`: {float(value):.6f}")
        lines.append("")
    lines.append("This report is intended to catch major renderer drift and missing evidence; exact Python/GLSL parity still requires stronger frame-level comparison.")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def metric_lines(title: str, metrics: dict[str, object]) -> list[str]:
    mean_rgb = metrics["mean_rgb"]
    assert isinstance(mean_rgb, list)
    return [
        f"## {title}",
        "",
        f"- Path: `{metrics['path']}`",
        f"- Modified UTC: {metrics['modified_utc']}",
        f"- Size: {metrics['width']}x{metrics['height']}",
        f"- Mean RGB: {float(mean_rgb[0]):.2f}, {float(mean_rgb[1]):.2f}, {float(mean_rgb[2]):.2f}",
        f"- Mean luma: {float(metrics['mean_luma']):.2f}",
        f"- Luma std: {float(metrics['luma_std']):.2f}",
        f"- Nonblack ratio: {float(metrics['nonblack_ratio']):.4f}",
        f"- Bright ratio: {float(metrics['bright_ratio']):.4f}",
        f"- Saturated ratio: {float(metrics['saturated_ratio']):.4f}",
        f"- Sampled colors: {metrics['sampled_color_count']}",
        f"- Horizontal edge mean: {float(metrics['horizontal_edge_mean']):.2f}",
        "",
    ]


def main() -> int:
    args = parse_args()
    native_path = resolve(args.native_image)
    reference_path = resolve(args.python_image)
    if args.run_native:
        native_path.parent.mkdir(parents=True, exist_ok=True)
        run_native_capture(native_path, args.no_build)
    if not native_path.exists():
        raise SystemExit(f"native image missing: {native_path}")
    native = image_metrics(native_path)
    reference = image_metrics(reference_path) if reference_path.exists() else None
    status = "compared" if reference else "reference-missing"
    comparison = compare_metrics(native, reference)
    write_reports(native, reference, comparison, args.json_output, args.markdown, status)
    print(f"native_visual_metrics_status={status}")
    print(f"native_visual_metrics_markdown={resolve(args.markdown)}")
    print(f"native_visual_metrics_json={resolve(args.json_output)}")
    if args.require_reference and reference is None:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
