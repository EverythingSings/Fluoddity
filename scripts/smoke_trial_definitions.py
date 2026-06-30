"""Validate Trial Dish definition schema and balance guardrails."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_service import TRIAL_DEFINITIONS
from scripts.write_trial_dish_tuning_reference import TUNING_KEYS


REQUIRED_COMMON_KEYS = {
    "trial_id",
    "title",
    "objective",
    "briefing",
    "station_line",
    "story_line",
    "running_hint",
    "protocol_steps",
    "unlocked_tools",
    "current_tool",
    "hold_seconds",
    "failure_seconds",
    "activity_threshold",
    "zones",
}

KNOWN_TUNING_KEYS = {key for key, _ in TUNING_KEYS}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_number(value, message: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
    require(isinstance(value, (int, float)), f"{message} should be numeric")
    if minimum is not None:
        require(value >= minimum, f"{message} should be >= {minimum}")
    if maximum is not None:
        require(value <= maximum, f"{message} should be <= {maximum}")


def validate_zone(definition: dict, zone) -> None:
    trial_id = definition["trial_id"]
    require(isinstance(zone, tuple) and len(zone) == 3, f"{trial_id} zone should be (name, center, radius)")
    name, center, radius = zone
    require(isinstance(name, str) and name, f"{trial_id} zone name should be nonempty")
    require(isinstance(center, tuple) and len(center) == 2, f"{trial_id} zone center should be a 2-tuple")
    require_number(center[0], f"{trial_id} zone {name} x", minimum=0.0, maximum=1.0)
    require_number(center[1], f"{trial_id} zone {name} y", minimum=0.0, maximum=1.0)
    require_number(radius, f"{trial_id} zone {name} radius", minimum=0.01, maximum=0.25)


def validate_definition(index: int, definition: dict) -> None:
    missing = sorted(REQUIRED_COMMON_KEYS - definition.keys())
    require(not missing, f"trial {index} missing keys: {', '.join(missing)}")
    trial_id = definition["trial_id"]

    require(definition["title"].startswith(f"Trial {index}: "), f"{trial_id} title should match sequence number")
    require("Nutrient Gel" in definition["unlocked_tools"], f"{trial_id} should include the base tool")
    require(definition["current_tool"] in definition["unlocked_tools"], f"{trial_id} current tool should be unlocked")
    require(1 <= len(definition["protocol_steps"]) <= 3, f"{trial_id} should keep onboarding protocol compact")
    require(definition["briefing"].strip(), f"{trial_id} briefing should be nonempty")
    require(definition["story_line"].strip(), f"{trial_id} story line should be nonempty")

    require_number(definition["activity_threshold"], f"{trial_id} activity threshold", minimum=0.0, maximum=0.01)
    require_number(definition["failure_seconds"], f"{trial_id} timeout", minimum=10.0, maximum=180.0)
    require_number(definition["hold_seconds"], f"{trial_id} hold time", minimum=0.0, maximum=30.0)

    zones = definition["zones"]
    require(isinstance(zones, list) and zones, f"{trial_id} should define visible objective zones")
    zone_names = set()
    for zone in zones:
        validate_zone(definition, zone)
        require(zone[0] not in zone_names, f"{trial_id} duplicate zone name: {zone[0]}")
        zone_names.add(zone[0])

    if definition.get("hazard_enabled", False):
        require("hazard_name" in definition, f"{trial_id} hazard should be named")
        require_number(definition.get("hazard_center_x"), f"{trial_id} hazard center", minimum=0.0, maximum=1.0)
        require_number(definition.get("hazard_width"), f"{trial_id} hazard width", minimum=0.01, maximum=0.5)
        require_number(definition.get("hazard_strength"), f"{trial_id} hazard strength", minimum=0.0, maximum=1.0)

    if definition.get("win_condition", "hold_all_zones") == "territory_at_timeout":
        require(definition.get("rival_enabled") is True, f"{trial_id} territory trial should enable rival pressure")
        require_number(definition.get("rival_radius"), f"{trial_id} rival radius", minimum=0.01, maximum=0.4)
        require_number(definition.get("rival_growth"), f"{trial_id} rival growth", minimum=0.0, maximum=0.02)
        require_number(definition.get("rival_strength"), f"{trial_id} rival strength", minimum=0.0, maximum=1.0)
        require_number(
            definition.get("rival_activity_threshold"),
            f"{trial_id} rival control threshold",
            minimum=0.0,
            maximum=1.0,
        )
    else:
        require(definition["hold_seconds"] > 0.0, f"{trial_id} hold trial should require positive hold time")
        require(definition["failure_seconds"] > definition["hold_seconds"], f"{trial_id} timeout should exceed hold time")


def smoke_trial_definitions() -> None:
    require(len(TRIAL_DEFINITIONS) == 3, "V1 should define exactly three Trial Dishes")
    trial_ids = [definition["trial_id"] for definition in TRIAL_DEFINITIONS]
    require(len(set(trial_ids)) == len(trial_ids), "trial ids should be unique")

    for index, definition in enumerate(TRIAL_DEFINITIONS, start=1):
        validate_definition(index, definition)

    require(len(TRIAL_DEFINITIONS[0]["zones"]) == 1, "Trial 1 should remain visually minimal")
    require(not TRIAL_DEFINITIONS[0].get("hazard_enabled", False), "Trial 1 should not introduce hazards")
    require(TRIAL_DEFINITIONS[1].get("hazard_enabled") is True, "Trial 2 should introduce the passive hazard")
    require(TRIAL_DEFINITIONS[2].get("rival_enabled") is True, "Trial 3 should introduce rival pressure")
    require("Irradiate Strain" in TRIAL_DEFINITIONS[2]["unlocked_tools"], "Trial 3 should unlock irradiation")
    require("Revert Strain" in TRIAL_DEFINITIONS[2]["unlocked_tools"], "Trial 3 should unlock revert")

    tunable_keys_in_trials = {
        key
        for definition in TRIAL_DEFINITIONS
        for key in definition
        if key in KNOWN_TUNING_KEYS
    }
    require(
        {"hold_seconds", "failure_seconds", "activity_threshold"} <= tunable_keys_in_trials,
        "tuning reference should cover core timing/activity values",
    )


def main() -> int:
    smoke_trial_definitions()
    print(f"trial_definition_smoke=ok trials={len(TRIAL_DEFINITIONS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
