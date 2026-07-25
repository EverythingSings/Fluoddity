"""Smoke-check the explicit V1 prototype done definition."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_service import TrialService
from state import TrialState


class ZoneTexture:
    size = (64, 64)

    def __init__(self, trial: TrialState, active_zone_names: set[str]):
        self.trial = trial
        self.active_zone_names = active_zone_names

    def read(self) -> bytes:
        width, height = self.size
        canvas = np.zeros((height, width, 4), dtype=np.float32)
        ys, xs = np.ogrid[:height, :width]
        norm_x = (xs + 0.5) / width
        norm_y = (ys + 0.5) / height
        for zone in self.trial.zones:
            if zone.name not in self.active_zone_names:
                continue
            dx = norm_x - zone.center[0]
            dy = norm_y - zone.center[1]
            mask = (dx * dx + dy * dy) <= zone.radius * zone.radius
            canvas[:, :, 2][mask] = self.trial.activity_threshold * 8.0
        return canvas.tobytes()


def request_state(**overrides):
    state = {
        "request_trial_next": False,
        "request_trial_retry": False,
        "request_trial_start": False,
        "request_trial_restart_sequence": False,
        "request_trial_pause": False,
        "request_reset": False,
        "request_full_reset": False,
        "request_randomize_mutations": False,
        "request_revert_strain": False,
    }
    state.update(overrides)
    return SimpleNamespace(**state)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_until_result(
    service: TrialService,
    trial: TrialState,
    texture,
    *,
    max_seconds: float,
    dt: float = 0.25,
) -> None:
    elapsed = 0.0
    frame = 0
    while elapsed < max_seconds and not (trial.won or trial.failed):
        frame += 1
        service.update(trial, request_state(), frame, dt, texture)
        elapsed += dt


def smoke_trial_one_minimum_loop() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)
    service.load_trial(trial, 0)

    require(trial.briefing_active, "fresh player should start at the briefing")
    require(trial.objective, "Trial 1 should have a visible objective")
    require("Nutrient Gel" in trial.unlocked_tools, "Trial 1 should expose the starting lab tool")
    require(trial.current_tool == "Nutrient Gel", "Trial 1 should default to the visible lab tool")
    require(trial.minimal_onboarding, "Trial 1 should use the minimal onboarding ramp")
    require(not trial.hazard_enabled and not trial.rival_enabled, "Trial 1 should start without hazards or rivals")

    service.process_requests(trial, request_state(request_trial_start=True))
    require(trial.status == "running", "Start Experiment should enter the playable loop")
    require("Specimen" in trial.objective_status, "running Trial 1 should use readable objective feedback")

    initial_progress = trial.progress
    initial_status = trial.objective_status
    service.update(trial, request_state(), 1, 0.25, ZoneTexture(trial, {"A"}))
    require(trial.zones[0].active, "Nutrient Gel input should activate the marked culture zone")
    require(trial.progress > initial_progress, "input should immediately move progress")
    require(trial.objective_status != initial_status, "input should change the status readout")
    require("responding" in trial.specimen_readout.lower(), "input should produce first-contact feedback")

    run_until_result(
        service,
        trial,
        ZoneTexture(trial, {"A"}),
        max_seconds=trial.hold_seconds + 2.0,
    )
    require(trial.won, "Trial 1 should be completable with the starting tool")
    require(trial.result_title, "success should produce a result title")
    require("Trial 2" in trial.result_next_step, "success should explain the next assay")
    require("Next experiment" in trial.result_experiment_hint, "success should suggest a follow-up experiment")

    service.load_trial(trial, 0)
    service.process_requests(trial, request_state(request_trial_start=True))
    trial.elapsed_seconds = trial.failure_seconds - 0.1
    service.update(trial, request_state(), 1, 0.2, ZoneTexture(trial, set()))
    require(trial.failed, "Trial 1 should be failable when the player does not feed the zone")
    require("Retry" in trial.result_next_step, "failure should explain the retry focus")
    require("Next experiment" in trial.result_experiment_hint, "failure should suggest a different attempt")


def smoke_done_definition_doc() -> None:
    text = (ROOT / "docs" / "game_v1_prototype.md").read_text(encoding="utf-8")
    for phrase in [
        "V1 is done when a fresh player can launch game mode and complete one Trial Dish without opening the raw editor.",
        "the objective is visible",
        "the tool is visible",
        "player input changes colony behavior",
        "progress feedback is immediate",
        "success and failure are possible",
        "the result makes the player want to retry with a different experimental choice",
    ]:
        require(phrase in text, f"done definition doc missing: {phrase}")


def main() -> int:
    smoke_done_definition_doc()
    smoke_trial_one_minimum_loop()
    print("game_v1_done_definition_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
