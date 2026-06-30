"""Smoke-check the Steam Deck hardware packet generator."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

EXPECTED_REPORTS = {
    ROOT / "artifacts" / "steam_deck_packet_index.md": "# Steam Deck Hardware Packet",
    ROOT / "artifacts" / "steam_input_handoff.md": "# Steam Input Handoff",
    ROOT / "artifacts" / "trial_dish_playtest.md": "# Trial Dish Manual Playtest Report",
    ROOT / "artifacts" / "trial_dish_playtest_summary.md": "# Trial Dish Playtest Summary",
    ROOT / "artifacts" / "trial_dish_tuning_reference.md": "# Trial Dish Tuning Reference",
    ROOT / "artifacts" / "trial_dish_tuning_plan.md": "# Trial Dish Post-Playtest Tuning Plan",
    ROOT / "artifacts" / "steam_deck_preflight.md": "# Steam Deck Preflight Report",
}
EXPECTED_JSON_REPORTS = {
    ROOT / "artifacts" / "trial_definitions.json": "fluoddity.trial_definitions.v1",
}
EXPECTED_JSON_SCHEMA_REPORTS = {
    ROOT / "artifacts" / "trial_definitions.schema.json": "fluoddity.trial_definitions.v1",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_packet(python: str) -> None:
    proc = subprocess.run(
        [
            python,
            "scripts/prepare_steam_deck_packet.py",
            "--tester",
            "Smoke",
            "--device",
            "Local",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode == 0, f"packet command failed: {proc.stdout}\n{proc.stderr}")
    require("steam_deck_packet_reports=" in proc.stdout, "packet command should print report paths")
    require("steam_deck_packet_build=" in proc.stdout, "packet command should print build metadata")
    require("steam_deck_packet_index=artifacts/steam_deck_packet_index.md" in proc.stdout, "packet command should print index path")

    for path, heading in EXPECTED_REPORTS.items():
        require(path.exists(), f"missing generated report: {path}")
        text = path.read_text(encoding="utf-8")
        require(heading in text, f"report should contain heading {heading!r}: {path}")
    for path, schema in EXPECTED_JSON_REPORTS.items():
        require(path.exists(), f"missing generated JSON report: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("schema") == schema, f"JSON report should contain schema {schema!r}: {path}")
    for path, schema_id in EXPECTED_JSON_SCHEMA_REPORTS.items():
        require(path.exists(), f"missing generated JSON schema report: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("$id") == schema_id, f"JSON schema report should contain $id {schema_id!r}: {path}")
        require(payload.get("properties", {}).get("trials"), f"JSON schema report should describe trial records: {path}")

    handoff = (ROOT / "artifacts" / "steam_input_handoff.md").read_text(encoding="utf-8")
    playtest = (ROOT / "artifacts" / "trial_dish_playtest.md").read_text(encoding="utf-8")
    summary = (ROOT / "artifacts" / "trial_dish_playtest_summary.md").read_text(encoding="utf-8")
    index = (ROOT / "artifacts" / "steam_deck_packet_index.md").read_text(encoding="utf-8")
    for report_name, text in {
        "packet index": index,
        "Steam Input handoff": handoff,
        "playtest report": playtest,
    }.items():
        require(f"- Game: {GAME_TITLE}" in text, f"{report_name} should be stamped with game title")
        require(f"- Engine/package: {ENGINE_NAME}" in text, f"{report_name} should be stamped with engine/package name")
    for report in [
        "artifacts/steam_input_handoff.md",
        "artifacts/trial_definitions.json",
        "artifacts/trial_definitions.schema.json",
        "artifacts/trial_dish_playtest.md",
        "artifacts/trial_dish_playtest_summary.md",
        "artifacts/trial_dish_tuning_reference.md",
        "artifacts/trial_dish_tuning_plan.md",
        "artifacts/steam_deck_preflight.md",
    ]:
        require(report in index, f"packet index should reference {report}")
    require("## Hardware Pass Order" in index, "packet index should include hardware pass order")
    require("trial_dish_tuning_reference.md" in index, "packet index should reference the tuning reference")
    require("Controller-only Trial Dish playtest summary is tuning-ready" in index, "packet index should list tuning-ready external gate")
    require("- Build:" in handoff, "Steam Input handoff should be stamped with build metadata")
    require("- Build / commit:" in playtest, "playtest report should be stamped with build metadata")
    require("- Status: not-ready" in summary, "fresh packet summary should reject the blank playtest template")
    require("Missing Evidence" in summary, "fresh packet summary should list missing playtest evidence")
    tuning = (ROOT / "artifacts" / "trial_dish_tuning_reference.md").read_text(encoding="utf-8")
    require("Trial 1: Bloom" in tuning, "tuning reference should include Trial 1")
    require("Activity threshold (`activity_threshold`)" in tuning, "tuning reference should include activity threshold")
    require("Rival growth (`rival_growth`)" in tuning, "tuning reference should include rival growth")
    plan = (ROOT / "artifacts" / "trial_dish_tuning_plan.md").read_text(encoding="utf-8")
    require("- Status: blocked" in plan, "fresh packet tuning plan should block on incomplete evidence")
    require("## Blocker" in plan, "fresh packet tuning plan should explain the evidence blocker")

    preflight = (ROOT / "artifacts" / "steam_deck_preflight.md").read_text(encoding="utf-8")
    require(f"- Game: {GAME_TITLE}" in preflight, "preflight report should be stamped with game title")
    require(f"- Engine/package: {ENGINE_NAME}" in preflight, "preflight report should be stamped with engine/package name")
    require("- Build:" in preflight, "preflight report should be stamped with build metadata")
    require(
        "Packet index: artifacts/steam_deck_packet_index.md" in preflight,
        "preflight packet should reference the packet index",
    )
    require(
        "## Companion Manual Reports" in preflight,
        "preflight packet should list companion reports",
    )
    require(
        "artifacts/trial_dish_playtest.md" in preflight,
        "preflight packet should reference playtest report",
    )
    require(
        "artifacts/trial_dish_playtest_summary.md" in preflight,
        "preflight packet should reference playtest summary",
    )
    require(
        "artifacts/trial_dish_tuning_reference.md" in preflight,
        "preflight packet should reference tuning reference",
    )
    require(
        "artifacts/trial_dish_tuning_plan.md" in preflight,
        "preflight packet should reference tuning plan",
    )


def expect_failure(python: str, args: list[str], expected_text: str) -> None:
    proc = subprocess.run(
        [python, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode != 0, f"expected command to fail: {' '.join(args)}")
    combined = proc.stdout + proc.stderr
    require(expected_text in combined, f"expected {expected_text!r} in failure output")


def main() -> int:
    python = sys.executable
    run_packet(python)
    expect_failure(
        python,
        ["scripts/steam_deck_preflight.py", "--with-fed-results", "--no-run"],
        "--with-fed-results requires --with-visual",
    )
    expect_failure(
        python,
        ["scripts/prepare_steam_deck_packet.py", "--with-visual"],
        "--with-visual and --with-fed-results require --run-automated",
    )
    print("steam_deck_packet_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
