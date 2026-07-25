"""Summarize a filled Trial Dish playtest report into tuning-ready evidence."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "artifacts" / "trial_dish_playtest.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "trial_dish_playtest_summary.md"

REQUIRED_FIELDS = [
    "Tester",
    "Device",
    "Build / commit",
    "Launch target",
    "Controller",
]

REQUIRED_RATINGS = [
    "Premise clarity",
    "Visual readability",
    "Controller confidence",
    "Objective clarity",
    "Action-feedback loop",
    "Meaningful choice",
    "Flow balance",
    "Friction/struggle",
    "Desire to retry",
]

REQUIRED_TUNING_ROWS = [
    "Trial 1 threshold/hold time",
    "Trial 2 threshold/hold time/hazard strength",
    "Trial 3 rival strength/timer/tool cooldowns",
    "HUD/copy changes",
    "Visual noise/readability changes",
]

VERDICT_OPTIONS = {
    "Ready for another hardware pass without tuning.",
    "Needs threshold/copy/visual tuning before another hardware pass.",
    "Needs mechanics changes before another hardware pass.",
}


@dataclass(frozen=True)
class Rating:
    dimension: str
    value: int
    notes: str


@dataclass(frozen=True)
class PlaytestSummary:
    source: Path
    fields: dict[str, str]
    ratings: list[Rating]
    selected_verdicts: list[str]
    tuning_notes: dict[str, str]
    missing_evidence: list[str]

    @property
    def tuning_ready(self) -> bool:
        return not self.missing_evidence

    @property
    def average_rating(self) -> float | None:
        if not self.ratings:
            return None
        return sum(rating.value for rating in self.ratings) / len(self.ratings)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize a filled Trial Dish playtest report.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Filled playtest report path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown summary output path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit nonzero when the report is still missing required tuning evidence.",
    )
    parser.add_argument("--expected-build", default="", help="Expected packet build identity.")
    parser.add_argument("--expected-tester", default="", help="Expected tester when supplied by the packet.")
    parser.add_argument("--expected-device", default="", help="Expected device when supplied by the packet.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def metadata_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"- ([^:]+):\s*(.*)$", line)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def parse_ratings(text: str) -> list[Rating]:
    ratings: list[Rating] = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) != 3:
            continue
        dimension, rating_text, notes = parts
        if dimension in {"Dimension", "---"}:
            continue
        if dimension not in REQUIRED_RATINGS:
            continue
        if not rating_text:
            continue
        try:
            rating = int(rating_text)
        except ValueError:
            continue
        if 1 <= rating <= 5:
            ratings.append(Rating(dimension, rating, notes))
    return ratings


def selected_verdicts(text: str) -> list[str]:
    verdicts: list[str] = []
    in_verdict_section = False
    for line in text.splitlines():
        if line.strip() == "## Verdict":
            in_verdict_section = True
            continue
        if in_verdict_section and line.startswith("## "):
            break
        if not in_verdict_section:
            continue
        match = re.match(r"- \[[xX]\]\s+(.+)$", line.strip())
        if match and match.group(1).strip() in VERDICT_OPTIONS:
            verdicts.append(match.group(1).strip())
    return verdicts


def parse_tuning_notes(text: str) -> dict[str, str]:
    notes: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"- (Trial [123][^:]+|HUD/copy changes|Visual noise/readability changes):\s*(.*)$", line)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        notes[key] = value
    return notes


def summarize(
    path: Path,
    *,
    expected_build: str = "",
    expected_tester: str = "",
    expected_device: str = "",
) -> PlaytestSummary:
    source = resolve_path(path)
    text = source.read_text(encoding="utf-8")
    fields = metadata_fields(text)
    ratings = parse_ratings(text)
    verdicts = selected_verdicts(text)
    tuning_notes = parse_tuning_notes(text)

    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        if not fields.get(field):
            missing.append(f"Missing `{field}` metadata.")
    for label, expected in (
        ("Build / commit", expected_build),
        ("Tester", expected_tester),
        ("Device", expected_device),
    ):
        if expected and fields.get(label, "") != expected:
            missing.append(
                f"`{label}` does not match this packet "
                f"(expected `{expected}`, found `{fields.get(label) or '(missing)'}`)."
            )

    rated = {rating.dimension for rating in ratings}
    for row in REQUIRED_RATINGS:
        if row not in rated:
            missing.append(f"Missing 1-5 rating for `{row}`.")

    if not verdicts:
        missing.append("No verdict checkbox is selected.")
    elif len(verdicts) > 1:
        missing.append("Select exactly one verdict checkbox.")

    for row in REQUIRED_TUNING_ROWS:
        if not tuning_notes.get(row):
            missing.append(f"Missing tuning note for `{row}`.")

    return PlaytestSummary(source, fields, ratings, verdicts, tuning_notes, missing)


def write_summary(summary: PlaytestSummary, output: Path) -> Path:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    status = "tuning-ready" if summary.tuning_ready else "not-ready"
    average = summary.average_rating
    average_text = f"{average:.2f}" if average is not None else "n/a"
    lowest = sorted(summary.ratings, key=lambda rating: rating.value)[:3]

    lines = [
        "# Trial Dish Playtest Summary",
        "",
        f"- Source: `{summary.source.relative_to(ROOT).as_posix()}`",
        f"- Status: {status}",
        f"- Completed ratings: {len(summary.ratings)}/{len(REQUIRED_RATINGS)}",
        f"- Average rating: {average_text}",
        "",
        "## Lowest Ratings",
        "",
    ]
    if lowest:
        lines.extend(f"- {rating.dimension}: {rating.value} ({rating.notes or 'no note'})" for rating in lowest)
    else:
        lines.append("- No completed ratings.")

    lines.extend(["", "## Verdict", ""])
    if summary.selected_verdicts:
        lines.extend(f"- {verdict}" for verdict in summary.selected_verdicts)
    else:
        lines.append("- No selected verdict.")

    lines.extend(["", "## Tuning Targets", ""])
    for row in REQUIRED_TUNING_ROWS:
        lines.append(f"- {row}: {summary.tuning_notes.get(row) or '(missing)'}")

    lines.extend(["", "## Missing Evidence", ""])
    if summary.missing_evidence:
        lines.extend(f"- {item}" for item in summary.missing_evidence)
    else:
        lines.append("- None.")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    summary = summarize(
        args.input,
        expected_build=args.expected_build,
        expected_tester=args.expected_tester,
        expected_device=args.expected_device,
    )
    output = write_summary(summary, args.output)
    print(f"trial_dish_playtest_summary={output}")
    print(f"trial_dish_playtest_status={'ready' if summary.tuning_ready else 'not_ready'}")
    if args.require_ready and not summary.tuning_ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
