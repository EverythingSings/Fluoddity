import glfw
import moderngl
import time
from pathlib import Path
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import RuleManager, EntityPicker, VideoRecorderService, ConfigSaver, ArrowDebugService
from utilities.gl_helpers import readback_rule
from state import load_preferences, save_preferences


class App:
    """Main application with Orchestrator pattern."""

    def __init__(self):
        # Initialize GLFW
        if not glfw.init():
            raise Exception("GLFW initialization failed")
        self.window = glfw.create_window(800, 600, "Particle Simulation", None, None)
        if not self.window:
            glfw.terminate()
            raise Exception("GLFW window creation failed")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)  # Enable vsync

        # Initialize ModernGL
        self.ctx = moderngl.create_context()
        self.ctx.gc_mode = 'auto'

        # Always on top
        glfw.set_window_attrib(self.window, glfw.FLOATING, glfw.TRUE)

        # Create components (no cross-references between UI and sim/camera)
        self.sim = Sim(self.ctx)
        self.camera = Camera(self.ctx, self.sim, self.window)
        self.ui = UI(self.window, self.ctx, self.sim.view_option_labels)

        # Load and apply preferences
        loaded_prefs = load_preferences()
        self.ui.state.preferences = loaded_prefs

        # Create services (Orchestrator owns these)
        self.rule_manager = RuleManager()
        # Divide by 4 to convert from bytes to floats (each float32 is 4 bytes)
        entity_stride = SIZE_OF_ENTITY_STRUCT // 4
        self.entity_picker = EntityPicker(self.sim.get_entity_buffer(), entity_stride)
        self.video_service = VideoRecorderService()
        self.config_saver = ConfigSaver()
        self.arrow_debug_service = ArrowDebugService(self.ctx)
        self.configs_dir = Path("physics_configs")
        self.configs_dir.mkdir(exist_ok=True)

        # Preview state
        self.preview_rule_active = False  # File->load preview
        self.history_preview_rule_active = False  # History window preview

        # Frame timing
        self.last_update_time = time.time()

        # Track user's desired speedmult (for restoration after recording)
        self.user_speedmult = 1
        self.was_recording = False

        # Mouse tracking for draw trail mode
        self.prev_mouse_tex_coords = (0.0, 0.0)
        self.mouse_button_state = False  # Track if left mouse button is currently pressed

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

        # 2. Process one-shot commands
        self.process_commands(ui_state)

        # 3. Process continuous input (camera movement)
        self.process_camera_input(ui_state)

        # 4. Lock speedmult to motion_blur_samples if recording
        is_recording = self.video_service.is_active()

        # Detect recording state changes
        if is_recording and not self.was_recording:
            # Recording just started - save user's speedmult
            self.user_speedmult = ui_state.preferences.speedmult
        elif not is_recording and self.was_recording:
            # Recording just stopped - restore user's speedmult
            ui_state.preferences.speedmult = self.user_speedmult

        # Lock speedmult while recording
        if is_recording:
            ui_state.preferences.speedmult = ui_state.preferences.motion_blur_samples

        # Update recording state for next frame
        self.was_recording = is_recording

        # 5. Apply state to components
        self.sim.apply_state(ui_state.sim)
        self.sim.apply_camera_state(ui_state.camera)
        self.sim.apply_preferences(ui_state.preferences)
        self.camera.apply_state(ui_state.camera)
        # Sync brightness from sim_state (appearance settings now in physics config)
        self.camera.BRIGHTNESS = ui_state.sim.brightness

        # 5.5. Calculate sweep reticle info (needed for both running and paused states)
        sweep_reticle_x, sweep_reticle_y, sweep_reticle_visible = self.sim.get_sweep_reticle_position()

        # Hide reticle when in sweep preview mode or when recording video
        if ui_state.sim.sweep_preview_active or is_recording:
            sweep_reticle_visible = False

        # Transform reticle from texture UV to screen UV (accounting for camera)
        width, height = glfw.get_framebuffer_size(self.window)
        screen_aspect = width / height if height > 0 else 1.0

        if sweep_reticle_visible:
            # Convert texture coords to screen pixels
            screen_x, screen_y = self.camera.tex_to_screen(
                (sweep_reticle_x, sweep_reticle_y),
                self.sim.view_tex.size
            )
            # Convert screen pixels to screen UV (0-1)
            sweep_reticle_x = screen_x / width
            sweep_reticle_y = screen_y / height

        sweep_mode = ui_state.sim.parameter_sweeps_enabled and not ui_state.sim.sweep_preview_active
        sweep_reticle_pos = (sweep_reticle_x, sweep_reticle_y)

        # 6. Run simulation if going
        if ui_state.sim.going:
            self.run_simulation_frame(ui_state, sweep_mode, sweep_reticle_pos, sweep_reticle_visible, screen_aspect)

        # 7. Render camera view
        self.camera.render(
            sim_going=ui_state.sim.going,
            current_view_option=ui_state.sim.current_view_option,
            sweep_mode=sweep_mode,
            sweep_reticle_pos=sweep_reticle_pos,
            sweep_reticle_visible=sweep_reticle_visible,
            screen_aspect=screen_aspect
        )

        # 7.5. Render arrow debug overlay if enabled
        if ui_state.preferences.debug_arrows:
            width, height = glfw.get_framebuffer_size(self.window)
            self.arrow_debug_service.render(
                canvas_texture=self.sim.can,
                cam_pos=tuple(self.camera.position),
                cam_zoom=self.camera.zoom,
                canvas_resolution=self.sim.can.size,
                window_size=(width, height),
                arrow_sensitivity=ui_state.preferences.arrow_sensitivity
            )

        # 8. Update UI display info and render
        self.ui.update_display_info({
            'time': self.sim.time,
            'frame_count': self.sim.frame_count,
            'tex_size': self.sim.view_tex.size,
            'recording_active': self.video_service.is_active(),
            'rule_history': self.rule_manager.rule_history,
        })
        self.ui.render()

    def process_commands(self, ui_state):
        """Handle one-shot commands."""

        # Toggle recording
        if ui_state.toggle_recording:
            self.video_service.toggle()

        # Shader reload
        if ui_state.request_reload:
            self.sim.reload()
            if self.rule_manager.has_rules():
                self.sim.apply_rule(self.rule_manager.get_current_rule())
            self.camera.reload()

        # Simple reset (R key)
        if ui_state.request_reset:
            self.sim.reset()

        # Full reset (Z key) - push zero rule (undoable) and reset entities
        if ui_state.request_full_reset:
            self.sim.reset()
            zero_rule = self.rule_manager.push_zero_rule()
            self.sim.apply_rule(zero_rule)

        # Handle entity clicking and rule undo (only in Select Particle mode)
        if ui_state.preferences.mouse_mode == "Select Particle":
            # Handle sweep preview mode: any click exits preview and restores sweeps
            if ui_state.sim.sweep_preview_active:
                if ui_state.left_click_this_frame or ui_state.right_click_this_frame:
                    # Exit sweep preview mode and restore saved sweeps
                    ui_state.sim.sweep_preview_active = False
                    ui_state.sim.x_sweeps = ui_state.sim.saved_x_sweeps.copy()
                    ui_state.sim.y_sweeps = ui_state.sim.saved_y_sweeps.copy()
                    ui_state.sim.cohort_sweeps = ui_state.sim.saved_cohort_sweeps.copy()
                    # Also update preferences so UI state stays in sync
                    ui_state.preferences.x_sweeps = ui_state.sim.saved_x_sweeps.copy()
                    ui_state.preferences.y_sweeps = ui_state.sim.saved_y_sweeps.copy()
                    ui_state.preferences.cohort_sweeps = ui_state.sim.saved_cohort_sweeps.copy()
            elif ui_state.left_click_this_frame:
                # Handle entity clicking (left click)
                tex_coords = self.camera.screen_to_tex(
                    ui_state.mouse_pos,
                    self.sim.view_tex.size
                )

                # When parameter sweeps are active, behavior changes:
                # - If cohort sweep active: need entity picker for cohort info
                # - If only X/Y sweeps: can resolve from position alone (no entity readback)
                # - In all sweep cases: only update sliders, don't pick a new rule
                if ui_state.sim.parameter_sweeps_enabled and self.sim.has_active_xy_sweep():
                    # Convert tex coords to world pos for sweep calculation
                    world_pos = (tex_coords[0] * 2 - 1, tex_coords[1] * 2 - 1)

                    if self.sim.has_active_cohort_sweep():
                        # Need entity picker for cohort info
                        entity_id, entity_pos, entity_cohort = self.entity_picker.find_nearest_entity(tex_coords)
                        self.sim.update_sliders_from_particle(world_pos, entity_cohort)
                    else:
                        # No cohort sweep - can update from position alone
                        self.sim.update_sliders_from_position(world_pos)
                else:
                    # Normal mode: pick entity and apply rule
                    entity_id, entity_pos, entity_cohort = self.entity_picker.find_nearest_entity(tex_coords)
                    print(f"Entity {entity_id} at pos {entity_pos}, cohort {entity_cohort}")
                    rule = readback_rule(self.sim.get_rule_buffer(), entity_id)
                    self.rule_manager.push_rule(rule)
                    self.sim.apply_rule(rule)
                    # Update sliders to show effective parameter values at this particle's location
                    self.sim.update_sliders_from_particle(entity_pos, entity_cohort)
            elif ui_state.right_click_this_frame:
                # Right click behavior depends on sweep mode
                if ui_state.sim.parameter_sweeps_enabled and self.sim.has_active_xy_sweep():
                    # Enter sweep preview mode: save sweeps and clear them
                    ui_state.sim.sweep_preview_active = True
                    ui_state.sim.saved_x_sweeps = ui_state.sim.x_sweeps.copy()
                    ui_state.sim.saved_y_sweeps = ui_state.sim.y_sweeps.copy()
                    ui_state.sim.saved_cohort_sweeps = ui_state.sim.cohort_sweeps.copy()
                    # Clear all sweeps
                    for key in ui_state.sim.x_sweeps:
                        ui_state.sim.x_sweeps[key] = 0.0
                    for key in ui_state.sim.y_sweeps:
                        ui_state.sim.y_sweeps[key] = 0.0
                    for key in ui_state.sim.cohort_sweeps:
                        ui_state.sim.cohort_sweeps[key] = 0.0
                    # Also update preferences so UI state stays in sync
                    ui_state.preferences.x_sweeps = ui_state.sim.x_sweeps.copy()
                    ui_state.preferences.y_sweeps = ui_state.sim.y_sweeps.copy()
                    ui_state.preferences.cohort_sweeps = ui_state.sim.cohort_sweeps.copy()
                else:
                    # Normal mode: pop rule from history
                    prev_rule = self.rule_manager.pop_rule()
                    self.sim.apply_rule(prev_rule)

        # Handle config save (Ctrl+C)
        if ui_state.request_save_config:
            current_rule = self.rule_manager.get_current_rule()
            config_string = self.config_saver.save_to_string(
                ui_state.sim, current_rule, ui_state.preferences.slider_ranges
            )
            self.ui.set_clipboard(config_string)
            print(f"Config copied to clipboard ({len(config_string)} chars)")

        # Handle config load (Ctrl+V)
        if ui_state.request_load_config:
            config_string = ui_state.clipboard_text
            if config_string:
                rule = self.config_saver.load_from_string(
                    config_string, ui_state.sim, ui_state.preferences.slider_ranges
                )
                if rule is not None:
                    self.rule_manager.push_rule(rule)
                    self.sim.apply_rule(rule)
                    print("Config loaded from clipboard")
                else:
                    print("Failed to load config from clipboard")

        # Handle file save (menu)
        if ui_state.request_save_file:
            filename = ui_state.save_filename
            if filename:
                current_rule = self.rule_manager.get_current_rule()
                config_string = self.config_saver.save_to_string(
                    ui_state.sim, current_rule, ui_state.preferences.slider_ranges
                )
                filepath = self.configs_dir / f"{filename}.txt"
                filepath.write_text(config_string)
                print(f"Config saved to {filepath}")

        # Handle file load (menu)
        if ui_state.request_load_file:
            # If we were previewing, pop the preview rule first
            if self.preview_rule_active:
                self.rule_manager.pop_rule()
                self.preview_rule_active = False

            filename = ui_state.load_filename
            if filename:
                filepath = self.configs_dir / f"{filename}.txt"
                if filepath.exists():
                    config_string = filepath.read_text()
                    rule = self.config_saver.load_from_string(
                        config_string, ui_state.sim, ui_state.preferences.slider_ranges
                    )
                    if rule is not None:
                        self.rule_manager.push_rule(rule)
                        self.sim.apply_rule(rule)
                        print(f"Config loaded from {filepath}")
                        # Update physics defaults for reset functionality
                        self.ui.update_physics_defaults(filename)
                    else:
                        print(f"Failed to parse config from {filepath}")
                else:
                    print(f"Config file not found: {filepath}")

        # Handle file delete (menu)
        if ui_state.request_delete_file:
            filename = ui_state.delete_filename
            if filename:
                filepath = self.configs_dir / f"{filename}.txt"
                if filepath.exists():
                    filepath.unlink()
                    print(f"Config deleted: {filepath}")

        # Handle clear preview (unhover or close submenu) - must happen before new preview
        if ui_state.request_clear_preview:
            if self.preview_rule_active:
                prev_rule = self.rule_manager.pop_rule()
                self.sim.apply_rule(prev_rule)
                self.preview_rule_active = False

        # Handle config preview (hover in Load submenu)
        if ui_state.request_preview_config:
            filename = ui_state.preview_filename
            if filename:
                filepath = self.configs_dir / f"{filename}.txt"
                if filepath.exists():
                    config_string = filepath.read_text()
                    config = self.config_saver.decode_config(config_string)
                    if config and config.rule is not None:
                        self.rule_manager.push_rule(config.rule)
                        self.sim.apply_rule(config.rule)
                        self.preview_rule_active = True

        # Handle rule history preview - clear must happen BEFORE new preview
        if ui_state.request_clear_history_preview:
            if self.history_preview_rule_active:
                prev_rule = self.rule_manager.pop_rule()
                self.ui.history_window_labels.pop()  # Also remove the preview's label
                self.sim.apply_rule(prev_rule)
                self.history_preview_rule_active = False

        if ui_state.request_preview_history_rule:
            idx = ui_state.history_preview_index
            if 0 <= idx < len(self.rule_manager.rule_history):
                rule_to_preview = self.rule_manager.rule_history[idx].copy()
                self.rule_manager.push_rule(rule_to_preview)
                self.sim.apply_rule(rule_to_preview)
                self.history_preview_rule_active = True

        if ui_state.request_load_history_rule:
            # Clear preview first
            if self.history_preview_rule_active:
                self.rule_manager.pop_rule()
                self.ui.history_window_labels.pop()  # Also remove the preview's label
                self.history_preview_rule_active = False

            idx = ui_state.history_preview_index
            if 0 <= idx < len(self.rule_manager.rule_history):
                # Move rule to top with metadata
                rule_to_load = self.rule_manager.rule_history[idx].copy()
                label_to_preserve = self.ui.history_window_labels[idx]

                self.rule_manager.rule_history.pop(idx)
                self.ui.history_window_labels.pop(idx)

                self.rule_manager.push_rule(rule_to_load)
                self.ui.history_window_labels.append(label_to_preserve)
                self.sim.apply_rule(rule_to_load)

        if ui_state.request_delete_history_rule:
            # Clear preview first
            if self.history_preview_rule_active:
                self.rule_manager.pop_rule()
                self.ui.history_window_labels.pop()  # Also remove the preview's label
                self.history_preview_rule_active = False

            idx = ui_state.history_preview_index
            if 0 <= idx < len(self.rule_manager.rule_history):
                self.rule_manager.rule_history.pop(idx)
                self.ui.history_window_labels.pop(idx)

                current_rule = self.rule_manager.get_current_rule()
                self.sim.apply_rule(current_rule)

    def process_camera_input(self, ui_state):
        """Handle continuous WASD/QE input for camera and scroll zoom."""
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        move_speed = 2.0 * dt * ui_state.camera.zoom
        zoom_speed = 2.6 * dt

        keys = ui_state.keys_pressed

        if glfw.KEY_W in keys:
            ui_state.camera.position[1] -= move_speed
        if glfw.KEY_S in keys:
            ui_state.camera.position[1] += move_speed
        if glfw.KEY_A in keys:
            ui_state.camera.position[0] -= move_speed
        if glfw.KEY_D in keys:
            ui_state.camera.position[0] += move_speed

        if glfw.KEY_E in keys:
            ui_state.camera.zoom *= (1.0 - zoom_speed)
        if glfw.KEY_Q in keys:
            ui_state.camera.zoom *= (1.0 + zoom_speed)

        # Handle scroll zoom (zoom around mouse pointer - "Factorio-style")
        if ui_state.scroll_delta != 0.0:
            # Get window dimensions
            width, height = glfw.get_framebuffer_size(self.window)

            # Convert mouse to NDC
            x_screen, y_screen = ui_state.mouse_pos
            x_ndc = (x_screen / width) * 2 - 1
            y_ndc = (1 - y_screen / height) * 2 - 1

            # Calculate aspect ratios
            tex_size = self.sim.view_tex.size
            tex_aspect = tex_size[0] / tex_size[1]
            window_aspect = width / height

            if tex_aspect > window_aspect:
                scale_x = 1.0
                scale_y = window_aspect / tex_aspect
            else:
                scale_x = tex_aspect / window_aspect
                scale_y = 1.0

            # Get world position under mouse BEFORE zoom
            old_zoom = ui_state.camera.zoom
            old_pos = ui_state.camera.position.copy()

            scale_x_old = scale_x / old_zoom
            scale_y_old = scale_y / old_zoom
            x_ndc_adj = x_ndc + old_pos[0] / old_zoom
            y_ndc_adj = y_ndc - old_pos[1] / old_zoom
            world_x = x_ndc_adj / scale_x_old
            world_y = y_ndc_adj / scale_y_old

            # Apply zoom (scroll up = zoom in = smaller zoom value)
            scroll_zoom_speed = 0.1
            zoom_factor = 1.0 - ui_state.scroll_delta * scroll_zoom_speed
            zoom_factor = max(0.5, min(2.0, zoom_factor))  # Clamp zoom step
            new_zoom = old_zoom * zoom_factor
            ui_state.camera.zoom = new_zoom

            # Calculate where the world point would now appear in NDC
            scale_x_new = scale_x / new_zoom
            scale_y_new = scale_y / new_zoom
            new_x_ndc_adj = world_x * scale_x_new
            new_y_ndc_adj = world_y * scale_y_new

            # Adjust camera position so the world point stays at the same screen position
            # We want: new_x_ndc_adj = x_ndc + new_pos[0] / new_zoom
            # So: new_pos[0] = (new_x_ndc_adj - x_ndc) * new_zoom
            ui_state.camera.position[0] = (new_x_ndc_adj - x_ndc) * new_zoom
            ui_state.camera.position[1] = -(new_y_ndc_adj - y_ndc) * new_zoom

    def run_simulation_frame(self, ui_state, sweep_mode: bool, sweep_reticle_pos: tuple,
                              sweep_reticle_visible: bool, screen_aspect: float):
        """Run simulation step(s) with frame assembly and video recording."""
        speedmult = ui_state.preferences.speedmult
        motion_blur = ui_state.preferences.motion_blur

        # Calculate draw mode parameters
        # Disable trail drawing when parameter sweeps are active
        draw_mode = (ui_state.preferences.mouse_mode == "Draw Trail" and
                     not ui_state.sim.parameter_sweeps_enabled)
        mouse_tex_coords = (0.0, 0.0)
        draw_power_value = 0.0

        if draw_mode:
            # Convert screen mouse position to texture coordinates (0-1 range)
            mouse_tex_coords = self.camera.screen_to_tex(
                ui_state.mouse_pos,
                self.sim.can.size
            )

            # Only set draw_power if button is pressed (respects imgui capture)
            if ui_state.mouse_left_held:
                draw_power_value = ui_state.preferences.draw_power

        if motion_blur:
            # Motion blur enabled: temporal accumulation with multiple render calls
            # Run simulation steps and accumulate frames
            for step in range(speedmult):
                self.sim.update(
                    self.ctx,
                    draw_mode=draw_mode,
                    mouse_pos=mouse_tex_coords,
                    prev_mouse_pos=self.prev_mouse_tex_coords,
                    draw_size=ui_state.preferences.draw_size,
                    draw_power=draw_power_value
                )

                # Generate raw view texture (PRE-gamma correction)
                raw_view_tex = self.camera.generate_view_texture()

                # Assemble frame (applies gamma correction on final sample)
                assembled_tex = self.camera.frame_assembler.assemble_frame(
                    raw_view_tex,
                    total_samples=speedmult,
                    current_sample_index=step,
                    view_mode=ui_state.sim.current_view_option,
                    sweep_mode=sweep_mode,
                    sweep_reticle_pos=sweep_reticle_pos,
                    sweep_reticle_visible=sweep_reticle_visible,
                    screen_aspect=screen_aspect,
                    brightness=self.camera.BRIGHTNESS
                )

                # Only process when accumulation cycle completes
                if assembled_tex is not None:
                    self.camera.assembled_texture = assembled_tex

                    # Send to video recorder if recording
                    if self.video_service.is_active():
                        self.video_service.process_frame(
                            self.camera.ctx,
                            assembled_tex,  # Already gamma-corrected and temporally complete
                            ui_state.preferences.max_frames,
                            ui_state.preferences.supersample_k,
                            ui_state.preferences.filename_prefix
                        )
        else:
            # Motion blur disabled: multiple physics steps, single render call
            # Run all simulation updates
            for step in range(speedmult):
                self.sim.update(
                    self.ctx,
                    draw_mode=draw_mode,
                    mouse_pos=mouse_tex_coords,
                    prev_mouse_pos=self.prev_mouse_tex_coords,
                    draw_size=ui_state.preferences.draw_size,
                    draw_power=draw_power_value
                )

            # Generate view texture only once at the end
            raw_view_tex = self.camera.generate_view_texture()

            # Apply gamma correction in single-sample mode (no temporal accumulation)
            assembled_tex = self.camera.frame_assembler.assemble_frame(
                raw_view_tex,
                total_samples=1,
                current_sample_index=0,
                view_mode=ui_state.sim.current_view_option,
                sweep_mode=sweep_mode,
                sweep_reticle_pos=sweep_reticle_pos,
                sweep_reticle_visible=sweep_reticle_visible,
                screen_aspect=screen_aspect,
                brightness=self.camera.BRIGHTNESS
            )

            self.camera.assembled_texture = assembled_tex

            # Send to video recorder if recording
            if self.video_service.is_active():
                self.video_service.process_frame(
                    self.camera.ctx,
                    assembled_tex,
                    ui_state.preferences.max_frames,
                    ui_state.preferences.supersample_k,
                    ui_state.preferences.filename_prefix
                )

        # Update previous mouse position for next frame
        if draw_mode:
            self.prev_mouse_tex_coords = mouse_tex_coords

    def cleanup(self):
        # Save preferences before cleanup
        ui_state = self.ui.get_state()
        save_preferences(ui_state.preferences)

        self.video_service.cleanup()
        self.ui.cleanup()
        glfw.terminate()


if __name__ == "__main__":
    app = App()
    app.run()
