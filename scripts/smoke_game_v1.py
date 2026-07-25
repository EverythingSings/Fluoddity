"""Run the V1 game prototype smoke suite."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DEPENDENCY_IMPORTS = [
    ("numpy", "numpy"),
    ("Pillow", "PIL"),
    ("ModernGL", "moderngl"),
    ("GLFW", "glfw"),
    ("imgui_bundle", "imgui_bundle"),
]

COMPILE_TARGETS = [
    "main.py",
    "launch_options.py",
    "command_handler.py",
    "simulation_runner.py",
    "sim.py",
    "controller_input.py",
    "scripts/export_trial_definitions.py",
    "scripts/build_metadata.py",
    "scripts/smoke_trial_definitions.py",
    "scripts/smoke_trial_definitions_export.py",
    "scripts/smoke_trial_definitions_schema.py",
    "scripts/smoke_trial_runtime_contract.py",
    "scripts/smoke_trial_dish_tuning_reference.py",
    "scripts/smoke_trial_module_boundaries.py",
    "scripts/smoke_trial_strain_reset.py",
    "scripts/smoke_game_design_alignment.py",
    "scripts/smoke_game_v1_done_definition.py",
    "scripts/smoke_game_v1_dependency_guard.py",
    "scripts/smoke_trial_dishes.py",
    "scripts/smoke_game_runtime.py",
    "scripts/smoke_game_identity.py",
    "scripts/smoke_game_controller.py",
    "scripts/smoke_game_performance.py",
    "scripts/smoke_game_shell_contract.py",
    "scripts/smoke_steam_input_manifest.py",
    "scripts/smoke_steam_input_handoff_summary.py",
    "scripts/smoke_steam_deck_packaging.py",
    "scripts/smoke_steam_deck_packet.py",
    "scripts/smoke_steam_deck_preflight_summary.py",
    "scripts/smoke_steam_deck_visual_evidence.py",
    "scripts/smoke_package_validation_summary.py",
    "scripts/smoke_release_readiness_summary.py",
    "scripts/smoke_release_readiness_schema.py",
    "scripts/smoke_trial_dish_playtest_summary.py",
    "scripts/summarize_trial_dish_playtest.py",
    "scripts/summarize_steam_deck_preflight.py",
    "scripts/summarize_steam_input_handoff.py",
    "scripts/summarize_package_validation.py",
    "scripts/summarize_release_readiness.py",
    "scripts/write_trial_dish_tuning_plan.py",
    "scripts/write_trial_dish_tuning_reference.py",
    "scripts/write_steam_input_handoff.py",
    "scripts/write_package_validation_report.py",
    "scripts/write_trial_dish_playtest_report.py",
    "scripts/prepare_steam_deck_packet.py",
    "scripts/validate_steam_deck_packet_manifest.py",
    "scripts/export_networked_html.py",
    "scripts/smoke_networked_video_artifact.py",
    "scripts/build_webgpu_artifact.py",
    "scripts/smoke_webgpu_artifact.py",
    "scripts/smoke_webgpu_responsive.py",
    "scripts/audit_webgpu_artifact_parity.py",
    "scripts/smoke_game_visual.py",
    "scripts/smoke_game_v1.py",
    "scripts/steam_deck_preflight.py",
    "state/trial_state.py",
    "state/ui_state.py",
    "state/__init__.py",
    "services/trial_definitions.py",
    "services/game_identity.py",
    "services/trial_service.py",
    "services/trial_prompts.py",
    "services/__init__.py",
    "services/config_saver.py",
    "ui/__init__.py",
    "ui/core.py",
    "ui/menu_bar.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V1 game prototype smoke checks.")
    parser.add_argument(
        "--with-runtime",
        action="store_true",
        help="Also launch OpenGL game mode briefly.",
    )
    parser.add_argument(
        "--with-deck-performance",
        action="store_true",
        help="Also run the runtime and frame-timing smokes with --deck-performance.",
    )
    parser.add_argument(
        "--with-visual",
        action="store_true",
        help="Also capture and validate a game-mode framebuffer.",
    )
    parser.add_argument(
        "--with-fed-results",
        action="store_true",
        help="Also capture rendered success and failure result screens.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for child smoke commands.",
    )
    parser.add_argument("--seconds", type=float, default=5.0, help="Runtime smoke duration.")
    parser.add_argument(
        "--min-fps",
        type=float,
        default=30.0,
        help="Minimum average FPS for --with-deck-performance.",
    )
    return parser.parse_args()


def run_step(label: str, args: list[str]) -> None:
    print(f"[smoke] {label}", flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def check_manual_report_overwrite_guard(
    label: str,
    command: list[str],
    output: Path,
) -> None:
    run_step(label, command)
    marker = "\nmanual-evidence-must-survive\n"
    output.write_text(output.read_text(encoding="utf-8") + marker, encoding="utf-8")

    refused = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if refused.returncode != 2 or "--force" not in (refused.stdout + refused.stderr):
        raise AssertionError(f"{label} should refuse an implicit overwrite")
    if marker.strip() not in output.read_text(encoding="utf-8"):
        raise AssertionError(f"{label} changed manual evidence after refusing overwrite")

    run_step(f"{label} explicit replacement", [*command, "--force"])
    if marker.strip() in output.read_text(encoding="utf-8"):
        raise AssertionError(f"{label} --force should replace the report")


def check_python_dependencies(python: str) -> None:
    imports = "; ".join(f"import {module}" for _, module in DEPENDENCY_IMPORTS)
    proc = subprocess.run(
        [python, "-c", imports],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        return

    missing = []
    for package, module in DEPENDENCY_IMPORTS:
        probe = subprocess.run(
            [python, "-c", f"import {module}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if probe.returncode != 0:
            missing.append(package)

    local_venv = ROOT / ".venv" / "Scripts" / "python.exe"
    hint = (
        f" Try `python scripts/smoke_game_v1.py --python {local_venv}`."
        if local_venv.exists()
        else " Install requirements with `python -m pip install -r requirements.txt`."
    )
    details = ", ".join(missing) if missing else "project dependencies"
    raise SystemExit(
        f"Selected smoke interpreter is missing {details}: {python}.{hint}"
    )


def main() -> int:
    args = parse_args()
    python = args.python
    check_python_dependencies(python)
    smoke_dir = ROOT / "artifacts" / "game_v1_smoke" / str(os.getpid())
    visual_dir = smoke_dir / "visual"

    def smoke_path(name: str) -> str:
        return str(smoke_dir / name)

    def visual_path(name: str) -> str:
        return str(visual_dir / name)

    run_step("trial definitions", [python, "scripts/smoke_trial_definitions.py"])
    run_step("trial definitions export", [python, "scripts/smoke_trial_definitions_export.py"])
    run_step("trial definitions schema", [python, "scripts/smoke_trial_definitions_schema.py"])
    run_step("trial runtime contract", [python, "scripts/smoke_trial_runtime_contract.py"])
    run_step("trial tuning reference", [python, "scripts/smoke_trial_dish_tuning_reference.py"])
    run_step("trial module boundaries", [python, "scripts/smoke_trial_module_boundaries.py"])
    run_step("trial strain reset", [python, "scripts/smoke_trial_strain_reset.py"])
    run_step("game design alignment", [python, "scripts/smoke_game_design_alignment.py"])
    run_step("game V1 done definition", [python, "scripts/smoke_game_v1_done_definition.py"])
    run_step("game V1 dependency guard", [python, "scripts/smoke_game_v1_dependency_guard.py"])
    run_step("trial logic", [python, "scripts/smoke_trial_dishes.py"])
    run_step("game identity", [python, "scripts/smoke_game_identity.py"])
    run_step("game controller", [python, "scripts/smoke_game_controller.py"])
    run_step("game shell contract", [python, "scripts/smoke_game_shell_contract.py"])
    run_step("steam input manifest", [python, "scripts/smoke_steam_input_manifest.py"])
    run_step("steam input handoff summary", [python, "scripts/smoke_steam_input_handoff_summary.py"])
    run_step("steam deck packaging", [python, "scripts/smoke_steam_deck_packaging.py"])
    run_step("steam deck packet", [python, "scripts/smoke_steam_deck_packet.py"])
    run_step("steam deck preflight summary", [python, "scripts/smoke_steam_deck_preflight_summary.py"])
    run_step("steam deck visual evidence", [python, "scripts/smoke_steam_deck_visual_evidence.py"])
    run_step("package validation summary", [python, "scripts/smoke_package_validation_summary.py"])
    run_step("release readiness summary", [python, "scripts/smoke_release_readiness_summary.py"])
    run_step("release readiness schema", [python, "scripts/smoke_release_readiness_schema.py"])
    run_step("trial dish playtest summary", [python, "scripts/smoke_trial_dish_playtest_summary.py"])
    run_step("networked video artifact", [python, "scripts/smoke_networked_video_artifact.py"])
    run_step(
        "steam input handoff report",
        [
            python,
            "scripts/write_steam_input_handoff.py",
            "--output",
            smoke_path("steam_input_handoff_smoke.md"),
        ],
    )
    trial_report_smoke = smoke_dir / "trial_dish_playtest_smoke.md"
    check_manual_report_overwrite_guard(
        "trial dish playtest report",
        [
            python,
            "scripts/write_trial_dish_playtest_report.py",
            "--output",
            str(trial_report_smoke),
        ],
        trial_report_smoke,
    )
    run_step(
        "steam deck preflight report",
            [
                python,
                "scripts/steam_deck_preflight.py",
                "--no-run",
                "--output",
                smoke_path("steam_deck_preflight_smoke.md"),
                "--visual-evidence-output",
                smoke_path("steam_deck_visual_evidence_smoke.md"),
            ],
        )
    package_report_smoke = smoke_dir / "package_validation_smoke.md"
    check_manual_report_overwrite_guard(
        "package validation report",
        [
            python,
            "scripts/write_package_validation_report.py",
            "--output",
            str(package_report_smoke),
        ],
        package_report_smoke,
    )
    run_step("py_compile", [python, "-m", "py_compile", *COMPILE_TARGETS])
    run_step(
        "imports",
        [
            python,
            "-c",
            "from ui import UI; import main; from services.trial_service import TrialService; print('imports ok')",
        ],
    )

    if args.with_runtime:
        run_step(
            "runtime --game",
            [
                python,
                "scripts/smoke_game_runtime.py",
                "--seconds",
                str(args.seconds),
                "--python",
                python,
            ],
        )

    if args.with_deck_performance:
        run_step(
            "runtime --game --deck-performance",
            [
                python,
                "scripts/smoke_game_runtime.py",
                "--seconds",
                str(args.seconds),
                "--python",
                python,
                "--extra-arg=--deck-performance",
            ],
        )
        run_step(
            "performance --game --deck-performance",
            [
                python,
                "scripts/smoke_game_performance.py",
                "--seconds",
                str(args.seconds),
                "--min-fps",
                str(args.min_fps),
                "--python",
                python,
                "--extra-arg=--deck-performance",
            ],
        )

    if args.with_visual:
        run_step(
            "visual --game Trial 1 briefing",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_briefing.png"),
                "--trial",
                "1",
                "--expect-prompt-contains",
                "Start",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
                "--expect-zone-overlays",
                "0",
                "--expect-no-hazard-overlay",
                "--expect-no-rival-overlay",
            ],
        )
        run_step(
            "visual --game Trial 1 running",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_running.png"),
                "--trial",
                "1",
                "--start",
                "--frame",
                "25",
                "--expect-active-zones",
                "1",
                "--expect-progress-min",
                "0.01",
                "--expect-status",
                "running",
                "--expect-specimen-contains",
                "Specimen responding",
                "--expect-feedback-contains",
                "Specimen response detected",
                "--expect-zone-overlays",
                "1",
                "--expect-no-hazard-overlay",
                "--expect-no-rival-overlay",
                "--expect-input-scheme",
                "hybrid",
                "--expect-prompt-contains",
                "Nutrient Gel",
                "--expect-prompt-contains",
                "Pause",
                "--expect-display-prompt-contains",
                "[Right Stick] + [R2]",
                "--expect-display-prompt-contains",
                "[Menu]",
                "--expect-glyph-contains",
                "steam_input/glyphs/right_stick.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/r2.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/menu.svg",
            ],
        )
        run_step(
            "visual --game Trial 1 controller feed",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_controller_feed.png"),
                "--trial",
                "1",
                "--start",
                "--frame",
                "45",
                "--controller-cursor",
                "--controller-feed",
                "--expect-active-zones",
                "1",
                "--expect-progress-min",
                "0.01",
                "--expect-status",
                "running",
                "--expect-input-scheme",
                "controller",
                "--expect-specimen-contains",
                "Specimen responding",
                "--expect-controller-cursor",
                "--expect-controller-draw",
                "--expect-prompt-contains",
                "Nutrient Gel",
                "--expect-display-prompt-contains",
                "[Right Stick] + [R2]",
                "--expect-glyph-contains",
                "steam_input/glyphs/right_stick.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/r2.svg",
            ],
        )
        run_step(
            "visual --game Trial 1 paused",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_paused.png"),
                "--trial",
                "1",
                "--start",
                "--pause",
                "--frame",
                "45",
                "--controller-cursor",
                "--controller-feed",
                "--expect-status",
                "running",
                "--expect-input-scheme",
                "controller",
                "--expect-paused",
                "--expect-no-controller-cursor",
                "--expect-no-controller-draw",
                "--expect-prompt-contains",
                "Resume",
                "--expect-prompt-contains",
                "Exit",
                "--expect-display-prompt-contains",
                "[Menu]",
                "--expect-display-prompt-contains",
                "[View]",
                "--expect-glyph-contains",
                "steam_input/glyphs/menu.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/view.svg",
            ],
        )
        run_step(
            "visual --game Trial 2 briefing",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial2_briefing.png"),
                "--trial",
                "2",
                "--expect-zone-overlays",
                "3",
                "--expect-no-hazard-overlay",
                "--expect-no-rival-overlay",
                "--expect-prompt-contains",
                "Start",
            ],
        )
        run_step(
            "visual --game Trial 2 retry transition",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial2_retry_transition.png"),
                "--trial",
                "2",
                "--transition-action",
                "retry",
                "--expect-status",
                "briefing",
                "--expect-zone-overlays",
                "3",
                "--expect-transition-contains",
                "Retry loaded",
                "--expect-prompt-contains",
                "Start",
            ],
        )
        run_step(
            "visual --game Trial 2 running",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial2_running.png"),
                "--trial",
                "2",
                "--start",
                "--frame",
                "90",
                "--feed",
                "--expect-active-zones",
                "2",
                "--expect-progress-min",
                "0.05",
                "--expect-status",
                "running",
                "--expect-zone-overlays",
                "3",
                "--expect-hazard-overlay",
                "--expect-no-rival-overlay",
                "--expect-route-contains",
                "Route stable",
                "--expect-feedback-contains",
                "Route survived the scar",
                "--expect-prompt-contains",
                "Nutrient Gel",
                "--expect-display-prompt-contains",
                "[Right Stick] + [R2]",
                "--expect-glyph-contains",
                "steam_input/glyphs/right_stick.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/r2.svg",
            ],
        )
        run_step(
            "visual --game Trial 3 briefing",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_briefing.png"),
                "--trial",
                "3",
                "--expect-zone-overlays",
                "3",
                "--expect-no-hazard-overlay",
                "--expect-no-rival-overlay",
                "--expect-prompt-contains",
                "Start",
            ],
        )
        run_step(
            "visual --game Trial 3 restart transition",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_restart_transition.png"),
                "--trial",
                "3",
                "--transition-action",
                "restart",
                "--expect-status",
                "briefing",
                "--expect-zone-overlays",
                "0",
                "--expect-transition-contains",
                "Sequence restarted",
                "--expect-prompt-contains",
                "Start",
            ],
        )
        run_step(
            "visual --game Trial 3 running",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_running.png"),
                "--trial",
                "3",
                "--start",
                "--frame",
                "90",
                "--feed",
                "--expect-active-zones",
                "2",
                "--expect-rival-zones",
                "1",
                "--expect-progress-min",
                "0.01",
                "--expect-status",
                "running",
                "--expect-zone-overlays",
                "3",
                "--expect-no-hazard-overlay",
                "--expect-rival-overlay",
                "--expect-containment-contains",
                "Containing by",
                "--expect-mutation-contains",
                "Baseline strain",
                "--expect-prompt-contains",
                "Irradiate",
                "--expect-prompt-contains",
                "No Archive",
                "--expect-display-prompt-contains",
                "[Y]",
                "--expect-display-prompt-contains",
                "[L1]",
                "--expect-glyph-contains",
                "steam_input/glyphs/y.svg",
                "--expect-glyph-contains",
                "steam_input/glyphs/l1.svg",
            ],
        )
        run_step(
            "visual --game Trial 3 mutated",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_mutated.png"),
                "--trial",
                "3",
                "--start",
                "--frame",
                "90",
                "--feed",
                "--mutate",
                "--expect-active-zones",
                "2",
                "--expect-rival-zones",
                "1",
                "--expect-status",
                "running",
                "--expect-containment-contains",
                "Containing by",
                "--expect-mutation-contains",
                "Mutated strain",
                "--expect-mutation-contains",
                "archive ready",
                "--expect-guidance-contains",
                "archive is loaded",
                "--expect-prompt-contains",
                "Recharge",
                "--expect-prompt-contains",
                "Revert",
                "--expect-display-prompt-contains",
                "[Y]",
                "--expect-display-prompt-contains",
                "[L1]",
            ],
        )
        run_step(
            "visual --game Trial 3 reverted",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_reverted.png"),
                "--trial",
                "3",
                "--start",
                "--frame",
                "95",
                "--feed",
                "--revert",
                "--expect-active-zones",
                "2",
                "--expect-rival-zones",
                "1",
                "--expect-status",
                "running",
                "--expect-containment-contains",
                "Containing by",
                "--expect-mutation-contains",
                "Archive restored",
                "--expect-prompt-contains",
                "Spent",
                "--expect-display-prompt-contains",
                "[L1]",
            ],
        )
        run_step(
            "visual --game Trial 3 closing",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_closing.png"),
                "--trial",
                "3",
                "--start",
                "--elapsed",
                "70",
                "--frame",
                "90",
                "--feed",
                "--expect-active-zones",
                "2",
                "--expect-rival-zones",
                "1",
                "--expect-status",
                "running",
                "--expect-containment-contains",
                "Containing by",
                "--expect-timer-contains",
                "Assay closing soon",
                "--expect-guidance-contains",
                "Irradiation is ready",
            ],
        )

    if args.with_fed_results:
        run_step(
            "visual --game Trial 1 resolved failure",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_result_failure.png"),
                "--trial",
                "1",
                "--start",
                "--resolve",
                "--frame",
                "120",
                "--expect-progress-max",
                "0.99",
                "--expect-status",
                "failed",
                "--expect-result-title",
                "Culture Failed",
                "--expect-result-readout",
                "Unstable",
                "--expect-result-summary-contains",
                "not sustained long enough",
                "--expect-result-summary-not-contains",
                "scar",
                "--expect-result-hint-contains",
                "marked circle",
                "--expect-result-hint-not-contains",
                "route",
                "--expect-result-next-contains",
                "Retry",
                "--expect-result-next-not-contains",
                "scar",
                "--expect-prompt-contains",
                "Retry",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
            ],
        )
        run_step(
            "visual --game Trial 2 resolved failure",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial2_result.png"),
                "--trial",
                "2",
                "--start",
                "--resolve",
                "--frame",
                "120",
                "--expect-progress-max",
                "0.99",
                "--expect-status",
                "failed",
                "--expect-result-title",
                "Culture Failed",
                "--expect-result-readout",
                "Unstable",
                "--expect-result-summary-contains",
                "culture sites",
                "--expect-result-hint-contains",
                "start reinforcing",
                "--expect-result-next-contains",
                "Retry",
                "--expect-prompt-contains",
                "Retry",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
            ],
        )
        run_step(
            "visual --game Trial 1 fed win",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial1_fed_win.png"),
                "--trial",
                "1",
                "--start",
                "--feed",
                "--frame",
                "240",
                "--expect-active-zones",
                "1",
                "--expect-progress-min",
                "1.0",
                "--expect-status",
                "won",
                "--expect-result-title",
                "Culture Stabilized",
                "--expect-result-summary-contains",
                "culture stabilized",
                "--expect-result-hint-contains",
                "antibiotic scar",
                "--expect-result-next-contains",
                "Trial 2",
                "--expect-prompt-contains",
                "Next",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
            ],
        )
        run_step(
            "visual --game Trial 2 fed win",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial2_fed_win.png"),
                "--trial",
                "2",
                "--start",
                "--feed",
                "--frame",
                "540",
                "--expect-active-zones",
                "2",
                "--expect-progress-min",
                "1.0",
                "--expect-status",
                "won",
                "--expect-result-title",
                "Culture Stabilized",
                "--expect-result-summary-contains",
                "culture stabilized",
                "--expect-result-hint-contains",
                "rival bloom race",
                "--expect-result-next-contains",
                "Trial 3",
                "--expect-prompt-contains",
                "Next",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
            ],
        )

        run_step(
            "visual --game Trial 3 resolved win",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
                "--output",
                visual_path("trial3_result.png"),
                "--trial",
                "3",
                "--start",
                "--feed",
                "--resolve",
                "--frame",
                "120",
                "--expect-active-zones",
                "2",
                "--expect-rival-zones",
                "1",
                "--expect-progress-min",
                "1.0",
                "--expect-status",
                "won",
                "--expect-result-title",
                "Rival Contained",
                "--expect-result-readout",
                "Contained",
                "--expect-result-summary-contains",
                "Culture held 2 sites",
                "--expect-result-hint-contains",
                "deliberate mutation",
                "--expect-result-next-contains",
                "Sequence complete",
                "--expect-containment-contains",
                "Containing by",
                "--expect-prompt-contains",
                "Restart",
                "--expect-display-prompt-contains",
                "[A]",
                "--expect-glyph-contains",
                "steam_input/glyphs/a.svg",
            ],
        )

    print("game_v1_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
