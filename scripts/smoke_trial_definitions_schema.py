"""Smoke-check the Trial Dish JSON export against its checked schema."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "trial_definitions.schema.json"
OUTPUT = ROOT / "artifacts" / "trial_definitions_schema_smoke.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_type(value, expected_type: str, path: str) -> None:
    checks = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "string": lambda item: isinstance(item, str),
    }
    require(expected_type in checks, f"schema type {expected_type!r} is not supported by smoke validator")
    require(checks[expected_type](value), f"{path} should be {expected_type}")


def validate_point(value, path: str) -> None:
    require_type(value, "array", path)
    require(len(value) == 2, f"{path} should contain two numbers")
    require_type(value[0], "number", f"{path}[0]")
    require_type(value[1], "number", f"{path}[1]")


def validate_zone(value, path: str) -> None:
    require_type(value, "array", path)
    require(len(value) == 3, f"{path} should contain name, center, radius")
    require_type(value[0], "string", f"{path}[0]")
    validate_point(value[1], f"{path}[1]")
    require_type(value[2], "number", f"{path}[2]")


def validate_export(schema: dict, payload: dict) -> None:
    for key in schema["required"]:
        require(key in payload, f"export missing top-level key {key}")
    require(payload["schema"] == schema["properties"]["schema"]["const"], "export schema id should match checked schema")
    require(payload["source"] == schema["properties"]["source"]["const"], "export source should match checked schema")
    require_type(payload["trial_count"], "integer", "trial_count")
    require_type(payload["trials"], "array", "trials")
    require(payload["trial_count"] == len(payload["trials"]), "trial_count should match exported trials length")

    trial_schema = schema["properties"]["trials"]["items"]
    for index, trial in enumerate(payload["trials"]):
        path = f"trials[{index}]"
        require_type(trial, "object", path)
        for key in trial_schema["required"]:
            require(key in trial, f"{path} missing required key {key}")
        for key, spec in trial_schema["properties"].items():
            if key not in trial:
                continue
            if spec.get("$ref") == "#/$defs/point":
                validate_point(trial[key], f"{path}.{key}")
            elif key == "zones":
                require_type(trial[key], "array", f"{path}.zones")
                require(trial[key], f"{path}.zones should not be empty")
                for zone_index, zone in enumerate(trial[key]):
                    validate_zone(zone, f"{path}.zones[{zone_index}]")
            elif spec.get("type") == "array":
                require_type(trial[key], "array", f"{path}.{key}")
                for item_index, item in enumerate(trial[key]):
                    require_type(item, spec["items"]["type"], f"{path}.{key}[{item_index}]")
            elif "type" in spec:
                require_type(trial[key], spec["type"], f"{path}.{key}")


def main() -> int:
    require(SCHEMA.exists(), "checked Trial Dish schema should exist")
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
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    validate_export(schema, payload)
    print("trial_definitions_schema_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
