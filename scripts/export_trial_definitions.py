"""Export Trial Dish definitions as machine-readable JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "trial_definitions.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_definitions import TRIAL_DEFINITIONS


RUNTIME_DEFAULTS = {
    "station_line": "",
    "story_line": "",
    "running_hint": "",
    "onboarding_focus": "single_culture",
    "protocol_steps": [],
    "unlocked_tools": ["Nutrient Gel"],
    "current_tool": "Nutrient Gel",
    "irradiation_charges": 0,
    "irradiation_cooldown_seconds": 0.0,
    "revert_charges": 0,
    "primer_enabled": False,
    "primer_center": (0.5, 0.5),
    "primer_radius": 0.055,
    "primer_power": 1.0,
    "primer_seconds": 1.0,
    "win_condition": "hold_all_zones",
    "hazard_enabled": False,
    "hazard_name": "Antibiotic Band",
    "hazard_center_x": 0.5,
    "hazard_width": 0.0,
    "hazard_strength": 0.0,
    "rival_enabled": False,
    "rival_name": "Rival Bloom",
    "rival_center": (0.82, 0.52),
    "rival_radius": 0.10,
    "rival_growth": 0.004,
    "rival_strength": 0.65,
    "rival_activity_threshold": 0.45,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Trial Dish definitions to JSON.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="JSON output path.")
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def runtime_definition(definition: dict) -> dict:
    normalized = dict(RUNTIME_DEFAULTS)
    normalized.update(definition)
    return normalized


def export_definitions(output: Path) -> Path:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "fluoddity.trial_definitions.v1",
        "source": "services/trial_definitions.py",
        "trial_count": len(TRIAL_DEFINITIONS),
        "trials": [runtime_definition(definition) for definition in TRIAL_DEFINITIONS],
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    output = export_definitions(args.output)
    print(f"trial_definitions_json={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
