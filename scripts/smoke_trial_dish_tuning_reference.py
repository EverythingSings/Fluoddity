"""Smoke-check the generated Trial Dish tuning reference."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "trial_dish_tuning_reference_smoke.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_service import TRIAL_DEFINITIONS
from scripts.write_trial_dish_tuning_reference import TUNING_KEYS


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/write_trial_dish_tuning_reference.py",
            "--output",
            str(OUTPUT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode == 0, f"tuning reference generation failed: {proc.stdout}\n{proc.stderr}")
    require("trial_dish_tuning_reference=" in proc.stdout, "generator should print output path")
    require(OUTPUT.exists(), "tuning reference output should exist")

    text = OUTPUT.read_text(encoding="utf-8")
    require("# Trial Dish Tuning Reference" in text, "reference should include heading")
    require("services/trial_service.py" in text, "reference should name the source file")

    for index, definition in enumerate(TRIAL_DEFINITIONS, start=1):
        title = definition["title"].split(": ", 1)[-1]
        require(f"## Trial {index}: {title}" in text, f"reference should include {definition['title']}")
        require(f"- Trial id: `{definition['trial_id']}`" in text, f"reference should include {definition['trial_id']} id")
        for key, label in TUNING_KEYS:
            if key in definition:
                require(
                    f"{label} (`{key}`)" in text,
                    f"reference should include {key} for {definition['trial_id']}",
                )

    required_readability_terms = [
        "Hold time (`hold_seconds`)",
        "Timeout (`failure_seconds`)",
        "Activity threshold (`activity_threshold`)",
        "Hazard strength (`hazard_strength`)",
        "Rival growth (`rival_growth`)",
        "Irradiation cooldown (`irradiation_cooldown_seconds`)",
    ]
    for term in required_readability_terms:
        require(term in text, f"reference should include readable term: {term}")

    print("trial_dish_tuning_reference_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
