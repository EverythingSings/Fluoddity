import glfw
import moderngl
import time
import numpy as np
import copy
from pathlib import Path
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import (
    RuleManager,
    EntityPicker,
    VideoRecorderService,
    ConfigSaver,
    ArrowDebugService,
    ENGINE_NAME,
    GAME_TITLE,
    MultiLoadService,
    TrialService,
)
from services.field_handler import FieldHandler
from services.parameter_lock_service import ParameterLockService
from utilities.paths import initialize_user_data, get_user_physics_configs_dir, get_app_physics_configs_dir, get_screenshots_dir
from state import load_preferences, save_preferences, SimState
from command_handler import CommandHandler
from simulation_runner import SimulationRunner
from camera_input import process_camera_input
from controller_input import (
    ControllerCam,
    apply_controller_to_2d_camera,
    apply_game_cursor_to_state,
    find_joystick,
    process_controller_input,
)
from launch_options import LaunchOptions, editor_tools_enabled, parse_launch_options


PLAYER_SHELL_BLOCKED_COMMAND_FLAGS = (
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

PLAYER_SHELL_BLOCKED_VALUE_FIELDS = (
    "clipboard_text",
    "save_filename",
    "load_filename",
    "load_category",
    "delete_filename",
    "delete_category",
    "preview_filename",
    "preview_category",
    "field_load_image_path",
    "clipboard_config_index",
)
from utilities.advanced_drawing import AdvancedDrawingProcessor


class App:
    """Main application orchestrator.

    Coordinates all components each frame: reads UI state, delegates commands
    to CommandHandler, physics to SimulationRunner, and manages recording/
    screenshot state machines.
    """

    def __init__(self, launch_options: LaunchOptions | None = None):
        self.launch_options = launch_options or LaunchOptions()
        # Initialize GLFW
        if not glfw.init():
            raise Exception("GLFW initialization failed")
        monitor = glfw.get_primary_monitor() if self.launch_options.fullscreen else None
        self.window = glfw.create_window(
            self.launch_options.width,
            self.launch_options.height,
            GAME_TITLE if self.launch_options.game else ENGINE_NAME,
            monitor,
            None,
        )
        if not self.window:
            glfw.terminate()
            raise Exception("GLFW window creation failed")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)  # Enable vsync

        # Initialize ModernGL
        self.ctx = moderngl.create_context()
        self.ctx.gc_mode = 'auto'

        # Always on top ONLY FOR WHEN LIVE EDITING THE SHADERS, NOT IN DISTRIBUTION
        #glfw.set_window_attrib(self.window, glfw.FLOATING, glfw.TRUE)

        # Initialize user data directory (creates Documents/Fluoddity on first run)
        initialize_user_data()

        # Load preferences first to get world_size
        loaded_prefs = load_preferences()
        self._editor_preferences_snapshot = copy.deepcopy(loaded_prefs)
        if self.launch_options.game:
            self._apply_game_runtime_defaults(loaded_prefs)
        if self.launch_options.deck_performance:
            self._apply_deck_performance_defaults(loaded_prefs)
            self._editor_preferences_snapshot = copy.deepcopy(loaded_prefs)

        # Create components (no cross-references between UI and sim/camera)
        self.sim = Sim(self.ctx, world_size=loaded_prefs.world_size, canvas_aspect_ratio=loaded_prefs.canvas_aspect_ratio)
        self.camera = Camera(self.ctx, self.sim, self.window)
        self.ui = UI(
            self.window,
            self.ctx,
            self.sim.view_option_labels,
            ui_scale=self.launch_options.ui_scale,
        )

        # Apply loaded preferences to UI
        self.ui.state.preferences = loaded_prefs
        self.ui._last_applied_world_size = loaded_prefs.world_size

        # Create services (Orchestrator owns these)
        self.rule_manager = RuleManager()
        entity_stride = SIZE_OF_ENTITY_STRUCT // 4
        self.entity_picker = EntityPicker(self.sim.get_entity_buffer(), entity_stride)
        self.video_service = VideoRecorderService()
        self.config_saver = ConfigSaver()
        self.arrow_debug_service = ArrowDebugService(self.ctx)
        self.multi_load_service = MultiLoadService()
        self.trial_service = TrialService()
        self.advanced_drawing_processor = AdvancedDrawingProcessor(self.ctx)
        self.ui.multi_load_service = self.multi_load_service
        self.ui.advanced_drawing_processor = self.advanced_drawing_processor
        self.ui.game_editor_enabled = editor_tools_enabled(self.launch_options)
        self._configure_game_mode()

        # Physics configs directories
        self.app_configs_dir = get_app_physics_configs_dir()
        self.user_configs_dir = get_user_physics_configs_dir()
        self.user_configs_dir.mkdir(exist_ok=True)

        # Create delegated handlers
        self.param_lock_service = ParameterLockService()
        self.field_handler = FieldHandler(
            self.advanced_drawing_processor, self.sim,
            param_lock_service=self.param_lock_service)
        self.ui.param_lock_service = self.param_lock_service
        self.command_handler = CommandHandler(
            self.sim, self.camera, self.ui, self.rule_manager,
            self.entity_picker, self.video_service, self.config_saver,
            self.multi_load_service, self.user_configs_dir,
            field_handler=self.field_handler,
            param_lock_service=self.param_lock_service
        )
        # Xbox controller (FPS camera for shader-driven field)
        self.controller_cam = ControllerCam()
        self.joystick_state = {'joystick_id': find_joystick(), 'prev_buttons': []}

        self.sim_runner = SimulationRunner(
            self.sim, self.camera, self.video_service,
            self.command_handler, self.window,
            advanced_drawing_processor=self.advanced_drawing_processor,
            controller_cam=self.controller_cam
        )

        # Frame timing
        self.last_update_time = time.time()

        # Track user's desired settings (for restoration after recording)
        self.user_speedmult = 1
        self.was_recording = False
        self.user_motion_blur = True
        self.user_blur_quality = 1

        # Screenshot state machine
        self.screenshot_pending = False
        self.screenshot_in_progress = False
        self.screenshot_saved_settings = {}

        # Track previous view option for camera repositioning when leaving tiling mode
        self.prev_view_option = 0
        self.visual_smoke_frame_count = 0
        self.visual_smoke_completed = False
        self.visual_smoke_mutation_applied = False
        self.visual_smoke_revert_applied = False
        self.game_cursor_screen_pos = None
        self.performance_smoke_completed = False
        self._performance_smoke_start = None
        self._performance_smoke_last_frame = None
        self._performance_smoke_frame_times = []

        # Ensure _Default.json exists and load it
        self._ensure_default_config()
        self._load_default_config()
        self._apply_game_mode_visual_defaults()
        self.sim.reload()
        self.sim.reset()

    def _configure_game_mode(self):
        """Apply the first Trial Dish shell without changing editor defaults."""
        if not self.launch_options.game:
            return

        self.ui.state.trial.game_mode = True
        trial_index = self.launch_options.visual_smoke_trial - 1
        self.trial_service.load_trial(self.ui.state.trial, trial_index)
        if self.launch_options.visual_smoke_output and self.launch_options.visual_smoke_transition_action:
            self._apply_visual_smoke_transition_action(self.ui.state.trial)
        if (
            (self.launch_options.visual_smoke_output and self.launch_options.visual_smoke_start)
            or self.launch_options.performance_smoke_seconds > 0.0
        ):
            self.trial_service.start_trial(self.ui.state.trial)
            if self.launch_options.visual_smoke_output and self.launch_options.visual_smoke_elapsed > 0.0:
                self.ui.state.trial.elapsed_seconds = self.launch_options.visual_smoke_elapsed
                self.trial_service._update_objective_status(self.ui.state.trial)
                self.trial_service._update_guidance(self.ui.state.trial)
            self.ui.state.sim.going = True
            if self.launch_options.visual_smoke_output and self.launch_options.visual_smoke_pause:
                self.ui.state.trial.paused = True
                self.trial_service._update_objective_status(self.ui.state.trial)
                self.trial_service._update_guidance(self.ui.state.trial)
        self.ui.state.trial.visual_smoke_feed = (
            self.launch_options.visual_smoke_output is not None
            and self.launch_options.visual_smoke_feed
        )
        self.ui.state.preferences.mouse_mode = "Draw Trail"
        self.ui.state.preferences.show_tutorial_window = False
        self.ui.state.preferences.show_preferences_window = False
        self.ui.state.preferences.show_controls_window = False
        self.ui.state.preferences.show_parameter_sweeps_window = False
        self.ui.state.preferences.show_performance_window = False
        self.ui.state.preferences.advanced_drawing_enabled = False
        self.ui.show_sidebar = False
        self.ui.show_video_recording_window = False
        self.ui.show_history_window = False
        glfw.set_window_title(self.window, GAME_TITLE)

    def _apply_game_mode_visual_defaults(self):
        """Make game mode readable even if editor configs/preferences were noisy."""
        if not self.launch_options.game:
            return

        sim_state = self.ui.state.sim
        prefs = self.ui.state.preferences

        sim_state.going = (
            (
                self.launch_options.visual_smoke_output is not None
                and self.launch_options.visual_smoke_start
                and not self.launch_options.visual_smoke_pause
            )
            or self.launch_options.performance_smoke_seconds > 0.0
        )
        sim_state.current_view_option = 0
        sim_state.parameter_sweeps_enabled = False
        sim_state.sweep_preview_pending_restore = False
        sim_state.watercolor_mode = False
        sim_state.emboss_mode = 0

        self.ui.state.camera.position[:] = 0.0
        self.ui.state.camera.zoom = 1.0

        prefs.mouse_mode = "Draw Trail"
        prefs.speedmult = min(max(prefs.speedmult, 3), 4)
        prefs.motion_blur = False
        prefs.debug_arrows = False
        prefs.advanced_drawing_enabled = False
        prefs.draw_size = max(prefs.draw_size, 0.040)
        prefs.draw_power = max(prefs.draw_power, 1.05)

    def _apply_deck_performance_defaults(self, prefs):
        """Prefer 30 FPS+ Steam Deck defaults without deleting user-tunable settings."""
        prefs.world_size = min(prefs.world_size, 0.35)
        prefs.speedmult = min(prefs.speedmult, 3)
        prefs.motion_blur = False
        prefs.blur_quality = max(prefs.blur_quality, 2)
        prefs.bloom_enabled = False
        prefs.show_tutorial_window = False

    def _apply_game_runtime_defaults(self, prefs):
        """Use a smaller, calmer simulation for the first playable game shell."""
        prefs.world_size = min(prefs.world_size, 0.06)
        prefs.motion_blur = False
        prefs.bloom_enabled = False
        prefs.brightness = min(prefs.brightness, 0.45)

    def _ensure_default_config(self):
        """Ensure _Default.json exists in physics_configs directory. Create it if missing."""
        default_path = self.app_configs_dir / "Core/_Default.json"
        if not default_path.exists():
            default_state = SimState()
            zero_rule = np.zeros((10, 8), dtype=np.float32)
            config = self.config_saver.create_config(default_state, zero_rule)
            self.config_saver.save_to_file(config, default_path)
            print(f"Created default config: {default_path}")

    def _load_default_config(self):
        """Load _Default.json on startup."""
        default_path = self.app_configs_dir / "Core/_Default.json"
        config = self.config_saver.load_from_file(default_path)
        if config is not None:
            rule = self.config_saver.apply_config(config, self.ui.state.sim)
            self.rule_manager.push_rule(rule, self.ui.state.sim.rule_seed)
            self.sim.apply_rule(rule)
            print(f"Loaded default config from {default_path}")
            self.ui.update_physics_defaults("_Default")
        else:
            print(f"Failed to load default config from {default_path}")

    def run(self):
        while not glfw.window_should_close(self.window):
            frame_start = time.perf_counter()
            glfw.poll_events()
            self.orchestrate_frame()
            self._handle_visual_smoke_capture()
            glfw.swap_buffers(self.window)
            self._handle_performance_smoke(frame_start)

        if self.visual_smoke_completed or self.performance_smoke_completed:
            glfw.terminate()
        else:
            self.cleanup()

    def _handle_performance_smoke(self, frame_start):
        """Print app-loop frame timing for timed runtime smoke checks."""
        seconds = self.launch_options.performance_smoke_seconds
        if seconds <= 0.0 or self.performance_smoke_completed:
            return

        now = time.perf_counter()
        if self._performance_smoke_start is None:
            self._performance_smoke_start = now
            self._performance_smoke_last_frame = now
            return

        frame_time = now - frame_start
        self._performance_smoke_frame_times.append(frame_time)
        elapsed = now - self._performance_smoke_start
        if elapsed < seconds:
            return

        frames = len(self._performance_smoke_frame_times)
        avg_frame = (
            sum(self._performance_smoke_frame_times) / frames
            if frames > 0 else 0.0
        )
        worst_frame = (
            max(self._performance_smoke_frame_times)
            if frames > 0 else 0.0
        )
        avg_fps = frames / elapsed if elapsed > 0.0 else 0.0
        print(
            "performance_smoke="
            f"frames={frames} "
            f"elapsed={elapsed:.3f} "
            f"avg_fps={avg_fps:.2f} "
            f"avg_frame_ms={avg_frame * 1000.0:.2f} "
            f"worst_frame_ms={worst_frame * 1000.0:.2f}"
        )
        self.performance_smoke_completed = True
        glfw.set_window_should_close(self.window, True)

    def _handle_visual_smoke_capture(self):
        """Save the rendered framebuffer for launch-level visual smoke checks."""
        output = self.launch_options.visual_smoke_output
        if not output:
            return

        self.visual_smoke_frame_count += 1
        if self.visual_smoke_frame_count < self.launch_options.visual_smoke_frame:
            return

        width, height = glfw.get_framebuffer_size(self.window)
        data = self.ctx.screen.read(components=3, alignment=1)
        pixels = np.frombuffer(data, dtype=np.uint8).reshape((height, width, 3))
        pixels = np.flipud(pixels)

        from PIL import Image

        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels, "RGB").save(path)
        print(f"visual_smoke_saved={path}")
        trial = self.ui.state.trial
        active_zones = sum(1 for zone in trial.zones if zone.active)
        rival_zones = sum(1 for zone in trial.zones if zone.rival_controlled)
        zone_overlays = self.ui._display_info.get('trial_zone_overlays', [])
        hazard_overlay = self.ui._display_info.get('trial_hazard_overlay')
        rival_overlay = self.ui._display_info.get('trial_rival_overlay')
        result_title = self._visual_smoke_token(trial.result_title)
        result_readout = self._visual_smoke_token(trial.result_grade)
        result_summary = self._visual_smoke_token(trial.result_summary)
        result_hint = self._visual_smoke_token(trial.result_experiment_hint)
        result_next = self._visual_smoke_token(trial.result_next_step)
        transition_message = self._visual_smoke_token(trial.transition_message)
        specimen_readout = self._visual_smoke_token(trial.specimen_readout)
        route_readout = self._visual_smoke_token(trial.route_readout)
        containment_readout = self._visual_smoke_token(trial.containment_readout)
        mutation_readout = self._visual_smoke_token(trial.mutation_readout)
        timer_readout = self._visual_smoke_token(trial.timer_readout)
        guidance_title = self._visual_smoke_token(trial.guidance_title)
        guidance_message = self._visual_smoke_token(trial.guidance_message)
        tool_feedback = self._visual_smoke_token(trial.tool_feedback)
        prompt_specs = self.ui.trial_action_prompt_specs(
            trial,
            self.ui.keybindings,
            self.ui.state.input_scheme,
        )
        prompt_text = self._visual_smoke_token(
            " | ".join(prompt.render_text() for prompt in prompt_specs)
        )
        display_prompt_text = self._visual_smoke_token(
            " | ".join(prompt.render_display_text() for prompt in prompt_specs)
        )
        prompt_glyphs = self._visual_smoke_token(
            " | ".join(
                glyph
                for prompt in prompt_specs
                for glyph in prompt.glyph_assets
            )
        )
        print(
            "visual_smoke_trial_state="
            f"trial={trial.trial_index + 1} "
            f"status={trial.status} "
            f"active_zones={active_zones}/{len(trial.zones)} "
            f"rival_zones={rival_zones} "
            f"containment_margin={trial.containment_margin} "
            f"containment={containment_readout} "
            f"zone_overlays={len(zone_overlays)} "
            f"hazard_overlay={int(hazard_overlay is not None)} "
            f"rival_overlay={int(rival_overlay is not None)} "
            f"specimen={specimen_readout} "
            f"route={route_readout} "
            f"mutation={mutation_readout} "
            f"timer={timer_readout} "
            f"guidance_title={guidance_title} "
            f"guidance={guidance_message} "
            f"feedback={tool_feedback} "
            f"progress={trial.progress:.3f} "
            f"elapsed={trial.elapsed_seconds:.2f} "
            f"paused={int(trial.paused)} "
            f"input_scheme={self.ui.state.input_scheme} "
            f"cursor={int(self.ui.state.game_cursor_active)} "
            f"cursor_draw={int(self.ui.state.game_draw_held)} "
            f"result_title={result_title} "
            f"result_readout={result_readout} "
            f"result_summary={result_summary} "
            f"result_hint={result_hint} "
            f"result_next={result_next} "
            f"transition={transition_message} "
            f"prompts={prompt_text} "
            f"display_prompts={display_prompt_text} "
            f"glyphs={prompt_glyphs}"
        )
        self.visual_smoke_completed = True
        glfw.set_window_should_close(self.window, True)

    @staticmethod
    def _visual_smoke_token(text):
        """Normalize smoke-only text fields into whitespace-free tokens."""
        return "_".join(str(text or "").strip().split()) or "-"

    def _apply_visual_smoke_transition_action(self, trial) -> None:
        """Apply a pre-capture Trial Dish transition for UI smoke coverage."""
        action = self.launch_options.visual_smoke_transition_action
        if action == "retry":
            self.trial_service.retry_trial(trial)
        elif action == "next":
            self.trial_service.next_trial(trial)
        elif action == "restart":
            self.trial_service.restart_sequence(trial)
        elif action == "sterilize":
            self.trial_service.sterilize(trial)

    def orchestrate_frame(self):
        """Main orchestration logic - reads UI state, coordinates components."""

        # 1. Get current UI state
        ui_state = self.ui.get_state()
        self._filter_player_shell_commands(ui_state)
        tiling_mode = (ui_state.sim.current_view_option == 3)

        # 2. Process continuous input (camera movement)
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        if self.launch_options.visual_smoke_output and self.launch_options.visual_smoke_start:
            dt = 1.0 / 30.0
        process_camera_input(ui_state, self.window, self.ui.keybindings,
                             self.sim.view_tex, dt)
        self.joystick_state['game_mode'] = ui_state.trial.game_mode
        controller_actions = process_controller_input(self.controller_cam, self.joystick_state, dt)
        apply_controller_to_2d_camera(ui_state, self.joystick_state, dt)
        self._apply_game_controller_cursor(ui_state, dt)
        self._apply_input_scheme(ui_state, controller_actions)
        self._apply_controller_actions(controller_actions, ui_state)
        self._apply_visual_smoke_tool_requests(ui_state)
        if ui_state.request_exit:
            glfw.set_window_should_close(self.window, True)

        trial_strain_reset_requested = (
            ui_state.trial.game_mode
            and (
                ui_state.request_trial_next
                or ui_state.request_trial_retry
                or ui_state.request_trial_restart_sequence
                or ui_state.request_reset
                or ui_state.request_full_reset
            )
        )
        self.trial_service.process_requests(ui_state.trial, ui_state)
        if trial_strain_reset_requested:
            self.command_handler.restore_trial_strain_baseline(ui_state)
            if ui_state.request_full_reset:
                # In the player shell, Full Reset is a dish sterilization, not
                # the editor's zero-rule operation.
                ui_state.request_full_reset = False
                ui_state.request_reset = True
        if ui_state.trial.game_mode:
            if (
                ui_state.trial.briefing_active
                or ui_state.trial.won
                or ui_state.trial.failed
                or ui_state.trial.paused
            ):
                ui_state.sim.going = False
            elif ui_state.request_trial_start or ui_state.request_trial_pause:
                ui_state.sim.going = True

        # 3. Process one-shot commands
        result = self.command_handler.process_commands(ui_state, tiling_mode)
        if result == 'screenshot_pending' and not self.screenshot_pending and not self.screenshot_in_progress:
            self.screenshot_pending = True

        # 3.2. Check if pending video should start
        cmd = self.command_handler
        if cmd.video_pending and self.sim.frame_count >= cmd.video_scheduled_start_frame:
            cmd.video_pending = False
            cmd.video_scheduled_start_frame = 0
            self.video_service.start()

        # 3.5. Screenshot state machine
        if self.screenshot_pending and not self.screenshot_in_progress:
            self.screenshot_pending = False
            self.screenshot_in_progress = True
            self.screenshot_saved_settings = {
                'speedmult': ui_state.preferences.speedmult,
                'blur_quality': ui_state.preferences.blur_quality,
                'motion_blur': ui_state.preferences.motion_blur,
                'going': ui_state.sim.going,
            }
            ui_state.preferences.speedmult = ui_state.preferences.motion_blur_samples
            ui_state.preferences.blur_quality = 1
            ui_state.preferences.motion_blur = True
            if not ui_state.sim.going:
                ui_state.sim.going = True

        # 4. Lock physics frequency to video recorder frequency if recording
        is_recording = self.video_service.is_active()

        if is_recording and not self.was_recording:
            self.user_speedmult = ui_state.preferences.speedmult
            self.user_motion_blur = ui_state.preferences.motion_blur
            self.user_blur_quality = ui_state.preferences.blur_quality
        elif not is_recording and self.was_recording:
            ui_state.preferences.speedmult = self.user_speedmult
            ui_state.preferences.motion_blur = self.user_motion_blur
            ui_state.preferences.blur_quality = self.user_blur_quality

        if is_recording:
            ui_state.preferences.speedmult = ui_state.preferences.motion_blur_samples
            ui_state.preferences.motion_blur = ui_state.preferences.recording_motion_blur
            ui_state.preferences.blur_quality = ui_state.preferences.recording_blur_quality

        self.was_recording = is_recording

        # 5. Apply state to components
        if ui_state.request_camera_reset:
            ui_state.camera.position[:] = [0.0, 0.0]
            ui_state.camera.zoom = 1.0
        self.sim.apply_state(ui_state.sim)
        self.sim.apply_camera_state(ui_state.camera)
        self.camera.apply_state(ui_state.camera)
        self.multi_load_service.apply_state(ui_state.multi_load)
        self.camera.BRIGHTNESS = ui_state.preferences.brightness

        # 5.0.1 Force/Strafe field view modes: override view_tex with field texture
        if ui_state.sim.current_view_option in (4, 5):
            field_tex = self.advanced_drawing_processor.field_texture
            if field_tex is not None:
                self.sim.view_tex = field_tex
            else:
                # Field texture not initialized yet — fall back to canvas view
                ui_state.sim.current_view_option = 0

        # 5.1. Multi-load conflict prevention
        if ui_state.multi_load.multi_load_enabled:
            ui_state.sim.parameter_sweeps_enabled = False
            ui_state.preferences.mouse_mode = "Draw Trail"
            if self.param_lock_service.enabled:
                self.param_lock_service.reset()
                ui_state.preferences.parameter_locks_enabled = False

        # 5.2. Sync parameter lock master toggle
        self.param_lock_service.enabled = ui_state.preferences.parameter_locks_enabled

        # 5.5. Calculate sweep reticle info
        sweep_reticle_x, sweep_reticle_y, sweep_reticle_visible = self.sim.get_sweep_reticle_position()

        if is_recording or self.screenshot_in_progress:
            sweep_reticle_visible = False

        width, height = glfw.get_framebuffer_size(self.window)
        screen_aspect = width / height if height > 0 else 1.0

        if sweep_reticle_visible:
            screen_x, screen_y = self.camera.tex_to_screen(
                (sweep_reticle_x, sweep_reticle_y),
                self.sim.view_tex.size
            )
            sweep_reticle_x = screen_x / width
            sweep_reticle_y = screen_y / height

        sweep_mode = ui_state.sim.parameter_sweeps_enabled
        sweep_reticle_pos = (sweep_reticle_x, sweep_reticle_y)

        # Reposition camera when leaving tiling mode
        if self.prev_view_option == 3 and ui_state.sim.current_view_option != 3:
            ui_state.camera.position[0] = np.fmod(ui_state.camera.position[0] + 100.0, 2.0) - 1.0
            ui_state.camera.position[1] = np.fmod(ui_state.camera.position[1] + 100.0, 2.0) - 1.0
        self.prev_view_option = ui_state.sim.current_view_option

        # 6. Run simulation if going
        if ui_state.sim.going:
            self.sim_runner.run_simulation_frame(
                ui_state, sweep_mode, sweep_reticle_pos, sweep_reticle_visible,
                screen_aspect, ui_state.sim.watercolor_mode,
                tiling_mode=tiling_mode,
                screenshot_in_progress=self.screenshot_in_progress
            )

        # 6.1. Update game-mode trial state after simulation advances.
        self._apply_visual_smoke_resolution(ui_state, dt)
        self.trial_service.update(
            ui_state.trial, ui_state, self.sim.frame_count, dt, self.sim.can
        )

        # 6.5. Screenshot save and settings restoration
        if self.screenshot_in_progress:
            self._save_screenshot(ui_state)

        if (
            ui_state.request_trial_next
            or ui_state.request_trial_retry
            or ui_state.request_trial_restart_sequence
        ):
            self.sim.reset()

        # 7. Render camera view
        self._render_camera_view(ui_state, sweep_mode, sweep_reticle_pos,
                                 sweep_reticle_visible, screen_aspect, tiling_mode)

        # 7.5. Render arrow debug overlay if enabled
        if ui_state.preferences.debug_arrows:
            width, height = glfw.get_framebuffer_size(self.window)
            adv_prefs = ui_state.preferences
            adv_active = adv_prefs.advanced_drawing_enabled
            field_tex = self.advanced_drawing_processor.field_texture
            # Use field_texture for force/strafe targets, canvas for trails
            if adv_active and not adv_prefs.advanced_draw_canvas and field_tex is not None:
                arrow_texture = field_tex
                arrow_resolution = field_tex.size
                use_zw = adv_prefs.advanced_draw_strafe_field
            else:
                arrow_texture = self.sim.can
                arrow_resolution = self.sim.can.size
                use_zw = False
            self.arrow_debug_service.render(
                canvas_texture=arrow_texture,
                cam_pos=tuple(self.camera.position),
                cam_zoom=self.camera.zoom,
                canvas_resolution=arrow_resolution,
                window_size=(width, height),
                arrow_sensitivity=ui_state.preferences.arrow_sensitivity,
                use_zw_channels=use_zw,
            )

        # 8. Update UI display info and render
        self.ui.update_display_info({
            'time': self.sim.time,
            'frame_count': self.sim.frame_count,
            'tex_size': self.sim.view_tex.size,
            'recording_active': self.video_service.is_active(),
            'video_pending': cmd.video_pending,
            'video_scheduled_start_frame': cmd.video_scheduled_start_frame,
            'game_mode': ui_state.trial.game_mode,
            'trial': ui_state.trial,
            'trial_zone_overlays': self._build_trial_zone_overlays(ui_state),
            'trial_hazard_overlay': self._build_trial_hazard_overlay(ui_state),
            'trial_rival_overlay': self._build_trial_rival_overlay(ui_state),
            'game_cursor': self._build_game_cursor_overlay(ui_state),
        })
        self.ui.render()

    def _filter_player_shell_commands(self, ui_state):
        """Defensively block raw editor commands from the default player shell."""
        if not (ui_state.trial.game_mode and not self.ui.game_editor_enabled):
            return

        for flag_name in PLAYER_SHELL_BLOCKED_COMMAND_FLAGS:
            setattr(ui_state, flag_name, False)
        for field_name in PLAYER_SHELL_BLOCKED_VALUE_FIELDS:
            current = getattr(ui_state, field_name)
            setattr(ui_state, field_name, -1 if isinstance(current, int) else "")

        ui_state.sim.parameter_sweeps_enabled = False
        ui_state.sim.sweep_preview_pending_restore = False
        ui_state.request_fill_operation = False
        ui_state.request_clear_force_field = False
        ui_state.request_clear_strafe_field = False
        ui_state.request_clear_canvas = False

    def _apply_visual_smoke_resolution(self, ui_state, dt):
        """Fast-forward a smoke capture to the Trial Dish result state."""
        if not (
            self.launch_options.visual_smoke_output
            and self.launch_options.visual_smoke_resolve
            and ui_state.trial.game_mode
            and not ui_state.trial.briefing_active
            and not ui_state.trial.won
            and not ui_state.trial.failed
        ):
            return

        next_capture_index = self.visual_smoke_frame_count + 1
        if next_capture_index < self.launch_options.visual_smoke_frame:
            return

        ui_state.trial.elapsed_seconds = max(
            ui_state.trial.elapsed_seconds,
            ui_state.trial.failure_seconds + max(dt, 1.0 / 30.0),
        )

    def _apply_visual_smoke_tool_requests(self, ui_state) -> None:
        """Drive one-shot Trial Dish tool requests for visual smoke captures."""
        trial = ui_state.trial
        if not (
            self.launch_options.visual_smoke_output
            and trial.game_mode
            and not trial.briefing_active
            and not trial.won
            and not trial.failed
            and not trial.paused
        ):
            return

        if (
            self.launch_options.visual_smoke_mutate
            and not self.visual_smoke_mutation_applied
            and trial.irradiation_ready
        ):
            ui_state.request_randomize_mutations = True
            self.visual_smoke_mutation_applied = True
            return

        if (
            self.launch_options.visual_smoke_revert
            and self.visual_smoke_mutation_applied
            and not self.visual_smoke_revert_applied
            and trial.revert_ready
        ):
            trial.irradiation_cooldown_remaining = 0.0
            ui_state.request_revert_strain = True
            self.visual_smoke_revert_applied = True

    def _apply_game_controller_cursor(self, ui_state, dt):
        """Use the right stick and right trigger as the game-mode lab applicator."""
        width, height = glfw.get_framebuffer_size(self.window)
        if (
            self.launch_options.visual_smoke_output
            and self.launch_options.visual_smoke_controller_cursor
            and ui_state.trial.game_mode
        ):
            ui_state.input_scheme = "controller"

        if (
            self.launch_options.visual_smoke_output
            and self.launch_options.visual_smoke_controller_cursor
            and ui_state.trial.game_mode
            and not ui_state.trial.paused
            and width > 0
            and height > 0
        ):
            if self.game_cursor_screen_pos is None:
                self.game_cursor_screen_pos = [width * 0.5, height * 0.5]
            ui_state.game_cursor_active = True
            ui_state.game_cursor_pos = tuple(self.game_cursor_screen_pos)
            ui_state.game_draw_held = self.launch_options.visual_smoke_controller_feed
            return

        self.game_cursor_screen_pos = apply_game_cursor_to_state(
            ui_state,
            self.joystick_state,
            dt,
            (width, height),
            self.game_cursor_screen_pos,
        )

    def _build_game_cursor_overlay(self, ui_state):
        """Return a screen-space marker for the controller lab applicator."""
        if not (
            ui_state.trial.game_mode
            and ui_state.game_cursor_active
            and not ui_state.trial.briefing_active
            and not ui_state.trial.won
            and not ui_state.trial.failed
            and not ui_state.trial.paused
        ):
            return None
        return {
            'pos': ui_state.game_cursor_pos,
            'drawing': ui_state.game_draw_held,
        }

    def _build_trial_zone_overlays(self, ui_state):
        """Convert Trial Dish texture-space objective zones to screen-space overlays."""
        if not ui_state.trial.game_mode:
            return []
        if ui_state.trial.briefing_active and ui_state.trial.minimal_onboarding:
            return []

        tex_size = self.sim.view_tex.size
        overlays = []
        for zone in ui_state.trial.zones:
            cx, cy = self.camera.tex_to_screen(zone.center, tex_size)
            rx, _ = self.camera.tex_to_screen((zone.center[0] + zone.radius, zone.center[1]), tex_size)
            _, ry = self.camera.tex_to_screen((zone.center[0], zone.center[1] + zone.radius), tex_size)
            radius_px = max(8.0, (abs(rx - cx) + abs(ry - cy)) * 0.5)
            overlays.append({
                'name': zone.name,
                'center': (cx, cy),
                'radius': radius_px,
                'active': zone.active,
                'activity': zone.activity,
                'rival_activity': zone.rival_activity,
                'rival_controlled': zone.rival_controlled,
            })
        return overlays

    def _build_trial_hazard_overlay(self, ui_state):
        """Convert the Trial Dish antibiotic band to a screen-space rectangle."""
        trial = ui_state.trial
        if not trial.game_mode or not trial.hazard_enabled or trial.briefing_active:
            return None

        half_width = trial.hazard_width * 0.5
        x0 = trial.hazard_center_x - half_width
        x1 = trial.hazard_center_x + half_width
        p0 = self.camera.tex_to_screen((x0, 0.0), self.sim.view_tex.size)
        p1 = self.camera.tex_to_screen((x1, 1.0), self.sim.view_tex.size)
        return {
            'name': trial.hazard_name,
            'min': (min(p0[0], p1[0]), min(p0[1], p1[1])),
            'max': (max(p0[0], p1[0]), max(p0[1], p1[1])),
            'strength': trial.hazard_strength,
        }

    def _build_trial_rival_overlay(self, ui_state):
        """Convert the Trial Dish rival bloom source to a screen-space circle."""
        trial = ui_state.trial
        if not trial.game_mode or not trial.rival_enabled or trial.briefing_active:
            return None

        tex_size = self.sim.view_tex.size
        cx, cy = self.camera.tex_to_screen(trial.rival_center, tex_size)
        age_radius = trial.rival_radius + trial.elapsed_seconds * trial.rival_growth
        rx, _ = self.camera.tex_to_screen(
            (trial.rival_center[0] + age_radius, trial.rival_center[1]),
            tex_size,
        )
        _, ry = self.camera.tex_to_screen(
            (trial.rival_center[0], trial.rival_center[1] + age_radius),
            tex_size,
        )
        return {
            'name': trial.rival_name,
            'center': (cx, cy),
            'radius': max(8.0, (abs(rx - cx) + abs(ry - cy)) * 0.5),
            'strength': trial.rival_strength,
        }

    def _apply_controller_actions(self, actions, ui_state):
        """Map gamepad button edges to app-level actions for Deck/controller play."""
        if ui_state.trial.game_mode:
            if "game_confirm" in actions:
                if ui_state.trial.briefing_active:
                    ui_state.request_trial_start = True
                elif ui_state.trial.won:
                    if ui_state.trial.final_trial:
                        ui_state.request_trial_restart_sequence = True
                    else:
                        ui_state.request_trial_next = True
                elif ui_state.trial.failed:
                    ui_state.request_trial_retry = True
            if "game_retry" in actions:
                ui_state.request_trial_retry = True
            if (
                "game_pause" in actions
                and not ui_state.trial.briefing_active
                and not ui_state.trial.won
                and not ui_state.trial.failed
            ):
                ui_state.request_trial_pause = True
            if "game_next" in actions and ui_state.trial.won:
                if ui_state.trial.final_trial:
                    ui_state.request_trial_restart_sequence = True
                else:
                    ui_state.request_trial_next = True
            if (
                "game_tool" in actions
                and not ui_state.trial.briefing_active
                and not ui_state.trial.won
                and not ui_state.trial.failed
                and ui_state.trial.irradiation_ready
            ):
                ui_state.request_randomize_mutations = True
            if (
                "game_revert" in actions
                and not ui_state.trial.briefing_active
                and not ui_state.trial.won
                and not ui_state.trial.failed
                and ui_state.trial.revert_ready
            ):
                ui_state.request_revert_strain = True
            if "toggle_sidebar" in actions and self.ui.game_editor_enabled:
                self.ui.show_sidebar = not self.ui.show_sidebar
            if "game_exit" in actions and ui_state.trial.paused:
                ui_state.request_exit = True
            if "toggle_mouse_mode" in actions and self.ui.game_editor_enabled:
                if ui_state.preferences.mouse_mode == "Select Particle":
                    ui_state.preferences.mouse_mode = "Draw Trail"
                else:
                    ui_state.preferences.mouse_mode = "Select Particle"
            return

        if "toggle_pause" in actions:
            ui_state.sim.going = not ui_state.sim.going
        if "reset_particles" in actions:
            ui_state.request_reset = True
        if "toggle_sidebar" in actions:
            self.ui.show_sidebar = not self.ui.show_sidebar
        if "randomize_mutations" in actions:
            ui_state.request_randomize_mutations = True
        if "toggle_mouse_mode" in actions:
            if ui_state.preferences.mouse_mode == "Select Particle":
                ui_state.preferences.mouse_mode = "Draw Trail"
            else:
                ui_state.preferences.mouse_mode = "Select Particle"

    def _apply_input_scheme(self, ui_state, controller_actions):
        """Keep Trial Dish prompts aligned with the most recent active input family."""
        controller_axis_active = any(
            abs(self.joystick_state.get(axis, 0.0)) > 0.01
            for axis in ("left_x", "left_y", "right_x", "right_y")
        )
        controller_trigger_active = (
            self.joystick_state.get("lt", 0.0) > 0.25
            or self.joystick_state.get("rt", 0.0) > 0.25
        )
        if controller_actions or controller_axis_active or controller_trigger_active:
            ui_state.input_scheme = "controller"

    def _render_camera_view(self, ui_state, sweep_mode, sweep_reticle_pos,
                             sweep_reticle_visible, screen_aspect, tiling_mode):
        """Render the camera view to screen."""
        emboss_mode = ui_state.sim.emboss_mode
        if emboss_mode == 1:
            emboss_tex = self.sim.can
        elif emboss_mode == 2:
            emboss_tex = self.sim.brush_tex
        else:
            emboss_tex = None

        draw_trail_mode = ui_state.preferences.mouse_mode == "Draw Trail"

        width, height = glfw.get_framebuffer_size(self.window)
        mouse_x_norm = ui_state.mouse_pos[0] / width if width > 0 else 0.5
        mouse_y_norm = ui_state.mouse_pos[1] / height if height > 0 else 0.5
        mouse_screen_coords = (mouse_x_norm, mouse_y_norm)

        self.camera.render(
            sim_going=ui_state.sim.going,
            current_view_option=ui_state.sim.current_view_option,
            sweep_mode=sweep_mode,
            sweep_reticle_pos=sweep_reticle_pos,
            sweep_reticle_visible=sweep_reticle_visible,
            screen_aspect=screen_aspect,
            watercolor_mode=ui_state.sim.watercolor_mode,
            ink_weight=ui_state.sim.ink_weight,
            emboss_tex=emboss_tex,
            emboss_mode=emboss_mode,
            emboss_intensity=ui_state.sim.emboss_intensity,
            emboss_smoothness=ui_state.sim.emboss_smoothness,
            draw_trail_mode=draw_trail_mode,
            draw_size=ui_state.preferences.draw_size,
            mouse_screen_coords=mouse_screen_coords,
            exposure=ui_state.preferences.exposure,
            tiling_mode=tiling_mode,
            tonemap_softness=ui_state.preferences.tonemap_softness,
            bloom_enabled=ui_state.preferences.bloom_enabled,
            bloom_threshold=ui_state.preferences.bloom_threshold,
            bloom_intensity=ui_state.preferences.bloom_intensity,
            bloom_radius=ui_state.preferences.bloom_radius
        )

    def _save_screenshot(self, ui_state):
        """Save screenshot and restore settings."""
        if self.camera.assembled_texture is not None:
            from utilities.save_frame_gpu import save_frame_gpu
            import datetime
            import os
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = ui_state.preferences.filename_prefix or "screenshot"
            filename = save_frame_gpu(
                self.camera.assembled_texture,
                self.ctx,
                supersample_k=ui_state.preferences.supersample_k,
                return_array=False
            )
            if filename and os.path.exists(filename):
                screenshots_dir = get_screenshots_dir()
                screenshots_dir.mkdir(parents=True, exist_ok=True)
                new_filename = screenshots_dir / f"{prefix}_{timestamp}.png"
                os.rename(filename, new_filename)
                print(f"Screenshot saved: {new_filename}")

        # Restore saved settings
        ui_state.preferences.speedmult = self.screenshot_saved_settings['speedmult']
        ui_state.preferences.blur_quality = self.screenshot_saved_settings['blur_quality']
        ui_state.preferences.motion_blur = self.screenshot_saved_settings['motion_blur']
        ui_state.sim.going = self.screenshot_saved_settings['going']
        self.screenshot_in_progress = False
        self.screenshot_saved_settings = {}

    def cleanup(self):
        # Save preferences before cleanup
        ui_state = self.ui.get_state()
        if self.launch_options.game:
            save_preferences(self._editor_preferences_snapshot)
        else:
            save_preferences(ui_state.preferences)

        self.advanced_drawing_processor.cleanup()
        self.video_service.cleanup()
        self.ui.cleanup()
        glfw.terminate()


if __name__ == "__main__":
    app = App(parse_launch_options())
    app.run()
