"""Smoke-check Steam Deck preflight summary readiness parsing."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = ROOT / "artifacts" / "steam_deck_preflight_summary_smoke" / str(os.getpid())
TEMPLATE = SMOKE_DIR / "steam_deck_preflight_summary_template.md"
FILLED = SMOKE_DIR / "steam_deck_preflight_summary_filled.md"
SUMMARY = SMOKE_DIR / "steam_deck_preflight_summary_smoke.md"
PERF_REPORT = SMOKE_DIR / "steam_deck_preflight_perf_highlight.md"
VISUAL_EVIDENCE = SMOKE_DIR / "steam_deck_visual_evidence.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def fill_preflight(text: str) -> str:
    text = text.replace("- Automated status: skipped", "- Automated status: passed")
    text = text.replace("- [ ] ", "- [x] ")
    text = text.replace("- Average FPS observed over five minutes:", "- Average FPS observed over five minutes: 45")
    text = text.replace("- Hardware tester:", "- Hardware tester: Smoke")
    text = text.replace("- Device / OS build:", "- Device / OS build: Steam Deck OLED / smoke")
    text = text.replace("- Steam launch target:", "- Steam launch target: ./run_steam_deck.sh")
    text = text.replace("- Lowest legibility issue found:", "- Lowest legibility issue found: none")
    text = text.replace("- Input or suspend/resume defects:", "- Input or suspend/resume defects: none")
    return text


def main() -> int:
    python = sys.executable
    proc = run(
        [
            python,
            "scripts/steam_deck_preflight.py",
            "--no-run",
            "--output",
            str(TEMPLATE),
            "--visual-evidence-output",
            str(VISUAL_EVIDENCE),
            "--build-id",
            "smoke-build",
        ]
    )
    require(proc.returncode == 0, f"preflight template failed: {proc.stdout}\n{proc.stderr}")

    blank = run(
        [
            python,
            "scripts/summarize_steam_deck_preflight.py",
            "--input",
            str(TEMPLATE),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(blank.returncode == 2, "blank preflight should not be release-ready")
    require("steam_deck_preflight_status=not-ready" in blank.stdout, "blank preflight should report not-ready")
    summary_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: not-ready" in summary_text, "summary should mark blank preflight not-ready")
    require("Actual Steam Deck hardware performance" in summary_text, "summary should list unchecked external gates")
    require("Notes: `Hardware tester` is missing hardware-pass evidence." in summary_text, "summary should require hardware tester notes")

    import steam_deck_preflight

    command = [
        python,
        "scripts/smoke_game_v1.py",
        "--with-deck-performance",
        "--python",
        python,
    ]
    steam_deck_preflight.write_report(
        PERF_REPORT,
        VISUAL_EVIDENCE,
        command,
        0,
        "\n".join(
            [
                "performance_smoke=ok avg_fps=60.25 avg_frame_ms=16.60 worst_frame_ms=20.00",
                "game_controller_smoke=ok",
                "game_shell_contract_smoke=ok",
                "game_v1_smoke=ok",
            ]
        ),
        "",
        False,
        "perf-highlight-smoke",
    )
    perf_text = PERF_REPORT.read_text(encoding="utf-8")
    require(
        "Deck-profile performance smoke passed locally: avg_fps=60.25, avg_frame_ms=16.60, worst_frame_ms=20.00." in perf_text,
        "preflight report should promote performance metrics into evidence highlights",
    )
    require(
        "Controller smoke drove app-level Trial Dish actions" in perf_text,
        "preflight report should preserve other automated evidence highlights",
    )

    FILLED.write_text(fill_preflight(TEMPLATE.read_text(encoding="utf-8")), encoding="utf-8")
    ready = run(
        [
            python,
            "scripts/summarize_steam_deck_preflight.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(ready.returncode == 0, f"filled preflight should be ready: {ready.stdout}\n{ready.stderr}")
    require("steam_deck_preflight_status=ready" in ready.stdout, "filled preflight should report ready")
    ready_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: ready" in ready_text, "summary should mark filled preflight ready")
    require("None. All required preflight evidence is checked." in ready_text, "ready summary should have no missing evidence")

    print("steam_deck_preflight_summary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
