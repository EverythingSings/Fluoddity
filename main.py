import glfw
import moderngl
import time
from pathlib import Path
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import RuleManager, EntityPicker, VideoRecorderService, ConfigSaver
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
        self.configs_dir = Path("physics_configs")
        self.configs_dir.mkdir(exist_ok=True)

        # Preview state
        self.preview_rule_active = False

        # Frame timing
        self.last_update_time = time.time()

        # Track user's desired speedmult (for restoration after recording)
        self.user_speedmult = 1
        self.was_recording = False

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

        # 6. Run simulation if going
        if ui_state.sim.going:
            self.run_simulation_frame(ui_state)

        # 7. Render camera view
        self.camera.render(sim_going=ui_state.sim.going,current_view_option=ui_state.sim.current_view_option)

        # 8. Update UI display info and render
        self.ui.update_display_info({
            'time': self.sim.time,
            'frame_count': self.sim.frame_count,
            'tex_size': self.sim.view_tex.size,
            'recording_active': self.video_service.is_active(),
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

        # Full reset (Z key) - also clears rules
        if ui_state.request_full_reset:
            self.sim.reset()
            self.rule_manager.clear()
            self.sim.apply_rule(None)

        # Handle entity clicking (left click)
        if ui_state.left_click_this_frame:
            tex_coords = self.camera.screen_to_tex(
                ui_state.mouse_pos,
                self.sim.view_tex.size
            )
            entity_id = self.entity_picker.find_nearest_entity(tex_coords)
            print(entity_id)
            rule = readback_rule(self.sim.get_rule_buffer(), entity_id)
            self.rule_manager.push_rule(rule)
            self.sim.apply_rule(rule)

        # Handle rule undo (right click)
        if ui_state.right_click_this_frame:
            prev_rule = self.rule_manager.pop_rule()
            self.sim.apply_rule(prev_rule)

        # Handle config save (Ctrl+C)
        if ui_state.request_save_config:
            current_rule = self.rule_manager.get_current_rule()
            config_string = self.config_saver.save_to_string(ui_state.sim, current_rule)
            self.ui.set_clipboard(config_string)
            print(f"Config copied to clipboard ({len(config_string)} chars)")

        # Handle config load (Ctrl+V)
        if ui_state.request_load_config:
            config_string = ui_state.clipboard_text
            if config_string:
                rule = self.config_saver.load_from_string(config_string, ui_state.sim)
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
                config_string = self.config_saver.save_to_string(ui_state.sim, current_rule)
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
                    rule = self.config_saver.load_from_string(config_string, ui_state.sim)
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

    def process_camera_input(self, ui_state):
        """Handle continuous WASD/QE input for camera."""
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

    def run_simulation_frame(self, ui_state):
        """Run simulation step(s) with frame assembly and video recording."""
        speedmult = ui_state.preferences.speedmult
        motion_blur = ui_state.preferences.motion_blur

        if motion_blur:
            # Motion blur enabled: temporal accumulation with multiple render calls
            # Run simulation steps and accumulate frames
            for step in range(speedmult):
                self.sim.update(self.ctx)

                # Generate raw view texture (PRE-gamma correction)
                raw_view_tex = self.camera.generate_view_texture()

                # Assemble frame (applies gamma correction on final sample)
                assembled_tex = self.camera.frame_assembler.assemble_frame(
                    raw_view_tex,
                    total_samples=speedmult,
                    current_sample_index=step,
                    view_mode = ui_state.sim.current_view_option
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
                self.sim.update(self.ctx)

            # Generate view texture only once at the end
            raw_view_tex = self.camera.generate_view_texture()

            # Apply gamma correction in single-sample mode (no temporal accumulation)
            assembled_tex = self.camera.frame_assembler.assemble_frame(
                raw_view_tex,
                total_samples=1,
                current_sample_index=0,
                view_mode = ui_state.sim.current_view_option
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
