"""Write a package/runtime validation report template for Steam launch testing."""
from __future__ import annotations

import argparse
import datetime as dt
import platform
import sys
from pathlib import Path

from build_metadata import current_build_id


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

DEFAULT_OUTPUT = ROOT / "artifacts" / "package_validation.md"

PACKAGE_BUILD_CHECKS = [
    "Package was built from the stamped build/commit.",
    "`dist/Fluoddity/run_steam_deck.sh` exists and launches the player shell with `--steam-deck --game`.",
    "`dist/Fluoddity/steam_input/steam_input_manifest.vdf` is present.",
    "`dist/Fluoddity/steam_input/trial_prompt_glyph_map.json` and mapped glyph assets are present.",
    "`dist/Fluoddity/steam_input/steam_input_handoff.md` is present for the Steamworks import pass.",
    "The native package contains its platform FFmpeg executable plus `third_party/ffmpeg/LICENSE` and `PROVENANCE.txt`; the encoder exposes `libx264`.",
]

LAUNCH_CHECKS = [
    "Steam launch target starts directly without a launcher, setup dialog, terminal prompt, or compatibility warning.",
    "The first visible screen is the Trial Dish player shell, not the raw editor.",
    "Controller input works from launch without manual remapping.",
    "Quit/relaunch returns to a usable player shell.",
]

RUNTIME_CHECKS = [
    "Selected runtime path is explicit: native Linux or Windows-through-Proton.",
    "OpenGL context and compute shaders initialize under the selected runtime.",
    "Steam overlay and Steam Input stay active during play.",
    "Suspend/resume and restart do not leave the window black or frozen.",
]

NATIVE_WGPU_PACKAGE_CHECKS = [
    "`dist/FluoddityNative/` was assembled with the Rust/wgpu package script for the tested platform.",
    "`dist/FluoddityNative/XenocultureTrialDish.exe` or `XenocultureTrialDish` exists as the Steam-facing native executable alias.",
    "`dist/FluoddityNative/run_steam_deck.sh` or `run_steam_deck.ps1` launches the native player window without Python, PyInstaller, ModernGL, GLFW, ImGui, or a bounded smoke frame count.",
    "`dist/FluoddityNative/artifacts/trial_definitions.json` and every shipped `physics_configs/Core/*.json` preset are present in the package.",
    "`dist/FluoddityNative/run_deck_profile.sh` or `run_deck_profile.ps1` writes `artifacts/wgpu_deck_timing.json` from the package directory with a `trial_runtime` snapshot.",
    "Native runtime renders the controller/status overlay and bitmap objective text at 1280x800.",
]

NATIVE_VIDEO_CHECKS = [
    "`run_export_video.ps1` or `run_export_video.sh` succeeds from an unrelated working directory and writes to a caller-relative path containing spaces.",
    "The package-local FFmpeg produces a fully decodable H.264/yuv420p MP4 with BT.709 primaries, transfer, matrix, and limited range.",
    "The deterministic export report uses schema `fluoddity.native_video_export.v1`, mode `offline-fixed-step`, a fixed 60 Hz simulation timeline, and final-presentation capture.",
    "A native 3840x2160 60 fps export was probed for exact dimensions, frame rate, frame count, faststart metadata placement, and nonzero byte/hash evidence.",
    "`run_record_video.ps1` or `run_record_video.sh` uses mode `window-frame-capture`; it is documented as frame-sequence capture rather than wall-clock screen recording.",
    "The evidence names its host OS, architecture, GPU adapter, wgpu backend, package target, and whether actual Steam Deck hardware was used.",
    "Windows package evidence is not labeled Linux/Steam Deck evidence; native Linux/Deck evidence comes from the package built and run on that target.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a package/runtime validation report template.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown output path.")
    parser.add_argument("--tester", default="", help="Optional tester name/handle.")
    parser.add_argument("--device", default="", help="Optional device name, such as Steam Deck OLED.")
    parser.add_argument("--build-id", default="", help="Optional build label to stamp into the report.")
    parser.add_argument("--force", action="store_true", help="Replace an existing report.")
    return parser.parse_args()


def checkbox_lines(items: list[str]) -> list[str]:
    return [f"- [ ] {item}" for item in items]


def write_report(output: Path, tester: str, device: str, build_id: str) -> Path:
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    lines = [
        "# Package Runtime Validation Report",
        "",
        f"- Generated: {now}",
        f"- Game: {GAME_TITLE}",
        f"- Engine/package: {ENGINE_NAME}",
        f"- Host: {platform.platform()}",
        f"- Tester: {tester or ''}",
        f"- Device / OS build: {device or ''}",
        f"- Build / commit: {build_id or current_build_id(ROOT)}",
        "- Package path:",
        "- Runtime path:",
        "- Steam launch target:",
        "- Package build host:",
        "- Package target:",
        "- GPU adapter:",
        "- wgpu backend:",
        "- Video evidence host:",
        "- Actual Steam Deck hardware used (yes/no):",
        "- Average FPS observed over five minutes:",
        "- Runtime defects:",
        "",
        "## Purpose",
        "",
        "This report proves the packaged Steam launch path works under the selected runtime. It is separate from game-feel playtesting and Steam Input import evidence.",
        "",
        "The Python/PyInstaller player package and the Rust/wgpu native runtime candidate have separate evidence because the migration target is a Steam Deck-ready native package, not just a wrapped desktop runtime.",
        "",
        "## Package Build",
        "",
    ]
    lines.extend(checkbox_lines(PACKAGE_BUILD_CHECKS))
    lines.extend(["", "## Launch Validation", ""])
    lines.extend(checkbox_lines(LAUNCH_CHECKS))
    lines.extend(["", "## Runtime Compatibility", ""])
    lines.extend(checkbox_lines(RUNTIME_CHECKS))
    lines.extend(["", "## Native wgpu Package", ""])
    lines.extend(checkbox_lines(NATIVE_WGPU_PACKAGE_CHECKS))
    lines.extend(["", "## Native Video Export", ""])
    lines.extend(checkbox_lines(NATIVE_VIDEO_CHECKS))
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Native Linux result:",
            "- Proton result:",
            "- Native wgpu package result:",
            "- Native video export result:",
            "- Native window-frame-capture result:",
            "- Video evidence scope / hardware boundary:",
            "- Performance notes:",
            "- Packaging fixes needed:",
            "",
        ]
    )

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    output_path = args.output if args.output.is_absolute() else ROOT / args.output
    if output_path.exists() and not args.force:
        print(
            f"refusing to replace existing manual report without --force: {output_path}",
            file=sys.stderr,
        )
        return 2
    output = write_report(args.output, args.tester, args.device, args.build_id)
    print(f"package_validation_report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
