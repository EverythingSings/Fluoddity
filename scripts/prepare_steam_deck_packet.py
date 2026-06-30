"""Generate the manual Steam Deck hardware-pass packet."""
from __future__ import annotations

import argparse
import datetime as dt
import platform
import subprocess
import sys
from pathlib import Path

from build_metadata import current_build_id


ROOT = Path(__file__).resolve().parents[1]


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
    args = parser.parse_args()
    if args.with_fed_results and not args.with_visual:
        parser.error("--with-fed-results requires --with-visual")
    if (args.with_visual or args.with_fed_results) and not args.run_automated:
        parser.error("--with-visual and --with-fed-results require --run-automated")
    return args


def run_step(label: str, command: list[str]) -> None:
    print(f"[packet] {label}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


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
        f"- Build: {build_id}",
        f"- Host: {platform.platform()}",
        f"- Tester: {args.tester or ''}",
        f"- Device: {args.device or ''}",
        f"- Automated gates: {automated_mode}",
        f"- Visual captures requested: {visual_mode}",
        f"- Fed result captures requested: {fed_mode}",
        f"- Performance target: {args.min_fps:.1f} FPS over {args.seconds:.1f}s local smoke",
        "",
        "## Packet Reports",
        "",
        "- `artifacts/steam_input_handoff.md` - Steamworks Steam Input import/default binding checklist.",
        "- `artifacts/trial_dish_playtest.md` - controller-only Trial Dish playtest sheet.",
        "- `artifacts/trial_dish_playtest_summary.md` - tuning-readiness summary for the filled playtest sheet.",
        "- `artifacts/trial_dish_tuning_reference.md` - current thresholds and mechanics values to compare with playtest findings.",
        "- `artifacts/trial_dish_tuning_plan.md` - post-playtest tuning action plan, blocked until the summary is tuning-ready.",
        "- `artifacts/steam_deck_preflight.md` - automated/local evidence plus manual Deck checklist.",
        "",
        "## Hardware Pass Order",
        "",
        "1. Review `artifacts/steam_input_handoff.md` while importing the TrialDish Steam Input manifest.",
        "2. Launch the packaged Steam target with `./run_steam_deck.sh` or the Steamworks launch option.",
        "3. Fill in `artifacts/steam_deck_preflight.md` while checking launch, controller, legibility, performance, and suspend/resume.",
        "4. Fill in `artifacts/trial_dish_playtest.md` during a controller-only Trial Dish playtest.",
        "5. Rerun `python scripts/summarize_trial_dish_playtest.py --require-ready` after the playtest sheet is filled.",
        "6. Rerun `python scripts/write_trial_dish_tuning_plan.py --require-ready` before changing thresholds.",
        "",
        "## Release-Blocking External Gates",
        "",
        "- [ ] Actual Steam Deck hardware performance and suspend/resume pass.",
        "- [ ] Steamworks Steam Input import, default configuration, and official glyph rendering pass.",
        "- [ ] Native Linux or Proton package validation from the Steam launch target.",
        "- [ ] Controller-only Trial Dish playtest summary is tuning-ready.",
        "",
    ]
    output.write_text("\n".join(lines), encoding="utf-8")
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
    run_step("trial dish playtest report", playtest_command)

    run_step(
        "trial dish playtest summary",
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            "artifacts/trial_dish_playtest.md",
            "--output",
            "artifacts/trial_dish_playtest_summary.md",
        ],
    )

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

    index = write_packet_index(args, build_id)

    print(f"steam_deck_packet={ROOT / 'artifacts'}")
    print(f"steam_deck_packet_build={build_id}")
    print(f"steam_deck_packet_index={index.relative_to(ROOT).as_posix()}")
    print(
        "steam_deck_packet_reports="
        "artifacts/steam_deck_packet_index.md "
        "artifacts/steam_input_handoff.md "
        "artifacts/trial_dish_playtest.md "
        "artifacts/trial_dish_playtest_summary.md "
        "artifacts/trial_dish_tuning_reference.md "
        "artifacts/trial_dish_tuning_plan.md "
        "artifacts/steam_deck_preflight.md"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
