"""Run or prepare a Steam Deck validation preflight report.

This is not a replacement for real Steam Deck hardware validation. It packages
the automated gates and the remaining manual checks into one report artifact so
hardware passes are repeatable and reviewable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import platform
import shlex
import subprocess
import sys
from pathlib import Path

from build_metadata import current_build_id


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

DEFAULT_OUTPUT = ROOT / "artifacts" / "steam_deck_preflight.md"
PACKET_INDEX_OUTPUT = ROOT / "artifacts" / "steam_deck_packet_index.md"
HANDOFF_OUTPUT = ROOT / "artifacts" / "steam_input_handoff.md"
PLAYTEST_OUTPUT = ROOT / "artifacts" / "trial_dish_playtest.md"
PLAYTEST_SUMMARY_OUTPUT = ROOT / "artifacts" / "trial_dish_playtest_summary.md"
TUNING_REFERENCE_OUTPUT = ROOT / "artifacts" / "trial_dish_tuning_reference.md"
TUNING_PLAN_OUTPUT = ROOT / "artifacts" / "trial_dish_tuning_plan.md"

MANUAL_CHECKS = [
    f"Launch {GAME_TITLE} from Steam with ./run_steam_deck.sh and confirm it opens the Trial Dish player shell.",
    "Confirm the app starts directly, with no console prompt, launcher, compatibility warning, setup dialog, or desktop-only first-run step.",
    "Confirm the framebuffer is 1280x800 or the Deck-native fullscreen equivalent.",
    "Confirm the default preset holds 30 FPS or better for five minutes.",
    "Confirm all visible text is readable at handheld distance.",
    "Use only controls to start Trial 1, aim Nutrient Gel with right stick, apply it with R2, pause/resume with Menu, retry with B, and exit from the paused state with View.",
    "Complete Trial 1 without opening the raw editor.",
    "Confirm --game does not expose editor panels, config save/load, text-entry popups, parameter sweeps, or field-loading windows unless --allow-editor-in-game is passed.",
    "Confirm no required player-shell workflow needs touch, mouse, keyboard, or manual Steam controller configuration.",
    "Confirm Steam Input is using the imported TrialDish action set and the default configuration does not require manual remapping.",
    "Confirm controller prompts use Steam/Deck glyph rendering or an approved shipped fallback, not keyboard-only labels.",
    "Confirm any dev/editor text-entry workflow is nonessential for normal play or opens a controller-safe text input path before exposure in a shipped build.",
    "Confirm suspend/resume does not leave the GL context black or frozen.",
    "Confirm a clean restart preserves preferences without corrupting user data.",
]

AUTOMATED_GATES = [
    "Trial Dish rules and result logic smoke.",
    "Controller lab cursor and player-shell action smoke.",
    "Default --game shell hides raw editor tools.",
    "Steam Input manifest, localization, prompt action, and glyph metadata smoke.",
    "Steam Input handoff report generation for Steamworks import/default configuration.",
    "Steam Deck packaging contract, including checked placeholder SVG glyph assets.",
    "PyInstaller source compile/import smoke for V1 game modules.",
    "Deck-sized runtime and performance smoke with the requested FPS threshold.",
]

OPTIONAL_VISUAL_GATES = [
    "Nonblank Trial Dish visual captures.",
    "HUD prompt input scheme, text, and active prompt glyph asset assertions.",
    "Fed win/failure result captures with result readout assertions.",
    "Controller reticle visibility and paused Nutrient Gel suppression checks.",
]


def extract_automated_evidence(stdout: str) -> list[str]:
    """Summarize high-signal smoke evidence for the generated report."""
    evidence: list[str] = []
    if "game_controller_smoke=ok" in stdout:
        evidence.append(
            "Controller smoke drove app-level Trial Dish actions through start, pause/resume, paused exit, retry, advance, mutation tools, and final restart."
        )
    if "game_shell_contract_smoke=ok" in stdout:
        evidence.append(
            "Game shell contract smoke verified default --game blocks editor-only command flags while preserving Trial Dish actions."
        )
    if "steam_input_handoff_report=" in stdout:
        evidence.append(
            "Steam Input handoff report was generated from the manifest/glyph map for the Steamworks import pass."
        )
    if "trial_dish_playtest_report=" in stdout:
        evidence.append(
            "Trial Dish manual playtest report was generated for onboarding, readability, friction, and threshold tuning notes."
        )

    visual_states = [
        line
        for line in stdout.splitlines()
        if line.startswith("visual_smoke_trial_state=")
    ]
    if not visual_states:
        return evidence

    controller_states = [line for line in visual_states if "input_scheme=controller" in line]
    hybrid_states = [line for line in visual_states if "input_scheme=hybrid" in line]
    paused_controller_states = [
        line
        for line in controller_states
        if "paused=1" in line and "cursor=0" in line and "cursor_draw=0" in line
    ]
    drawing_controller_states = [
        line
        for line in controller_states
        if "cursor=1" in line and "cursor_draw=1" in line
    ]

    evidence.append(
        f"Visual smoke emitted {len(visual_states)} Trial Dish state snapshots "
        f"({len(controller_states)} controller, {len(hybrid_states)} hybrid)."
    )
    if drawing_controller_states:
        evidence.append(
            "Controller feed visual smoke proved controller-mode prompts with visible reticle and held Nutrient Gel input."
        )
    if paused_controller_states:
        evidence.append(
            "Paused controller visual smoke proved controller-mode Resume/Retry/Exit prompts while suppressing reticle and Nutrient Gel input."
        )
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Steam Deck preflight checks and write a report.")
    parser.add_argument("--python", default=sys.executable, help="Python executable for child smoke commands.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Seconds for runtime/performance smoke.")
    parser.add_argument("--min-fps", type=float, default=30.0, help="Minimum average FPS for Deck performance smoke.")
    parser.add_argument("--with-visual", action="store_true", help="Capture visual smoke frames as part of the preflight.")
    parser.add_argument("--with-fed-results", action="store_true", help="Capture rendered result states when visual smoke is enabled.")
    parser.add_argument("--no-run", action="store_true", help="Write the report skeleton without running automated checks.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown report output path.")
    parser.add_argument("--build-id", default="", help="Optional build label to stamp into the report.")
    args = parser.parse_args()
    if args.with_fed_results and not args.with_visual:
        parser.error("--with-fed-results requires --with-visual")
    return args


def command_for(args: argparse.Namespace) -> list[str]:
    command = [
        args.python,
        "scripts/smoke_game_v1.py",
        "--with-deck-performance",
        "--seconds",
        str(args.seconds),
        "--min-fps",
        str(args.min_fps),
        "--python",
        args.python,
    ]
    if args.with_visual:
        command.append("--with-visual")
    if args.with_fed_results:
        command.append("--with-fed-results")
    return command


def format_command(command: list[str]) -> str:
    if platform.system() == "Windows":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def run_automated(command: list[str]) -> tuple[int | None, str, str]:
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr


def write_report(
    output: Path,
    command: list[str],
    returncode: int | None,
    stdout: str,
    stderr: str,
    skipped: bool,
    build_id: str,
) -> None:
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    status = "skipped" if skipped else ("passed" if returncode == 0 else f"failed ({returncode})")

    lines = [
        "# Steam Deck Preflight Report",
        "",
        f"- Generated: {now}",
        f"- Game: {GAME_TITLE}",
        f"- Engine/package: {ENGINE_NAME}",
        f"- Build: {build_id or current_build_id(ROOT)}",
        f"- Host: {platform.platform()}",
        f"- Python: {sys.version.split()[0]}",
        f"- Automated status: {status}",
        f"- Packet index: {PACKET_INDEX_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Steam Input handoff report: {HANDOFF_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Trial Dish playtest report: {PLAYTEST_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Trial Dish playtest summary: {PLAYTEST_SUMMARY_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Trial Dish tuning reference: {TUNING_REFERENCE_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Trial Dish tuning plan: {TUNING_PLAN_OUTPUT.relative_to(ROOT).as_posix()}",
        f"- Visual captures requested: {'yes' if '--with-visual' in command else 'no'}",
        f"- Fed result captures requested: {'yes' if '--with-fed-results' in command else 'no'}",
        "",
        "## Automated Command",
        "",
        "```bash",
        format_command(command),
        "```",
        "",
        "## Automated Output",
        "",
    ]

    if skipped:
        lines.extend(["Automated checks were not run.", ""])
    else:
        lines.extend(["```text", stdout.rstrip() or "(no stdout)", "```", ""])
        if stderr:
            lines.extend(["## Automated Stderr", "", "```text", stderr.rstrip(), "```", ""])

    evidence = extract_automated_evidence(stdout) if not skipped else []
    lines.extend([
        "## Automated Evidence Highlights",
        "",
    ])
    if evidence:
        lines.extend(f"- {item}" for item in evidence)
    else:
        lines.append("- No automated evidence was captured in this report.")
    lines.append("")

    lines.extend([
        "## Automated Gate Coverage",
        "",
    ])
    lines.extend(f"- [{'x' if returncode == 0 and not skipped else ' '}] {gate}" for gate in AUTOMATED_GATES)
    if "--with-visual" in command:
        lines.extend(f"- [{'x' if returncode == 0 and not skipped else ' '}] {gate}" for gate in OPTIONAL_VISUAL_GATES)
    else:
        lines.extend(f"- [ ] {gate} (run with --with-visual and --with-fed-results)" for gate in OPTIONAL_VISUAL_GATES)
    lines.extend([
        "",
        "## Remaining External Gates",
        "",
        "- [ ] Actual Steam Deck hardware performance and suspend/resume pass.",
        "- [ ] Steamworks Steam Input import, default configuration, and official glyph rendering pass.",
        "- [ ] Native Linux or Proton package validation from the Steam launch target.",
        "",
    ])

    lines.extend([
        "## Companion Manual Reports",
        "",
        f"- [ ] Start from `{PACKET_INDEX_OUTPUT.relative_to(ROOT).as_posix()}` for the hardware-pass order.",
        f"- [ ] Fill in `{HANDOFF_OUTPUT.relative_to(ROOT).as_posix()}` during Steamworks Steam Input import.",
        f"- [ ] Fill in `{PLAYTEST_OUTPUT.relative_to(ROOT).as_posix()}` during the controller-only Trial Dish playtest before tuning thresholds.",
        f"- [ ] Rerun `python scripts/summarize_trial_dish_playtest.py --require-ready` to refresh `{PLAYTEST_SUMMARY_OUTPUT.relative_to(ROOT).as_posix()}`.",
        f"- [ ] Compare findings with `{TUNING_REFERENCE_OUTPUT.relative_to(ROOT).as_posix()}` before changing Trial Dish values.",
        f"- [ ] Rerun `python scripts/write_trial_dish_tuning_plan.py --require-ready` and use `{TUNING_PLAN_OUTPUT.relative_to(ROOT).as_posix()}` before tuning thresholds.",
        "",
    ])

    lines.extend([
        "## Manual Deck Checks",
        "",
        "These must be completed on actual Steam Deck hardware or the closest Linux handheld target available.",
        "",
    ])
    lines.extend(f"- [ ] {check}" for check in MANUAL_CHECKS)
    lines.extend([
        "",
        "## Notes",
        "",
        "- Hardware tester:",
        "- Device / OS build:",
        "- Steam launch target:",
        "- Average FPS observed over five minutes:",
        "- Lowest legibility issue found:",
        "- Input or suspend/resume defects:",
        "",
    ])

    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"steam_deck_preflight_report={output}")


def main() -> int:
    args = parse_args()
    command = command_for(args)
    returncode: int | None = None
    stdout = ""
    stderr = ""

    if not args.no_run:
        returncode, stdout, stderr = run_automated(command)

    write_report(args.output, command, returncode, stdout, stderr, args.no_run, args.build_id)
    if args.no_run:
        return 0
    return returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
