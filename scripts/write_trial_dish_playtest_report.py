"""Write a manual Trial Dish playtest report template."""
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

DEFAULT_OUTPUT = ROOT / "artifacts" / "trial_dish_playtest.md"

PLAYTEST_GOALS = [
    "Confirm the first run teaches the alien lab premise without extra explanation.",
    "Confirm each trial adds one new concern before the screen becomes visually overwhelming.",
    "Measure whether Trial 1, Trial 2, and Trial 3 thresholds feel fair under controller play.",
    "Record where the player feels friction, confusion, boredom, or loss of agency.",
    "Capture whether Rival Bloom creates a real counterpoint instead of just visual noise.",
]

SESSION_CHECKS = [
    "Launch `python main.py --steam-deck --game` or `./dist/Fluoddity/run_steam_deck.sh`.",
    "Use controller only unless the report explicitly marks a keyboard/mouse escape.",
    "Start from Trial 1 briefing with no prior explanation from the tester.",
    "Play until Trial 3 is won, failed, or abandoned.",
    "Retry any failed trial once before changing settings or stopping.",
]

TRIAL_PROMPTS = [
    (
        "Trial 1: Bloom",
        [
            "Did the player understand where to apply Nutrient Gel?",
            "Was the first visible specimen response clear enough?",
            "Time to stabilize:",
            "Moments of confusion:",
            "Suggested threshold/visual/copy changes:",
        ],
    ),
    (
        "Trial 2: Antibiotic Band",
        [
            "Did the red band read as a counterforce before the text explained it?",
            "Did routing across/around the band feel intentional?",
            "First failure reason, if any:",
            "Time to stabilize:",
            "Suggested threshold/visual/copy changes:",
        ],
    ),
    (
        "Trial 3: Rival Bloom",
        [
            "Did the rival bloom create urgency or just background noise?",
            "Did Irradiate/Revert feel understandable and worth using?",
            "Did the final site-margin result feel fair?",
            "Time to outcome:",
            "Suggested threshold/visual/copy changes:",
        ],
    ),
]

RATING_ROWS = [
    "Premise clarity",
    "Visual readability",
    "Controller confidence",
    "Objective clarity",
    "Friction/struggle",
    "Desire to retry",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a Trial Dish manual playtest report template.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown output path.")
    parser.add_argument("--tester", default="", help="Optional tester name/handle.")
    parser.add_argument("--device", default="", help="Optional device name, such as Steam Deck OLED.")
    parser.add_argument("--build-id", default="", help="Optional build label to stamp into the report.")
    return parser.parse_args()


def checkbox_lines(items: list[str]) -> list[str]:
    return [f"- [ ] {item}" for item in items]


def write_report(output: Path, tester: str, device: str, build_id: str) -> Path:
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")

    lines = [
        "# Trial Dish Manual Playtest Report",
        "",
        f"- Generated: {now}",
        f"- Game: {GAME_TITLE}",
        f"- Engine/package: {ENGINE_NAME}",
        f"- Host: {platform.platform()}",
        f"- Tester: {tester or ''}",
        f"- Device: {device or ''}",
        f"- Build / commit: {build_id or current_build_id(ROOT)}",
        "- Launch target:",
        "- Controller:",
        "",
        "## Purpose",
        "",
        "This report is for game-feel and onboarding evidence. It does not replace the Steam Deck preflight report or Steamworks validation.",
        "",
        "## Playtest Goals",
        "",
    ]
    lines.extend(checkbox_lines(PLAYTEST_GOALS))
    lines.extend([
        "",
        "## Session Setup",
        "",
    ])
    lines.extend(checkbox_lines(SESSION_CHECKS))
    lines.extend([
        "",
        "## Ratings",
        "",
        "Use 1-5, where 1 means broken/confusing and 5 means clear/compelling.",
        "",
        "| Dimension | Rating | Notes |",
        "| --- | --- | --- |",
    ])
    lines.extend(f"| {row} |  |  |" for row in RATING_ROWS)
    lines.extend([""])

    for title, prompts in TRIAL_PROMPTS:
        lines.extend([
            f"## {title}",
            "",
        ])
        for prompt in prompts:
            lines.append(f"- {prompt}")
        lines.append("")

    lines.extend([
        "## Failure / Friction Log",
        "",
        "| Time / trial | What happened | Player interpretation | Fix candidate |",
        "| --- | --- | --- | --- |",
        "|  |  |  |  |",
        "|  |  |  |  |",
        "|  |  |  |  |",
        "",
        "## Tuning Notes",
        "",
        "- Trial 1 threshold/hold time:",
        "- Trial 2 threshold/hold time/hazard strength:",
        "- Trial 3 rival strength/timer/tool cooldowns:",
        "- HUD/copy changes:",
        "- Visual noise/readability changes:",
        "",
        "## Verdict",
        "",
        "- [ ] Ready for another hardware pass without tuning.",
        "- [ ] Needs threshold/copy/visual tuning before another hardware pass.",
        "- [ ] Needs mechanics changes before another hardware pass.",
        "",
        "Summary:",
        "",
    ])

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    output = write_report(args.output, args.tester, args.device, args.build_id)
    print(f"trial_dish_playtest_report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
