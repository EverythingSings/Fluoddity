"""Smoke-check aggregate release-readiness summary behavior."""
from __future__ import annotations

import json
import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = ROOT / "artifacts" / "release_readiness_smoke" / str(os.getpid())
SUMMARY = SMOKE_DIR / "release_readiness_summary.md"
SUMMARY_JSON = SMOKE_DIR / "release_readiness_summary.json"
READY_SUMMARY = SMOKE_DIR / "release_readiness_ready_summary.md"
READY_SUMMARY_JSON = SMOKE_DIR / "release_readiness_ready_summary.json"
STEAM_INPUT_READY = SMOKE_DIR / "steam_input_handoff_summary_ready.md"
DECK_READY = SMOKE_DIR / "steam_deck_preflight_summary_ready.md"
PACKAGE_READY = SMOKE_DIR / "package_validation_summary_ready.md"
PLAYTEST_READY = SMOKE_DIR / "trial_dish_playtest_summary_ready.md"
TUNING_READY = SMOKE_DIR / "trial_dish_tuning_plan_ready.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def write_fixture(path: Path, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Fixture",
                "",
                f"- Status: {status}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    python = sys.executable
    proc = run(
        [
            python,
            "scripts/summarize_release_readiness.py",
            "--output",
            str(SUMMARY),
            "--json-output",
            str(SUMMARY_JSON),
            "--require-ready",
        ]
    )
    require(proc.returncode == 2, "fresh generated artifacts should not be release-ready")
    require("release_readiness_status=not-ready" in proc.stdout, "summary should report not-ready")
    text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: not-ready" in text, "summary file should mark not-ready")
    require("Steam Input handoff" in text, "summary should include Steam Input gate")
    require("Steam Deck preflight" in text, "summary should include Deck preflight gate")
    require("Package runtime validation" in text, "summary should include package runtime gate")
    require("Trial Dish playtest" in text, "summary should include playtest gate")
    require("Post-playtest tuning plan" in text, "summary should include tuning gate")
    require("## Blocking Next Steps" in text, "summary should list blocking next steps")
    payload = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    require(payload["schema"] == "xenoculture.release_readiness.v1", "JSON should include release readiness schema")
    require(payload["status"] == "not-ready", "JSON should mark not-ready")
    require(payload["ready"] is False, "JSON ready flag should be false")
    require(len(payload["gates"]) == 5, "JSON should include five gates")
    require(payload["blocking_next_steps"], "JSON should include blocking next steps")

    write_fixture(STEAM_INPUT_READY, "ready")
    write_fixture(DECK_READY, "ready")
    write_fixture(PACKAGE_READY, "ready")
    write_fixture(PLAYTEST_READY, "tuning-ready")
    write_fixture(TUNING_READY, "actionable")
    ready = run(
        [
            python,
            "scripts/summarize_release_readiness.py",
            "--output",
            str(READY_SUMMARY),
            "--json-output",
            str(READY_SUMMARY_JSON),
            "--steam-input-summary",
            str(STEAM_INPUT_READY),
            "--deck-preflight-summary",
            str(DECK_READY),
            "--package-summary",
            str(PACKAGE_READY),
            "--playtest-summary",
            str(PLAYTEST_READY),
            "--tuning-plan",
            str(TUNING_READY),
            "--require-ready",
        ]
    )
    require(ready.returncode == 0, f"ready fixtures should pass: {ready.stdout}\n{ready.stderr}")
    require("release_readiness_status=ready" in ready.stdout, "ready fixtures should report ready")
    ready_text = READY_SUMMARY.read_text(encoding="utf-8")
    require("- Status: ready" in ready_text, "ready summary should mark ready")
    require("None. All release-readiness gates are ready." in ready_text, "ready summary should have no blockers")
    ready_payload = json.loads(READY_SUMMARY_JSON.read_text(encoding="utf-8"))
    require(ready_payload["status"] == "ready", "ready JSON should mark ready")
    require(ready_payload["ready"] is True, "ready JSON flag should be true")
    require(not ready_payload["blocking_next_steps"], "ready JSON should have no blockers")
    print("release_readiness_summary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
