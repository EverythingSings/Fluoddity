"""Smoke-check Trial Dish playtest summary generation."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

SMOKE_DIR = ROOT / "artifacts" / "trial_dish_playtest_summary_smoke" / str(os.getpid())
TEMPLATE = SMOKE_DIR / "trial_dish_playtest_summary_template.md"
FILLED = SMOKE_DIR / "trial_dish_playtest_summary_filled.md"
NO_VERDICT = SMOKE_DIR / "trial_dish_playtest_summary_no_verdict.md"
CONTRADICTORY = SMOKE_DIR / "trial_dish_playtest_summary_contradictory.md"
SUMMARY = SMOKE_DIR / "trial_dish_playtest_summary_smoke.md"
REFERENCE = SMOKE_DIR / "trial_dish_tuning_reference_smoke.md"
PLAN = SMOKE_DIR / "trial_dish_tuning_plan_smoke.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True)


def write_filled_report(text: str) -> None:
    replacements = {
        "- Launch target:": "- Launch target: ./dist/Fluoddity/run_steam_deck.sh",
        "- Controller:": "- Controller: Steam Deck built-in controls",
        "| Premise clarity |  |  |": "| Premise clarity | 4 | Story was clear after first prompt. |",
        "| Visual readability |  |  |": "| Visual readability | 3 | Trial 3 got noisy near the far sites. |",
        "| Controller confidence |  |  |": "| Controller confidence | 4 | R2 feed was clear. |",
        "| Objective clarity |  |  |": "| Objective clarity | 4 | Hold progress was readable. |",
        "| Action-feedback loop |  |  |": "| Action-feedback loop | 4 | Specimen and route feedback arrived quickly. |",
        "| Meaningful choice |  |  |": "| Meaningful choice | 3 | Mutation mattered, but revert timing needs clearer stakes. |",
        "| Flow balance |  |  |": "| Flow balance | 3 | Trial 3 pressure spiked near timeout. |",
        "| Friction/struggle |  |  |": "| Friction/struggle | 3 | Rival pressure needs stronger intro. |",
        "| Desire to retry |  |  |": "| Desire to retry | 5 | Wanted another Trial 3 attempt. |",
        "- Trial 1 threshold/hold time:": "- Trial 1 threshold/hold time: keep hold time, lower activation threshold slightly.",
        "- Trial 2 threshold/hold time/hazard strength:": "- Trial 2 threshold/hold time/hazard strength: make antibiotic band 10% wider but reduce suppression.",
        "- Trial 3 rival strength/timer/tool cooldowns:": "- Trial 3 rival strength/timer/tool cooldowns: reduce rival spread during first 20 seconds.",
        "- HUD/copy changes:": "- HUD/copy changes: call out rival site count before mutation unlock.",
        "- Visual noise/readability changes:": "- Visual noise/readability changes: dim rival trails behind the HUD.",
        "- [ ] Needs threshold/copy/visual tuning before another hardware pass.": "- [x] Needs threshold/copy/visual tuning before another hardware pass.",
        "Summary:": "Summary:\nTrial 3 is promising but needs cleaner rival-pressure ramping.",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    FILLED.write_text(text, encoding="utf-8")


def main() -> int:
    python = sys.executable
    proc = run(
        [
            python,
            "scripts/write_trial_dish_playtest_report.py",
            "--output",
            str(TEMPLATE),
            "--tester",
            "Smoke",
            "--device",
            "Local Deck profile",
            "--build-id",
            "smoke-build",
        ]
    )
    require(proc.returncode == 0, f"template generation failed: {proc.stdout}\n{proc.stderr}")
    template_text = TEMPLATE.read_text(encoding="utf-8")
    require(f"- Game: {GAME_TITLE}" in template_text, "playtest template should include game title")
    require(f"- Engine/package: {ENGINE_NAME}" in template_text, "playtest template should include engine/package identity")

    blank_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(TEMPLATE),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(blank_proc.returncode == 2, "blank playtest template should not be tuning-ready")
    require("trial_dish_playtest_status=not_ready" in blank_proc.stdout, "blank summary should report not_ready")
    reference_proc = run(
        [
            python,
            "scripts/write_trial_dish_tuning_reference.py",
            "--output",
            str(REFERENCE),
        ]
    )
    require(reference_proc.returncode == 0, f"reference generation failed: {reference_proc.stdout}\n{reference_proc.stderr}")
    blocked_plan = run(
        [
            python,
            "scripts/write_trial_dish_tuning_plan.py",
            "--summary",
            str(SUMMARY),
            "--reference",
            str(REFERENCE),
            "--output",
            str(PLAN),
            "--require-ready",
        ]
    )
    require(blocked_plan.returncode == 2, "not-ready summary should block tuning plan")
    require("trial_dish_tuning_plan_status=blocked" in blocked_plan.stdout, "blocked plan should report blocked")

    write_filled_report(template_text)
    filled_text = FILLED.read_text(encoding="utf-8")
    no_verdict_text = filled_text.replace(
        "- [x] Needs threshold/copy/visual tuning before another hardware pass.",
        "- [ ] Needs threshold/copy/visual tuning before another hardware pass.",
    ).replace(
        "- [ ] Complete all three Trial Dishes with controller-only input.",
        "- [x] Complete all three Trial Dishes with controller-only input.",
    )
    NO_VERDICT.write_text(no_verdict_text, encoding="utf-8")
    no_verdict_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(NO_VERDICT),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(
        no_verdict_proc.returncode == 2,
        "checked setup goals must not satisfy the dedicated verdict gate",
    )

    contradictory_text = filled_text.replace(
        "- [ ] Ready for another hardware pass without tuning.",
        "- [x] Ready for another hardware pass without tuning.",
    )
    CONTRADICTORY.write_text(contradictory_text, encoding="utf-8")
    contradictory_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(CONTRADICTORY),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(contradictory_proc.returncode == 2, "multiple verdicts must not be tuning-ready")
    require(
        "Select exactly one verdict checkbox." in SUMMARY.read_text(encoding="utf-8"),
        "contradictory verdict summary should explain the conflict",
    )

    filled_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(filled_proc.returncode == 0, f"filled summary failed: {filled_proc.stdout}\n{filled_proc.stderr}")
    require("trial_dish_playtest_status=ready" in filled_proc.stdout, "filled summary should report ready")
    summary_text = SUMMARY.read_text(encoding="utf-8")
    require("- Status: tuning-ready" in summary_text, "summary should mark filled report tuning-ready")
    require("Completed ratings: 9/9" in summary_text, "summary should require all design-contract ratings")
    require("Meaningful choice" in summary_text, "summary should include design-contract ratings")
    require("Trial 3 rival strength/timer/tool cooldowns" in summary_text, "summary should include tuning targets")
    stale_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--expected-build",
            "different-build",
            "--require-ready",
        ]
    )
    require(stale_proc.returncode == 2, "stale playtest evidence must not be tuning-ready")
    require(
        "`Build / commit` does not match this packet" in SUMMARY.read_text(encoding="utf-8"),
        "stale playtest summary should name the build mismatch",
    )
    filled_proc = run(
        [
            python,
            "scripts/summarize_trial_dish_playtest.py",
            "--input",
            str(FILLED),
            "--output",
            str(SUMMARY),
            "--require-ready",
        ]
    )
    require(filled_proc.returncode == 0, "fresh summary should recover after mismatch probe")
    plan_proc = run(
        [
            python,
            "scripts/write_trial_dish_tuning_plan.py",
            "--summary",
            str(SUMMARY),
            "--reference",
            str(REFERENCE),
            "--output",
            str(PLAN),
            "--require-ready",
        ]
    )
    require(plan_proc.returncode == 0, f"tuning plan failed: {plan_proc.stdout}\n{plan_proc.stderr}")
    require("trial_dish_tuning_plan_status=actionable" in plan_proc.stdout, "filled summary should produce actionable plan")
    plan_text = PLAN.read_text(encoding="utf-8")
    require("Trial 3: Rival Bloom" in plan_text, "plan should include Trial 3 action section")
    require("Rival growth (`rival_growth`): 0.0016" in plan_text, "plan should carry current rival growth")
    require("reduce rival spread" in plan_text, "plan should carry playtest finding")
    print("trial_dish_playtest_summary_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
