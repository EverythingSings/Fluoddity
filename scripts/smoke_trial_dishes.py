"""Smoke checks for the game-mode Trial Dish service.

This intentionally avoids GLFW/OpenGL. It verifies the objective and tool-state
logic that can be exercised without a renderer.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_definitions import TRIAL_DEFINITIONS
from services.trial_service import TrialService
from services.trial_prompts import TRIAL_PROMPT_GLYPHS, trial_action_prompt_specs
from state import TrialState
from main import App
from ui.core import UI


class FakeTexture:
    size = (16, 16)

    def __init__(self, density: float):
        self.density = density

    def read(self) -> bytes:
        canvas = np.zeros((self.size[1], self.size[0], 4), dtype=np.float32)
        canvas[:, :, 2] = self.density
        return canvas.tobytes()


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
        "request_exit": False,
    }
    state.update(overrides)
    return SimpleNamespace(**state)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_updates_until_result(
    service: TrialService,
    trial: TrialState,
    texture,
    *,
    max_seconds: float,
    dt: float = 0.25,
) -> None:
    frame = 0
    elapsed = 0.0
    while not trial.won and not trial.failed and elapsed < max_seconds:
        frame += 1
        elapsed += dt
        service.update(trial, request_state(), frame, dt, texture)


def smoke_full_trial_dish_playthrough() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)

    service.load_trial(trial, 0)
    service.process_requests(trial, request_state(request_trial_start=True))
    assert_true(trial.status == "running", "Trial 1 should start from briefing")
    run_updates_until_result(
        service,
        trial,
        ZoneTexture(trial, {"A"}),
        max_seconds=trial.hold_seconds + 2.0,
    )
    assert_true(trial.won, "Trial 1 should complete when the only zone stays active")
    assert_true("Trial 2" in trial.result_next_step, "Trial 1 should unlock Trial 2")

    service.process_requests(trial, request_state(request_trial_next=True))
    assert_true(trial.trial_index == 1, "Next should load Trial 2")
    service.process_requests(trial, request_state(request_trial_start=True))
    trial.elapsed_seconds = trial.failure_seconds - 0.1
    service.update(trial, request_state(), 1, 0.2, ZoneTexture(trial, set()))
    assert_true(trial.failed, "Trial 2 should fail if no zones survive to timeout")
    assert_true("Retry" in trial.result_next_step, "Trial 2 failure should explain retry")

    service.process_requests(trial, request_state(request_trial_retry=True))
    assert_true(trial.trial_index == 1, "Retry should stay on Trial 2")
    assert_true(trial.briefing_active, "Retry should reset Trial 2 to briefing")
    assert_true("Retry loaded" in trial.transition_message, "Retry should explain the loaded assay")
    service.process_requests(trial, request_state(request_trial_start=True))
    run_updates_until_result(
        service,
        trial,
        ZoneTexture(trial, {"A", "B", "C"}),
        max_seconds=trial.hold_seconds + 2.0,
    )
    assert_true(trial.won, "Trial 2 should complete when all zones stay active")
    assert_true("Trial 3" in trial.result_next_step, "Trial 2 should unlock Trial 3")

    service.process_requests(trial, request_state(request_trial_next=True))
    assert_true(trial.trial_index == 2, "Next should load Trial 3")
    assert_true("Next assay loaded" in trial.transition_message, "Next should explain the loaded assay")
    service.process_requests(trial, request_state(request_trial_start=True))
    assert_true(trial.irradiation_ready, "Trial 3 should begin with irradiation ready")
    assert_true(trial.mutation_readout == "Baseline strain", "Trial 3 should begin with baseline strain readout")
    ui = request_state(request_randomize_mutations=True)
    service.process_requests(trial, ui)
    assert_true(ui.request_randomize_mutations, "Ready irradiation should pass to command handler")
    assert_true(trial.preserved_strain_available, "Irradiation should create a revert archive")
    assert_true(
        trial.mutation_readout == "Mutated strain; archive ready",
        "irradiation should show archive-ready mutated strain",
    )
    trial.irradiation_cooldown_remaining = 0.0
    ui = request_state(request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(ui.request_revert_strain, "Ready revert should pass to command handler")
    assert_true(not trial.preserved_strain_available, "Revert should consume the archive")
    assert_true(trial.mutation_readout == "Archive restored", "revert should show restored archive readout")

    trial.elapsed_seconds = trial.failure_seconds - 0.1
    service.update(trial, request_state(), 1, 0.2, ZoneTexture(trial, {"A", "B"}))
    assert_true(trial.won, "Trial 3 should win when the culture holds more sites at timeout")
    assert_true(trial.result_grade == "Contained", "Trial 3 narrow win should grade as contained")
    assert_true("Sequence complete" in trial.result_next_step, "Final trial should complete the sequence")

    service.process_requests(trial, request_state(request_trial_restart_sequence=True))
    assert_true(trial.trial_index == 0, "Final restart should return to Trial 1")
    assert_true(trial.briefing_active, "Final restart should return to briefing")
    assert_true("Sequence restarted" in trial.transition_message, "Final restart should explain the sequence reset")


def smoke_trial_sequence() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)

    service.load_trial(trial, 0)
    assert_true(len(TRIAL_DEFINITIONS) == 3, "expected three V1 trial definitions")
    assert_true(len(trial.zones) == 1, "Trial 1 should start with one zone")
    assert_true(not trial.irradiation_unlocked, "Trial 1 should not unlock irradiation")
    assert_true("K-7" in trial.story_line, "Trial 1 should establish the K-7 story frame")
    assert_true("protocol" in trial.guidance_message.lower(), "briefing should show protocol guidance")

    ui = request_state(request_trial_start=True)
    service.process_requests(trial, ui)
    assert_true(trial.status == "running", "trial start should enter running state")
    assert_true(trial.primer_remaining > 0.0, "starter primer should be armed")
    assert_true("nutrient gel" in trial.guidance_message.lower(), "Trial 1 should guide nutrient gel use")
    assert_true("Specimen" in trial.objective_status, "Trial 1 should use biological objective status")
    assert_true(trial.specimen_readout == "Specimen dormant", "Trial 1 should start with dormant specimen readout")

    service.load_trial(trial, 1)
    assert_true(not trial.irradiation_unlocked, "Trial 2 should not unlock irradiation yet")
    assert_true(not trial.revert_unlocked, "Trial 2 should not unlock revert yet")
    assert_true("antibiotic scar" in trial.briefing.lower(), "Trial 2 should frame the counterforce as an antibiotic scar")

    trial.status = "running"
    service.process_requests(trial, request_state(request_reset=True))
    assert_true(trial.briefing_active, "sterilize should return to briefing")
    assert_true("sterilized" in trial.guidance_message.lower(), "sterilize should show station feedback")
    assert_true("sterilized" in trial.transition_message.lower(), "sterilize should show briefing transition feedback")

    service.process_requests(trial, request_state(request_trial_start=True, request_reset=True))
    assert_true(trial.briefing_active, "sterilize should outrank simultaneous start")
    assert_true("sterilized" in trial.guidance_message.lower(), "start+sterilize should keep sterilize feedback")

    service.load_trial(trial, 2)
    assert_true("sterilized" not in trial.guidance_message.lower(), "new trial load should clear sterilize feedback")
    assert_true(trial.transition_message == "", "new trial load should clear transition feedback")
    assert_true(trial.irradiation_unlocked, "Trial 3 should unlock irradiation")
    assert_true(trial.revert_unlocked, "Trial 3 should unlock revert")
    assert_true(not trial.revert_ready, "revert should require a preserved archive")
    assert_true(trial.mutation_readout == "Baseline strain", "Trial 3 briefing should expose baseline strain readout")
    assert_true("rival bloom" in trial.story_line.lower(), "Trial 3 should establish rival fiction")
    assert_true(len(trial.protocol_steps) == 3, "Trial 3 briefing should keep mutation onboarding compact")

    ui = request_state(request_randomize_mutations=True, request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(not ui.request_randomize_mutations, "briefing should consume stale irradiation request")
    assert_true(not ui.request_revert_strain, "briefing should consume stale revert request")
    assert_true(trial.irradiation_charges == 3, "briefing irradiation request should not consume charge")
    assert_true(trial.revert_charges == 1, "briefing revert request should not consume charge")

    trial.status = "running"
    ui = request_state(request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(not ui.request_revert_strain, "revert should be blocked before archive")
    assert_true(trial.revert_charges == 1, "blocked revert should not consume charge")
    assert_true(trial.revert_uses == 0, "blocked revert should not increment uses")
    assert_true("No archived strain" in trial.tool_feedback, "blocked revert should explain missing archive")

    ui = request_state(request_randomize_mutations=True)
    service.process_requests(trial, ui)
    assert_true(ui.request_randomize_mutations, "ready irradiation should pass through")
    assert_true(trial.irradiation_charges == 2, "irradiation should consume a charge")
    assert_true(trial.preserved_strain_available, "irradiation should preserve archive")
    assert_true(
        trial.mutation_readout == "Mutated strain; archive ready",
        "irradiation should update mutation readout",
    )
    assert_true("archive" in trial.guidance_message.lower(), "irradiation should surface archive guidance")
    trial.zones[0].active = True
    trial.zones[1].active = True
    trial.zones[2].rival_controlled = True
    service._update_zone_control_counts(trial)
    service._update_guidance(trial)
    assert_true(trial.containment_margin > 0, "test setup should be ahead while archive is loaded")
    assert_true(
        "archive" in trial.guidance_message.lower(),
        "archive guidance should outrank positive containment guidance after irradiation",
    )

    ui = request_state(request_randomize_mutations=True)
    service.process_requests(trial, ui)
    assert_true(not ui.request_randomize_mutations, "cooldown irradiation should be blocked")
    assert_true(trial.irradiation_uses == 1, "blocked irradiation should not increment uses")
    assert_true("recharging" in trial.tool_feedback.lower(), "blocked irradiation should explain recharge")

    ui = request_state(request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(ui.request_revert_strain, "ready revert should pass through")
    assert_true(trial.revert_charges == 0, "revert should consume its charge")
    assert_true(not trial.preserved_strain_available, "revert should consume archive")
    assert_true(trial.current_tool == "Revert Strain", "ready revert should mark current tool")
    assert_true(trial.mutation_readout == "Archive restored", "revert should update mutation readout")

    ui = request_state(request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(not ui.request_revert_strain, "spent revert should be blocked")
    assert_true("spent" in trial.tool_feedback.lower(), "spent revert should explain spent charge")

    service.process_requests(trial, request_state(request_trial_retry=True))
    assert_true(trial.current_tool == "Nutrient Gel", "retry should restore default tool")

    service.load_trial(trial, 2)
    trial.status = "running"
    trial.irradiation_uses = 1
    trial.revert_uses = 1

    trial.zones[0].active = True
    trial.zones[1].active = True
    trial.zones[2].rival_controlled = True
    service._settle_territory_trial(trial)
    assert_true(trial.won, "2 culture sites should beat 1 rival site")
    assert_true(trial.result_grade == "Contained", "narrow territory win should get contained grade")
    assert_true("Irradiation pulses used: 1" in trial.result_summary, "result should mention irradiation usage")
    assert_true("reverts used: 1" in trial.result_summary, "result should mention revert usage")
    assert_true("without reverting" in trial.result_experiment_hint, "revert win should suggest a no-revert comparison")
    assert_true("zone" not in trial.result_summary.lower(), "territory result should use culture-site language")
    assert_true(trial.objective_status == "Assay complete.", "territory win should update objective status")
    assert_true("Sequence complete" in trial.result_next_step, "final win should explain sequence completion")

    ui = request_state(request_randomize_mutations=True, request_revert_strain=True)
    service.process_requests(trial, ui)
    assert_true(not ui.request_randomize_mutations, "result should consume stale irradiation request")
    assert_true(not ui.request_revert_strain, "result should consume stale revert request")
    assert_true(trial.irradiation_uses == 1, "result irradiation request should not change counters")
    assert_true(trial.revert_uses == 1, "result revert request should not change counters")

    ui = request_state(request_trial_restart_sequence=True)
    service.process_requests(trial, ui)
    assert_true(trial.trial_index == 0, "restart sequence should return to Trial 1")
    assert_true(trial.briefing_active, "restart sequence should return to briefing")
    assert_true("Sequence restarted" in trial.transition_message, "restart sequence should explain the reset")


def smoke_activity_sampling() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)
    service.load_trial(trial, 0)
    trial.status = "running"

    service.update(trial, request_state(), 0, 0.25, FakeTexture(0.0))
    assert_true(not trial.zones[0].active, "empty texture should not activate Trial 1 zone")

    service.update(trial, request_state(), 1, 0.25, FakeTexture(0.01))
    assert_true(trial.zones[0].active, "dense texture should activate Trial 1 zone")
    assert_true(trial.specimen_readout == "Specimen responding", "active Trial 1 zone should show responding readout")
    assert_true(trial.first_response_seen, "active Trial 1 zone should mark first response seen")
    assert_true("response detected" in trial.tool_feedback.lower(), "first active Trial 1 zone should show a response cue")
    assert_true("responding" in trial.guidance_message.lower(), "active Trial 1 zone should shift guidance")
    assert_true("responding" in trial.objective_status.lower(), "active Trial 1 zone should show biological hold status")

    trial.progress = 0.5
    service.update(trial, request_state(), 2, 0.25, FakeTexture(0.01))
    assert_true(trial.specimen_readout == "Specimen stabilizing", "progressing Trial 1 should show stabilizing readout")
    assert_true("response detected" in trial.tool_feedback.lower(), "first response cue should remain briefly visible")

    service.reset(trial)
    assert_true(not trial.first_response_seen, "reset should clear first response cue state")


def smoke_result_guidance() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)
    service.load_trial(trial, 0)
    trial.status = "running"
    trial.progress = 0.99

    service.update(trial, request_state(), 1, 0.20, FakeTexture(0.01))
    assert_true(trial.won, "active final hold should win Trial 1")
    assert_true(trial.guidance_title == "Assay Result", "win should switch guidance to result mode")
    assert_true(trial.result_summary == trial.guidance_message, "result guidance should mirror result summary")
    assert_true(trial.result_grade in {"Rapid", "Stable", "Fragile"}, "Trial 1 result should use lab readout labels")
    assert_true("antibiotic scar" in trial.result_experiment_hint, "Trial 1 win should point to the next experiment")
    assert_true("Trial 2" in trial.result_next_step, "Trial 1 win should preview Trial 2")

    service.load_trial(trial, 0)
    trial.status = "running"
    trial.elapsed_seconds = trial.failure_seconds
    service.update(trial, request_state(), 1, 0.20, FakeTexture(0.0))
    assert_true(trial.failed, "timeout should fail Trial 1")
    assert_true(trial.guidance_title == "Assay Result", "failure should switch guidance to result mode")
    assert_true(trial.objective_status == "Assay failed.", "failure should update objective status")
    assert_true(trial.result_grade == "Unstable", "failed hold trial should use unstable readout")
    assert_true("wake every marked site" in trial.result_experiment_hint, "failure should suggest a specific retry experiment")
    assert_true("Retry" in trial.result_next_step, "failure should explain retry focus")

    service.load_trial(trial, 0)
    trial.status = "running"
    trial.zones[0].active = True
    trial.elapsed_seconds = trial.failure_seconds
    service.update(trial, request_state(), 1, 0.20, None)
    assert_true(trial.failed, "late active Trial 1 culture should still fail at timeout")
    assert_true("not sustained long enough" in trial.result_summary, "late Trial 1 failure should use specimen sustain language")
    assert_true("marked circle" in trial.result_experiment_hint, "late Trial 1 failure should suggest holding the marked circle")
    assert_true("scar" not in trial.result_next_step.lower(), "Trial 1 failure should not mention Trial 2 scar language")


def smoke_guidance_progression() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)

    service.load_trial(trial, 1)
    service.process_requests(trial, request_state(request_trial_start=True))
    service.update(trial, request_state(), 1, 0.25, FakeTexture(0.0))
    assert_true("red scar" in trial.guidance_message.lower(), "Trial 2 should explain the red scar")
    assert_true("Route absent" in trial.route_readout, "Trial 2 should expose missing route state")
    assert_true("Route absent" in trial.objective_status, "Trial 2 should show route progress")

    service.update(trial, request_state(), 2, 0.25, ZoneTexture(trial, {"A", "B"}))
    assert_true("Partial route" in trial.route_readout, "Trial 2 should expose partial route state")
    assert_true(trial.route_forming_seen, "Trial 2 partial route should mark forming feedback seen")
    assert_true("route forming" in trial.tool_feedback.lower(), "Trial 2 partial route should show forming feedback")

    service.update(trial, request_state(), 3, 0.25, ZoneTexture(trial, {"A", "B", "C"}))
    assert_true(trial.route_readout == "Route stable", "Trial 2 should expose stable route state")
    assert_true(trial.route_stable_seen, "Trial 2 stable route should mark stable feedback seen")
    assert_true("survived the scar" in trial.tool_feedback.lower(), "Trial 2 stable route should show survival feedback")

    service.reset(trial)
    assert_true(not trial.route_forming_seen, "Trial 2 reset should clear route forming feedback state")
    assert_true(not trial.route_stable_seen, "Trial 2 reset should clear route stable feedback state")

    service.load_trial(trial, 2)
    service.process_requests(trial, request_state(request_trial_start=True))
    service.update(trial, request_state(), 1, 0.25, FakeTexture(0.0))
    assert_true("irradiation" in trial.guidance_message.lower(), "Trial 3 should explain irradiation")
    assert_true("Culture" in trial.objective_status, "Trial 3 should show culture territory status")
    assert_true("rival" in trial.objective_status, "Trial 3 should show rival territory pressure")
    assert_true(trial.timer_readout == "", "Trial 3 should not warn before the assay is near closing")
    assert_true(trial.containment_margin == 0, "Trial 3 should start with tied containment")
    assert_true("Containment tied" in trial.containment_readout, "Trial 3 should expose tied containment")

    trial.elapsed_seconds = trial.failure_seconds - 10.0
    service.update(trial, request_state(), 2, 0.25, ZoneTexture(trial, {"A", "B"}))
    assert_true(trial.timer_readout == "Assay closing soon", "Trial 3 should warn when the assay is closing")
    assert_true("closes in" in trial.objective_status, "Trial 3 objective should keep exact close timing")

    trial.elapsed_seconds = trial.failure_seconds - 0.1
    service.update(trial, request_state(), 3, 0.25, ZoneTexture(trial, {"A", "B"}))
    assert_true(trial.won, "Trial 3 territory advantage should win")
    assert_true("Culture held 2 sites" in trial.result_summary, "Trial 3 result should use culture-site language")
    assert_true("Player controlled" not in trial.result_summary, "Trial 3 result should avoid raw player territory phrasing")


def smoke_pause_flow() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)
    service.load_trial(trial, 0)
    service.process_requests(trial, request_state(request_trial_start=True))
    service.update(trial, request_state(), 1, 0.5, FakeTexture(0.01))
    elapsed_before_pause = trial.elapsed_seconds

    ui = request_state(request_trial_pause=True, request_randomize_mutations=True)
    service.process_requests(trial, ui)
    assert_true(trial.paused, "pause request should pause a running trial")
    assert_true(not ui.request_randomize_mutations, "pause should block stale tool actions")
    assert_true(trial.objective_status == "Assay paused.", "pause should update objective status")
    assert_true("paused" in trial.guidance_message.lower(), "pause should show station stasis guidance")

    service.update(trial, request_state(), 2, 3.0, FakeTexture(0.01))
    assert_true(trial.elapsed_seconds == elapsed_before_pause, "paused update should not advance time")

    service.process_requests(trial, request_state(request_trial_pause=True))
    assert_true(not trial.paused, "second pause request should resume")
    service.update(trial, request_state(), 3, 0.5, FakeTexture(0.01))
    assert_true(trial.elapsed_seconds > elapsed_before_pause, "resumed trial should advance time")


def smoke_territory_grades() -> None:
    service = TrialService()
    trial = TrialState(game_mode=True)
    service.load_trial(trial, 2)

    trial.status = "running"
    trial.zones[0].active = True
    trial.zones[1].active = True
    trial.zones[2].active = True
    service._update_zone_control_counts(trial)
    assert_true(trial.containment_margin == 3, "three culture sites should produce a positive containment margin")
    assert_true("Containing by 3 sites" in trial.containment_readout, "positive margin should read as containment")
    service._settle_territory_trial(trial)
    assert_true(trial.won, "3 culture sites should win")
    assert_true(trial.result_grade == "Clean Dominance", "clean sweep should reward low-mutation control")
    assert_true("deliberate mutation" in trial.result_experiment_hint, "clean win should suggest mutation comparison")

    service.load_trial(trial, 2)
    trial.status = "running"
    trial.irradiation_uses = 2
    trial.zones[0].active = True
    trial.zones[1].active = True
    trial.zones[2].active = True
    service._settle_territory_trial(trial)
    assert_true(trial.result_grade == "Dominant", "decisive win with more mutation should be dominant")

    service.load_trial(trial, 2)
    trial.status = "running"
    trial.zones[0].active = True
    trial.zones[1].rival_controlled = True
    service._update_zone_control_counts(trial)
    assert_true(trial.containment_margin == 0, "one culture and one rival site should tie containment")
    assert_true("Containment tied" in trial.containment_readout, "tie should read as tied containment")
    service._settle_territory_trial(trial)
    assert_true(trial.failed, "tie should fail territory trial")
    assert_true(trial.result_grade == "Stalemate", "tie should report stalemate")
    assert_true("one extra marked site" in trial.result_experiment_hint, "stalemate should suggest one-site improvement")


def smoke_controller_final_restart() -> None:
    app = App.__new__(App)
    app.ui = SimpleNamespace(show_sidebar=False, game_editor_enabled=False)
    ui = request_state()
    ui.trial = TrialState(game_mode=True)
    ui.trial.status = "running"
    App._apply_controller_actions(app, {"game_pause", "toggle_sidebar", "game_exit"}, ui)
    assert_true(ui.request_trial_pause, "controller Menu should pause/resume a running Trial Dish")
    assert_true(not ui.request_exit, "controller View should not exit while trial is active")
    assert_true(not app.ui.show_sidebar, "game controller X should not expose editor panels in player shell")

    ui = request_state()
    ui.trial = TrialState(game_mode=True)
    ui.trial.status = "running"
    ui.trial.paused = True
    App._apply_controller_actions(app, {"game_exit"}, ui)
    assert_true(ui.request_exit, "controller View should exit from paused Trial Dish")

    ui = request_state()
    ui.trial = TrialState(game_mode=True)
    ui.trial.trial_index = 2
    ui.trial.trial_count = 3
    ui.trial.status = "won"

    App._apply_controller_actions(app, {"game_confirm"}, ui)
    assert_true(ui.request_trial_restart_sequence, "controller confirm should restart after final win")

    ui = request_state()
    ui.trial = TrialState(game_mode=True)
    ui.trial.trial_index = 1
    ui.trial.trial_count = 3
    ui.trial.status = "won"

    App._apply_controller_actions(app, {"game_confirm"}, ui)
    assert_true(ui.request_trial_next, "controller confirm should advance before final win")


def smoke_player_shell_editor_gate() -> None:
    ui = UI.__new__(UI)
    ui.state = request_state()
    ui.state.trial = TrialState(game_mode=True)
    ui.game_editor_enabled = False
    assert_true(not UI._editor_tools_visible(ui), "default game shell should hide raw editor tools")

    ui.game_editor_enabled = True
    assert_true(UI._editor_tools_visible(ui), "developer game shell should expose raw editor tools")

    ui.state.trial.game_mode = False
    ui.game_editor_enabled = False
    assert_true(UI._editor_tools_visible(ui), "normal editor launch should expose raw editor tools")


def smoke_trial_action_hints() -> None:
    class FakeKeybindings:
        labels = {
            "game_confirm": "SPACE",
            "game_retry": "R",
            "game_tool": "T",
            "game_revert": "V",
            "game_pause": "ESC",
            "game_exit": "Q",
        }

        def get_key_display_name(self, action):
            return self.labels.get(action, "?")

    trial = TrialState(game_mode=True)
    trial.status = "briefing"
    hints = UI.trial_action_hints(trial)
    assert_true(any("Start" in hint for hint in hints), "briefing should show start prompt")
    hints = UI.trial_action_hints(trial, FakeKeybindings())
    assert_true(any("A / Space: Start" in hint for hint in hints), "briefing should use configured key label")
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "controller")
    assert_true(any("A: Start" in hint for hint in hints), "controller scheme should hide keyboard label")
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "keyboard_mouse")
    assert_true(any("Space: Start" in hint for hint in hints), "keyboard scheme should hide controller label")

    trial.status = "running"
    trial.unlocked_tools = ["Nutrient Gel", "Irradiate Strain", "Revert Strain"]
    trial.irradiation_charges = 1
    trial.irradiation_cooldown_remaining = 0.0
    trial.revert_charges = 1
    trial.preserved_strain_available = True
    hints = UI.trial_action_hints(trial)
    assert_true(any("Irradiate" in hint for hint in hints), "ready irradiation should show tool prompt")
    assert_true(any("Revert" in hint for hint in hints), "ready revert should show tool prompt")
    hints = UI.trial_action_hints(trial, FakeKeybindings())
    assert_true(any("Y / T: Irradiate" in hint for hint in hints), "tool prompt should use configured key label")
    assert_true(any("L1 / V: Revert" in hint for hint in hints), "revert prompt should use configured key label")
    assert_true(any("Menu / Esc: Pause" in hint for hint in hints), "running trial should show pause prompt")
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "controller")
    assert_true(
        any("Right Stick + R2: Nutrient Gel" in hint for hint in hints),
        "controller scheme should show controller nutrient input",
    )
    assert_true(any("Y: Irradiate" in hint for hint in hints), "controller scheme should show controller tool label")
    assert_true(not any(" / " in hint for hint in hints), "controller scheme should not show hybrid separators")
    prompt_specs = trial_action_prompt_specs(trial, FakeKeybindings(), "controller")
    nutrient_spec = next(prompt for prompt in prompt_specs if prompt.label == "Nutrient Gel")
    assert_true(
        nutrient_spec.controller_labels == ("Right Stick", "R2"),
        "nutrient prompt should keep glyph-ready controller labels",
    )
    assert_true(
        nutrient_spec.steam_input_actions == ("AimNutrientGel", "ApplyNutrientGel"),
        "nutrient prompt should keep Steam Input action ids",
    )
    assert_true(
        nutrient_spec.glyph_assets == (
            "steam_input/glyphs/right_stick.svg",
            "steam_input/glyphs/r2.svg",
        ),
        "nutrient prompt should keep glyph asset ids",
    )
    assert_true(nutrient_spec.has_controller_glyphs, "nutrient prompt should be glyph-renderable")
    assert_true(
        nutrient_spec.render_controller_glyph_text() == "[Right Stick] + [R2]",
        "nutrient prompt should expose glyph-chip fallback text",
    )
    assert_true(
        "[Right Stick] + [R2]" in nutrient_spec.render_display_text(),
        "nutrient display prompt should use glyph-chip fallback text",
    )
    revert_spec = next(prompt for prompt in prompt_specs if prompt.label == "Revert")
    assert_true(
        revert_spec.steam_input_actions == ("RevertStrain",),
        "revert prompt should keep Steam Input action id",
    )
    assert_true(
        revert_spec.glyph_assets == ("steam_input/glyphs/l1.svg",),
        "revert prompt should keep glyph asset id",
    )
    assert_true(revert_spec.render_controller_glyph_text() == "[L1]", "revert prompt should expose glyph-chip fallback text")
    assert_true("[L1]" in revert_spec.render_display_text(), "revert display prompt should use glyph-chip fallback text")
    for prompt in prompt_specs:
        for action, controller_label in zip(prompt.steam_input_actions, prompt.controller_labels):
            glyph = TRIAL_PROMPT_GLYPHS.get(action)
            assert_true(glyph is not None, f"missing glyph metadata for {action}")
            assert_true(
                glyph.fallback_label == controller_label,
                f"glyph fallback label should match prompt label for {action}",
            )
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "keyboard_mouse")
    assert_true(
        any("Mouse / Touch: Nutrient Gel" in hint for hint in hints),
        "keyboard scheme should show mouse nutrient input",
    )
    assert_true(any("T: Irradiate" in hint for hint in hints), "keyboard scheme should show keyboard tool label")
    labels = UI.trial_tool_status_labels(trial)
    assert_true("ready" in labels["irradiation"], "ready irradiation should show ready label")
    assert_true("archive ready" in labels["revert"], "ready revert should show archive label")

    trial.preserved_strain_available = False
    trial.irradiation_cooldown_remaining = 4.4
    hints = UI.trial_action_hints(trial)
    assert_true(any("Recharge" in hint for hint in hints), "cooldown should show recharge prompt")
    assert_true(any("No Archive" in hint for hint in hints), "missing archive should show blocked revert prompt")
    labels = UI.trial_tool_status_labels(trial)
    assert_true("recharge" in labels["irradiation"], "cooldown should show recharge label")
    assert_true("no archive" in labels["revert"], "missing archive should show no archive label")

    trial.irradiation_charges = 0
    trial.irradiation_cooldown_remaining = 4.4
    trial.revert_charges = 0
    hints = UI.trial_action_hints(trial)
    assert_true(any("Depleted" in hint for hint in hints), "depleted should override recharge prompt")
    labels = UI.trial_tool_status_labels(trial)
    assert_true("depleted" in labels["irradiation"], "spent irradiation should show depleted label")
    assert_true("recharge" not in labels["irradiation"], "depleted should override recharge label")
    assert_true("spent" in labels["revert"], "spent revert should show spent label")

    trial.status = "won"
    trial.trial_index = 2
    trial.trial_count = 3
    hints = UI.trial_action_hints(trial)
    assert_true(any("Restart" in hint for hint in hints), "final win should show restart prompt")

    trial.status = "failed"
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "controller")
    assert_true(hints == ["A: Retry"], "failed controller prompt should show one primary retry action")

    trial.status = "running"
    trial.paused = True
    hints = UI.trial_action_hints(trial, FakeKeybindings(), "controller")
    assert_true(any("Menu: Resume" in hint for hint in hints), "paused controller prompt should show resume")
    assert_true(any("View: Exit" in hint for hint in hints), "paused controller prompt should show exit")


def main() -> None:
    smoke_full_trial_dish_playthrough()
    smoke_trial_sequence()
    smoke_activity_sampling()
    smoke_result_guidance()
    smoke_guidance_progression()
    smoke_pause_flow()
    smoke_territory_grades()
    smoke_controller_final_restart()
    smoke_player_shell_editor_gate()
    smoke_trial_action_hints()
    print("trial_dish_smoke=ok")


if __name__ == "__main__":
    main()
