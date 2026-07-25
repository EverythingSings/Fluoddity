"""Smoke-check that V1 game docs stay anchored to imported design research."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_MD = ROOT / "docs" / "research" / "foundations-of-fun.md"
RESEARCH_PDF = ROOT / "docs" / "research" / "foundations-of-fun.pdf"
RESEARCH_README = ROOT / "docs" / "research" / "README.md"
V1_DOC = ROOT / "docs" / "game_v1_prototype.md"
TECH_STACK_DOC = ROOT / "docs" / "tech_stack_strategy.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read(path: Path) -> str:
    require(path.exists(), f"missing required design artifact: {path}")
    require(path.stat().st_size > 0, f"empty required design artifact: {path}")
    return path.read_text(encoding="utf-8")


def require_terms(text: str, terms: list[str], source: Path) -> None:
    lowered = text.lower()
    missing = [term for term in terms if term.lower() not in lowered]
    require(not missing, f"{source} missing design terms: {', '.join(missing)}")


def main() -> int:
    require(RESEARCH_PDF.exists(), "imported source PDF should stay in docs/research")
    require(RESEARCH_PDF.stat().st_size > 0, "imported source PDF should not be empty")

    research_readme = read(RESEARCH_README)
    research = read(RESEARCH_MD)
    v1 = read(V1_DOC)
    tech_stack = read(TECH_STACK_DOC)

    require_terms(
        research_readme,
        [
            "easy to learn and hard to master",
            "action-feedback-reward",
            "meaningful choices",
            "flow-state",
            "learnable pattern mastery",
        ],
        RESEARCH_README,
    )
    require_terms(
        research,
        [
            "Foundations of Fun",
            "easy to learn",
            "hard to master",
            "meaningful choices",
            "immediate feedback",
            "flow",
        ],
        RESEARCH_MD,
    )
    require_terms(
        v1,
        [
            "docs/research/foundations-of-fun.md",
            "easy to learn, hard to master",
            "fun comes from learning patterns",
            "clear goals and immediate feedback",
            "meaningful decisions",
            "10-to-60-second action-feedback-reward loop",
            "one zone, one tool, no hazard",
            "multiple zones plus one passive hazard",
            "culture-site control",
            "alien petri-dish xenotech",
            "The game needs friction",
            "Pretty emergence is not enough",
            "Xenoculture: Trial Dish",
            "docs/tech_stack_strategy.md",
        ],
        V1_DOC,
    )
    playtest = read(ROOT / "scripts" / "write_trial_dish_playtest_report.py")
    summary = read(ROOT / "scripts" / "summarize_trial_dish_playtest.py")
    require_terms(
        playtest,
        [
            "Action-feedback loop",
            "Meaningful choice",
            "Flow balance",
            "10-60 seconds",
            "mutation/revert creates a meaningful choice",
        ],
        ROOT / "scripts" / "write_trial_dish_playtest_report.py",
    )
    require_terms(
        summary,
        [
            "Action-feedback loop",
            "Meaningful choice",
            "Flow balance",
        ],
        ROOT / "scripts" / "summarize_trial_dish_playtest.py",
    )
    require_terms(
        tech_stack,
        [
            "keep Python for the current V1 game prototype",
            "not assume Python is the final shipping runtime",
            "Steam Deck",
            "Do one real Steam Deck hardware pass",
            "The game should not become Python-shaped",
        ],
        TECH_STACK_DOC,
    )

    print("game_design_alignment_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
