import glfw
import moderngl
import time
from camera import Camera
from sim import Sim, SIZE_OF_ENTITY_STRUCT
from ui import UI
from services import RuleManager, EntityPicker, VideoRecorderService
from utilities.gl_helpers import readback_rule


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

        # Create services (Orchestrator owns these)
        self.rule_manager = RuleManager()
        # Divide by 4 to convert from bytes to floats (each float32 is 4 bytes)
        entity_stride = SIZE_OF_ENTITY_STRUCT // 4
        self.entity_picker = EntityPicker(self.sim.get_entity_buffer(), entity_stride)
        self.video_service = VideoRecorderService()

        # Frame timing
        self.last_update_time = time.time()

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

        # 4. Lock speedmult if recording
        if self.video_service.is_active():
            ui_state.sim.speedmult = 1

        # 5. Apply state to components
        self.sim.apply_state(ui_state.sim)
        self.camera.apply_state(ui_state.camera)

        # 6. Run simulation if going
        if ui_state.sim.going:
            self.run_simulation_frame(ui_state)

        # 7. Render camera view
        self.camera.render(sim_going=ui_state.sim.going)

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
        """Run simulation step(s) and handle video recording."""
        speedmult = ui_state.sim.speedmult

        if speedmult > 1:
            # Motion blur accumulation
            for step in range(speedmult):
                self.sim.update(self.ctx)
                view_tex = self.camera.generate_view_texture()
                accumulated_tex = self.sim.temporal_accumulator.accumulate_frame(
                    view_tex, speedmult
                )

            if accumulated_tex is not None:
                self.camera.accumulated_view_texture = accumulated_tex
                self.camera.use_accumulated_view = True
        else:
            # Normal operation: single step, no accumulation
            self.sim.update(self.ctx)
            self.camera.use_accumulated_view = False

        # Video recording
        self.video_service.process_frame(
            self.camera.ctx,
            self.camera.cam_brush_target,
            ui_state.recording.max_frames,
            ui_state.recording.motion_blur_samples,
            ui_state.recording.supersample_k
        )

    def cleanup(self):
        self.video_service.cleanup()
        self.ui.cleanup()
        glfw.terminate()


if __name__ == "__main__":
    app = App()
    app.run()
