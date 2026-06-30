"""Write a tuning reference for current Trial Dish thresholds."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "trial_dish_tuning_reference.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_service import TRIAL_DEFINITIONS


TUNING_KEYS = [
    ("hold_seconds", "Hold time"),
    ("failure_seconds", "Timeout"),
    ("activity_threshold", "Activity threshold"),
    ("hazard_width", "Hazard width"),
    ("hazard_strength", "Hazard strength"),
    ("rival_radius", "Rival start radius"),
    ("rival_growth", "Rival growth"),
    ("rival_strength", "Rival strength"),
    ("rival_activity_threshold", "Rival control threshold"),
    ("irradiation_charges", "Irradiation charges"),
    ("irradiation_cooldown_seconds", "Irradiation cooldown"),
    ("revert_charges", "Revert charges"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the Trial Dish tuning reference.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown output path.")
    return parser.parse_args()


def format_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def write_reference(output: Path) -> Path:
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Trial Dish Tuning Reference",
        "",
        "Generated from `services/trial_service.py`. Read this next to `artifacts/trial_dish_playtest_summary.md` before changing thresholds.",
        "",
    ]

    for index, definition in enumerate(TRIAL_DEFINITIONS, start=1):
        title = definition["title"].split(": ", 1)[-1]
        lines.extend([
            f"## Trial {index}: {title}",
            "",
            f"- Trial id: `{definition['trial_id']}`",
            f"- Objective: {definition['objective']}",
            f"- Win condition: `{definition.get('win_condition', 'hold_all_zones')}`",
            f"- Tools: {', '.join(definition.get('unlocked_tools', []))}",
            f"- Zones: {len(definition.get('zones', []))}",
            "",
            "| Tunable | Value |",
            "| --- | --- |",
        ])
        for key, label in TUNING_KEYS:
            if key in definition:
                lines.append(f"| {label} (`{key}`) | {format_value(definition[key])} |")
        lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    output = write_reference(args.output)
    print(f"trial_dish_tuning_reference={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
