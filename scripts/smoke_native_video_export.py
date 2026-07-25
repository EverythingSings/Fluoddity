"""Smoke-check the native Rust/wgpu high-resolution MP4 export path."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np

from native_runtime_tools import build_native_runtime, native_runtime_binary


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VIDEO = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.mp4"
DEFAULT_POSTER = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.ppm"
DEFAULT_EXPORT_REPORT = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.metadata.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_video_export_smoke.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_video_export_smoke.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate native high-resolution MP4 export.")
    parser.add_argument("--no-build", action="store_true", help="Use the newest existing native release binary.")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--frames", type=int, default=4)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--poster", type=Path, default=DEFAULT_POSTER)
    parser.add_argument("--export-report", type=Path, default=DEFAULT_EXPORT_REPORT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--skip-repeat", action="store_true", help="Skip the repeated export hash check.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_export(
    args: argparse.Namespace,
    binary: Path,
    *,
    video_path: Path | None = None,
    poster_path: Path | None = None,
    report_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    video_path = resolve(video_path or args.video)
    poster_path = resolve(poster_path or args.poster)
    report_path = resolve(report_path or args.export_report)
    command = [
        str(binary),
        "--trial",
        "artifacts/trial_definitions.json",
        "--trial-id",
        "rival_bloom",
        "--config",
        "physics_configs/Core/Bubbles.json",
        "--frames",
        str(args.frames),
        "--render-width",
        str(args.width),
        "--render-height",
        str(args.height),
        "--video-out",
        str(video_path),
        "--video-report",
        str(report_path),
        "--video-fps",
        str(args.fps),
        "--video-crf",
        "15",
        "--video-preset",
        "slow",
        "--out",
        str(poster_path),
    ]
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def run_collision_guard(
    args: argparse.Namespace,
    binary: Path,
    video_path: Path,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(binary),
        "--trial",
        "artifacts/trial_definitions.json",
        "--trial-id",
        "rival_bloom",
        "--config",
        "physics_configs/Core/Bubbles.json",
        "--frames",
        "1",
        "--render-width",
        str(args.width),
        "--render-height",
        str(args.height),
        "--video-out",
        str(video_path),
        "--out",
        str(video_path),
    ]
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def run_transaction_guard(binary: Path, parent: Path) -> dict[str, object]:
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="video-export-transaction-", dir=parent) as raw_directory:
        directory = Path(raw_directory)
        video_path = directory / "known-good.mp4"
        poster_path = directory / "blocked.ppm"
        report_path = directory / "guard.json"
        video_path.write_bytes(b"known-good-video-sentinel")
        poster_path.mkdir()
        before_hash = sha256_file(video_path)
        command = [
            str(binary),
            "--trial",
            "artifacts/trial_definitions.json",
            "--trial-id",
            "rival_bloom",
            "--config",
            "physics_configs/Core/Bubbles.json",
            "--frames",
            "1",
            "--render-width",
            "640",
            "--render-height",
            "360",
            "--video-out",
            str(video_path),
            "--video-report",
            str(report_path),
            "--video-fps",
            "60",
            "--video-preset",
            "ultrafast",
            "--out",
            str(poster_path),
        ]
        proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        after_hash = sha256_file(video_path) if video_path.is_file() else ""
        work_files = sorted(
            str(path.relative_to(directory))
            for path in directory.iterdir()
            if ".partial." in path.name or ".backup." in path.name
        )
        valid = (
            proc.returncode != 0
            and before_hash == after_hash
            and poster_path.is_dir()
            and not report_path.exists()
            and not work_files
            and "regular file" in proc.stderr
        )
        return {
            "status": "pass" if valid else "fail",
            "returncode": proc.returncode,
            "prior_video_preserved": before_hash == after_hash,
            "blocked_directory_preserved": poster_path.is_dir(),
            "report_published": report_path.exists(),
            "remaining_work_files": work_files,
            "stderr_tail": "\n".join(proc.stderr.splitlines()[-20:]),
        }


def probe_video(path: Path) -> tuple[dict[str, object], subprocess.CompletedProcess[str]]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}, subprocess.CompletedProcess(["ffprobe"], 127, "", "ffprobe was not found in PATH")
    command = [
        ffprobe,
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt,avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,duration,color_range,color_space,color_transfer,color_primaries",
        "-show_entries",
        "format=format_name,duration,size",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        return {}, proc
    return json.loads(proc.stdout), proc


def decode_complete_video(path: Path) -> subprocess.CompletedProcess[bytes]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return subprocess.CompletedProcess(["ffmpeg"], 127, b"", b"ffmpeg was not found in PATH")
    return subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        cwd=ROOT,
        capture_output=True,
    )


def decode_frame(path: Path, frame_index: int) -> subprocess.CompletedProcess[bytes]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return subprocess.CompletedProcess(["ffmpeg"], 127, b"", b"ffmpeg was not found in PATH")
    return subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"select=eq(n\\,{frame_index})",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        cwd=ROOT,
        capture_output=True,
    )


def read_ppm_rgb(path: Path) -> tuple[int, int, bytes]:
    parts = path.read_bytes().split(b"\n", 3)
    if len(parts) != 4 or parts[0] != b"P6" or parts[2] != b"255":
        raise ValueError("poster is not a supported binary PPM")
    width_text, height_text = parts[1].split()
    width, height = int(width_text), int(height_text)
    pixels = parts[3]
    expected = width * height * 3
    if len(pixels) != expected:
        raise ValueError(f"poster contains {len(pixels)} RGB bytes; expected {expected}")
    return width, height, pixels


def compare_poster_to_video(
    poster_path: Path,
    video_path: Path,
    frame_index: int,
) -> tuple[dict[str, object], subprocess.CompletedProcess[bytes]]:
    poster_width, poster_height, poster_rgb = read_ppm_rgb(poster_path)
    decoded = decode_frame(video_path, frame_index)
    expected_bytes = poster_width * poster_height * 3
    if decoded.returncode != 0 or len(decoded.stdout) != expected_bytes:
        return {
            "valid": False,
            "poster_width": poster_width,
            "poster_height": poster_height,
            "decoded_bytes": len(decoded.stdout),
            "expected_bytes": expected_bytes,
        }, decoded
    poster_array = np.frombuffer(poster_rgb, dtype=np.uint8).astype(np.float32)
    decoded_array = np.frombuffer(decoded.stdout, dtype=np.uint8).astype(np.float32)
    delta = poster_array - decoded_array
    mse = float(np.mean(delta * delta))
    psnr = math.inf if mse == 0.0 else 10.0 * math.log10((255.0 * 255.0) / mse)
    mean_absolute_error = float(np.mean(np.abs(delta)))
    return {
        "valid": psnr >= 30.0,
        "poster_width": poster_width,
        "poster_height": poster_height,
        "decoded_bytes": len(decoded.stdout),
        "expected_bytes": expected_bytes,
        "mse": mse,
        "psnr_db": psnr,
        "mean_absolute_error": mean_absolute_error,
        "minimum_psnr_db": 30.0,
    }, decoded


def check_faststart(path: Path) -> dict[str, object]:
    prefix = path.read_bytes()[: 4 * 1024 * 1024]
    moov_offset = prefix.find(b"moov")
    mdat_offset = prefix.find(b"mdat")
    return {
        "moov_offset": moov_offset,
        "mdat_offset": mdat_offset,
        "valid": moov_offset >= 0 and mdat_offset >= 0 and moov_offset < mdat_offset,
    }


def validate(
    args: argparse.Namespace,
    export_proc: subprocess.CompletedProcess[str],
    probe: dict[str, object],
    probe_proc: subprocess.CompletedProcess[str],
) -> tuple[list[str], dict[str, object]]:
    failures: list[str] = []
    video = resolve(args.video)
    poster = resolve(args.poster)
    export_report = resolve(args.export_report)
    if export_proc.returncode != 0:
        failures.append(f"native exporter exited with {export_proc.returncode}")
    for path, label in [(video, "MP4"), (poster, "poster PPM"), (export_report, "export report")]:
        if not path.exists() or path.stat().st_size <= 0:
            failures.append(f"{label} was not created as a non-empty file")

    stream: dict[str, object] = {}
    container: dict[str, object] = {}
    if probe_proc.returncode != 0:
        failures.append(f"ffprobe exited with {probe_proc.returncode}")
    else:
        streams = probe.get("streams", [])
        if not isinstance(streams, list) or len(streams) != 1:
            failures.append("ffprobe did not return exactly one video stream")
        else:
            stream = streams[0]
        container = probe.get("format", {}) if isinstance(probe.get("format"), dict) else {}

    expected_duration = args.frames / args.fps
    if stream:
        checks = {
            "codec": stream.get("codec_name") == "h264",
            "width": stream.get("width") == args.width,
            "height": stream.get("height") == args.height,
            "pixel_format": stream.get("pix_fmt") == "yuv420p",
            "frame_count": int(stream.get("nb_read_frames", stream.get("nb_frames", -1))) == args.frames,
            "fps": Fraction(str(stream.get("avg_frame_rate", "0/1"))) == Fraction(args.fps, 1),
            "duration": abs(float(stream.get("duration", -1.0)) - expected_duration) <= 0.5 / args.fps,
            "color_range": stream.get("color_range") == "tv",
            "color_space": stream.get("color_space") == "bt709",
            "color_transfer": stream.get("color_transfer") == "bt709",
            "color_primaries": stream.get("color_primaries") == "bt709",
        }
        failures.extend(f"ffprobe {name} mismatch" for name, valid in checks.items() if not valid)
    else:
        checks = {}

    metadata: dict[str, object] = {}
    if export_report.exists():
        metadata = json.loads(export_report.read_text(encoding="utf-8"))
        render = metadata.get("render", {})
        video_meta = metadata.get("video", {})
        timeline = metadata.get("timeline", {})
        metadata_checks = {
            "status": metadata.get("status") == "pass",
            "schema": metadata.get("schema") == "fluoddity.native_video_export.v1",
            "width": render.get("width") == args.width,
            "height": render.get("height") == args.height,
            "presentation": render.get("captures_final_presentation") is True,
            "fps": video_meta.get("fps") == args.fps,
            "frames": video_meta.get("frames") == args.frames,
            "crf": video_meta.get("crf") == 15,
            "preset": video_meta.get("preset") == "slow",
            "color_space": video_meta.get("color_space") == "bt709",
            "simulation_hz": timeline.get("simulation_hz") == 60,
            "simulation_ticks": timeline.get("simulation_ticks")
            == math.ceil(args.frames * 60 / args.fps),
        }
        failures.extend(f"export report {name} mismatch" for name, valid in metadata_checks.items() if not valid)
    else:
        metadata_checks = {}

    faststart = check_faststart(video) if video.exists() else {"valid": False}
    if not faststart["valid"]:
        failures.append("MP4 moov atom is not ahead of mdat; faststart was not proven")

    complete_decode = (
        decode_complete_video(video)
        if video.exists()
        else subprocess.CompletedProcess([], 1, b"", b"missing video")
    )
    if complete_decode.returncode != 0:
        failures.append(f"full MP4 decode exited with {complete_decode.returncode}")

    fidelity: dict[str, object] = {"valid": False}
    frame_decode = subprocess.CompletedProcess([], 1, b"", b"missing poster or video")
    if poster.exists() and video.exists():
        try:
            fidelity, frame_decode = compare_poster_to_video(poster, video, args.frames - 1)
        except (OSError, ValueError) as error:
            fidelity = {"valid": False, "error": str(error)}
    if not fidelity.get("valid"):
        failures.append("decoded final MP4 frame does not match the final presentation-pass poster")

    work_files: list[Path] = []
    for output_path in (video, poster, export_report):
        if output_path.parent.exists():
            work_files.extend(
                path
                for path in output_path.parent.glob(f".{output_path.name}.*")
                if ".partial." in path.name or ".backup." in path.name
            )
    work_files = sorted(set(work_files))
    if work_files:
        failures.append("temporary partial or backup files remain after successful export")

    evidence = {
        "ffprobe_stream": stream,
        "ffprobe_format": container,
        "stream_checks": checks,
        "metadata_checks": metadata_checks,
        "faststart": faststart,
        "complete_decode_returncode": complete_decode.returncode,
        "complete_decode_stderr": complete_decode.stderr.decode("utf-8", errors="replace"),
        "frame_decode_returncode": frame_decode.returncode,
        "frame_decode_stderr": frame_decode.stderr.decode("utf-8", errors="replace"),
        "final_frame_fidelity": fidelity,
        "remaining_work_files": [str(path) for path in work_files],
        "expected_duration_seconds": expected_duration,
    }
    return failures, evidence


def write_reports(payload: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Native Video Export Smoke",
        "",
        f"- Status: {payload['status']}",
        f"- Output: `{payload['video']['path']}`",
        f"- Resolution: {payload['video']['width']}x{payload['video']['height']}",
        f"- Frame rate: {payload['video']['fps']} fps",
        f"- Frames: {payload['video']['frames']}",
        f"- Codec: {payload['probe'].get('ffprobe_stream', {}).get('codec_name', 'missing')}",
        f"- Pixel format: {payload['probe'].get('ffprobe_stream', {}).get('pix_fmt', 'missing')}",
        f"- Color: {payload['probe'].get('ffprobe_stream', {}).get('color_space', 'missing')} / {payload['probe'].get('ffprobe_stream', {}).get('color_range', 'missing')}",
        f"- Faststart: {'yes' if payload['probe'].get('faststart', {}).get('valid') else 'no'}",
        f"- Final-frame PSNR: {float(payload['probe'].get('final_frame_fidelity', {}).get('psnr_db', 0.0)):.2f} dB",
        f"- Repeat determinism: {payload['repeat_export']['status']}",
        f"- Collision guard: {payload['collision_guard']['status']}",
        f"- Transaction rollback guard: {payload['transaction_guard']['status']}",
        f"- SHA-256: `{payload['video'].get('sha256', 'missing')}`",
        "",
        "## Failures",
        "",
    ]
    failures = payload["failures"]
    lines.extend(f"- {failure}" for failure in failures)
    if not failures:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "This smoke proves a native offscreen GPU frame path through the final presentation shader and a probed MP4 artifact. It does not replace a long-form quality review or Steam Deck hardware export.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.no_build:
        build_native_runtime()
    binary = native_runtime_binary()
    export_proc = run_export(args, binary)
    video = resolve(args.video)
    probe, probe_proc = probe_video(video) if video.exists() else ({}, subprocess.CompletedProcess([], 1, "", "missing video"))
    failures, evidence = validate(args, export_proc, probe, probe_proc)
    repeat: dict[str, object] = {"status": "skipped"}
    if not args.skip_repeat and video.exists():
        repeat_video = video.with_name(f"{video.stem}.repeat.mp4")
        repeat_poster = resolve(args.poster).with_name(f"{resolve(args.poster).stem}.repeat.ppm")
        repeat_report = resolve(args.export_report).with_name(
            f"{resolve(args.export_report).stem}.repeat.json"
        )
        repeat_proc = run_export(
            args,
            binary,
            video_path=repeat_video,
            poster_path=repeat_poster,
            report_path=repeat_report,
        )
        primary_hash = sha256_file(video)
        repeat_hash = sha256_file(repeat_video) if repeat_video.exists() else ""
        primary_poster_hash = sha256_file(resolve(args.poster)) if resolve(args.poster).exists() else ""
        repeat_poster_hash = sha256_file(repeat_poster) if repeat_poster.exists() else ""
        repeat_valid = (
            repeat_proc.returncode == 0
            and primary_hash == repeat_hash
            and primary_poster_hash == repeat_poster_hash
        )
        if not repeat_valid:
            failures.append("repeated native export was not byte-for-byte deterministic")
        repeat = {
            "status": "pass" if repeat_valid else "fail",
            "returncode": repeat_proc.returncode,
            "video": str(repeat_video),
            "video_sha256": repeat_hash,
            "poster": str(repeat_poster),
            "poster_sha256": repeat_poster_hash,
            "stdout_tail": "\n".join(repeat_proc.stdout.splitlines()[-20:]),
            "stderr_tail": "\n".join(repeat_proc.stderr.splitlines()[-20:]),
        }

    before_collision_hash = sha256_file(video) if video.exists() else ""
    collision_proc = run_collision_guard(args, binary, video)
    after_collision_hash = sha256_file(video) if video.exists() else ""
    collision_valid = (
        collision_proc.returncode != 0
        and before_collision_hash
        and before_collision_hash == after_collision_hash
        and "must be distinct paths" in collision_proc.stderr
    )
    if not collision_valid:
        failures.append("output path collision guard did not reject safely")
    collision_guard = {
        "status": "pass" if collision_valid else "fail",
        "returncode": collision_proc.returncode,
        "artifact_preserved": before_collision_hash == after_collision_hash,
        "stderr_tail": "\n".join(collision_proc.stderr.splitlines()[-20:]),
    }
    transaction_guard = run_transaction_guard(binary, video.parent)
    if transaction_guard["status"] != "pass":
        failures.append("transactional publication did not preserve the prior export")
    payload = {
        "schema": "fluoddity.native_video_export_smoke.v1",
        "status": "pass" if not failures else "fail",
        "native_binary": str(binary),
        "video": {
            "path": str(video),
            "bytes": video.stat().st_size if video.exists() else 0,
            "sha256": sha256_file(video) if video.exists() else "",
            "width": args.width,
            "height": args.height,
            "fps": args.fps,
            "frames": args.frames,
        },
        "poster": str(resolve(args.poster)),
        "export_report": str(resolve(args.export_report)),
        "export_returncode": export_proc.returncode,
        "export_stdout_tail": "\n".join(export_proc.stdout.splitlines()[-30:]),
        "export_stderr_tail": "\n".join(export_proc.stderr.splitlines()[-30:]),
        "ffprobe_returncode": probe_proc.returncode,
        "ffprobe_stderr": probe_proc.stderr,
        "probe": evidence,
        "repeat_export": repeat,
        "collision_guard": collision_guard,
        "transaction_guard": transaction_guard,
        "failures": failures,
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_video_export_smoke_status={payload['status']}")
    print(f"native_video_export_smoke_video={video}")
    print(f"native_video_export_smoke_json={resolve(args.json_output)}")
    print(f"native_video_export_smoke_markdown={resolve(args.markdown)}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
