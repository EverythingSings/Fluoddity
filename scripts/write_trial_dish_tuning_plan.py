"""Write a post-playtest tuning plan from summary and current values."""
from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "artifacts" / "trial_dish_playtest_summary.md"
DEFAULT_REFERENCE = ROOT / "artifacts" / "trial_dish_tuning_reference.md"
DEFAULT_OUTPUT = ROOT / "artifacts" / "trial_dish_tuning_plan.md"

PLAN_SECTIONS = [
    ("Trial 1 threshold/hold time", "Trial 1: Bloom"),
    ("Trial 2 threshold/hold time/hazard strength", "Trial 2: Antibiotic Band"),
    ("Trial 3 rival strength/timer/tool cooldowns", "Trial 3: Rival Bloom"),
    ("HUD/copy changes", "HUD and Copy"),
    ("Visual noise/readability changes", "Visual Readability"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a Trial Dish post-playtest tuning plan.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY, help="Playtest summary path.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE, help="Tuning reference path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown output path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit nonzero when the playtest summary is not tuning-ready.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def summary_status(text: str) -> str:
    match = re.search(r"^- Status:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"


def summary_tuning_targets(text: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"- (Trial [123][^:]+|HUD/copy changes|Visual noise/readability changes):\s*(.*)$", line)
        if not match:
            continue
        targets[match.group(1).strip()] = match.group(2).strip()
    return targets


def reference_section(text: str, heading: str) -> list[str]:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index
            break
    if start is None:
        return []

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return lines[start:end]


def reference_table_rows(text: str, heading: str) -> list[str]:
    rows = []
    for line in reference_section(text, heading):
        if not line.startswith("| "):
            continue
        if line.startswith("| Tunable") or line.startswith("| ---"):
            continue
        rows.append(line)
    return rows


def write_plan(summary_path: Path, reference_path: Path, output_path: Path) -> tuple[Path, bool]:
    summary_path = resolve_path(summary_path)
    reference_path = resolve_path(reference_path)
    output_path = resolve_path(output_path)
    summary = summary_path.read_text(encoding="utf-8")
    reference = reference_path.read_text(encoding="utf-8")
    status = summary_status(summary)
    ready = status == "tuning-ready"
    targets = summary_tuning_targets(summary)

    lines = [
        "# Trial Dish Post-Playtest Tuning Plan",
        "",
        f"- Summary: `{summary_path.relative_to(ROOT).as_posix()}`",
        f"- Reference: `{reference_path.relative_to(ROOT).as_posix()}`",
        f"- Status: {'actionable' if ready else 'blocked'}",
        "",
    ]

    if not ready:
        lines.extend([
            "## Blocker",
            "",
            "The playtest summary is not tuning-ready. Fill the manual playtest report and rerun `python scripts/summarize_trial_dish_playtest.py --require-ready` before changing thresholds.",
            "",
        ])

    lines.extend([
        "## Tuning Actions",
        "",
    ])

    for target_key, title in PLAN_SECTIONS:
        note = targets.get(target_key, "(missing)")
        lines.extend([
            f"### {title}",
            "",
            f"- Playtest finding: {note}",
        ])
        if title.startswith("Trial "):
            rows = reference_table_rows(reference, title)
            if rows:
                lines.append("- Current values:")
                lines.extend(f"  - {row.strip('| ').replace(' | ', ': ')}" for row in rows)
        lines.extend([
            "- Proposed change:",
            "- Verification:",
            "",
        ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path, ready


def main() -> int:
    args = parse_args()
    output, ready = write_plan(args.summary, args.reference, args.output)
    print(f"trial_dish_tuning_plan={output}")
    print(f"trial_dish_tuning_plan_status={'actionable' if ready else 'blocked'}")
    if args.require_ready and not ready:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
