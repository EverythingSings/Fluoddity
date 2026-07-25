"""Smoke-check Steam Deck visual evidence report generation."""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import steam_deck_preflight


SMOKE_DIR = ROOT / "artifacts" / "steam_deck_visual_evidence_smoke" / str(os.getpid())
CAPTURED = SMOKE_DIR / "captured.md"
SKIPPED = SMOKE_DIR / "skipped.md"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    stdout = "\n".join(
        [
            "visual_smoke_saved=artifacts/game_v1_smoke/123/visual/trial1_running.png",
            "visual_smoke_saved=artifacts/game_v1_smoke/123/visual/trial3_mutated.png",
            (
                "visual_smoke_trial_state=trial=1 status=running active_zones=1/1 "
                "rival_zones=0 containment_margin=0 progress=0.420 input_scheme=controller "
                "feedback=Specimen_response_detected. guidance=The_specimen_is_responding."
            ),
            (
                "visual_smoke_trial_state=trial=3 status=running active_zones=2/3 "
                "rival_zones=1 containment_margin=1 progress=0.370 input_scheme=hybrid "
                "feedback=Strain_archived. guidance=A_strain_archive_is_loaded. "
                "mutation=Mutated-strain;archive-ready containment=Containing_by_1_site"
            ),
        ]
    )

    steam_deck_preflight.write_visual_evidence(
        CAPTURED,
        stdout,
        skipped=False,
        build_id="visual-evidence-smoke",
    )
    captured = CAPTURED.read_text(encoding="utf-8")
    require("# Steam Deck Visual Evidence" in captured, "captured report should include heading")
    require(
        "- Automated visual capture status: captured" in captured,
        "captured report should mark captured status",
    )
    require("- Saved image count: 2" in captured, "captured report should count saved images")
    require(
        "- Trial state snapshot count: 2" in captured,
        "captured report should count state snapshots",
    )
    require(
        "artifacts/game_v1_smoke/123/visual/trial1_running.png" in captured,
        "captured report should list saved visual image paths",
    )
    require(
        "input_scheme=controller" in captured,
        "captured report should preserve trial state snapshots",
    )
    require("## Capture Review" in captured, "captured report should include a human review section")
    require(
        "Trial 1 `running`: active `1/1`, progress `0.420`, input `controller`" in captured,
        "captured report should summarize Trial 1 state",
    )
    require(
        "feedback `Specimen_response_detected.`" in captured,
        "captured report should surface first-response feedback",
    )
    require(
        "mutation `Mutated-strain;archive-ready`, containment `Containing_by_1_site`" in captured,
        "captured report should summarize Trial 3 mutation and containment state",
    )

    steam_deck_preflight.write_visual_evidence(
        SKIPPED,
        "",
        skipped=True,
        build_id="visual-evidence-smoke",
    )
    skipped = SKIPPED.read_text(encoding="utf-8")
    require(
        "- Automated visual capture status: skipped" in skipped,
        "skipped report should mark skipped status",
    )
    require("- Saved image count: 0" in skipped, "skipped report should record zero images")
    require(
        "No visual smoke images were captured" in skipped,
        "skipped report should explain missing images",
    )

    print("steam_deck_visual_evidence_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
