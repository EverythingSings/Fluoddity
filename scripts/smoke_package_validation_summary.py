"""Smoke-check package/runtime validation summary readiness parsing."""
from __future__ import annotations

import subprocess
import sys
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SMOKE_DIR = ROOT / "artifacts" / "package_validation_summary_smoke" / str(os.getpid())
TEMPLATE = SMOKE_DIR / "package_validation_template.md"
FILLED = SMOKE_DIR / "package_validation_filled.md"
SUMMARY = SMOKE_DIR / "package_validation_summary_smoke.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def filled_report(text: str) -> str:
    replacements = {
        "- Tester:": "- Tester: Smoke",
        "- Device / OS build:": "- Device / OS build: Steam Deck OLED / SteamOS smoke",
        "- Package path:": "- Package path: dist/Fluoddity",
        "- Runtime path:": "- Runtime path: native Linux",
        "- Steam launch target:": "- Steam launch target: ./run_steam_deck.sh",
        "- Package build host:": "- Package build host: Steam Deck OLED / SteamOS smoke",
        "- Package target:": "- Package target: native Linux",
        "- GPU adapter:": "- GPU adapter: AMD Van Gogh",
        "- wgpu backend:": "- wgpu backend: Vulkan",
        "- Video evidence host:": "- Video evidence host: Steam Deck OLED / SteamOS smoke",
        "- Actual Steam Deck hardware used (yes/no):": "- Actual Steam Deck hardware used (yes/no): yes",
        "- Average FPS observed over five minutes:": "- Average FPS observed over five minutes: 60",
        "- Runtime defects:": "- Runtime defects: none",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"^- \[ \] ", "- [x] ", text, flags=re.MULTILINE)


def main() -> int:
    python = sys.executable
    template_proc = run(
        [
            python,
            "scripts/write_package_validation_report.py",
            "--output",
            str(TEMPLATE),
        ]
    )
    require(template_proc.returncode == 0, f"template generation failed: {template_proc.stdout}\n{template_proc.stderr}")
    template_text = TEMPLATE.read_text(encoding="utf-8")
    require("# Package Runtime Validation Report" in template_text, "template should include package validation heading")
    require("## Native wgpu Package" in template_text, "template should include native wgpu package validation")
    require("## Native Video Export" in template_text, "template should include native video validation")

    blank = run(
        [
            python,
            "scripts/summarize_package_validation.py",
            "--input",
            str(TEMPLATE),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(blank.returncode == 2, "blank package validation report should not be ready")
    require("package_validation_status=not-ready" in blank.stdout, "blank summary should report not-ready")
    summary_text = SUMMARY.read_text(encoding="utf-8")
    require("Package Build" in summary_text, "summary should include package build coverage")
    require("Native wgpu Package" in summary_text, "summary should include native wgpu package coverage")
    require("Native Video Export" in summary_text, "summary should include native video coverage")
    require("Notes: `Tester` is missing package/runtime evidence." in summary_text, "summary should require tester notes")
    require(
        "Native wgpu Package: `dist/FluoddityNative/` was assembled with the Rust/wgpu package script for the tested platform."
        in summary_text,
        "summary should require native wgpu package evidence",
    )

    FILLED.write_text(filled_report(template_text), encoding="utf-8")
    filled = run(
        [
            python,
            "scripts/summarize_package_validation.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(filled.returncode == 0, f"filled package validation should pass: {filled.stdout}\n{filled.stderr}")
    require("package_validation_status=ready" in filled.stdout, "filled summary should report ready")
    ready_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: ready" in ready_text, "filled summary should mark ready")
    require("None. Package/runtime validation evidence is complete." in ready_text, "filled summary should have no missing evidence")
    stale = run(
        [
            python,
            "scripts/summarize_package_validation.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--expected-build",
            "different-build",
            "--require-ready",
        ]
    )
    require(stale.returncode == 2, "stale package evidence must not be ready")
    require(
        "`Build / commit` does not match this packet" in SUMMARY.read_text(encoding="utf-8"),
        "stale package summary should name the build mismatch",
    )
    print("package_validation_summary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
