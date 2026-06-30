"""Smoke-check game-mode controller lab cursor behavior."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from controller_input import apply_controller_to_2d_camera, apply_game_cursor_to_state
from main import App
from services.trial_service import TrialService
from state import UIState


def assert_close(actual: float, expected: float, tolerance: float = 0.001) -> None:
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"expected {expected}, got {actual}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def controller_app(editor_enabled: bool = False):
    app = App.__new__(App)

    class ShellUI:
        show_sidebar = False
        game_editor_enabled = editor_enabled

    app.ui = ShellUI()
    return app


def apply_controller_request(service: TrialService, trial, actions: set[str]) -> UIState:
    ui_state = UIState()
    ui_state.trial = trial
    App._apply_controller_actions(controller_app(), actions, ui_state)
    service.process_requests(trial, ui_state)
    return ui_state


def smoke_controller_trial_flow() -> None:
    service = TrialService()
    ui_state = UIState()
    trial = ui_state.trial
    trial.game_mode = True
    service.load_trial(trial, 0)

    apply_controller_request(service, trial, {"game_confirm"})
    assert_true(trial.status == "running", "controller A should start Trial 1 from briefing")
    assert_true(not trial.briefing_active, "controller start should leave briefing")

    apply_controller_request(service, trial, {"game_pause"})
    assert_true(trial.paused, "controller Menu should pause a running Trial Dish")

    ui_state = apply_controller_request(service, trial, {"game_exit"})
    assert_true(ui_state.request_exit, "controller View should request exit from paused Trial Dish")
    assert_true(trial.paused, "controller exit request should not implicitly resume")

    apply_controller_request(service, trial, {"game_pause"})
    assert_true(not trial.paused, "controller Menu should resume a paused Trial Dish")

    apply_controller_request(service, trial, {"game_retry"})
    assert_true(trial.briefing_active, "controller B should retry back to briefing")
    assert_true(trial.trial_index == 0, "controller retry should keep the current trial index")

    trial.status = "won"
    apply_controller_request(service, trial, {"game_confirm"})
    assert_true(trial.trial_index == 1, "controller A should advance after a non-final win")
    assert_true(trial.briefing_active, "controller advance should land on the next briefing")

    service.load_trial(trial, 2)
    apply_controller_request(service, trial, {"game_confirm"})
    assert_true(trial.status == "running", "controller A should start Trial 3")

    ui_state = apply_controller_request(service, trial, {"game_tool"})
    assert_true(ui_state.request_randomize_mutations, "controller Y should pass through ready irradiation")
    assert_true(trial.irradiation_uses == 1, "controller Y should consume one irradiation use")
    assert_true(trial.preserved_strain_available, "controller Y should archive the strain")

    ui_state = apply_controller_request(service, trial, {"game_revert"})
    assert_true(ui_state.request_revert_strain, "controller L1 should pass through ready revert")
    assert_true(trial.revert_uses == 1, "controller L1 should consume one revert use")
    assert_true(not trial.preserved_strain_available, "controller L1 should consume the archive")

    trial.status = "won"
    apply_controller_request(service, trial, {"game_confirm"})
    assert_true(trial.trial_index == 0, "controller A should restart sequence after final win")
    assert_true(trial.briefing_active, "controller final restart should return to Trial 1 briefing")


def main() -> int:
    ui_state = UIState()
    ui_state.trial.game_mode = True
    ui_state.camera.zoom = 1.0
    joystick_state = {
        "joystick_id": 0,
        "right_x": 0.5,
        "right_y": -0.25,
        "rt": 0.7,
        "lt": 0.0,
        "fast": False,
    }

    cursor = apply_game_cursor_to_state(
        ui_state,
        joystick_state,
        dt=0.5,
        viewport_size=(800, 600),
        cursor_pos=None,
    )
    if not ui_state.game_cursor_active:
        raise AssertionError("game cursor should be active")
    if not ui_state.game_draw_held:
        raise AssertionError("right trigger should apply nutrient gel")
    if cursor is None:
        raise AssertionError("cursor position should be initialized")
    assert_close(ui_state.game_cursor_pos[0], 508.0)
    assert_close(ui_state.game_cursor_pos[1], 246.0)

    apply_controller_to_2d_camera(ui_state, joystick_state, dt=1.0)
    assert_close(ui_state.camera.zoom, 1.0)

    app = App.__new__(App)
    app.joystick_state = joystick_state
    ui_state.input_scheme = "keyboard_mouse"
    App._apply_input_scheme(app, ui_state, set())
    if ui_state.input_scheme != "controller":
        raise AssertionError("active controller axes/triggers should switch prompt scheme")

    ui_state.trial.paused = True
    cursor = apply_game_cursor_to_state(
        ui_state,
        joystick_state,
        dt=1.0,
        viewport_size=(800, 600),
        cursor_pos=cursor,
    )
    if ui_state.game_cursor_active or ui_state.game_draw_held:
        raise AssertionError("game cursor should disable while Trial Dish is paused")
    ui_state.trial.paused = False

    ui_state.trial.game_mode = False
    cursor = apply_game_cursor_to_state(
        ui_state,
        joystick_state,
        dt=1.0,
        viewport_size=(800, 600),
        cursor_pos=cursor,
    )
    if ui_state.game_cursor_active or ui_state.game_draw_held:
        raise AssertionError("game cursor should disable outside game mode")

    smoke_controller_trial_flow()

    print("game_controller_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
