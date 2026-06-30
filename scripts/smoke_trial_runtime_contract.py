"""Smoke-check that exported Trial Dish data matches runtime-loaded state."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "trial_definitions_runtime_contract.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_definitions import TRIAL_DEFINITIONS
from services.trial_service import TrialService
from state import TrialState


RUNTIME_FIELDS = [
    "trial_id",
    "title",
    "objective",
    "briefing",
    "station_line",
    "story_line",
    "running_hint",
    "onboarding_focus",
    "protocol_steps",
    "unlocked_tools",
    "current_tool",
    "irradiation_charges",
    "irradiation_cooldown_seconds",
    "revert_charges",
    "primer_enabled",
    "primer_center",
    "primer_radius",
    "primer_power",
    "primer_seconds",
    "hold_seconds",
    "failure_seconds",
    "activity_threshold",
    "win_condition",
    "hazard_enabled",
    "hazard_name",
    "hazard_center_x",
    "hazard_width",
    "hazard_strength",
    "rival_enabled",
    "rival_name",
    "rival_center",
    "rival_radius",
    "rival_growth",
    "rival_strength",
    "rival_activity_threshold",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def json_value(value):
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def zones_from_state(trial: TrialState) -> list:
    return [
        [zone.name, json_value(zone.center), zone.radius]
        for zone in trial.zones
    ]


def main() -> int:
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/export_trial_definitions.py",
            "--output",
            str(OUTPUT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode == 0, f"trial definition export failed: {proc.stdout}\n{proc.stderr}")

    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    trials = payload["trials"]
    require(len(trials) == len(TRIAL_DEFINITIONS), "export should include every authored trial")

    service = TrialService()
    for index, exported in enumerate(trials):
        trial = TrialState(game_mode=True)
        service.load_trial(trial, index)

        require(trial.trial_index == index, f"{exported['trial_id']} runtime index should match export order")
        require(trial.trial_count == len(trials), f"{exported['trial_id']} runtime trial count should match export")
        require(trial.default_tool == exported["current_tool"], f"{exported['trial_id']} default tool should match export")
        require(trial.zones and zones_from_state(trial) == exported["zones"], f"{exported['trial_id']} zones should match export")

        for field in RUNTIME_FIELDS:
            actual = json_value(getattr(trial, field))
            expected = exported[field]
            require(actual == expected, f"{exported['trial_id']} runtime field {field} should match export")

    print("trial_runtime_contract_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
