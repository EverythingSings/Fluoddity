"""Generate the manual Steam Deck hardware-pass packet."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from build_metadata import current_build_id


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

TRIAL_DEFINITIONS_SCHEMA = ROOT / "schemas" / "trial_definitions.schema.json"
RELEASE_READINESS_SCHEMA = ROOT / "schemas" / "release_readiness.schema.json"
PACKET_MANIFEST_SCHEMA = ROOT / "schemas" / "steam_deck_packet_manifest.schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Steam Deck hardware-pass reports.")
    parser.add_argument("--python", default=sys.executable, help="Python executable for child commands.")
    parser.add_argument("--tester", default="", help="Optional tester name for the playtest report.")
    parser.add_argument("--device", default="", help="Optional device name for the playtest report.")
    parser.add_argument(
        "--run-automated",
        action="store_true",
        help="Run automated preflight checks instead of writing a no-run skeleton.",
    )
    parser.add_argument("--with-visual", action="store_true", help="Include visual smoke captures in automated preflight.")
    parser.add_argument("--with-fed-results", action="store_true", help="Include rendered result captures in automated preflight.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Runtime/performance smoke duration.")
    parser.add_argument("--min-fps", type=float, default=30.0, help="Minimum average FPS for performance smoke.")
    parser.add_argument("--build-id", default="", help="Optional build label to stamp into every packet report.")
    parser.add_argument(
        "--replace-manual-reports",
        action="store_true",
        help="Replace existing manual playtest/package reports with fresh blank templates.",
    )
    args = parser.parse_args()
    if args.with_fed_results and not args.with_visual:
        parser.error("--with-fed-results requires --with-visual")
    if (args.with_visual or args.with_fed_results) and not args.run_automated:
        parser.error("--with-visual and --with-fed-results require --run-automated")
    return args


def run_step(label: str, command: list[str]) -> None:
    print(f"[packet] {label}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def run_manual_report_step(
    label: str,
    command: list[str],
    output: Path,
    *,
    replace: bool,
) -> None:
    if output.exists() and not replace:
        print(f"[packet] preserve existing manual report: {output.relative_to(ROOT)}", flush=True)
        return
    if replace:
        command.append("--force")
    run_step(label, command)


def copy_trial_definitions_schema() -> Path:
    output = ROOT / "artifacts" / "trial_definitions.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(TRIAL_DEFINITIONS_SCHEMA, output)
    return output


def copy_release_readiness_schema() -> Path:
    output = ROOT / "artifacts" / "release_readiness.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE_READINESS_SCHEMA, output)
    return output


def copy_packet_manifest_schema() -> Path:
    output = ROOT / "artifacts" / "steam_deck_packet_manifest.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PACKET_MANIFEST_SCHEMA, output)
    return output


def packet_artifact_paths() -> list[Path]:
    names = [
        "steam_deck_packet_index.md",
        "steam_deck_packet_manifest.json",
        "steam_deck_packet_manifest.schema.json",
        "trial_definitions.json",
        "trial_definitions.schema.json",
        "steam_input_handoff.md",
        "steam_input_handoff_summary.md",
        "trial_dish_playtest.md",
        "trial_dish_playtest_summary.md",
        "trial_dish_tuning_reference.md",
        "trial_dish_tuning_plan.md",
        "package_validation.md",
        "package_validation_summary.md",
        "native_wgpu_runtime.md",
        "native_validation_suite.md",
        "native_validation_suite.json",
        "native_rust_quality.md",
        "native_rust_quality.json",
        "native_rust_tests.md",
        "native_rust_tests.json",
        "native_shader_parity.md",
        "native_shader_parity.json",
        "native_config_contract.md",
        "native_config_contract.json",
        "native_input_contract.md",
        "native_input_contract.json",
        "native_input_runtime.md",
        "native_input_runtime.json",
        "native_steam_input_alignment.md",
        "native_steam_input_alignment.json",
        "native_visual_metrics.md",
        "native_visual_metrics.json",
        "native_python_visual_parity.md",
        "native_python_visual_parity.json",
        "native_replay_determinism.md",
        "native_replay_determinism.json",
        "native_video_export_smoke.md",
        "native_video_export_smoke.json",
        "native-wgpu/native_video_export_smoke.mp4",
        "native-wgpu/native_video_export_smoke.ppm",
        "native-wgpu/native_video_export_smoke.metadata.json",
        "native_trial_matrix.md",
        "native_trial_matrix.json",
        "native_preset_matrix.md",
        "native_preset_matrix.json",
        "native_rule_sensitivity.md",
        "native_rule_sensitivity.json",
        "native_parameter_sensitivity.md",
        "native_parameter_sensitivity.json",
        "native_package_smoke.md",
        "native_package_smoke.json",
        "native_package_manifest.md",
        "native_package_manifest.json",
        "native_timing_budget.md",
        "native_timing_budget.json",
        "native_steam_launch_contract.md",
        "native_steam_launch_contract.json",
        "steam_deck_preflight.md",
        "steam_deck_preflight_summary.md",
        "steam_deck_visual_evidence.md",
        "release_readiness_summary.md",
        "release_readiness_summary.json",
        "release_readiness.schema.json",
    ]
    return [ROOT / "artifacts" / name for name in names]


def write_packet_index(args: argparse.Namespace, build_id: str) -> Path:
    output = ROOT / "artifacts" / "steam_deck_packet_index.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    automated_mode = "run" if args.run_automated else "skipped"
    visual_mode = "yes" if args.with_visual else "no"
    fed_mode = "yes" if args.with_fed_results else "no"

    lines = [
        "# Steam Deck Hardware Packet",
        "",
        f"- Generated: {now}",
        f"- Game: {GAME_TITLE}",
        f"- Engine/package: {ENGINE_NAME}",
        f"- Build: {build_id}",
        f"- Host: {platform.platform()}",
        f"- Tester: {args.tester or ''}",
        f"- Device: {args.device or ''}",
        f"- Preflight automated gates: {automated_mode}",
        "- Native validation suite: run",
        f"- Visual captures requested: {visual_mode}",
        f"- Fed result captures requested: {fed_mode}",
        f"- Performance target: {args.min_fps:.1f} FPS over {args.seconds:.1f}s local smoke",
        "",
        "## Packet Reports",
        "",
        "- `artifacts/steam_deck_packet_manifest.json` - machine-readable inventory of this packet, including build identity, readiness status, byte counts, and SHA-256 hashes.",
        "- `artifacts/steam_deck_packet_manifest.schema.json` - checked schema for the packet manifest.",
        "- `artifacts/trial_definitions.json` - machine-readable Trial Dish definitions for tooling and future runtime ports.",
        "- `artifacts/trial_definitions.schema.json` - checked schema for the Trial Dish definitions export.",
        "- `artifacts/steam_input_handoff.md` - Steamworks Steam Input import/default binding checklist.",
        "- `artifacts/steam_input_handoff_summary.md` - readiness summary for filled Steam Input import/configuration evidence.",
        "- `artifacts/trial_dish_playtest.md` - controller-only Trial Dish playtest sheet.",
        "- `artifacts/trial_dish_playtest_summary.md` - tuning-readiness summary for the filled playtest sheet.",
        "- `artifacts/trial_dish_tuning_reference.md` - current thresholds and mechanics values to compare with playtest findings.",
        "- `artifacts/trial_dish_tuning_plan.md` - post-playtest tuning action plan, blocked until the summary is tuning-ready.",
        "- `artifacts/package_validation.md` - native Linux or Proton package/runtime validation checklist, including the Rust/wgpu `dist/FluoddityNative/` package candidate.",
        "- `artifacts/package_validation_summary.md` - release-gate summary for filled package/runtime validation evidence.",
        "- `artifacts/native_wgpu_runtime.md` - Rust/wgpu native runtime spike handoff, smoke commands, and current evidence boundary.",
        "- `artifacts/native_validation_suite.md` - ordered Rust/wgpu native validation suite summary, including allowed non-final statuses for shader parity and Python visual parity.",
        "- `artifacts/native_validation_suite.json` - machine-readable native validation suite summary for tooling.",
        "- `artifacts/native_rust_quality.md` - Rust formatting and clippy report for native replacement runtime code quality.",
        "- `artifacts/native_rust_quality.json` - machine-readable native Rust quality report for tooling.",
        "- `artifacts/native_rust_tests.md` - Rust unit test report for native config and Trial Dish contract parsing.",
        "- `artifacts/native_rust_tests.json` - machine-readable native Rust unit test report for tooling.",
        "- `artifacts/native_shader_parity.md` - machine-generated audit of Python/GLSL fluid-engine features mapped or missing in the Rust/wgpu runtime.",
        "- `artifacts/native_shader_parity.json` - machine-readable native shader parity audit for tooling.",
        "- `artifacts/native_config_contract.md` - machine-generated check that Rust/wgpu normalized config inputs match the saved v7 config contract for shipped Core presets.",
        "- `artifacts/native_config_contract.json` - machine-readable native config contract check for tooling.",
        "- `artifacts/native_input_contract.md` - Rust/wgpu native controller/input contract proving the intended Deck-critical actions and axes are exported from the native binary.",
        "- `artifacts/native_input_contract.json` - machine-readable native controller/input contract for tooling.",
        "- `artifacts/native_input_runtime.md` - Rust/wgpu scripted input smoke proving start/resume, apply, pause suppression, and right-stick cursor behavior through native runtime state.",
        "- `artifacts/native_input_runtime.json` - machine-readable native scripted input smoke for tooling.",
        "- `artifacts/native_steam_input_alignment.md` - machine-generated check that native Rust/gilrs controls align with the Steam Input manifest, glyph map, and package input wrappers.",
        "- `artifacts/native_steam_input_alignment.json` - machine-readable native Steam Input alignment check for tooling.",
        "- `artifacts/native_visual_metrics.md` - coarse rendered-output metric comparison between the Rust/wgpu native capture and Python visual-smoke reference image.",
        "- `artifacts/native_visual_metrics.json` - machine-readable native visual metric comparison for tooling.",
        "- `artifacts/native_python_visual_parity.md` - same-scenario image-level drift measurement between the Python/OpenGL Trial Dish visual smoke and the Rust/wgpu native player capture.",
        "- `artifacts/native_python_visual_parity.json` - machine-readable native-vs-Python visual parity measurement for tooling.",
        "- `artifacts/native_replay_determinism.md` - native Rust/wgpu replay determinism check proving the same saved Trial Dish scenario produces bit-exact headless captures.",
        "- `artifacts/native_replay_determinism.json` - machine-readable native replay determinism report for tooling.",
        "- `artifacts/native_video_export_smoke.md` - local-host native 4K/60 H.264 export validation, including probe, decode, fidelity, determinism, and collision-safety evidence.",
        "- `artifacts/native_video_export_smoke.json` - machine-readable native video export validation; the packet manifest records its explicit local-host evidence boundary.",
        "- `artifacts/native-wgpu/native_video_export_smoke.mp4` - probed 3840x2160 60 fps H.264/yuv420p export artifact generated by the native runtime.",
        "- `artifacts/native-wgpu/native_video_export_smoke.ppm` - lossless final presentation-pass frame used to validate encoded-frame fidelity.",
        "- `artifacts/native-wgpu/native_video_export_smoke.metadata.json` - native exporter report for the MP4 artifact, including fixed-timeline and codec settings.",
        "- `artifacts/native_trial_matrix.md` - Rust/wgpu headless smoke matrix proving every exported Trial Dish contract loads, runs, and renders a nonblank varied frame.",
        "- `artifacts/native_trial_matrix.json` - machine-readable native Trial Dish matrix for tooling.",
        "- `artifacts/native_preset_matrix.md` - Rust/wgpu saved-preset matrix proving representative Core presets load, render, and produce distinct fluid outputs.",
        "- `artifacts/native_preset_matrix.json` - machine-readable native saved-preset matrix for tooling.",
        "- `artifacts/native_rule_sensitivity.md` - Rust/wgpu saved-rule sensitivity check comparing one saved Fourier rule against a zero-rule variant.",
        "- `artifacts/native_rule_sensitivity.json` - machine-readable native saved-rule sensitivity check for tooling.",
        "- `artifacts/native_parameter_sensitivity.md` - Rust/wgpu mapped-parameter effect matrix proving representative saved physics/settings fields materially change native rendered output.",
        "- `artifacts/native_parameter_sensitivity.json` - machine-readable native mapped-parameter effect matrix for tooling.",
        "- `artifacts/native_package_smoke.md` - Windows package-local Rust/wgpu smoke proving `dist/FluoddityNative/` player launch, smoke/timing wrappers, input wrappers, Steam Input handoff files, and bundled data work without repo-relative paths.",
        "- `artifacts/native_package_smoke.json` - machine-readable native package smoke for tooling.",
        "- `artifacts/native_package_manifest.md` - hashed inventory of the package-local `dist/FluoddityNative/` files produced and smoked locally, including the Steam-facing `XenocultureTrialDish` executable alias and Steam Input handoff files.",
        "- `artifacts/native_package_manifest.json` - machine-readable native package content manifest for tooling.",
        "- `artifacts/native_timing_budget.md` - bounded local Deck-profile frame-time budget check for the native package timing report.",
        "- `artifacts/native_timing_budget.json` - machine-readable native timing budget check for tooling.",
        "- `artifacts/native_steam_launch_contract.md` - machine-generated native Steam launch target contract for Windows/Proton and Deck/Linux package launches.",
        "- `artifacts/native_steam_launch_contract.json` - machine-readable native Steam launch target contract for tooling.",
        "- `artifacts/steam_deck_preflight.md` - automated/local evidence plus manual Deck checklist.",
        "- `artifacts/steam_deck_preflight_summary.md` - release-gate summary for filled hardware preflight evidence.",
        "- `artifacts/steam_deck_visual_evidence.md` - stable index of rendered visual-smoke image paths and Trial Dish state snapshots from the automated preflight.",
        "- `artifacts/release_readiness_summary.md` - aggregate readiness gate across Steam Input, Deck preflight, playtest, and tuning evidence.",
        "- `artifacts/release_readiness_summary.json` - machine-readable aggregate readiness gate for tooling and CI.",
        "- `artifacts/release_readiness.schema.json` - checked schema for the release readiness JSON artifact.",
        "",
        "## Hardware Pass Order",
        "",
        "1. Review and fill `artifacts/steam_input_handoff.md` while importing the TrialDish Steam Input manifest.",
        "2. Rerun `python scripts/summarize_steam_input_handoff.py --require-ready` after the Steamworks import/default config pass.",
        f"3. Launch {GAME_TITLE} from the packaged Steam target with `./run_steam_deck.sh`, `./run_steam_deck.ps1`, or the Steamworks launch option.",
        "4. Fill in `artifacts/steam_deck_preflight.md` while checking launch, controller, legibility, performance, and suspend/resume.",
        "5. Rerun `python scripts/summarize_steam_deck_preflight.py --require-ready` after the preflight sheet is filled.",
        "6. Fill in `artifacts/trial_dish_playtest.md` during a controller-only Trial Dish playtest.",
        "7. Rerun `python scripts/summarize_trial_dish_playtest.py --require-ready` after the playtest sheet is filled.",
        "8. Rerun `python scripts/write_trial_dish_tuning_plan.py --require-ready` before changing thresholds.",
        "9. Fill in `artifacts/package_validation.md` while validating the native Linux or Proton Steam launch target and the Rust/wgpu `dist/FluoddityNative/` package candidate.",
        "10. Rerun `python scripts/summarize_package_validation.py --require-ready` after package/runtime validation.",
        "11. Review `artifacts/native_validation_suite.md` before trusting the native runtime candidate as a coherent local build.",
        "12. Review `artifacts/native_shader_parity.md` before treating the native runtime as fluid-engine parity work.",
        "13. Review `artifacts/native_config_contract.md` before trusting native saved-config behavior.",
        "14. Review `artifacts/native_input_contract.md` before trusting native controller mappings.",
        "15. Review `artifacts/native_input_runtime.md` before trusting native controller state transitions.",
        "16. Review `artifacts/native_steam_input_alignment.md` before trusting Steam Input handoff parity for the native runtime.",
        "17. Review `artifacts/native_visual_metrics.md` before trusting native rendered-output behavior.",
        "18. Review `artifacts/native_python_visual_parity.md` before claiming the native renderer has replicated the Python/OpenGL fluid look.",
        "19. Review `artifacts/native_replay_determinism.md` before trusting native headless captures as stable regression evidence.",
        "20. Review `artifacts/native_video_export_smoke.md`, its JSON report, MP4, metadata, and poster before trusting native high-resolution export.",
        "21. Review `artifacts/native_trial_matrix.md` before trusting Trial Dish coverage in the native runtime.",
        "22. Review `artifacts/native_preset_matrix.md` before trusting saved-preset fluid behavior in the native runtime.",
        "23. Review `artifacts/native_rule_sensitivity.md` before trusting saved Fourier rules in the native runtime.",
        "24. Review `artifacts/native_parameter_sensitivity.md` before trusting mapped native physics/settings fields.",
        "25. Review `artifacts/native_package_smoke.md` before trusting the native package candidate.",
        "26. Review `artifacts/native_package_manifest.md` before handing off the native package candidate.",
        "27. Review `artifacts/native_timing_budget.md` before treating local bounded native timing as healthy.",
        "28. Review `artifacts/native_steam_launch_contract.md` before configuring the Steam launch target.",
        "29. Run `bash runtime/rust-wgpu-spike/scripts/smoke-deck.sh` if validating the Rust/wgpu native runtime candidate.",
        "30. Rerun `python scripts/summarize_release_readiness.py --require-ready` before treating the packet as release-ready.",
        "",
        "## Release-Blocking External Gates",
        "",
        "- [ ] Actual Steam Deck hardware performance and suspend/resume pass.",
        "- [ ] Steamworks Steam Input import, default configuration, and official glyph rendering pass.",
        "- [ ] Native Linux or Proton package validation from the Steam launch target, including the Rust/wgpu `dist/FluoddityNative/` package candidate.",
        "- [ ] Rust/wgpu native runtime 60-second timing and controller-only pass on actual Steam Deck hardware.",
        "- [ ] Native validation suite reviewed; all local native gates pass their allowed statuses in ordered, non-racing execution.",
        "- [ ] Native shader parity audit reviewed; missing fluid-engine features are either ported or explicitly accepted for the build.",
        "- [ ] Native config contract check reviewed; saved Core presets normalize identically in the Rust/wgpu runtime.",
        "- [ ] Native input contract reviewed; right stick, R2, A, and Start/Menu mappings match the intended Deck controls.",
        "- [ ] Native input runtime smoke reviewed; scripted start/apply/pause/cursor transitions pass through native state.",
        "- [ ] Native Steam Input alignment reviewed; Rust/gilrs controls match the TrialDish action ids, glyph fallbacks, and package input wrappers.",
        "- [ ] Native visual metrics reviewed; coarse rendered-output differences are understood before claiming parity.",
        "- [ ] Native-vs-Python visual parity measurement reviewed; measured drift is understood before claiming the Rust/wgpu runtime replicated the Python/OpenGL fluid look.",
        "- [ ] Native replay determinism reviewed; the same saved scenario produces bit-exact native headless captures on the validation machine.",
        "- [ ] Native 4K/60 video export reviewed; the MP4, poster, metadata, and smoke report agree and fully decode on the named validation host.",
        "- [ ] Deck/Linux package video wrappers reviewed on their native target; the static bundled FFmpeg exports successfully, while local Windows evidence remains labeled non-Deck evidence.",
        "- [ ] Native Trial Dish matrix reviewed; all exported Trial Dish contracts run through the native runtime.",
        "- [ ] Native saved-preset matrix reviewed; representative Core presets produce distinct rendered fluid outputs.",
        "- [ ] Native saved-rule sensitivity reviewed; saved Fourier rules produce measurable native output differences.",
        "- [ ] Native parameter sensitivity reviewed; representative mapped physics/settings fields produce measurable native output differences.",
        "- [ ] Native package smoke reviewed; `dist/FluoddityNative/` includes player-facing `run_steam_deck` launch wrappers, Steam Input handoff files, and launches from package-local data.",
        "- [ ] Native package manifest reviewed; bundled native files, Steam-facing executable alias, Steam Input handoff files, and smoke artifacts have expected byte counts and hashes.",
        "- [ ] Native Steam launch contract reviewed; Steamworks launch target uses the product-named native executable/window path instead of Python or bounded smoke wrappers.",
        "- [ ] Controller-only Trial Dish playtest summary is tuning-ready.",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def write_native_wgpu_runtime_report(build_id: str) -> Path:
    output = ROOT / "artifacts" / "native_wgpu_runtime.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    local_timing = ROOT / "artifacts" / "native-wgpu-smoke" / "wgpu_deck_timing_smoke.json"
    canonical_timing = ROOT / "artifacts" / "native-wgpu" / "wgpu_deck_timing.json"
    packaged_timing = ROOT / "dist" / "FluoddityNative" / "artifacts" / "wgpu_deck_timing.json"
    timing_note = "No native wgpu timing artifact was found in this packet."
    if packaged_timing.exists():
        timing_note = f"Packaged native runtime timing artifact present: `{packaged_timing.relative_to(ROOT).as_posix()}`."
    elif canonical_timing.exists():
        timing_note = f"Native Deck/Linux timing artifact present: `{canonical_timing.relative_to(ROOT).as_posix()}`."
    elif local_timing.exists():
        timing_note = f"Local Windows native smoke timing artifact present: `{local_timing.relative_to(ROOT).as_posix()}`."

    lines = [
        "# Native wgpu Runtime Handoff",
        "",
        f"- Generated: {now}",
        f"- Game: {GAME_TITLE}",
        f"- Engine/package: {ENGINE_NAME}",
        f"- Build: {build_id}",
        "- Runtime candidate: Rust + wgpu",
        "- Spike path: `runtime/rust-wgpu-spike/`",
        "- Windows smoke: `./runtime/rust-wgpu-spike/scripts/smoke-windows.ps1`",
        "- Windows package: `./runtime/rust-wgpu-spike/scripts/package-windows.ps1`",
        "- Steam Deck/Linux smoke: `bash runtime/rust-wgpu-spike/scripts/smoke-deck.sh`",
        "- Steam Deck/Linux package: `bash runtime/rust-wgpu-spike/scripts/package-deck.sh`",
        "- Package output: `dist/FluoddityNative/`",
        f"- Timing artifact status: {timing_note}",
        "",
        "## Proven Locally",
        "",
        "- [x] Native release build path exists.",
        "- [x] Native package assembly path exists.",
        "- [x] Exported Trial Dish definitions are loaded by the native runtime.",
        "- [x] Existing physics config and saved 80-float rule coefficients are loaded.",
        "- [x] wgpu compute updates persistent particle and trail buffers.",
        "- [x] Native window and Deck-sized timing report path exist.",
        "- [x] Primitive controller/status overlay and bitmap objective text render without Python/ImGui.",
        "",
        "## Steam Deck Hardware Pass",
        "",
        "- [ ] Run `bash runtime/rust-wgpu-spike/scripts/smoke-deck.sh` on actual Steam Deck hardware.",
        "- [ ] Or build `dist/FluoddityNative/` with `bash runtime/rust-wgpu-spike/scripts/package-deck.sh` and run `bash run_deck_profile.sh` from the package folder.",
        "- [ ] Confirm selected backend is Vulkan.",
        "- [ ] Confirm the generated `artifacts/native-wgpu/wgpu_deck_timing.json` covers the full 60-second profile.",
        "- [ ] Confirm average FPS is at least 30 at 1280x800.",
        "- [ ] Confirm right stick cursor movement, R2 apply, Start/Menu pause, and A resume work with Deck controls.",
        "- [ ] Confirm the native objective text and controller prompts are readable at handheld distance.",
        "- [ ] Record suspend/resume behavior for the native window.",
        "",
        "## Known Native Runtime Gaps",
        "",
        "- No Steam Input or Steamworks integration in the Rust/wgpu spike yet.",
        "- Briefing/running/win/fail/result progression exists; the retained menu shell, settings, save data, achievements, cloud saves, and installer remain open.",
        "- Shader behavior is not fully parity-matched for mutation history, orientation modes, symmetry handling, or multi-load selection.",
        "- Text rendering is a fixed bitmap overlay, not a retained UI/layout/localization system.",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_readiness_status() -> dict[str, object]:
    path = ROOT / "artifacts" / "release_readiness_summary.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "status": payload.get("status", ""),
        "ready": bool(payload.get("ready")),
        "gate_count": len(payload.get("gates", [])),
        "blocking_count": len(payload.get("blocking_next_steps", [])),
    }


def native_video_status() -> dict[str, object]:
    report_path = ROOT / "artifacts" / "native_video_export_smoke.json"
    video_path = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.mp4"
    metadata_path = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.metadata.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    stream = payload.get("probe", {}).get("ffprobe_stream", {})
    adapter_output = str(payload.get("export_stdout_tail", ""))
    adapter = ""
    backend = ""
    match = re.search(
        r'wgpu_adapter name="(?P<name>[^"]+)" backend=(?P<backend>\S+)',
        adapter_output,
    )
    if match:
        adapter = match.group("name")
        backend = match.group("backend")
    return {
        "status": payload.get("status", ""),
        "evidence_scope": "local-host-offscreen-export",
        "host": platform.platform(),
        "gpu_adapter": adapter,
        "wgpu_backend": backend,
        "steam_deck_hardware_verified": False,
        "width": payload.get("video", {}).get("width"),
        "height": payload.get("video", {}).get("height"),
        "fps": payload.get("video", {}).get("fps"),
        "frames": payload.get("video", {}).get("frames"),
        "codec": stream.get("codec_name", ""),
        "pixel_format": stream.get("pix_fmt", ""),
        "timeline_mode": metadata.get("timeline", {}).get("mode", ""),
        "video_path": video_path.relative_to(ROOT).as_posix(),
        "video_sha256": sha256_file(video_path),
        "smoke_report_path": report_path.relative_to(ROOT).as_posix(),
        "export_report_path": metadata_path.relative_to(ROOT).as_posix(),
    }


def write_packet_manifest(args: argparse.Namespace, build_id: str) -> Path:
    output = ROOT / "artifacts" / "steam_deck_packet_manifest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    artifacts = []
    for path in packet_artifact_paths():
        if path == output:
            continue
        if not path.exists():
            raise FileNotFoundError(path)
        artifacts.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    payload = {
        "schema": "xenoculture.steam_deck_packet_manifest.v1",
        "generated": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "game": GAME_TITLE,
        "engine_package": ENGINE_NAME,
        "build": build_id,
        "host": platform.platform(),
        "tester": args.tester or "",
        "device": args.device or "",
        "options": {
            "preflight_automated_gates": "run" if args.run_automated else "skipped",
            "native_validation_suite": "run",
            "visual_captures": bool(args.with_visual),
            "fed_result_captures": bool(args.with_fed_results),
            "seconds": args.seconds,
            "min_fps": args.min_fps,
        },
        "release_readiness": release_readiness_status(),
        "native_video": native_video_status(),
        "artifacts": artifacts,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    python = args.python
    build_id = args.build_id or current_build_id(ROOT)

    run_step(
        "steam input handoff",
        [
            python,
            "scripts/write_steam_input_handoff.py",
            "--output",
            "artifacts/steam_input_handoff.md",
            "--build-id",
            build_id,
        ],
    )
    run_step(
        "steam input handoff summary",
        [
            python,
            "scripts/summarize_steam_input_handoff.py",
            "--input",
            "artifacts/steam_input_handoff.md",
            "--output",
            "artifacts/steam_input_handoff_summary.md",
        ],
    )

    run_step(
        "trial definitions json",
        [
            python,
            "scripts/export_trial_definitions.py",
            "--output",
            "artifacts/trial_definitions.json",
        ],
    )

    copy_trial_definitions_schema()
    copy_release_readiness_schema()
    copy_packet_manifest_schema()

    playtest_command = [
        python,
        "scripts/write_trial_dish_playtest_report.py",
        "--output",
        "artifacts/trial_dish_playtest.md",
    ]
    if args.tester:
        playtest_command.extend(["--tester", args.tester])
    if args.device:
        playtest_command.extend(["--device", args.device])
    playtest_command.extend(["--build-id", build_id])
    run_manual_report_step(
        "trial dish playtest report",
        playtest_command,
        ROOT / "artifacts" / "trial_dish_playtest.md",
        replace=args.replace_manual_reports,
    )

    playtest_summary_command = [
        python,
        "scripts/summarize_trial_dish_playtest.py",
        "--input",
        "artifacts/trial_dish_playtest.md",
        "--output",
        "artifacts/trial_dish_playtest_summary.md",
        "--expected-build",
        build_id,
    ]
    if args.tester:
        playtest_summary_command.extend(["--expected-tester", args.tester])
    if args.device:
        playtest_summary_command.extend(["--expected-device", args.device])
    run_step("trial dish playtest summary", playtest_summary_command)

    run_step(
        "trial dish tuning reference",
        [
            python,
            "scripts/write_trial_dish_tuning_reference.py",
            "--output",
            "artifacts/trial_dish_tuning_reference.md",
        ],
    )

    run_step(
        "trial dish tuning plan",
        [
            python,
            "scripts/write_trial_dish_tuning_plan.py",
            "--summary",
            "artifacts/trial_dish_playtest_summary.md",
            "--reference",
            "artifacts/trial_dish_tuning_reference.md",
            "--output",
            "artifacts/trial_dish_tuning_plan.md",
        ],
    )

    package_command = [
        python,
        "scripts/write_package_validation_report.py",
        "--output",
        "artifacts/package_validation.md",
    ]
    if args.tester:
        package_command.extend(["--tester", args.tester])
    if args.device:
        package_command.extend(["--device", args.device])
    package_command.extend(["--build-id", build_id])
    run_manual_report_step(
        "package validation report",
        package_command,
        ROOT / "artifacts" / "package_validation.md",
        replace=args.replace_manual_reports,
    )

    package_summary_command = [
        python,
        "scripts/summarize_package_validation.py",
        "--input",
        "artifacts/package_validation.md",
        "--output",
        "artifacts/package_validation_summary.md",
        "--expected-build",
        build_id,
    ]
    if args.tester:
        package_summary_command.extend(["--expected-tester", args.tester])
    if args.device:
        package_summary_command.extend(["--expected-device", args.device])
    run_step("package validation summary", package_summary_command)

    run_step(
        "native validation suite",
        [
            python,
            "scripts/smoke_native_validation_suite.py",
            "--json-output",
            "artifacts/native_validation_suite.json",
            "--markdown",
            "artifacts/native_validation_suite.md",
        ],
    )
    write_native_wgpu_runtime_report(build_id)

    preflight_command = [
        python,
        "scripts/steam_deck_preflight.py",
        "--output",
        "artifacts/steam_deck_preflight.md",
        "--seconds",
        str(args.seconds),
        "--min-fps",
        str(args.min_fps),
        "--python",
        python,
        "--build-id",
        build_id,
    ]
    if not args.run_automated:
        preflight_command.append("--no-run")
    if args.with_visual:
        preflight_command.append("--with-visual")
    if args.with_fed_results:
        preflight_command.append("--with-fed-results")
    run_step("steam deck preflight", preflight_command)

    run_step(
        "steam deck preflight summary",
        [
            python,
            "scripts/summarize_steam_deck_preflight.py",
            "--input",
            "artifacts/steam_deck_preflight.md",
            "--output",
            "artifacts/steam_deck_preflight_summary.md",
        ],
    )
    run_step(
        "release readiness summary",
        [
            python,
            "scripts/summarize_release_readiness.py",
            "--output",
            "artifacts/release_readiness_summary.md",
            "--json-output",
            "artifacts/release_readiness_summary.json",
            "--package-summary",
            "artifacts/package_validation_summary.md",
        ],
    )

    index = write_packet_index(args, build_id)
    manifest = write_packet_manifest(args, build_id)
    run_step(
        "steam deck packet manifest validation",
        [
            python,
            "scripts/validate_steam_deck_packet_manifest.py",
            "--manifest",
            "artifacts/steam_deck_packet_manifest.json",
            "--readiness-json",
            "artifacts/release_readiness_summary.json",
        ],
    )

    print(f"steam_deck_packet={ROOT / 'artifacts'}")
    print(f"steam_deck_packet_build={build_id}")
    print(f"steam_deck_packet_index={index.relative_to(ROOT).as_posix()}")
    print(f"steam_deck_packet_manifest={manifest.relative_to(ROOT).as_posix()}")
    print(
        "steam_deck_packet_reports="
        "artifacts/steam_deck_packet_index.md "
        "artifacts/steam_deck_packet_manifest.json "
        "artifacts/steam_deck_packet_manifest.schema.json "
        "artifacts/trial_definitions.json "
        "artifacts/trial_definitions.schema.json "
        "artifacts/steam_input_handoff.md "
        "artifacts/steam_input_handoff_summary.md "
        "artifacts/trial_dish_playtest.md "
        "artifacts/trial_dish_playtest_summary.md "
        "artifacts/trial_dish_tuning_reference.md "
        "artifacts/trial_dish_tuning_plan.md "
        "artifacts/package_validation.md "
        "artifacts/package_validation_summary.md "
        "artifacts/native_wgpu_runtime.md "
        "artifacts/native_validation_suite.md "
        "artifacts/native_validation_suite.json "
        "artifacts/native_rust_quality.md "
        "artifacts/native_rust_quality.json "
        "artifacts/native_rust_tests.md "
        "artifacts/native_rust_tests.json "
        "artifacts/native_shader_parity.md "
        "artifacts/native_shader_parity.json "
        "artifacts/native_config_contract.md "
        "artifacts/native_config_contract.json "
        "artifacts/native_input_contract.md "
        "artifacts/native_input_contract.json "
        "artifacts/native_input_runtime.md "
        "artifacts/native_input_runtime.json "
        "artifacts/native_steam_input_alignment.md "
        "artifacts/native_steam_input_alignment.json "
        "artifacts/native_visual_metrics.md "
        "artifacts/native_visual_metrics.json "
        "artifacts/native_python_visual_parity.md "
        "artifacts/native_python_visual_parity.json "
        "artifacts/native_replay_determinism.md "
        "artifacts/native_replay_determinism.json "
        "artifacts/native_video_export_smoke.md "
        "artifacts/native_video_export_smoke.json "
        "artifacts/native-wgpu/native_video_export_smoke.mp4 "
        "artifacts/native-wgpu/native_video_export_smoke.ppm "
        "artifacts/native-wgpu/native_video_export_smoke.metadata.json "
        "artifacts/native_trial_matrix.md "
        "artifacts/native_trial_matrix.json "
        "artifacts/native_preset_matrix.md "
        "artifacts/native_preset_matrix.json "
        "artifacts/native_rule_sensitivity.md "
        "artifacts/native_rule_sensitivity.json "
        "artifacts/native_parameter_sensitivity.md "
        "artifacts/native_parameter_sensitivity.json "
        "artifacts/native_package_smoke.md "
        "artifacts/native_package_smoke.json "
        "artifacts/native_package_manifest.md "
        "artifacts/native_package_manifest.json "
        "artifacts/native_timing_budget.md "
        "artifacts/native_timing_budget.json "
        "artifacts/native_steam_launch_contract.md "
        "artifacts/native_steam_launch_contract.json "
        "artifacts/steam_deck_preflight.md "
        "artifacts/steam_deck_preflight_summary.md "
        "artifacts/steam_deck_visual_evidence.md "
        "artifacts/release_readiness_summary.md "
        "artifacts/release_readiness_summary.json "
        "artifacts/release_readiness.schema.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
