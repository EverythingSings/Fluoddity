"""Smoke-check release readiness JSON against its checked schema."""
from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "release_readiness.schema.json"
SMOKE_DIR = ROOT / "artifacts" / "release_readiness_schema_smoke" / str(os.getpid())
OUTPUT = SMOKE_DIR / "release_readiness_schema_smoke.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_type(value, expected_type: str, path: str) -> None:
    checks = {
        "array": lambda item: isinstance(item, list),
        "boolean": lambda item: isinstance(item, bool),
        "object": lambda item: isinstance(item, dict),
        "string": lambda item: isinstance(item, str),
    }
    require(expected_type in checks, f"unsupported schema type {expected_type!r}")
    require(checks[expected_type](value), f"{path} should be {expected_type}")


def validate_payload(schema: dict, payload: dict) -> None:
    for key in schema["required"]:
        require(key in payload, f"release readiness JSON missing {key}")
    require(payload["schema"] == schema["properties"]["schema"]["const"], "schema id should match checked schema")
    require(payload["status"] in schema["properties"]["status"]["enum"], "status should be a known value")
    require_type(payload["ready"], "boolean", "ready")
    require((payload["status"] == "ready") == payload["ready"], "ready flag should match status")
    require_type(payload["gates"], "array", "gates")
    require(payload["gates"], "gates should not be empty")
    require_type(payload["blocking_next_steps"], "array", "blocking_next_steps")

    for index, gate in enumerate(payload["gates"]):
        path = f"gates[{index}]"
        require_type(gate, "object", path)
        for key in schema["$defs"]["gate"]["required"]:
            require(key in gate, f"{path} missing {key}")
        require_type(gate["name"], "string", f"{path}.name")
        require_type(gate["source"], "string", f"{path}.source")
        require_type(gate["status"], "string", f"{path}.status")
        require_type(gate["ready"], "boolean", f"{path}.ready")
        require_type(gate["next_step"], "string", f"{path}.next_step")

    for index, blocker in enumerate(payload["blocking_next_steps"]):
        path = f"blocking_next_steps[{index}]"
        require_type(blocker, "object", path)
        for key in schema["$defs"]["blocker"]["required"]:
            require(key in blocker, f"{path} missing {key}")
        require_type(blocker["gate"], "string", f"{path}.gate")
        require_type(blocker["next_step"], "string", f"{path}.next_step")


def main() -> int:
    require(SCHEMA.exists(), "checked release readiness schema should exist")
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/summarize_release_readiness.py",
            "--output",
            str(SMOKE_DIR / "release_readiness_schema_smoke.md"),
            "--json-output",
            str(OUTPUT),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode == 0, f"release readiness export failed: {proc.stdout}\n{proc.stderr}")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    validate_payload(schema, payload)
    print("release_readiness_schema_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
