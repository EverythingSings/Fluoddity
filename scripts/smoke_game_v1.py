"""Run the V1 game prototype smoke suite."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

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
    "scripts/smoke_trial_dishes.py",
    "scripts/smoke_game_runtime.py",
    "scripts/smoke_game_identity.py",
    "scripts/smoke_game_controller.py",
    "scripts/smoke_game_performance.py",
    "scripts/smoke_game_shell_contract.py",
    "scripts/smoke_steam_input_manifest.py",
    "scripts/smoke_steam_deck_packaging.py",
    "scripts/smoke_steam_deck_packet.py",
    "scripts/smoke_trial_dish_playtest_summary.py",
    "scripts/summarize_trial_dish_playtest.py",
    "scripts/write_trial_dish_tuning_plan.py",
    "scripts/write_trial_dish_tuning_reference.py",
    "scripts/write_steam_input_handoff.py",
    "scripts/write_trial_dish_playtest_report.py",
    "scripts/prepare_steam_deck_packet.py",
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


def main() -> int:
    args = parse_args()
    python = args.python

    run_step("trial definitions", [python, "scripts/smoke_trial_definitions.py"])
    run_step("trial definitions export", [python, "scripts/smoke_trial_definitions_export.py"])
    run_step("trial definitions schema", [python, "scripts/smoke_trial_definitions_schema.py"])
    run_step("trial runtime contract", [python, "scripts/smoke_trial_runtime_contract.py"])
    run_step("trial tuning reference", [python, "scripts/smoke_trial_dish_tuning_reference.py"])
    run_step("trial module boundaries", [python, "scripts/smoke_trial_module_boundaries.py"])
    run_step("trial logic", [python, "scripts/smoke_trial_dishes.py"])
    run_step("game identity", [python, "scripts/smoke_game_identity.py"])
    run_step("game controller", [python, "scripts/smoke_game_controller.py"])
    run_step("game shell contract", [python, "scripts/smoke_game_shell_contract.py"])
    run_step("steam input manifest", [python, "scripts/smoke_steam_input_manifest.py"])
    run_step("steam deck packaging", [python, "scripts/smoke_steam_deck_packaging.py"])
    run_step("steam deck packet", [python, "scripts/smoke_steam_deck_packet.py"])
    run_step("trial dish playtest summary", [python, "scripts/smoke_trial_dish_playtest_summary.py"])
    run_step(
        "steam input handoff report",
        [
            python,
            "scripts/write_steam_input_handoff.py",
            "--output",
            "artifacts/steam_input_handoff_smoke.md",
        ],
    )
    run_step(
        "trial dish playtest report",
        [
            python,
            "scripts/write_trial_dish_playtest_report.py",
            "--output",
            "artifacts/trial_dish_playtest_smoke.md",
        ],
    )
    run_step(
        "steam deck preflight report",
        [
            python,
            "scripts/steam_deck_preflight.py",
            "--no-run",
            "--output",
            "artifacts/steam_deck_preflight_smoke.md",
        ],
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
            "visual --game Trial 2 running",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
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
            "visual --game Trial 3 running",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
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

    if args.with_fed_results:
        run_step(
            "visual --game Trial 2 resolved failure",
            [
                python,
                "scripts/smoke_game_visual.py",
                "--python",
                python,
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
