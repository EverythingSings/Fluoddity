import glfw
import moderngl
import time
import numpy as np
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import RuleManager, EntityPicker, VideoRecorderService, ConfigSaver, ArrowDebugService, RenderSpecService, PlottingManager
from parameter_locks import ParameterLockService
from utilities.paths import initialize_user_data, get_user_physics_configs_dir, get_app_physics_configs_dir, get_screenshots_dir
from state import load_preferences, save_preferences, SimState
from command_handler import CommandHandler
from simulation_runner import SimulationRunner
from camera_input import process_camera_input, reposition_orbit_camera
from controller_input import ControllerCam, process_controller_input, find_joystick
from rendering import RendererHost
from viewer import Viewer
from controllers import RecordingController, BatchRenderController


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

        # Load preferences first to get entity_count / canvas_resolution
        loaded_prefs = load_preferences()

        # Xbox controller (FPS camera for 3D view + shader-driven field). Built
        # first — it has no dependencies — so it can be constructor-injected into
        # Camera, UI, and CommandHandler below.
        self.controller_cam = ControllerCam()
        self.joystick_state = {'joystick_id': find_joystick(), 'prev_buttons': []}

        # Simulation + camera.
        self.sim = Sim(self.ctx,
                       entity_count=loaded_prefs.rendering.entity_count,
                       canvas_resolution=loaded_prefs.rendering.canvas_resolution)
        self.camera = Camera(self.ctx, self.sim, self.window,
                             controller_cam=self.controller_cam)

        # Services UI depends on — built before UI so they can be injected.
        self.rule_manager = RuleManager()
        entity_stride = SIZE_OF_ENTITY_STRUCT // 4
        self.entity_picker = EntityPicker(self.sim.get_entity_buffer(), entity_stride)
        self.video_service = VideoRecorderService()
        self.config_saver = ConfigSaver()
        self.arrow_debug_service = ArrowDebugService(self.ctx)
        self.plotting_manager = PlottingManager(self.ctx)
        self.render_spec_service = RenderSpecService()
        self.param_lock_service = ParameterLockService()

        # Viewer: the always-displayed "Viewer" ImGui window that shows the
        # active renderer's finished frame and composites display-only overlays.
        # Single display sink (parallel to the video recorder's file sink).
        self.viewer = Viewer(self.ctx, self.window)

        # UI — all cross-component dependencies injected via constructor.
        self.ui = UI(self.window, self.ctx,
                     param_lock_service=self.param_lock_service,
                     plotting_manager=self.plotting_manager,
                     render_spec_service=self.render_spec_service,
                     viewer=self.viewer,
                     tracer_sim=self.sim,
                     tracer_controller_cam=self.controller_cam,
                     tracer_camera=self.camera)

        # Apply loaded preferences to UI
        self.ui.state.preferences = loaded_prefs
        self.ui._last_applied_entity_count = loaded_prefs.rendering.entity_count
        self.ui._last_applied_canvas_resolution = loaded_prefs.rendering.canvas_resolution

        # Restore 3D camera settings from preferences
        cam = self.ui.state.camera
        cam.fov = loaded_prefs.camera3d.fov
        cam.aperture = loaded_prefs.camera3d.aperture
        cam.focal_plane_depth = loaded_prefs.camera3d.focal_plane_depth
        cam.move_speed = loaded_prefs.camera3d.move_speed
        cam.rotate_speed = loaded_prefs.camera3d.rotate_speed
        cam.orbit_center[:] = loaded_prefs.camera3d.orbit_center
        cam.orbit_rate = loaded_prefs.camera3d.orbit_rate
        # OptiX active is derived each frame from the renderer dropdown.
        cam.optix_enabled = (loaded_prefs.rendering.renderer == 1)

        # Physics configs directories
        self.app_configs_dir = get_app_physics_configs_dir()
        self.user_configs_dir = get_user_physics_configs_dir()
        self.user_configs_dir.mkdir(exist_ok=True)

        # Recording controller: owns the video-recording state machine
        # (idle -> pending -> recording -> finished), including video-strategy
        # build, speedmult/motion-blur override + restore, and its RecordingState.
        self.recording_controller = RecordingController(
            self.video_service, self.camera, self.ui, self.sim)

        self.command_handler = CommandHandler(
            self.sim, self.camera, self.ui, self.rule_manager,
            self.entity_picker, self.video_service, self.config_saver,
            self.user_configs_dir,
            param_lock_service=self.param_lock_service,
            render_spec_service=self.render_spec_service,
            recording_controller=self.recording_controller,
            controller_cam=self.controller_cam,
            plotting_manager=self.plotting_manager
        )

        # Renderer host: owns the OptiX path tracer's lifecycle (lazy creation,
        # VRAM release, error recovery, prefs sync, preview). The path tracer is
        # the single OptiX renderer; rt_mode 0 (rasterize) is a preset on it.
        # `self._pathtracer_interface` is a property aliasing `renderer_host.optix`.
        self.renderer_host = RendererHost(self.ctx)

        self.sim_runner = SimulationRunner(
            self.sim, self.camera, self.video_service,
            self.command_handler, self.window,
            controller_cam=self.controller_cam,
            plotting_manager=self.plotting_manager
        )

        # Batch-render controller: owns the render-queue state machine
        # (loading -> start_recording -> recording -> done).
        self.batch_render_controller = BatchRenderController(
            self.render_spec_service, self.video_service, self.sim, self.camera,
            self.config_saver, self.rule_manager, self.entity_picker, self.ui,
            self.window)

        # Frame timing
        self.last_update_time = time.time()
        self.last_orbit_frame_count = 0  # For frame-synced orbit stepping

        # Screenshot state machine
        self.screenshot_pending = False
        self.screenshot_in_progress = False
        self.screenshot_saved_settings = {}

        # Camera movement tracking for realtime tracer accumulation reset
        self._prev_controller_pos = self.controller_cam.pos.copy()
        self._prev_controller_yaw = self.controller_cam.yaw
        self._prev_controller_pitch = self.controller_cam.pitch
        self._prev_camera_position = np.array([0.0, 0.0])
        self._prev_camera_zoom = 1.0

        # Physics step tracking for GAS rebuild scheduling
        self._prev_sim_frame_count = 0

        # Ensure _Default.json exists and load it
        self._ensure_default_config()
        self._load_default_config()
        self.sim.reload()
        self.sim.reset()

    @property
    def _pathtracer_interface(self):
        """The active OptiX path tracer interface (or None).

        Backed by ``renderer_host.optix`` so the host owns the single instance
        while existing call sites keep using this name.
        """
        return self.renderer_host.optix

    @_pathtracer_interface.setter
    def _pathtracer_interface(self, value):
        self.renderer_host.optix = value

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
        self.plotting_manager.enabled = ui_state.preferences.ui_windows.show_plotting_window

        # Derive the transient "OptiX active" flag from the renderer dropdown.
        # (The RendererHost may clear it back to False if OptiX fails to init,
        # falling back to the OpenGL path for this frame.)
        ui_state.camera.optix_enabled = (ui_state.preferences.rendering.renderer == 1)

        # 1.5. Poll gamepad and inject one-shot flags before command processing
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        process_controller_input(self.controller_cam, self.joystick_state, dt,
                                 move_speed=ui_state.camera.move_speed,
                                 rotate_speed=ui_state.camera.rotate_speed)
        # Gamepad face buttons
        if self.joystick_state.get('cycle_rt_mode_pressed', False):
            ui_state.preferences.optix.rt_mode = (ui_state.preferences.optix.rt_mode + 1) % 3
        if self.joystick_state.get('toggle_pause_pressed', False):
            ui_state.sim.going = not ui_state.sim.going
        if self.joystick_state.get('reset_pressed', False):
            ui_state.request_reset = True
        if self.joystick_state.get('randomize_mutations_pressed', False):
            ui_state.request_randomize_mutations = True

        # 2. Process one-shot commands
        result = self.command_handler.process_commands(ui_state)
        if result == 'screenshot_pending' and not self.screenshot_pending and not self.screenshot_in_progress:
            self.screenshot_pending = True

        # Force full GAS rebuild after sim reset or config change.
        # (The RendererHost applies this to the OptiX interface in update().)
        needs_gas_rebuild = (
            ui_state.request_reset
            or ui_state.request_full_reset
            or self.command_handler.config_applied_this_frame
        )

        # 2.5. Handle render-queue execute / cancel requests
        def _save_prefs_before_batch(us):
            self.command_handler._sync_tracer_to_preferences(us)
            save_preferences(us.preferences)
        self.batch_render_controller.handle_requests(
            ui_state, on_before_execute=_save_prefs_before_batch)

        # 2.6. Advance render pipeline state machine
        if self.batch_render_controller.executing:
            self.batch_render_controller.advance(ui_state)

        # 3. Process continuous input (camera movement)
        process_camera_input(ui_state, self.window, self.ui.keybindings,
                             self.sim.view_tex, dt, controller_cam=self.controller_cam)

        # 3.2. Check if pending video should start
        self.recording_controller.check_pending_start(ui_state)

        # 3.5. Screenshot state machine
        if self.screenshot_pending and not self.screenshot_in_progress:
            self.screenshot_pending = False
            self.screenshot_in_progress = True
            self.screenshot_saved_settings = {
                'speedmult': ui_state.preferences.rendering.speedmult,
                'blur_quality': ui_state.preferences.rendering.blur_quality,
                'motion_blur': ui_state.preferences.rendering.motion_blur,
                'going': ui_state.sim.going,
            }
            ui_state.preferences.rendering.speedmult = ui_state.preferences.recording.motion_blur_samples
            ui_state.preferences.rendering.blur_quality = 1
            ui_state.preferences.rendering.motion_blur = True
            if not ui_state.sim.going:
                ui_state.sim.going = True

        # 4. Advance the recording state machine: lock physics frequency to the
        # video recorder while recording, build/drop the renderer video strategy,
        # and restore user settings afterward. On a natural (max-frames) finish,
        # advance the batch render if one is running, else pause the sim.
        def _on_recording_finished(us):
            if self.batch_render_controller.executing:
                self.batch_render_controller.on_recording_complete()
            else:
                us.sim.going = False

        rec = self.recording_controller.update(
            ui_state,
            pathtracer_interface=self._pathtracer_interface,
            sim_runner=self.sim_runner,
            on_finished_naturally=_on_recording_finished,
        )
        is_recording = rec.is_recording
        tracer_video_active = rec.tracer_video_active
        optix_pt_video_active = rec.optix_pt_video_active
        active_video_strategy = rec.active_video_strategy

        # 5. Apply state to components
        if ui_state.request_camera_reset:
            ui_state.camera.position[:] = [0.0, 0.0]
            ui_state.camera.zoom = 1.0
            self.controller_cam.reset()
            ui_state.camera.orbit_angle = 0.0
            ui_state.camera.orbit_pitch = 0.0
            ui_state.camera.orbit_center[:] = [0.0, 0.0, 0.0]
            reposition_orbit_camera(self.controller_cam, ui_state.camera)
        self.controller_cam.fov = ui_state.camera.fov
        self.sim.apply_state(ui_state.sim)
        self.sim.apply_camera_state(ui_state.camera)
        self.camera.apply_state(ui_state.camera)
        self.camera.BRIGHTNESS = ui_state.preferences.rendering.brightness

        # OptiX renderer lifecycle — owned by the RendererHost. The path tracer
        # is the single OptiX renderer; rt_mode 0 (rasterize) is a preset on it.
        rt_mode = ui_state.preferences.optix.rt_mode
        pt_active = self.renderer_host.update(
            ui_state,
            is_recording=is_recording,
            needs_gas_rebuild=needs_gas_rebuild,
            camera_moved=self._camera_moved(),
        )

        # Expose path tracer to UI for preview progress display
        self.ui._pathtracer_interface = self._pathtracer_interface

        # Handle OptiX preview request (one-shot flag from UI)
        if getattr(self.ui, '_request_optix_preview', False):
            self.ui._request_optix_preview = False
            pt = self.renderer_host.ensure_optix_for_preview(ui_state)
            self.ui._pathtracer_interface = pt
            if pt is not None:
                # Sync settings before starting preview
                self.renderer_host.sync_optix_prefs(ui_state)

                cam = self.controller_cam
                width_px, height_px = glfw.get_framebuffer_size(self.window)
                scale = max(0.1, ui_state.preferences.optix.resolution_scale)
                width_px = max(1, int(width_px * scale))
                height_px = max(1, int(height_px * scale))
                entity_buffer = self.sim.get_entity_buffer()
                entity_count = self.sim.entity_count
                pt.start_preview(
                    target_spp=ui_state.preferences.optix.rt_preview_spp,
                    entity_buffer=entity_buffer,
                    entity_count=entity_count,
                    cam_pos=cam.pos,
                    cam_dir=cam.dir,
                    cam_up=cam.up,
                    fov=cam.fov,
                    width=width_px,
                    height=height_px,
                )

        # Tick active preview (traces 1 sample per app frame)
        if (self._pathtracer_interface is not None
                and self._pathtracer_interface.preview_active):
            self._pathtracer_interface.tick_preview()

        # Route the single OptiX renderer to the camera
        self.camera.optix_interface = self._pathtracer_interface if pt_active else None
        self.camera.optix_resolution_scale = ui_state.preferences.optix.resolution_scale

        # Sync tracer SDF toggle to preferences for 3D preview
        ti = self.ui._tracer_interface
        if ti is not None:
            ui_state.preferences.tracer.sdf_enabled = ti.sdf_enabled
            # Push the SHARED lighting each frame so the volumetric tracer stays
            # in sync with edits made from either renderer's controls.
            lit = ui_state.preferences.lighting
            ti.sun_direction = list(lit.light_direction)
            ti.sun_color = list(lit.light_color)
            ti.sun_intensity = lit.light_intensity
            ti.sky_color_top = list(lit.sky_color_top)
            ti.sky_color_bottom = list(lit.sky_color_bottom)
            ti.sky_intensity = lit.sky_intensity
            ti.sun_sampling = lit.nee
            ti.photosphere = lit.photosphere

        # 5.2. Sync parameter lock master toggle
        self.param_lock_service.enabled = ui_state.preferences.parameter_locks.enabled

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

        # 6. Run simulation if going. The realtime volumetric tracer only drives
        # the display for the OpenGL renderer (Optix uses the path tracer).
        ti = self.ui._tracer_interface
        opengl_renderer = ui_state.preferences.rendering.renderer == 0
        rt_active = (ti is not None and ti.realtime_mode > 0
                     and opengl_renderer and not is_recording)

        # OptiX preview owns the path tracer while accumulating/displaying, so
        # the normal per-frame OptiX render must be skipped (it would reset the
        # preview's accumulation). The preview is shown fullscreen in
        # _render_camera_view instead.
        pt_preview = self._pathtracer_interface
        optix_preview_display = (
            pt_preview is not None
            and (pt_preview.preview_active or pt_preview.preview_has_result)
            and ui_state.preferences.optix.rt_mode == 0
            and not is_recording
        )

        if tracer_video_active and ui_state.sim.going:
            # Tracer video mode: progressive path tracing with interleaved physics
            if active_video_strategy is None:
                active_video_strategy = self.sim_runner.make_tracer_video_strategy(
                    self.ui._tracer_interface)
                self.recording_controller.active_video_strategy = active_video_strategy
            tracer_frame = active_video_strategy.run_frame(ui_state)
            if tracer_frame is not None:
                # A complete output frame is ready. Display it (the most recent
                # completed frame, matching OptiX-video behavior) AND send it to
                # the recorder. camera.render() returns assembled_texture while
                # sim_going, so this also avoids a wasted GL-points render.
                self.camera.assembled_texture = tracer_frame
                self.video_service.process_frame(
                    self.ctx,
                    tracer_frame,
                    ui_state.preferences.recording.max_frames,
                    ui_state.preferences.recording.supersample_k,
                    ui_state.preferences.recording.filename_prefix,
                    flip_y=False  # natural orientation (matches OptiX video)
                )
        elif optix_pt_video_active and ui_state.sim.going:
            # OptiX path tracer video mode: offline rendering with motion blur
            if active_video_strategy is None:
                active_video_strategy = self.sim_runner.make_optix_pt_video_strategy(
                    self._pathtracer_interface)
                self.recording_controller.active_video_strategy = active_video_strategy
            pt_frame_hdr = active_video_strategy.run_frame(ui_state)
            if pt_frame_hdr is not None:
                # Tonemap HDR frame through the image pipeline
                pt_frame = self.camera.image_pipeline.assemble_frame(
                    pt_frame_hdr,
                    total_samples=1,
                    current_sample_index=0,
                    brightness=ui_state.preferences.rendering.brightness,
                    tonemap_softness=ui_state.preferences.rendering.tonemap_softness,
                )
                if pt_frame is not None:
                    # Display the completed frame in the camera view
                    self.camera.assembled_texture = pt_frame
                    # Send to video recorder
                    self.video_service.process_frame(
                        self.ctx,
                        pt_frame,
                        ui_state.preferences.recording.max_frames,
                        ui_state.preferences.recording.supersample_k,
                        ui_state.preferences.recording.filename_prefix,
                        flip_y=False  # 3D path tracer: no flip needed
                    )
        elif ui_state.sim.going:
            self.sim_runner.run_simulation_frame(
                ui_state, sweep_mode, sweep_reticle_pos, sweep_reticle_visible,
                screen_aspect, ui_state.sim.watercolor_mode,
                screenshot_in_progress=self.screenshot_in_progress,
                skip_view_generation=rt_active or optix_preview_display
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

        # 6.6. Compute physics step delta for GAS rebuild scheduling
        current_frame = self.sim.frame_count
        physics_steps = max(0, current_frame - self._prev_sim_frame_count)
        self._prev_sim_frame_count = current_frame
        if self._pathtracer_interface is not None:
            self._pathtracer_interface.physics_steps = physics_steps

        # 7. Render camera view
        self._render_camera_view(ui_state, sweep_mode, sweep_reticle_pos,
                                  sweep_reticle_visible, screen_aspect,
                                  rt_active=rt_active)

        # 7.5. Render arrow debug overlay if enabled. It composites into a
        # Viewer-owned display copy (display-only, never into recorded frames).
        if ui_state.preferences.ui_windows.debug_arrows:
            width, height = glfw.get_framebuffer_size(self.window)
            arrow_texture = self.sim.can
            arrow_resolution = self.sim.can.size
            use_zw = False
            self.viewer.draw_debug_overlay(lambda: self.arrow_debug_service.render(
                canvas_texture=arrow_texture,
                cam_pos=tuple(self.camera.position),
                cam_zoom=self.camera.zoom,
                canvas_resolution=arrow_resolution,
                window_size=(width, height),
                arrow_sensitivity=ui_state.preferences.ui_windows.arrow_sensitivity,
                use_zw_channels=use_zw,
            ))

        # 7.9. Snapshot camera for next-frame movement detection
        self._snapshot_camera()

        # 8. Update UI display info and render
        display_info = {
            'time': self.sim.time,
            'frame_count': self.sim.frame_count,
            'tex_size': self.sim.view_tex.size,
            'recording_active': self.video_service.is_active(),
            'video_pending': self.recording_controller.video_pending,
            'video_scheduled_start_frame': self.recording_controller.video_scheduled_start_frame,
            'video_current_frame': self.video_service.current_frame,
            'video_max_frames': ui_state.preferences.recording.max_frames,
        }
        display_info.update(self.batch_render_controller.display_status())
        self.ui.update_display_info(display_info)
        # Clear the default framebuffer before ImGui draws. The renderer no
        # longer blits to the screen (its finished frame goes into the Viewer
        # ImGui image), so clear here to avoid stale garbage behind the UI.
        self.ctx.screen.use()
        width, height = glfw.get_framebuffer_size(self.window)
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
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
                             sweep_reticle_visible, screen_aspect,
                             rt_active=False):
        """Prepare the Viewer's display texture for this frame.

        Produces the renderer's finished (markup-free) frame and hands it to the
        Viewer, which composites display-only overlays and shows it in the
        "Viewer" ImGui window. No longer draws to the screen directly — the
        Viewer image fills the docking central node, so mouse coordinates stay
        in full-window screen space (picking/drawing math unchanged).
        """
        # Realtime tracer mode: display the path-traced image fullscreen (no
        # overlays — matches the previous fullscreen behavior).
        ti = self.ui._tracer_interface
        if rt_active and ti is not None and ti.display_texture is not None:
            self.viewer.prepare(ti.display_texture)
            return

        # OptiX preview: tonemap via the image pipeline and display fullscreen.
        pt = self._pathtracer_interface
        if (pt is not None
                and (pt.preview_active or pt.preview_has_result)
                and pt.display_texture is not None
                and ui_state.preferences.optix.rt_mode == 0):
            # Run HDR preview texture through the image pipeline for tonemapping
            tonemapped = self.camera.image_pipeline.assemble_frame(
                pt.display_texture,
                total_samples=1,
                current_sample_index=0,
                brightness=ui_state.preferences.rendering.brightness,
                tonemap_softness=ui_state.preferences.rendering.tonemap_softness,
            )
            self.viewer.prepare(tonemapped)
            return

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
        sdf_enabled = ui_state.preferences.tracer.sdf_enabled
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
            sun_d = np.array(p.lighting.light_direction, dtype=np.float64)
            sun_len = max(np.linalg.norm(sun_d), 1e-8)
            sdf_sun_dir = tuple((sun_d / sun_len).astype(np.float32))
            sc = p.lighting.light_color
            si = p.lighting.light_intensity
            sdf_sun_color = (sc[0] * si, sc[1] * si, sc[2] * si)
            skc = p.lighting.sky_color_top
            ski = p.lighting.sky_intensity
            sdf_sky_color = (skc[0] * ski, skc[1] * ski, skc[2] * ski)

        # Build overlay markup params (sweep reticle). These composite over the
        # finished frame for DISPLAY only; the recorded frame stays markup-free.
        overlay_params = {
            'sweep_mode': sweep_mode,
            'sweep_reticle_pos': sweep_reticle_pos,
            'sweep_reticle_visible': sweep_reticle_visible,
        }

        finished_tex = self.camera.render(
            sim_going=ui_state.sim.going,
            screen_aspect=screen_aspect,
            watercolor_mode=ui_state.sim.watercolor_mode,
            ink_weight=ui_state.sim.ink_weight,
            exposure=ui_state.preferences.rendering.exposure,
            tonemap_softness=ui_state.preferences.rendering.tonemap_softness,
            bloom_enabled=ui_state.preferences.bloom.enabled,
            bloom_threshold=ui_state.preferences.bloom.threshold,
            bloom_intensity=ui_state.preferences.bloom.intensity,
            bloom_radius=ui_state.preferences.bloom.radius,
            sdf_enabled=sdf_enabled,
            inv_view_proj=inv_view_proj,
            sdf_sun_dir=sdf_sun_dir,
            sdf_sun_color=sdf_sun_color,
            sdf_sky_color=sdf_sky_color,
        )

        # Hand the finished (markup-free) frame to the Viewer, which composites
        # display-only overlays and shows it in the Viewer window.
        self.viewer.prepare(
            finished_tex,
            overlay_params=overlay_params,
            watercolor_mode=ui_state.sim.watercolor_mode,
            screen_aspect=screen_aspect,
            exposure=ui_state.preferences.rendering.exposure,
            mouse_screen_coords=mouse_screen_coords,
            camera_position=tuple(self.camera.position),
            camera_zoom=self.camera.zoom,
            canvas_resolution=self.sim.get_canvas_dimensions(),
        )

    def _save_screenshot(self, ui_state):
        """Save screenshot and restore settings."""
        if self.camera.assembled_texture is not None:
            from utilities.save_frame_gpu import save_frame_gpu
            import datetime
            import os
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            prefix = ui_state.preferences.recording.filename_prefix or "screenshot"
            flip_y = False  # always-3D orientation
            filename = save_frame_gpu(
                self.camera.assembled_texture,
                self.ctx,
                supersample_k=ui_state.preferences.recording.supersample_k,
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
        ui_state.preferences.rendering.speedmult = self.screenshot_saved_settings['speedmult']
        ui_state.preferences.rendering.blur_quality = self.screenshot_saved_settings['blur_quality']
        ui_state.preferences.rendering.motion_blur = self.screenshot_saved_settings['motion_blur']
        ui_state.sim.going = self.screenshot_saved_settings['going']
        self.screenshot_in_progress = False
        self.screenshot_saved_settings = {}

    def cleanup(self):
        # Save preferences before cleanup
        ui_state = self.ui.get_state()

        # Sync 3D camera settings into preferences
        cam = ui_state.camera
        ui_state.preferences.camera3d.fov = cam.fov
        ui_state.preferences.camera3d.aperture = cam.aperture
        ui_state.preferences.camera3d.focal_plane_depth = cam.focal_plane_depth
        ui_state.preferences.camera3d.move_speed = cam.move_speed
        ui_state.preferences.camera3d.rotate_speed = cam.rotate_speed
        ui_state.preferences.camera3d.orbit_center = list(cam.orbit_center)
        ui_state.preferences.camera3d.orbit_rate = cam.orbit_rate
        # Keep the legacy optix.enabled mirror in sync (renderer enum is the
        # source of truth and persists directly via rendering.renderer).
        ui_state.preferences.optix.enabled = (ui_state.preferences.rendering.renderer == 1)

        # Sync tracer settings into preferences
        ti = self.ui._tracer_interface
        if ti is not None:
            ui_state.preferences.tracer.sdf_enabled = ti.sdf_enabled
            ui_state.preferences.tracer.colored_extinction = ti.colored_extinction
            ui_state.preferences.tracer.extinction_rgb = list(ti.extinction_rgb)
            ui_state.preferences.tracer.albedo_saturation = ti.albedo_saturation
            ui_state.preferences.tracer.albedo_brightness = ti.albedo_brightness
            ui_state.preferences.tracer.density_scale = ti.density_scale
            ui_state.preferences.tracer.hg_g = ti.hg_g
            ui_state.preferences.tracer.emission_strength = ti.emission_strength
            # Sun + sky live on the shared LightingPrefs slice (edited directly);
            # nothing to sync back from ti.
            ui_state.preferences.tracer.num_samples = ti.num_samples
            ui_state.preferences.tracer.exposure = ti.exposure
            ui_state.preferences.tracer.realtime_mode = ti.realtime_mode
            ui_state.preferences.tracer.max_bounces = ti.max_bounces
            ui_state.preferences.tracer.firefly_clamp = ti.firefly_clamp
            ui_state.preferences.tracer.firefly_clamp_max = ti.firefly_clamp_max
            ui_state.preferences.tracer.resolution_scale = ti.resolution_scale
            ui_state.preferences.tracer.density_resolution_log2 = ti.density_resolution_log2
            ui_state.preferences.tracer.color_resolution_log2 = ti.color_resolution_log2
            ui_state.preferences.tracer.majorant_resolution_log2 = ti.majorant_resolution_log2

        save_preferences(ui_state.preferences)

        self.renderer_host.release_optix()
        # Tear down the volumetric tracer's GPU resources (previously leaked at exit)
        if ti is not None:
            ti.cleanup()
            self.ui._tracer_interface = None
        self.video_service.cleanup()
        self.viewer.cleanup()
        self.ui.cleanup()
        glfw.terminate()


if __name__ == "__main__":
    app = App()
    app.run()
