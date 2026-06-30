"""Smoke-check launch contracts for the player-facing game shell."""
from __future__ import annotations

from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import App
from launch_options import STEAM_DECK_SIZE, editor_tools_enabled, parse_launch_options
from services.trial_service import TrialService
from state import UIState


EDITOR_ONLY_FLAGS = (
    "request_reload",
    "toggle_recording",
    "request_screenshot",
    "request_world_size_change",
    "request_camera_reset",
    "request_clear_canvas_and_fields",
    "request_save_config",
    "request_load_config",
    "request_save_file",
    "request_load_file",
    "request_delete_file",
    "request_preview_config",
    "request_clear_preview",
    "request_load_force_field_image",
    "request_load_strafe_field_image",
    "request_preview_clipboard_config",
    "request_clear_clipboard_preview",
    "request_load_clipboard_config",
    "request_delete_clipboard_config",
    "request_import_clipboard_to_multiload",
)

EDITOR_ONLY_TEXT_FIELDS = (
    "clipboard_text",
    "save_filename",
    "load_filename",
    "load_category",
    "delete_filename",
    "delete_category",
    "preview_filename",
    "preview_category",
    "field_load_image_path",
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def flagged_game_state() -> UIState:
    state = UIState()
    state.trial.game_mode = True
    for flag in EDITOR_ONLY_FLAGS:
        setattr(state, flag, True)
    for field in EDITOR_ONLY_TEXT_FIELDS:
        setattr(state, field, "editor-value")
    state.clipboard_config_index = 2
    state.sim.parameter_sweeps_enabled = True
    state.sim.sweep_preview_pending_restore = True
    state.request_fill_operation = True
    state.request_clear_force_field = True
    state.request_clear_strafe_field = True
    state.request_clear_canvas = True

    # Game-shell operations should survive the editor-command filter.
    state.request_trial_start = True
    state.request_trial_retry = True
    state.request_trial_pause = True
    state.request_trial_next = True
    state.request_trial_restart_sequence = True
    state.request_revert_strain = True
    state.request_reset = True
    state.request_randomize_mutations = True
    state.request_exit = True
    return state


def shell_app(editor_enabled: bool):
    app = App.__new__(App)

    class ShellUI:
        game_editor_enabled = editor_enabled

    app.ui = ShellUI()
    return app


def overlay_app():
    app = App.__new__(App)

    class ViewTexture:
        size = (1024, 1024)

    class Sim:
        view_tex = ViewTexture()

    class Camera:
        @staticmethod
        def tex_to_screen(point, tex_size):
            return (point[0] * tex_size[0], point[1] * tex_size[1])

    app.sim = Sim()
    app.camera = Camera()
    return app


def assert_editor_commands_blocked(state: UIState) -> None:
    for flag in EDITOR_ONLY_FLAGS:
        assert_true(not getattr(state, flag), f"{flag} should be blocked in default --game")
    for field in EDITOR_ONLY_TEXT_FIELDS:
        assert_true(getattr(state, field) == "", f"{field} should be cleared in default --game")
    assert_true(state.clipboard_config_index == -1, "clipboard_config_index should be reset")
    assert_true(not state.sim.parameter_sweeps_enabled, "parameter sweeps should be disabled in default --game")
    assert_true(
        not state.sim.sweep_preview_pending_restore,
        "sweep preview restore should be disabled in default --game",
    )
    assert_true(not state.request_fill_operation, "fill operation should be blocked in default --game")
    assert_true(not state.request_clear_force_field, "force field clear should be blocked in default --game")
    assert_true(not state.request_clear_strafe_field, "strafe field clear should be blocked in default --game")
    assert_true(not state.request_clear_canvas, "canvas clear should be blocked in default --game")


def assert_game_commands_preserved(state: UIState) -> None:
    assert_true(state.request_trial_start, "trial start should stay available in default --game")
    assert_true(state.request_trial_retry, "trial retry should stay available in default --game")
    assert_true(state.request_trial_pause, "trial pause should stay available in default --game")
    assert_true(state.request_trial_next, "trial next should stay available in default --game")
    assert_true(
        state.request_trial_restart_sequence,
        "trial restart sequence should stay available in default --game",
    )
    assert_true(state.request_revert_strain, "revert strain should stay available in default --game")
    assert_true(state.request_reset, "Sterilize Dish reset should stay available in default --game")
    assert_true(state.request_randomize_mutations, "Irradiate Strain should stay available in default --game")
    assert_true(state.request_exit, "paused exit should stay available in default --game")


def assert_onboarding_overlay_reveal() -> None:
    service = TrialService()
    app = overlay_app()
    state = UIState()
    state.trial.game_mode = True

    service.load_trial(state.trial, 0)
    assert_true(state.trial.minimal_onboarding, "Trial 1 should use minimal onboarding")
    assert_true(
        App._build_trial_zone_overlays(app, state) == [],
        "Trial 1 briefing should not show objective overlays before the protocol starts",
    )
    service.process_requests(state.trial, UIState(request_trial_start=True))
    assert_true(
        len(App._build_trial_zone_overlays(app, state)) == 1,
        "Trial 1 running should reveal the single objective zone",
    )

    service.load_trial(state.trial, 1)
    assert_true(state.trial.onboarding_focus == "counterforce", "Trial 2 should use counterforce focus")
    assert_true(
        len(App._build_trial_zone_overlays(app, state)) == 3,
        "Trial 2 briefing should reveal multi-site route context",
    )
    assert_true(
        App._build_trial_hazard_overlay(app, state) is None,
        "Trial 2 briefing should hold the hazard overlay until the assay starts",
    )
    service.process_requests(state.trial, UIState(request_trial_start=True))
    assert_true(
        App._build_trial_hazard_overlay(app, state) is not None,
        "Trial 2 running should reveal the antibiotic band overlay",
    )

    service.load_trial(state.trial, 2)
    assert_true(
        App._build_trial_rival_overlay(app, state) is None,
        "Trial 3 briefing should hold the rival overlay until the assay starts",
    )
    service.process_requests(state.trial, UIState(request_trial_start=True))
    assert_true(
        App._build_trial_rival_overlay(app, state) is not None,
        "Trial 3 running should reveal rival pressure",
    )


def main() -> int:
    editor = parse_launch_options([])
    game = parse_launch_options(["--game"])
    game_dev = parse_launch_options(["--game", "--allow-editor-in-game"])
    deck_player = parse_launch_options(["--steam-deck", "--game"])
    deck_env_previous = os.environ.get("FLUODDITY_STEAM_DECK")
    try:
        os.environ["FLUODDITY_STEAM_DECK"] = "1"
        deck_env_player = parse_launch_options(["--game"])
    finally:
        if deck_env_previous is None:
            os.environ.pop("FLUODDITY_STEAM_DECK", None)
        else:
            os.environ["FLUODDITY_STEAM_DECK"] = deck_env_previous

    assert_true(editor_tools_enabled(editor), "normal editor launch should expose editor tools")
    assert_true(not editor_tools_enabled(game), "--game should hide raw editor tools by default")
    assert_true(
        editor_tools_enabled(game_dev),
        "--allow-editor-in-game should re-enable editor tools for development",
    )
    assert_true(deck_player.steam_deck, "--steam-deck --game should enable Steam Deck profile")
    assert_true(deck_player.game, "--steam-deck --game should enter the player shell")
    assert_true(not editor_tools_enabled(deck_player), "--steam-deck --game should hide editor tools")
    assert_true(
        (deck_player.width, deck_player.height) == STEAM_DECK_SIZE,
        "--steam-deck --game should default to Deck resolution",
    )
    assert_true(deck_player.fullscreen, "--steam-deck --game should default to fullscreen")
    assert_true(deck_player.deck_performance, "--steam-deck --game should enable performance defaults")
    assert_true(deck_player.ui_scale > editor.ui_scale, "--steam-deck --game should increase UI scale")
    assert_true(
        deck_env_player.steam_deck and deck_env_player.game,
        "FLUODDITY_STEAM_DECK=1 plus --game should match the packaged wrapper profile",
    )

    player_state = flagged_game_state()
    App._filter_player_shell_commands(shell_app(editor_enabled=False), player_state)
    assert_editor_commands_blocked(player_state)
    assert_game_commands_preserved(player_state)

    dev_state = flagged_game_state()
    App._filter_player_shell_commands(shell_app(editor_enabled=True), dev_state)
    for flag in EDITOR_ONLY_FLAGS:
        assert_true(getattr(dev_state, flag), f"{flag} should stay available with --allow-editor-in-game")
    assert_true(dev_state.clipboard_text == "editor-value", "clipboard text should stay available in dev mode")
    assert_true(dev_state.clipboard_config_index == 2, "clipboard index should stay available in dev mode")

    assert_onboarding_overlay_reveal()

    print("game_shell_contract_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
