"""Smoke-check Steam Input handoff summary readiness parsing."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = ROOT / "artifacts" / "steam_input_handoff_summary_smoke" / str(os.getpid())
TEMPLATE = SMOKE_DIR / "steam_input_handoff_summary_template.md"
FILLED = SMOKE_DIR / "steam_input_handoff_summary_filled.md"
SUMMARY = SMOKE_DIR / "steam_input_handoff_summary_smoke.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def fill_handoff(text: str) -> str:
    text = text.replace("- [ ] ", "- [x] ")
    text = text.replace("- Steamworks app / branch:", "- Steamworks app / branch: Smoke app / default")
    text = text.replace("- Imported manifest version:", "- Imported manifest version: steam_input/steam_input_manifest.vdf")
    text = text.replace("- Default configuration name:", "- Default configuration name: TrialDish Deck Smoke")
    text = text.replace("- Glyph rendering path:", "- Glyph rendering path: official Steam Deck glyphs")
    text = text.replace("- Tester / device:", "- Tester / device: Smoke / Steam Deck OLED")
    text = text.replace("- Defects or remaps:", "- Defects or remaps: none")
    return text


def main() -> int:
    python = sys.executable
    proc = run(
        [
            python,
            "scripts/write_steam_input_handoff.py",
            "--output",
            str(TEMPLATE),
            "--build-id",
            "smoke-build",
        ]
    )
    require(proc.returncode == 0, f"handoff template failed: {proc.stdout}\n{proc.stderr}")

    blank = run(
        [
            python,
            "scripts/summarize_steam_input_handoff.py",
            "--input",
            str(TEMPLATE),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(blank.returncode == 2, "blank handoff should not be ready")
    require("steam_input_handoff_status=not-ready" in blank.stdout, "blank handoff should report not-ready")
    summary_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: not-ready" in summary_text, "summary should mark blank handoff not-ready")
    require("Steamworks manifest import" in summary_text, "summary should list unchecked Steamworks import gate")
    require("Import Notes: `Steamworks app / branch` is missing Steam Input evidence." in summary_text, "summary should require import notes")

    FILLED.write_text(fill_handoff(TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    ready = run(
        [
            python,
            "scripts/summarize_steam_input_handoff.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(ready.returncode == 0, f"filled handoff should be ready: {ready.stdout}\n{ready.stderr}")
    require("steam_input_handoff_status=ready" in ready.stdout, "filled handoff should report ready")
    ready_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: ready" in ready_text, "summary should mark filled handoff ready")
    require("None. Steam Input handoff evidence is complete." in ready_text, "ready summary should have no missing evidence")

    print("steam_input_handoff_summary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
