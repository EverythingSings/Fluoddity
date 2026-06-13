import glfw
import moderngl
import time
import numpy as np
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import RuleManager, EntityPicker, VideoRecorderService, ConfigSaver, ArrowDebugService, MultiLoadService, RenderSpecService
from services.field_handler import FieldHandler
from services.parameter_lock_service import ParameterLockService
from utilities.paths import initialize_user_data, get_user_physics_configs_dir, get_app_physics_configs_dir, get_screenshots_dir
from state import load_preferences, save_preferences, SimState
from command_handler import CommandHandler
from simulation_runner import SimulationRunner
from camera_input import process_camera_input, reposition_orbit_camera
from controller_input import ControllerCam, process_controller_input, find_joystick
from utilities.advanced_drawing import AdvancedDrawingProcessor
from plotting_manager import PlottingManager


class App:
    """Main application orchestrator.

    Coordinates all components each frame: reads UI state, delegates commands
    to CommandHandler, physics to SimulationRunner, and manages recording/
    screenshot state machines.
    """

    def __init__(self):
        # Initialize GLFW
        if not glfw.init():
            raise Exception("GLFW initialization failed")
        self.window = glfw.create_window(800, 600, "Fluoddity", None, None)
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

        # Create components (no cross-references between UI and sim/camera)
        self.sim = Sim(self.ctx, world_size=loaded_prefs.world_size, canvas_aspect_ratio=loaded_prefs.canvas_aspect_ratio)
        self.camera = Camera(self.ctx, self.sim, self.window)
        self.ui = UI(self.window, self.ctx, self.sim.view_option_labels)

        # Apply loaded preferences to UI
        self.ui.state.preferences = loaded_prefs
        self.ui._last_applied_world_size = loaded_prefs.world_size

        # Restore 3D camera settings from preferences
        cam = self.ui.state.camera
        cam.render_3d = loaded_prefs.three_d_render_3d
        cam.fov = loaded_prefs.three_d_fov
        cam.aperture = loaded_prefs.three_d_aperture
        cam.focal_plane_depth = loaded_prefs.three_d_focal_plane_depth
        cam.move_speed = loaded_prefs.three_d_move_speed
        cam.rotate_speed = loaded_prefs.three_d_rotate_speed
        cam.orbit_center[:] = loaded_prefs.three_d_orbit_center
        cam.orbit_rate = loaded_prefs.three_d_orbit_rate
        cam.optix_enabled = loaded_prefs.three_d_optix_enabled

        # Create services (Orchestrator owns these)
        self.rule_manager = RuleManager()
        entity_stride = SIZE_OF_ENTITY_STRUCT // 4
        self.entity_picker = EntityPicker(self.sim.get_entity_buffer(), entity_stride)
        self.video_service = VideoRecorderService()
        self.config_saver = ConfigSaver()
        self.arrow_debug_service = ArrowDebugService(self.ctx)
        self.multi_load_service = MultiLoadService()
        self.advanced_drawing_processor = AdvancedDrawingProcessor(self.ctx)
        self.plotting_manager = PlottingManager(self.ctx)
        self.render_spec_service = RenderSpecService()
        self.ui.multi_load_service = self.multi_load_service
        self.ui.advanced_drawing_processor = self.advanced_drawing_processor
        self.ui.plotting_manager = self.plotting_manager
        self.ui.render_spec_service = self.render_spec_service

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
            param_lock_service=self.param_lock_service,
            render_spec_service=self.render_spec_service
        )
        # Xbox controller (FPS camera for 3D view and shader-driven field)
        self.controller_cam = ControllerCam()
        self.camera.controller_cam = self.controller_cam
        self.joystick_state = {'joystick_id': find_joystick(), 'prev_buttons': []}

        self.command_handler.controller_cam = self.controller_cam
        self.command_handler.plotting_manager = self.plotting_manager

        # OptiX sphere renderer (lazy — created on first use when toggled on)
        self._optix_interface = None

        # Tracer references (for entity buffer and camera access)
        self.ui.tracer_sim = self.sim
        self.ui.tracer_controller_cam = self.controller_cam
        self.ui.tracer_camera = self.camera

        self.sim_runner = SimulationRunner(
            self.sim, self.camera, self.video_service,
            self.command_handler, self.window,
            advanced_drawing_processor=self.advanced_drawing_processor,
            controller_cam=self.controller_cam,
            plotting_manager=self.plotting_manager
        )

        # Frame timing
        self.last_update_time = time.time()
        self.last_orbit_frame_count = 0  # For frame-synced orbit stepping

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

        # Camera movement tracking for realtime tracer accumulation reset
        self._prev_controller_pos = self.controller_cam.pos.copy()
        self._prev_controller_yaw = self.controller_cam.yaw
        self._prev_controller_pitch = self.controller_cam.pitch
        self._prev_camera_position = np.array([0.0, 0.0])
        self._prev_camera_zoom = 1.0

        # Render queue execution state machine
        self.render_queue_executing = False
        self.render_queue_index = 0
        self.render_queue_phase = 'idle'  # idle / loading / start_recording / recording / done
        self.render_queue = []            # list of path strings
        self.render_queue_names = []      # display names (parallel list)

        # Ensure _Default.json exists and load it
        self._ensure_default_config()
        self._load_default_config()
        self.sim.reload()
        self.sim.reset()

    def _ensure_default_config(self):
        """Ensure _Default.json exists in physics_configs directory. Create it if missing."""
        default_path = self.app_configs_dir / "Core/_Default.json"
        if not default_path.exists():
            default_state = SimState()
            zero_rule = np.zeros((10, 12), dtype=np.float32)
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
            glfw.poll_events()
            self.orchestrate_frame()
            glfw.swap_buffers(self.window)

        self.cleanup()

    def orchestrate_frame(self):
        """Main orchestration logic - reads UI state, coordinates components."""

        # 1. Get current UI state
        ui_state = self.ui.get_state()
        tiling_mode = (ui_state.sim.current_view_option == 2)
        self.plotting_manager.enabled = ui_state.preferences.show_plotting_window

        # 2. Process one-shot commands
        result = self.command_handler.process_commands(ui_state, tiling_mode)
        if result == 'screenshot_pending' and not self.screenshot_pending and not self.screenshot_in_progress:
            self.screenshot_pending = True

        # 2.5. Check for render queue execution request
        if ui_state.request_execute_render_queue and not self.render_queue_executing:
            if ui_state.render_queue_paths:
                # Validate all spec paths exist on disk
                from pathlib import Path
                valid_paths = []
                valid_names = []
                for p, n in zip(ui_state.render_queue_paths, ui_state.render_queue_names):
                    if Path(p).exists():
                        valid_paths.append(p)
                        valid_names.append(n)
                    else:
                        print(f"[RenderQueue] Spec not found, skipping: {p}")
                if valid_paths:
                    # Save preferences before execution (in case app auto-closes)
                    self.command_handler._sync_tracer_to_preferences(ui_state)
                    save_preferences(ui_state.preferences)
                    self.render_queue_executing = True
                    self.render_queue_index = 0
                    self.render_queue_phase = 'loading'
                    self.render_queue = valid_paths
                    self.render_queue_names = valid_names
                    print(f"[RenderQueue] Starting batch render of {len(self.render_queue)} specs")
                else:
                    print("[RenderQueue] No valid specs to render")

        # 2.5.1. Check for render queue cancel request
        if ui_state.request_cancel_render_queue and self.render_queue_executing:
            if self.video_service.is_active():
                self.video_service.stop()
            self.render_queue_executing = False
            self.render_queue_phase = 'idle'
            ui_state.sim.going = False
            print("[RenderQueue] Batch render cancelled")

        # 2.6. Advance render pipeline state machine
        if self.render_queue_executing:
            self._advance_render_pipeline(ui_state)

        # 3. Process continuous input (camera movement)
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        process_camera_input(ui_state, self.window, self.ui.keybindings,
                             self.sim.view_tex, dt, controller_cam=self.controller_cam)
        process_controller_input(self.controller_cam, self.joystick_state, dt,
                                 move_speed=ui_state.camera.move_speed,
                                 rotate_speed=ui_state.camera.rotate_speed)

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
        tracer_video_active = is_recording and ui_state.preferences.tracer_mode

        if is_recording and not self.was_recording:
            self.user_speedmult = ui_state.preferences.speedmult
            self.user_motion_blur = ui_state.preferences.motion_blur
            self.user_blur_quality = ui_state.preferences.blur_quality
            # Initialize tracer video state when starting a tracer-mode recording
            if tracer_video_active:
                self.sim_runner.init_tracer_video_state()
                # Ensure TracerInterface is created
                if self.ui._tracer_interface is None:
                    from tracer_interface import TracerInterface
                    self.ui._tracer_interface = TracerInterface(self.ctx)
                    self.ui._apply_tracer_preferences(self.ui._tracer_interface)
                # Sync DOF from camera state
                self.ui._tracer_interface.aperture = ui_state.camera.aperture
                self.ui._tracer_interface.focal_plane_depth = ui_state.camera.focal_plane_depth
        elif not is_recording and self.was_recording:
            ui_state.preferences.speedmult = self.user_speedmult
            ui_state.preferences.motion_blur = self.user_motion_blur
            ui_state.preferences.blur_quality = self.user_blur_quality
            # Pause simulation when recording ended by reaching max_frames
            if self.video_service.finished_naturally():
                if self.render_queue_executing:
                    # Batch render mode: advance to next spec instead of pausing
                    self._on_render_spec_complete()
                else:
                    ui_state.sim.going = False

        if is_recording:
            if tracer_video_active:
                # Tracer mode: physics steps are managed by run_tracer_video_frame
                ui_state.preferences.speedmult = 1
                ui_state.preferences.motion_blur = False
            else:
                ui_state.preferences.speedmult = ui_state.preferences.motion_blur_samples
                ui_state.preferences.motion_blur = ui_state.preferences.recording_motion_blur
                ui_state.preferences.blur_quality = ui_state.preferences.recording_blur_quality

        self.was_recording = is_recording

        # 5. Apply state to components
        if ui_state.request_camera_reset:
            ui_state.camera.position[:] = [0.0, 0.0]
            ui_state.camera.zoom = 1.0
            if ui_state.camera.render_3d:
                self.controller_cam.reset()
                ui_state.camera.orbit_angle = 0.0
                ui_state.camera.orbit_pitch = 0.0
                ui_state.camera.orbit_center[:] = [0.0, 0.0, 0.0]
                reposition_orbit_camera(self.controller_cam, ui_state.camera)
        self.controller_cam.fov = ui_state.camera.fov
        self.sim.apply_state(ui_state.sim)
        self.sim.apply_camera_state(ui_state.camera)
        self.camera.apply_state(ui_state.camera)
        self.multi_load_service.apply_state(ui_state.multi_load)
        self.camera.BRIGHTNESS = ui_state.preferences.brightness

        # OptiX interface lifecycle: lazy creation when toggled on
        if ui_state.camera.optix_enabled and self._optix_interface is None:
            try:
                from optix_interface import OptiXInterface
                if OptiXInterface.is_available():
                    self._optix_interface = OptiXInterface(self.ctx)
                    print("OptiX sphere renderer initialized")
                else:
                    ui_state.camera.optix_enabled = False
                    print("OptiX not available — disabling")
            except Exception as e:
                ui_state.camera.optix_enabled = False
                print(f"OptiX init failed: {e}")

        # Sync OptiX settings from preferences
        if self._optix_interface is not None:
            # Check for per-frame error recovery (auto-disable on crash)
            if self._optix_interface.failed:
                print(f"OptiX auto-disabled: {self._optix_interface.fail_reason}")
                self._optix_interface = None
                ui_state.camera.optix_enabled = False
            else:
                self._optix_interface.gas_rebuild_interval = ui_state.preferences.three_d_optix_gas_rebuild_interval
                self._optix_interface.radius_scale = ui_state.preferences.three_d_optix_sphere_radius_scale
                self._optix_interface.light_dir = tuple(ui_state.preferences.three_d_optix_light_direction)
                self._optix_interface.light_color = tuple(ui_state.preferences.three_d_optix_light_color)
                self._optix_interface.light_intensity = ui_state.preferences.three_d_optix_light_intensity
                self._optix_interface.shadows_enabled = ui_state.preferences.three_d_optix_shadows_enabled
                self._optix_interface.ambient = ui_state.preferences.three_d_optix_ambient
                self._optix_interface.sky_color_top = tuple(ui_state.preferences.three_d_optix_sky_color_top)
                self._optix_interface.sky_color_bottom = tuple(ui_state.preferences.three_d_optix_sky_color_bottom)
                # Copy timing for UI display
                ui_state.camera.optix_gas_time_ms = self._optix_interface.gas_time_ms
                ui_state.camera.optix_render_time_ms = self._optix_interface.render_time_ms
        self.camera.optix_interface = self._optix_interface

        # Sync tracer SDF toggle to preferences for 3D preview
        ti = self.ui._tracer_interface
        if ti is not None:
            ui_state.preferences.tracer_sdf_enabled = ti.sdf_enabled

        # 5.0.1 Force/Strafe field view modes: override view_tex with field texture
        if ui_state.sim.current_view_option in (3, 4):
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
        if self.prev_view_option == 2 and ui_state.sim.current_view_option != 2:
            ui_state.camera.position[0] = np.fmod(ui_state.camera.position[0] + 100.0, 2.0) - 1.0
            ui_state.camera.position[1] = np.fmod(ui_state.camera.position[1] + 100.0, 2.0) - 1.0
        self.prev_view_option = ui_state.sim.current_view_option

        # 6. Run simulation if going
        ti = self.ui._tracer_interface
        rt_active = ti is not None and ti.realtime_mode > 0 and not is_recording

        if tracer_video_active and ui_state.sim.going:
            # Tracer video mode: progressive path tracing with interleaved physics
            tracer_frame = self.sim_runner.run_tracer_video_frame(
                ui_state, self.ui._tracer_interface, tiling_mode=tiling_mode
            )
            if tracer_frame is not None:
                # A complete output frame is ready — send to video recorder
                self.video_service.process_frame(
                    self.ctx,
                    tracer_frame,
                    ui_state.preferences.max_frames,
                    ui_state.preferences.supersample_k,
                    ui_state.preferences.filename_prefix
                )
        elif ui_state.sim.going:
            self.sim_runner.run_simulation_frame(
                ui_state, sweep_mode, sweep_reticle_pos, sweep_reticle_visible,
                screen_aspect, ui_state.sim.watercolor_mode,
                tiling_mode=tiling_mode,
                screenshot_in_progress=self.screenshot_in_progress,
                skip_view_generation=rt_active
            )

        # 6.2. Frame-synced orbit stepping (deterministic with physics)
        steps = self.sim.frame_count - self.last_orbit_frame_count
        self.last_orbit_frame_count = self.sim.frame_count
        orbit_rate = ui_state.camera.orbit_rate
        if abs(orbit_rate) > 1e-6 and steps > 0:
            ui_state.camera.orbit_angle += orbit_rate * steps
            reposition_orbit_camera(self.controller_cam, ui_state.camera)

        # 6.3. Realtime tracer mode (runs every frame, even when sim is paused)
        if rt_active:
            # In Accumulate mode, reset on camera move or joystick select
            if ti.realtime_mode == 2:
                if self._camera_moved() or self.joystick_state.get('select_pressed', False):
                    ti.reset_realtime_accumulation()

            entity_buffer = self.sim.get_entity_buffer()
            entity_count = self.sim.entity_count
            cam = self.controller_cam
            width, height = glfw.get_framebuffer_size(self.window)
            scale = max(0.1, ti.resolution_scale)
            rt_width = max(1, int(width * scale))
            rt_height = max(1, int(height * scale))
            view_proj = self.camera.compute_fps_view_proj(
                cam.pos, cam.dir, cam.up, cam.fov, (width / max(height, 1))
            )
            cam_right, cam_up = self.camera.compute_fps_camera_basis(
                cam.dir, cam.up
            )
            ti.aperture = ui_state.camera.aperture
            ti.focal_plane_depth = ui_state.camera.focal_plane_depth
            ti.realtime_tick(entity_buffer, entity_count, view_proj,
                             rt_width, rt_height,
                             sim_going=ui_state.sim.going,
                             camera_right=cam_right, camera_up=cam_up)

        # 6.5. Screenshot save and settings restoration
        if self.screenshot_in_progress:
            self._save_screenshot(ui_state)

        # 7. Render camera view
        self._render_camera_view(ui_state, sweep_mode, sweep_reticle_pos,
                                  sweep_reticle_visible, screen_aspect, tiling_mode,
                                  rt_active=rt_active)

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

        # 7.9. Snapshot camera for next-frame movement detection
        self._snapshot_camera()

        # 8. Update UI display info and render
        self.ui.update_display_info({
            'time': self.sim.time,
            'frame_count': self.sim.frame_count,
            'tex_size': self.sim.view_tex.size,
            'recording_active': self.video_service.is_active(),
            'video_pending': cmd.video_pending,
            'video_scheduled_start_frame': cmd.video_scheduled_start_frame,
            'render_queue_executing': self.render_queue_executing,
            'render_queue_index': self.render_queue_index,
            'render_queue_total': len(self.render_queue),
            'render_queue_phase': self.render_queue_phase,
            'render_queue_current_name': self.render_queue_names[self.render_queue_index] if self.render_queue_executing and self.render_queue_index < len(self.render_queue_names) else '',
            'video_current_frame': self.video_service.current_frame,
            'video_max_frames': ui_state.preferences.max_frames,
        })
        self.ui.render()

    def _camera_moved(self):
        """Check if the camera has moved since last frame (3D or 2D)."""
        cam = self.controller_cam
        pos_changed = not np.allclose(cam.pos, self._prev_controller_pos, atol=1e-6)
        yaw_changed = abs(cam.yaw - self._prev_controller_yaw) > 1e-6
        pitch_changed = abs(cam.pitch - self._prev_controller_pitch) > 1e-6
        pos_2d_changed = not np.allclose(
            self.ui.state.camera.position, self._prev_camera_position, atol=1e-6)
        zoom_changed = abs(self.ui.state.camera.zoom - self._prev_camera_zoom) > 1e-6
        return pos_changed or yaw_changed or pitch_changed or pos_2d_changed or zoom_changed

    def _snapshot_camera(self):
        """Snapshot current camera state for next-frame comparison."""
        self._prev_controller_pos = self.controller_cam.pos.copy()
        self._prev_controller_yaw = self.controller_cam.yaw
        self._prev_controller_pitch = self.controller_cam.pitch
        self._prev_camera_position = self.ui.state.camera.position.copy()
        self._prev_camera_zoom = self.ui.state.camera.zoom

    def _render_camera_view(self, ui_state, sweep_mode, sweep_reticle_pos,
                             sweep_reticle_visible, screen_aspect, tiling_mode,
                             rt_active=False):
        """Render the camera view to screen."""
        # Realtime tracer mode: render path-traced image fullscreen
        ti = self.ui._tracer_interface
        if rt_active and ti is not None and ti.display_texture is not None:
            self.ctx.screen.use()
            width, height = glfw.get_framebuffer_size(self.window)
            self.ctx.viewport = (0, 0, width, height)
            self.ctx.clear(0.0, 0.0, 0.0, 1.0)
            self.camera.program['cam_pos'].value = (0, 0)
            self.camera.program['cam_zoom'].value = 1.0
            self.camera.program['tex_size'].value = (float(width), float(height))
            self.camera.program['window_size'].value = (width, height)
            ti.display_texture.use(location=0)
            self.camera.program['view_tex'].value = 0
            self.camera.vao.render()
            return

        draw_trail_mode = ui_state.preferences.mouse_mode == "Draw Trail"

        width, height = glfw.get_framebuffer_size(self.window)
        mouse_x_norm = ui_state.mouse_pos[0] / width if width > 0 else 0.5
        mouse_y_norm = ui_state.mouse_pos[1] / height if height > 0 else 0.5
        mouse_screen_coords = (mouse_x_norm, mouse_y_norm)

        # SDF preview params
        sdf_enabled = False
        inv_view_proj = None
        sdf_sun_dir = (0.577, 0.577, 0.577)
        sdf_sun_color = (3.0, 3.0, 3.0)
        sdf_sky_color = (0.5, 0.7, 1.0)
        if ui_state.camera.render_3d:
            sdf_enabled = ui_state.preferences.tracer_sdf_enabled
            if sdf_enabled:
                cam = self.controller_cam
                aspect = width / max(height, 1)
                view_proj = self.camera.compute_fps_view_proj(
                    cam.pos, cam.dir, cam.up, cam.fov, aspect
                )
                inv_view_proj = np.linalg.inv(
                    view_proj.astype(np.float64)
                ).astype(np.float32)
                p = ui_state.preferences
                sun_d = np.array(p.tracer_sun_direction, dtype=np.float64)
                sun_len = max(np.linalg.norm(sun_d), 1e-8)
                sdf_sun_dir = tuple((sun_d / sun_len).astype(np.float32))
                sc = p.tracer_sun_color
                si = p.tracer_sun_intensity
                sdf_sun_color = (sc[0] * si, sc[1] * si, sc[2] * si)
                skc = p.tracer_sky_color
                ski = p.tracer_sky_intensity
                sdf_sky_color = (skc[0] * ski, skc[1] * ski, skc[2] * ski)

        self.camera.render(
            sim_going=ui_state.sim.going,
            current_view_option=ui_state.sim.current_view_option,
            sweep_mode=sweep_mode,
            sweep_reticle_pos=sweep_reticle_pos,
            sweep_reticle_visible=sweep_reticle_visible,
            screen_aspect=screen_aspect,
            watercolor_mode=ui_state.sim.watercolor_mode,
            ink_weight=ui_state.sim.ink_weight,
            draw_trail_mode=draw_trail_mode,
            draw_size=ui_state.preferences.draw_size,
            mouse_screen_coords=mouse_screen_coords,
            exposure=ui_state.preferences.exposure,
            tiling_mode=tiling_mode,
            tonemap_softness=ui_state.preferences.tonemap_softness,
            bloom_enabled=ui_state.preferences.bloom_enabled,
            bloom_threshold=ui_state.preferences.bloom_threshold,
            bloom_intensity=ui_state.preferences.bloom_intensity,
            bloom_radius=ui_state.preferences.bloom_radius,
            sdf_enabled=sdf_enabled,
            inv_view_proj=inv_view_proj,
            sdf_sun_dir=sdf_sun_dir,
            sdf_sun_color=sdf_sun_color,
            sdf_sky_color=sdf_sky_color
        )

    def _save_screenshot(self, ui_state):
        """Save screenshot and restore settings."""
        if self.camera.assembled_texture is not None:
            from utilities.save_frame_gpu import save_frame_gpu
            import datetime
            import os
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = ui_state.preferences.filename_prefix or "screenshot"
            flip_y = not ui_state.camera.render_3d
            filename = save_frame_gpu(
                self.camera.assembled_texture,
                self.ctx,
                supersample_k=ui_state.preferences.supersample_k,
                return_array=False,
                flip_y=flip_y
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

    def _advance_render_pipeline(self, ui_state):
        """State machine for sequential batch rendering.

        Called every frame from orchestrate_frame() when render_queue_executing is True.
        Phases: loading -> start_recording -> recording -> (next spec or done)
        """
        phase = self.render_queue_phase

        if phase == 'loading':
            from pathlib import Path
            idx = self.render_queue_index
            dir_path = Path(self.render_queue[idx])
            display_name = self.render_queue_names[idx]

            print(f"[RenderQueue] Loading spec {idx + 1}/{len(self.render_queue)}: {display_name}")

            spec = self.render_spec_service.load_metadata(dir_path)
            if spec is None:
                print(f"[RenderQueue] Failed to load metadata for {display_name}, skipping")
                self._render_queue_advance_or_finish()
                return

            gpu_buffers = self.render_spec_service.load_gpu_buffers(dir_path)
            if gpu_buffers is None:
                print(f"[RenderQueue] Failed to load GPU buffers for {display_name}, skipping")
                self._render_queue_advance_or_finish()
                return

            self.render_spec_service.apply_state(
                spec, gpu_buffers,
                self.sim, self.camera, self.controller_cam, ui_state,
                self.config_saver, self.rule_manager,
                self.field_handler.adv_draw if self.field_handler else None
            )

            # Re-sync tracer interface if it exists
            if self.ui._tracer_interface is not None:
                self.ui._apply_tracer_preferences(self.ui._tracer_interface)

            # Set filename_prefix so VidSaver uses the display name
            ui_state.preferences.filename_prefix = display_name

            # Unpause simulation (recording requires going = True)
            ui_state.sim.going = True

            self.render_queue_phase = 'start_recording'

        elif phase == 'start_recording':
            # GPU state has settled for one frame. Start recording.
            ui_state.sim.going = True
            self.video_service.start()
            self.render_queue_phase = 'recording'
            display_name = self.render_queue_names[self.render_queue_index]
            print(f"[RenderQueue] Recording started for: {display_name}")

        elif phase == 'recording':
            # Normal frame execution handles physics + recording.
            # Completion detected by the modified recording lifecycle block.
            pass

        elif phase == 'done':
            print(f"[RenderQueue] All {len(self.render_queue)} renders complete. Closing app.")
            if self.ui._shutdown_after_render_queue:
                import os
                print("[RenderQueue] PC shutdown scheduled in 60 seconds (cancel with 'shutdown /a')")
                os.system('shutdown /s /t 60')
            self.render_queue_executing = False
            glfw.set_window_should_close(self.window, True)

    def _on_render_spec_complete(self):
        """Called when a recording finishes naturally during batch execution."""
        idx = self.render_queue_index
        display_name = self.render_queue_names[idx]
        print(f"[RenderQueue] Recording complete for: {display_name} ({idx + 1}/{len(self.render_queue)})")
        self._render_queue_advance_or_finish()

    def _render_queue_advance_or_finish(self):
        """Move to the next spec in the queue, or finish if all done."""
        self.render_queue_index += 1
        if self.render_queue_index < len(self.render_queue):
            self.render_queue_phase = 'loading'
        else:
            self.render_queue_phase = 'done'

    def cleanup(self):
        # Save preferences before cleanup
        ui_state = self.ui.get_state()

        # Sync 3D camera settings into preferences
        cam = ui_state.camera
        ui_state.preferences.three_d_render_3d = cam.render_3d
        ui_state.preferences.three_d_fov = cam.fov
        ui_state.preferences.three_d_aperture = cam.aperture
        ui_state.preferences.three_d_focal_plane_depth = cam.focal_plane_depth
        ui_state.preferences.three_d_move_speed = cam.move_speed
        ui_state.preferences.three_d_rotate_speed = cam.rotate_speed
        ui_state.preferences.three_d_orbit_center = list(cam.orbit_center)
        ui_state.preferences.three_d_orbit_rate = cam.orbit_rate
        ui_state.preferences.three_d_optix_enabled = cam.optix_enabled

        # Sync tracer settings into preferences
        ti = self.ui._tracer_interface
        if ti is not None:
            ui_state.preferences.tracer_sdf_enabled = ti.sdf_enabled
            ui_state.preferences.tracer_colored_extinction = ti.colored_extinction
            ui_state.preferences.tracer_extinction_rgb = list(ti.extinction_rgb)
            ui_state.preferences.tracer_albedo_saturation = ti.albedo_saturation
            ui_state.preferences.tracer_albedo_brightness = ti.albedo_brightness
            ui_state.preferences.tracer_density_scale = ti.density_scale
            ui_state.preferences.tracer_hg_g = ti.hg_g
            ui_state.preferences.tracer_emission_strength = ti.emission_strength
            ui_state.preferences.tracer_sun_direction = list(ti.sun_direction)
            ui_state.preferences.tracer_sun_color = list(ti.sun_color)
            ui_state.preferences.tracer_sun_intensity = ti.sun_intensity
            ui_state.preferences.tracer_sky_color = list(ti.sky_color)
            ui_state.preferences.tracer_sky_intensity = ti.sky_intensity
            ui_state.preferences.tracer_num_samples = ti.num_samples
            ui_state.preferences.tracer_exposure = ti.exposure
            ui_state.preferences.tracer_realtime_mode = ti.realtime_mode
            ui_state.preferences.tracer_max_bounces = ti.max_bounces
            ui_state.preferences.tracer_firefly_clamp = ti.firefly_clamp
            ui_state.preferences.tracer_firefly_clamp_max = ti.firefly_clamp_max
            ui_state.preferences.tracer_resolution_scale = ti.resolution_scale
            ui_state.preferences.tracer_density_resolution_log2 = ti.density_resolution_log2
            ui_state.preferences.tracer_color_resolution_log2 = ti.color_resolution_log2
            ui_state.preferences.tracer_majorant_resolution_log2 = ti.majorant_resolution_log2
            ui_state.preferences.tracer_sun_sampling = ti.sun_sampling
            ui_state.preferences.tracer_photosphere = ti.photosphere

        save_preferences(ui_state.preferences)

        if self._optix_interface is not None:
            self._optix_interface.cleanup()
            self._optix_interface = None
        self.advanced_drawing_processor.cleanup()
        self.video_service.cleanup()
        self.ui.cleanup()
        glfw.terminate()


if __name__ == "__main__":
    app = App()
    app.run()
