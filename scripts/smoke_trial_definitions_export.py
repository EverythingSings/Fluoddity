"""Smoke-check the Trial Dish JSON export artifact."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "trial_definitions_smoke.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_definitions import TRIAL_DEFINITIONS


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


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
    require("trial_definitions_json=" in proc.stdout, "exporter should print output path")
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))

    require(payload["schema"] == "fluoddity.trial_definitions.v1", "export should include schema id")
    require(payload["source"] == "services/trial_definitions.py", "export should name source module")
    require(payload["trial_count"] == len(TRIAL_DEFINITIONS), "export trial count should match source")
    require(len(payload["trials"]) == len(TRIAL_DEFINITIONS), "export should contain all trials")
    require([trial["trial_id"] for trial in payload["trials"]] == [trial["trial_id"] for trial in TRIAL_DEFINITIONS], "export should preserve trial order")

    for trial in payload["trials"]:
        require("hazard_enabled" in trial, "export should include effective hazard default")
        require("rival_enabled" in trial, "export should include effective rival default")
        require("win_condition" in trial, "export should include effective win-condition default")
        require("irradiation_charges" in trial, "export should include effective irradiation default")
        require("revert_charges" in trial, "export should include effective revert default")
        require(isinstance(trial["zones"], list), "exported zones should be JSON arrays")
        for zone in trial["zones"]:
            require(isinstance(zone, list) and len(zone) == 3, "exported zone should be [name, center, radius]")
            require(isinstance(zone[1], list) and len(zone[1]) == 2, "exported zone center should be a JSON array")

    print("trial_definitions_export_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
