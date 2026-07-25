"""Build and smoke the Rust/wgpu package-local native runtime."""
from __future__ import annotations

import argparse
import platform
import hashlib
import json
import re
import shutil
import subprocess
import datetime as dt
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = ROOT / "dist" / "FluoddityNative"
DEFAULT_JSON = ROOT / "artifacts" / "native_package_smoke.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_package_smoke.md"
DEFAULT_PACKAGE_MANIFEST_JSON = ROOT / "artifacts" / "native_package_manifest.json"
DEFAULT_PACKAGE_MANIFEST_MARKDOWN = ROOT / "artifacts" / "native_package_manifest.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and smoke the packaged native runtime.")
    parser.add_argument("--package-dir", type=Path, default=PACKAGE_DIR, help="Native package output directory.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--package-manifest-json", type=Path, default=DEFAULT_PACKAGE_MANIFEST_JSON, help="Package content manifest JSON path.")
    parser.add_argument("--package-manifest-markdown", type=Path, default=DEFAULT_PACKAGE_MANIFEST_MARKDOWN, help="Package content manifest Markdown path.")
    parser.add_argument("--frames", type=int, default=24, help="Package-local headless frames.")
    parser.add_argument("--max-window-frames", type=int, default=5, help="Package-local bounded Deck-profile window frames.")
    parser.add_argument("--skip-window", action="store_true", help="Skip package-local Deck-profile window smoke.")
    parser.add_argument(
        "--video-seconds",
        type=float,
        default=2.0 / 60.0,
        help="Duration of the package-wrapper 4K/60 export smoke (default: two frames).",
    )
    parser.add_argument("--ffprobe", default="", help="Optional ffprobe path for packaged MP4 validation.")
    parser.add_argument("--no-build", action="store_true", help="Skip package assembly and smoke an existing package.")
    parser.add_argument("--no-sign", action="store_true", help="Pass -NoSign to the Windows package script.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def run_command(command: list[str], cwd: Path) -> dict[str, object]:
    proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    return {
        "command": subprocess.list2cmdline(command),
        "cwd": str(cwd),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def build_package(package_dir: Path, no_sign: bool) -> dict[str, object]:
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "runtime" / "rust-wgpu-spike" / "scripts" / "package-windows.ps1"),
        "-OutputDir",
        package_dir.relative_to(ROOT).as_posix() if package_dir.is_relative_to(ROOT) else str(package_dir),
    ]
    if no_sign:
        command.append("-NoSign")
    return run_command(command, ROOT)


def smoke_headless(package_dir: Path, frames: int) -> dict[str, object]:
    return run_command(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(package_dir / "run_headless.ps1"),
            "-Frames",
            str(frames),
        ],
        package_dir,
    )


def smoke_window(package_dir: Path, max_window_frames: int) -> dict[str, object]:
    return run_command(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(package_dir / "run_deck_profile.ps1"),
            "-MaxWindowFrames",
            str(max_window_frames),
        ],
        package_dir,
    )


def smoke_input_contract(package_dir: Path) -> dict[str, object]:
    return run_command(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(package_dir / "run_input_contract.ps1"),
        ],
        package_dir,
    )


def smoke_input_runtime(package_dir: Path) -> dict[str, object]:
    return run_command(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(package_dir / "run_input_runtime.ps1"),
        ],
        package_dir,
    )


def smoke_video_export(
    package_dir: Path,
    seconds: float,
    ffprobe_override: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    smoke_cwd = ROOT / "artifacts" / "native package video smoke" / "unrelated working directory"
    relative_video = Path("exports with spaces") / "packaged native 4k60.mp4"
    video_path = smoke_cwd / relative_video
    report_path = video_path.with_suffix(".json")
    smoke_cwd.mkdir(parents=True, exist_ok=True)
    video_path.parent.mkdir(parents=True, exist_ok=True)
    for path in [video_path, report_path]:
        if path.exists():
            path.unlink()

    wrapper_command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(package_dir / "run_export_video.ps1"),
        "-Seconds",
        format(seconds, ".17g"),
        "-Width",
        "3840",
        "-Height",
        "2160",
        "-Fps",
        "60",
        "-Crf",
        "15",
        "-Preset",
        "ultrafast",
        "-OutputPath",
        str(relative_video),
    ]
    wrapper = run_command(wrapper_command, smoke_cwd)
    commands = [{"name": "video_export_wrapper", **trim_command_result(wrapper)}]

    ffprobe_path = ffprobe_override or shutil.which("ffprobe") or ""
    probe_payload: dict[str, object] = {}
    probe: dict[str, object] = {
        "path": ffprobe_path,
        "returncode": None,
    }
    if ffprobe_path and video_path.exists():
        probe_command = [
            ffprobe_path,
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,pix_fmt,avg_frame_rate,nb_read_frames,color_range,color_space,color_transfer,color_primaries",
            "-of",
            "json",
            str(video_path),
        ]
        probe_result = run_command(probe_command, smoke_cwd)
        commands.append({"name": "video_ffprobe", **trim_command_result(probe_result)})
        probe["returncode"] = probe_result["returncode"]
        if probe_result["returncode"] == 0:
            try:
                probe_payload = json.loads(str(probe_result["stdout"]))
            except json.JSONDecodeError:
                probe_payload = {}
    decode: dict[str, object] = {"returncode": None}
    packaged_ffmpeg = package_dir / "ffmpeg.exe"
    if packaged_ffmpeg.exists() and video_path.exists():
        decode_result = run_command(
            [
                str(packaged_ffmpeg),
                "-v",
                "error",
                "-i",
                str(video_path),
                "-map",
                "0:v:0",
                "-f",
                "null",
                "-",
            ],
            smoke_cwd,
        )
        commands.append({"name": "video_full_decode", **trim_command_result(decode_result)})
        decode["returncode"] = decode_result["returncode"]

    metadata: dict[str, object] = {}
    if report_path.exists():
        try:
            metadata = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
    streams = probe_payload.get("streams", []) if isinstance(probe_payload, dict) else []
    stream = streams[0] if isinstance(streams, list) and len(streams) == 1 else {}
    render = metadata.get("render", {}) if isinstance(metadata, dict) else {}
    video = metadata.get("video", {}) if isinstance(metadata, dict) else {}
    timeline = metadata.get("timeline", {}) if isinstance(metadata, dict) else {}
    expected_frames = max(1, round(seconds * 60))
    probe_checks = {
        "codec": stream.get("codec_name") == "h264",
        "width": stream.get("width") == 3840,
        "height": stream.get("height") == 2160,
        "pixel_format": stream.get("pix_fmt") == "yuv420p",
        "fps": _fraction(stream.get("avg_frame_rate")) == Fraction(60, 1),
        "frames": _int_or_default(stream.get("nb_read_frames"), -1) == expected_frames,
        "color_primaries": stream.get("color_primaries") == "bt709",
        "color_transfer": stream.get("color_transfer") == "bt709",
        "color_space": stream.get("color_space") == "bt709",
        "color_range": stream.get("color_range") == "tv",
    }
    metadata_checks = {
        "schema": metadata.get("schema") == "fluoddity.native_video_export.v1",
        "status": metadata.get("status") == "pass",
        "output_path": bool(metadata.get("output"))
        and Path(str(metadata.get("output"))).resolve() == video_path.resolve(),
        "output_bytes": metadata.get("output_bytes")
        == (video_path.stat().st_size if video_path.exists() else -1),
        "width": render.get("width") == 3840,
        "height": render.get("height") == 2160,
        "final_presentation": render.get("captures_final_presentation") is True,
        "fps": video.get("fps") == 60,
        "frames": video.get("frames") == expected_frames,
        "codec": video.get("codec") == "h264",
        "pixel_format": video.get("pixel_format") == "yuv420p",
        "timeline_mode": timeline.get("mode") == "offline-fixed-step",
        "deterministic": timeline.get("deterministic_frame_rate") is True,
        "simulation_hz": timeline.get("simulation_hz") == 60,
    }
    remaining_partials = [
        path.name
        for path in video_path.parent.glob(f".{video_path.name}.*.partial.mp4")
    ]
    path_with_spaces = " " in str(video_path)
    outside_package = not video_path.is_relative_to(package_dir)
    caller_relative_resolved = video_path == (smoke_cwd / relative_video).resolve()
    valid = (
        wrapper["returncode"] == 0
        and video_path.exists()
        and video_path.stat().st_size > 0
        and report_path.exists()
        and report_path.stat().st_size > 0
        and all(probe_checks.values())
        and all(metadata_checks.values())
        and decode.get("returncode") == 0
        and _faststart(video_path)
        and not remaining_partials
        and path_with_spaces
        and outside_package
        and caller_relative_resolved
    )
    result = {
        "valid": valid,
        "evidence_scope": "local-windows-package-wrapper",
        "package_target": "windows",
        "steam_deck_hardware_verified": False,
        "working_directory": str(smoke_cwd),
        "caller_relative_output": relative_video.as_posix(),
        "path_with_spaces": path_with_spaces,
        "outside_package": outside_package,
        "caller_relative_resolved": caller_relative_resolved,
        "video": {
            "path": str(video_path),
            "exists": video_path.exists(),
            "bytes": video_path.stat().st_size if video_path.exists() else 0,
            "sha256": sha256_file(video_path) if video_path.exists() else "",
            "faststart": _faststart(video_path),
        },
        "report": {
            "path": str(report_path),
            "exists": report_path.exists(),
            "schema": metadata.get("schema"),
            "timeline_mode": timeline.get("mode"),
        },
        "probe": {
            **probe,
            "stream": stream,
            "checks": probe_checks,
        },
        "metadata_checks": metadata_checks,
        "full_decode": decode,
        "remaining_partials": remaining_partials,
    }
    return result, commands


def _fraction(value: object) -> Fraction:
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return Fraction(0, 1)


def _int_or_default(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _faststart(path: Path) -> bool:
    if not path.exists():
        return False
    data = path.read_bytes()
    moov = data.find(b"moov")
    mdat = data.find(b"mdat")
    return moov >= 0 and mdat >= 0 and moov < mdat


def validate_package_files(package_dir: Path) -> list[str]:
    required = [
        "XenocultureTrialDish.exe",
        "fluoddity-wgpu-spike.exe",
        "ffmpeg.exe",
        "artifacts/trial_definitions.json",
        "physics_configs/Core/Bubbles.json",
        "run_headless.ps1",
        "run_export_video.ps1",
        "run_export_video.sh",
        "run_record_video.ps1",
        "run_record_video.sh",
        "run_steam_deck.ps1",
        "run_steam_deck.sh",
        "run_deck_profile.ps1",
        "run_deck_profile.sh",
        "run_input_contract.ps1",
        "run_input_contract.sh",
        "run_input_runtime.ps1",
        "run_input_runtime.sh",
        "PACKAGE_README.md",
        "third_party/ffmpeg/LICENSE",
        "third_party/ffmpeg/PROVENANCE.txt",
        "steam_input/README.md",
        "steam_input/steam_input_manifest.vdf",
        "steam_input/trial_prompt_glyph_map.json",
        "steam_input/steam_input_handoff.md",
        "steam_input/glyphs/a.svg",
        "steam_input/glyphs/r2.svg",
        "steam_input/glyphs/right_stick.svg",
        "steam_input/glyphs/menu.svg",
    ]
    failures = []
    for relative in required:
        path = package_dir / relative
        if not path.exists():
            failures.append(f"missing package file: {relative}")
        elif path.is_file() and path.stat().st_size <= 0:
            failures.append(f"empty package file: {relative}")
    launch_wrappers = ["run_steam_deck.ps1", "run_steam_deck.sh"]
    for relative in launch_wrappers:
        path = package_dir / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "--window" not in text:
            failures.append(f"Steam launch wrapper should open the native window: {relative}")
        if "--max-window-frames" in text or "--deck-profile" in text:
            failures.append(f"Steam launch wrapper should not be a bounded timing smoke: {relative}")
        if relative.endswith(".ps1") and "XenocultureTrialDish.exe" not in text:
            failures.append(f"Windows Steam launch wrapper should use the Steam-facing executable alias: {relative}")
        if relative.endswith(".sh") and "fluoddity-wgpu-spike" in text:
            failures.append(f"Deck/Linux Steam launch wrapper should not fall back to the compatibility binary: {relative}")
    video_wrappers = {
        "run_export_video.ps1": {"window": False, "ffmpeg": "ffmpeg.exe"},
        "run_export_video.sh": {"window": False, "ffmpeg": "/ffmpeg"},
        "run_record_video.ps1": {"window": True, "ffmpeg": "ffmpeg.exe"},
        "run_record_video.sh": {"window": True, "ffmpeg": "/ffmpeg"},
    }
    for relative, expected in video_wrappers.items():
        path = package_dir / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "--video-out" not in text or "--video-report" not in text:
            failures.append(f"video wrapper should write MP4 and JSON outputs: {relative}")
        if "--render-width" not in text or "3840" not in text or "2160" not in text or "60" not in text:
            failures.append(f"video wrapper should expose 4K/60 defaults: {relative}")
        if str(expected["ffmpeg"]) not in text:
            failures.append(f"video wrapper should select the packaged FFmpeg: {relative}")
        if bool("--window" in text) is not expected["window"]:
            failures.append(f"video wrapper window/export mode mismatch: {relative}")
        if "fluoddity-wgpu-spike" in text:
            failures.append(f"video wrapper should use the Steam-facing executable alias: {relative}")
    package_readme = package_dir / "PACKAGE_README.md"
    if package_readme.exists():
        package_readme_text = package_readme.read_text(encoding="utf-8").lower()
        if "not a wall-clock" not in package_readme_text:
            failures.append(
                "package README should identify window recording as frame capture, not wall-clock recording"
            )
        if "fixed 60 hz" not in package_readme_text and "fixed 60-hz" not in package_readme_text:
            failures.append("package README should identify the offline export fixed 60 Hz timeline")
    packaged_presets = {path.name for path in (package_dir / "physics_configs" / "Core").glob("*.json")}
    source_presets = {path.name for path in (ROOT / "physics_configs" / "Core").glob("*.json")}
    if packaged_presets != source_presets:
        missing = ", ".join(sorted(source_presets - packaged_presets))
        extra = ", ".join(sorted(packaged_presets - source_presets))
        failures.append(f"packaged Core preset set mismatch; missing=[{missing}] extra=[{extra}]")
    failures.extend(validate_packaged_steam_input(package_dir))
    return failures


def quoted_values(text: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', text))


def validate_packaged_steam_input(package_dir: Path) -> list[str]:
    failures: list[str] = []
    steam_input_dir = package_dir / "steam_input"
    manifest = steam_input_dir / "steam_input_manifest.vdf"
    glyph_map_path = steam_input_dir / "trial_prompt_glyph_map.json"
    handoff = steam_input_dir / "steam_input_handoff.md"
    if not manifest.exists() or not glyph_map_path.exists() or not handoff.exists():
        return failures
    manifest_values = quoted_values(manifest.read_text(encoding="utf-8"))
    required_actions = {
        "TrialDish",
        "AimNutrientGel",
        "ApplyNutrientGel",
        "StartExperiment",
        "PauseExperiment",
    }
    missing_actions = sorted(required_actions - manifest_values)
    if missing_actions:
        failures.append(f"packaged Steam Input manifest missing actions: {', '.join(missing_actions)}")
    glyph_map = json.loads(glyph_map_path.read_text(encoding="utf-8"))
    if glyph_map.get("schema_version") != 1:
        failures.append("packaged Steam Input glyph map schema_version should be 1")
    for action in ["AimNutrientGel", "ApplyNutrientGel", "StartExperiment", "PauseExperiment"]:
        entry = glyph_map.get("actions", {}).get(action, {})
        glyph_asset = entry.get("glyph_asset", "")
        if not glyph_asset:
            failures.append(f"packaged glyph map missing asset for {action}")
            continue
        packaged_asset = package_dir / glyph_asset
        if not packaged_asset.exists():
            failures.append(f"packaged glyph asset missing for {action}: {glyph_asset}")
    handoff_text = handoff.read_text(encoding="utf-8")
    if "Steam Input Handoff" not in handoff_text or "TrialDish" not in handoff_text:
        failures.append("packaged Steam Input handoff should include TrialDish import checklist")
    return failures


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_manifest(package_dir: Path) -> dict[str, object]:
    artifacts = []
    total_bytes = 0
    for path in sorted(p for p in package_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(package_dir).as_posix()
        size = path.stat().st_size
        total_bytes += size
        artifacts.append(
            {
                "path": relative,
                "bytes": size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema": "fluoddity.native_package_manifest.v1",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "package_dir": package_dir.relative_to(ROOT).as_posix() if package_dir.is_relative_to(ROOT) else str(package_dir),
        "file_count": len(artifacts),
        "total_bytes": total_bytes,
        "artifacts": artifacts,
    }


def write_package_manifest(manifest: dict[str, object], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Native Package Manifest",
        "",
        f"- Package: `{manifest['package_dir']}`",
        f"- Files: {manifest['file_count']}",
        f"- Total bytes: {manifest['total_bytes']}",
        "",
        "## Files",
        "",
    ]
    for artifact in manifest["artifacts"]:
        lines.append(f"- `{artifact['path']}` ({artifact['bytes']} bytes) `{artifact['sha256']}`")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def parse_headless(output: str, frames: int) -> dict[str, object]:
    result: dict[str, object] = {}
    frame = re.search(
        r"wgpu_spike_result trials=(?P<trials>\d+) frames=(?P<frames>\d+) "
        r"(?:width=(?P<width>\d+) height=(?P<height>\d+) particles=(?P<particles>\d+) )?"
        r"avg_fps=(?P<fps>[0-9.]+) avg_frame_ms=(?P<ms>[0-9.]+) "
        r"nonblank_pixels=(?P<nonblank>\d+) output=(?P<output>.+)",
        output,
    )
    if frame:
        result["frame_result"] = {
            "trial_count": int(frame.group("trials")),
            "frames": int(frame.group("frames")),
            "width": int(frame.group("width")) if frame.group("width") else None,
            "height": int(frame.group("height")) if frame.group("height") else None,
            "particle_count": int(frame.group("particles")) if frame.group("particles") else None,
            "avg_fps": float(frame.group("fps")),
            "avg_frame_ms": float(frame.group("ms")),
            "nonblank_pixels": int(frame.group("nonblank")),
            "output": frame.group("output").strip(),
        }
    state = re.search(
        r"trial_runtime_state status=(?P<status>\d+) progress=(?P<progress>[0-9.]+) active_zones=(?P<active>\d+) rival_zones=(?P<rival>\d+) elapsed_seconds=(?P<elapsed>[0-9.]+)",
        output,
    )
    if state:
        result["trial_runtime"] = {
            "status": int(state.group("status")),
            "progress": float(state.group("progress")),
            "active_zones": int(state.group("active")),
            "rival_zones": int(state.group("rival")),
            "elapsed_seconds": float(state.group("elapsed")),
        }
    result["valid"] = (
        result.get("frame_result", {}).get("frames") == frames
        and result.get("frame_result", {}).get("nonblank_pixels", 0) > 0
        and result.get("frame_result", {}).get("width") in {None, 1280}
        and result.get("frame_result", {}).get("height") in {None, 800}
        and (
            result.get("frame_result", {}).get("particle_count") is None
            or result.get("frame_result", {}).get("particle_count", 0) > 0
        )
        and result.get("trial_runtime", {}).get("status") == 1
    )
    return result


def parse_window(output: str, package_dir: Path) -> dict[str, object]:
    timing_path = package_dir / "artifacts" / "wgpu_deck_timing.json"
    result: dict[str, object] = {
        "timing_path": timing_path.relative_to(ROOT).as_posix() if timing_path.is_relative_to(ROOT) else str(timing_path),
        "timing_exists": timing_path.exists(),
    }
    timing = re.search(
        r"wgpu_window_timing frames=(?P<frames>\d+) avg_fps=(?P<fps>[0-9.]+) avg_frame_ms=(?P<ms>[0-9.]+) worst_frame_ms=(?P<worst>[0-9.]+)",
        output,
    )
    if timing:
        result["window_timing"] = {
            "frames": int(timing.group("frames")),
            "avg_fps": float(timing.group("fps")),
            "avg_frame_ms": float(timing.group("ms")),
            "worst_frame_ms": float(timing.group("worst")),
        }
    if timing_path.exists():
        payload = json.loads(timing_path.read_text(encoding="utf-8"))
        result["timing_report"] = {
            "profile": payload.get("profile"),
            "width": payload.get("width"),
            "height": payload.get("height"),
            "frames": payload.get("frames"),
            "trial_id": payload.get("trial_id"),
            "trial_runtime_present": payload.get("trial_runtime") is not None,
        }
    result["valid"] = bool(result.get("window_timing")) and result["timing_exists"] and result.get("timing_report", {}).get("trial_runtime_present") is True
    return result


def parse_input_contract(package_dir: Path) -> dict[str, object]:
    path = package_dir / "artifacts" / "native_input_contract.json"
    result: dict[str, object] = {
        "path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "exists": path.exists(),
    }
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        actions = {action.get("action"): action for action in payload.get("actions", [])}
        result.update(
            {
                "schema": payload.get("schema"),
                "input_backend": payload.get("input_backend"),
                "has_right_stick": payload.get("cursor", {}).get("axis_x") == "RightStickX"
                and payload.get("cursor", {}).get("axis_y") == "RightStickY",
                "has_start": "South" in actions.get("StartOrResume", {}).get("buttons", []),
                "has_apply": "RightTrigger2" in actions.get("ApplyNutrientGel", {}).get("buttons", []),
                "has_pause": "Start" in actions.get("PauseToggle", {}).get("buttons", []),
            }
        )
    result["valid"] = (
        result.get("schema") == "fluoddity.native_input_contract.v1"
        and result.get("input_backend") == "gilrs"
        and result.get("has_right_stick") is True
        and result.get("has_start") is True
        and result.get("has_apply") is True
        and result.get("has_pause") is True
    )
    return result


def parse_input_runtime(package_dir: Path) -> dict[str, object]:
    path = package_dir / "artifacts" / "native_input_runtime.json"
    result: dict[str, object] = {
        "path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
        "exists": path.exists(),
    }
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        checks = payload.get("checks", {})
        result.update(
            {
                "schema": payload.get("schema"),
                "status": payload.get("status"),
                "all_checks_passed": all(
                    checks.get(name) is True
                    for name in [
                        "briefing_starts_paused",
                        "south_starts_running",
                        "r2_applies_when_running",
                        "pause_suppresses_apply",
                        "resume_restores_running",
                        "right_stick_moves_cursor",
                    ]
                ),
                "cursor_delta": payload.get("cursor_delta", {}),
            }
        )
    result["valid"] = (
        result.get("schema") == "fluoddity.native_input_runtime_smoke.v1"
        and result.get("status") == "pass"
        and result.get("all_checks_passed") is True
    )
    return result


def parse_gpu_scope(output: str) -> dict[str, object]:
    match = re.search(
        r'wgpu_adapter name="(?P<name>[^"]+)" backend=(?P<backend>\S+) device_type=(?P<device_type>\S+)',
        output,
    )
    return {
        "host_os": platform.platform(),
        "host_system": platform.system(),
        "host_architecture": platform.machine(),
        "package_target": "windows",
        "gpu_adapter": match.group("name") if match else "",
        "wgpu_backend": match.group("backend") if match else "",
        "device_type": match.group("device_type") if match else "",
        "steam_deck_hardware_verified": False,
        "scope": "local Windows package smoke; not native Linux or Steam Deck hardware evidence",
    }


def write_reports(payload: dict, json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Package Smoke",
        "",
        f"- Status: {payload['status']}",
        f"- Package: `{payload['package_dir']}`",
        f"- Files present: {'yes' if not payload['file_failures'] else 'no'}",
        f"- Steam launch wrappers: {'pass' if payload['steam_launch_wrappers']['valid'] else 'fail'}",
        f"- Headless smoke: {'pass' if payload['headless']['valid'] else 'fail'}",
        f"- Window smoke: {payload['window_status']}",
        f"- Input contract: {'pass' if payload['input_contract']['valid'] else 'fail'}",
        f"- Input runtime: {'pass' if payload['input_runtime']['valid'] else 'fail'}",
        f"- Packaged FFmpeg: {'pass' if payload['ffmpeg_bundle']['valid'] else 'fail'}",
        f"- Packaged 4K/60 export: {'pass' if payload['video_export']['valid'] else 'fail'}",
        f"- Evidence scope: {payload['environment']['scope']}",
        "",
        "## Headless",
        "",
    ]
    frame = payload["headless"].get("frame_result", {})
    state = payload["headless"].get("trial_runtime", {})
    if frame:
        lines.append(
            f"- frames={frame['frames']} nonblank_pixels={frame['nonblank_pixels']} avg_fps={frame['avg_fps']:.2f}"
        )
    if state:
        lines.append(
            f"- status={state['status']} active_zones={state['active_zones']} progress={state['progress']:.3f}"
        )
    lines.extend(["", "## Steam Launch", ""])
    steam_exe = payload["steam_launch_wrappers"].get("steam_facing_executable", {})
    lines.append(
        f"- Steam-facing executable: `{steam_exe.get('path')}` exists={steam_exe.get('exists')} bytes={steam_exe.get('bytes')}"
    )
    for wrapper, details in payload["steam_launch_wrappers"]["wrappers"].items():
        lines.append(
            f"- `{wrapper}` exists={details['exists']} window={details['uses_window']} "
            f"bounded={details['bounded_timing']} deck_profile={details['deck_profile']} "
            f"steam_binary={details['uses_steam_facing_binary']}"
        )
    lines.extend(["", "## Window", ""])
    if payload.get("window"):
        timing = payload["window"].get("window_timing", {})
        report = payload["window"].get("timing_report", {})
        if timing:
            lines.append(
                f"- frames={timing['frames']} avg_fps={timing['avg_fps']:.2f} worst_frame_ms={timing['worst_frame_ms']:.2f}"
            )
        if report:
            lines.append(
                f"- timing_report profile={report['profile']} size={report['width']}x{report['height']} trial_runtime_present={report['trial_runtime_present']}"
            )
    else:
        lines.append("- skipped")
    lines.extend(["", "## Input", ""])
    input_contract = payload.get("input_contract", {})
    input_runtime = payload.get("input_runtime", {})
    lines.append(
        f"- contract exists={input_contract.get('exists')} backend={input_contract.get('input_backend')} "
        f"right_stick={input_contract.get('has_right_stick')} apply={input_contract.get('has_apply')}"
    )
    lines.append(
        f"- runtime status={input_runtime.get('status')} all_checks_passed={input_runtime.get('all_checks_passed')} "
        f"cursor_delta={input_runtime.get('cursor_delta')}"
    )
    video = payload.get("video_export", {})
    video_artifact = video.get("video", {})
    video_report = video.get("report", {})
    lines.extend(["", "## Native Video Export", ""])
    lines.append(
        f"- scope={video.get('evidence_scope')} target={video.get('package_target')} "
        f"steam_deck_hardware_verified={video.get('steam_deck_hardware_verified')}"
    )
    lines.append(
        f"- output=`{video_artifact.get('path')}` bytes={video_artifact.get('bytes')} "
        f"faststart={video_artifact.get('faststart')} sha256=`{video_artifact.get('sha256')}`"
    )
    lines.append(
        f"- report=`{video_report.get('path')}` schema={video_report.get('schema')} "
        f"timeline={video_report.get('timeline_mode')}"
    )
    environment = payload.get("environment", {})
    lines.extend(["", "## Evidence Scope", ""])
    lines.append(
        f"- host={environment.get('host_os')} architecture={environment.get('host_architecture')} "
        f"gpu=`{environment.get('gpu_adapter')}` backend={environment.get('wgpu_backend')}"
    )
    lines.append(
        "- This Windows package smoke does not prove native Linux packaging, static Linux FFmpeg behavior, "
        "SteamOS compatibility, or actual Steam Deck hardware performance."
    )
    steam_input = payload.get("steam_input", {})
    lines.extend(["", "## Steam Input Package", ""])
    lines.append(
        f"- manifest={steam_input.get('manifest_exists')} glyph_map={steam_input.get('glyph_map_exists')} "
        f"handoff={steam_input.get('handoff_exists')} glyphs={steam_input.get('glyph_count')}"
    )
    if payload["file_failures"] or payload["command_failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in payload["file_failures"] + payload["command_failures"]:
            lines.append(f"- {failure}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    package_dir = resolve(args.package_dir)
    command_results = []
    command_failures: list[str] = []
    if not args.no_build:
        build = build_package(package_dir, args.no_sign)
        command_results.append({"name": "package", **trim_command_result(build)})
        if build["returncode"] != 0:
            command_failures.append("package assembly failed")

    file_failures = validate_package_files(package_dir) if not command_failures else ["package files not checked after failed build"]
    headless: dict[str, object] = {"valid": False}
    window: dict[str, object] | None = None
    input_contract: dict[str, object] = {"valid": False}
    input_runtime: dict[str, object] = {"valid": False}
    video_export: dict[str, object] = {"valid": False}
    ffmpeg_bundle: dict[str, object] = {"valid": False}
    environment = parse_gpu_scope("")
    if not command_failures and not file_failures:
        ffmpeg_command = run_command(
            [str(package_dir / "ffmpeg.exe"), "-hide_banner", "-encoders"],
            package_dir,
        )
        command_results.append({"name": "ffmpeg_encoders", **trim_command_result(ffmpeg_command)})
        ffmpeg_output = str(ffmpeg_command["stdout"]) + str(ffmpeg_command["stderr"])
        ffmpeg_bundle = {
            "valid": ffmpeg_command["returncode"] == 0 and "libx264" in ffmpeg_output,
            "encoder": "libx264",
            "license": "third_party/ffmpeg/LICENSE",
            "provenance": "third_party/ffmpeg/PROVENANCE.txt",
        }
        if not ffmpeg_bundle["valid"]:
            command_failures.append("packaged FFmpeg does not expose libx264")

        headless_command = smoke_headless(package_dir, args.frames)
        command_results.append({"name": "headless", **trim_command_result(headless_command)})
        if headless_command["returncode"] != 0:
            command_failures.append("package-local headless smoke failed")
        headless = parse_headless(str(headless_command["stdout"]) + str(headless_command["stderr"]), args.frames)
        if not headless["valid"]:
            command_failures.append("package-local headless smoke did not produce valid runtime/frame output")
        environment = parse_gpu_scope(
            str(headless_command["stdout"]) + str(headless_command["stderr"])
        )

        if not args.skip_window:
            window_command = smoke_window(package_dir, args.max_window_frames)
            command_results.append({"name": "window", **trim_command_result(window_command)})
            if window_command["returncode"] != 0:
                command_failures.append("package-local window smoke failed")
            window = parse_window(str(window_command["stdout"]) + str(window_command["stderr"]), package_dir)
            if not window["valid"]:
                command_failures.append("package-local window smoke did not produce valid timing report")

        input_contract_command = smoke_input_contract(package_dir)
        command_results.append({"name": "input_contract", **trim_command_result(input_contract_command)})
        if input_contract_command["returncode"] != 0:
            command_failures.append("package-local input contract smoke failed")
        input_contract = parse_input_contract(package_dir)
        if not input_contract["valid"]:
            command_failures.append("package-local input contract did not produce valid action mapping output")

        input_runtime_command = smoke_input_runtime(package_dir)
        command_results.append({"name": "input_runtime", **trim_command_result(input_runtime_command)})
        if input_runtime_command["returncode"] != 0:
            command_failures.append("package-local input runtime smoke failed")
        input_runtime = parse_input_runtime(package_dir)
        if not input_runtime["valid"]:
            command_failures.append("package-local input runtime did not produce valid state transition output")

        video_export, video_commands = smoke_video_export(
            package_dir,
            args.video_seconds,
            args.ffprobe,
        )
        command_results.extend(video_commands)
        if not video_export["valid"]:
            command_failures.append(
                "package-local 4K/60 export wrapper did not produce a fully probed and decoded MP4"
            )

    manifest = package_manifest(package_dir) if package_dir.exists() else None
    if manifest is not None:
        write_package_manifest(manifest, args.package_manifest_json, args.package_manifest_markdown)

    window_status = "skipped" if args.skip_window else ("pass" if window and window.get("valid") else "fail")
    steam_launch_wrappers = validate_steam_launch_wrappers(package_dir)
    steam_input = steam_input_summary(package_dir)
    status = (
        "pass"
        if not file_failures
        and not command_failures
        and steam_launch_wrappers["valid"]
        and steam_input["valid"]
        and headless.get("valid")
        and input_contract.get("valid")
        and input_runtime.get("valid")
        and ffmpeg_bundle.get("valid")
        and video_export.get("valid")
        and (args.skip_window or (window and window.get("valid")))
        else "fail"
    )
    payload = {
        "schema": "fluoddity.native_package_smoke.v1",
        "status": status,
        "package_dir": package_dir.relative_to(ROOT).as_posix() if package_dir.is_relative_to(ROOT) else str(package_dir),
        "file_failures": file_failures,
        "command_failures": command_failures,
        "commands": command_results,
        "headless": headless,
        "window": window,
        "window_status": window_status,
        "steam_launch_wrappers": steam_launch_wrappers,
        "steam_input": steam_input,
        "input_contract": input_contract,
        "input_runtime": input_runtime,
        "ffmpeg_bundle": ffmpeg_bundle,
        "video_export": video_export,
        "environment": environment,
        "package_manifest": {
            "json": resolve(args.package_manifest_json).relative_to(ROOT).as_posix()
            if resolve(args.package_manifest_json).is_relative_to(ROOT)
            else str(resolve(args.package_manifest_json)),
            "markdown": resolve(args.package_manifest_markdown).relative_to(ROOT).as_posix()
            if resolve(args.package_manifest_markdown).is_relative_to(ROOT)
            else str(resolve(args.package_manifest_markdown)),
            "file_count": manifest.get("file_count") if manifest else 0,
            "total_bytes": manifest.get("total_bytes") if manifest else 0,
        },
    }
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_package_smoke_status={status}")
    print(f"native_package_smoke_markdown={resolve(args.markdown)}")
    print(f"native_package_smoke_json={resolve(args.json_output)}")
    print(f"native_package_manifest_markdown={resolve(args.package_manifest_markdown)}")
    print(f"native_package_manifest_json={resolve(args.package_manifest_json)}")
    return 0 if status == "pass" else 2


def validate_steam_launch_wrappers(package_dir: Path) -> dict[str, object]:
    wrappers: dict[str, dict[str, object]] = {}
    valid = True
    for relative in ["run_steam_deck.ps1", "run_steam_deck.sh"]:
        path = package_dir / relative
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        details = {
            "exists": path.exists(),
            "uses_window": "--window" in text,
            "bounded_timing": "--max-window-frames" in text,
            "deck_profile": "--deck-profile" in text,
            "uses_steam_facing_binary": "XenocultureTrialDish" in text,
            "compatibility_fallback": "fluoddity-wgpu-spike" in text,
        }
        wrappers[relative] = details
        valid = (
            valid
            and details["exists"] is True
            and details["uses_window"] is True
            and details["bounded_timing"] is False
            and details["deck_profile"] is False
            and details["uses_steam_facing_binary"] is True
            and details["compatibility_fallback"] is False
        )
    steam_exe = package_dir / "XenocultureTrialDish.exe"
    return {
        "valid": valid and steam_exe.exists() and steam_exe.stat().st_size > 0,
        "steam_facing_executable": {
            "path": "XenocultureTrialDish.exe",
            "exists": steam_exe.exists(),
            "bytes": steam_exe.stat().st_size if steam_exe.exists() else 0,
        },
        "wrappers": wrappers,
    }


def steam_input_summary(package_dir: Path) -> dict[str, object]:
    steam_input_dir = package_dir / "steam_input"
    manifest = steam_input_dir / "steam_input_manifest.vdf"
    glyph_map = steam_input_dir / "trial_prompt_glyph_map.json"
    handoff = steam_input_dir / "steam_input_handoff.md"
    glyphs = list((steam_input_dir / "glyphs").glob("*.svg")) if (steam_input_dir / "glyphs").exists() else []
    failures = validate_packaged_steam_input(package_dir)
    return {
        "valid": not failures and manifest.exists() and glyph_map.exists() and handoff.exists() and len(glyphs) >= 4,
        "manifest": "steam_input/steam_input_manifest.vdf",
        "manifest_exists": manifest.exists(),
        "glyph_map": "steam_input/trial_prompt_glyph_map.json",
        "glyph_map_exists": glyph_map.exists(),
        "handoff": "steam_input/steam_input_handoff.md",
        "handoff_exists": handoff.exists(),
        "glyph_count": len(glyphs),
        "failures": failures,
    }


def trim_command_result(result: dict[str, object]) -> dict[str, object]:
    return {
        "command": result["command"],
        "cwd": result["cwd"],
        "returncode": result["returncode"],
        "stdout_tail": "\n".join(str(result["stdout"]).splitlines()[-20:]),
        "stderr_tail": "\n".join(str(result["stderr"]).splitlines()[-20:]),
    }


if __name__ == "__main__":
    raise SystemExit(main())
