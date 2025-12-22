import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
from state import UIState, SimState, CameraState, RecordingState


class UI:
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(self, window, view_option_labels: list[str]):
        self.window = window
        self.view_option_labels = view_option_labels

        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        # Set up event callbacks
        self.setup_callbacks()

        # UI-only state
        self.show_demo_window = False

        # State containers (Orchestrator reads these each frame)
        self.state = UIState(
            sim=SimState(),
            camera=CameraState(),
            recording=RecordingState()
        )

        # Input state (updated by callbacks)
        self._keys_pressed = set()
        self._mouse_pos = (0.0, 0.0)

        # One-shot flags (reset after get_state)
        self._left_click_pending = False
        self._right_click_pending = False
        self._request_reload = False
        self._request_reset = False
        self._request_full_reset = False
        self._toggle_recording = False

        # Display info (received from Orchestrator)
        self._display_info = {
            'time': 0.0,
            'frame_count': 0,
            'tex_size': (1024, 1024),
            'recording_active': False,
        }

        # Resize debouncing
        self.pending_resize_time = None
        self.resize_debounce_delay = 0.15  # seconds

        # Timing for camera input
        self.last_update_time = time.time()

    def setup_callbacks(self):
        self.imgui_mouse_callback = glfw.set_mouse_button_callback(self.window, None)
        self.imgui_cursor_callback = glfw.set_cursor_pos_callback(self.window, None)
        self.imgui_scroll_callback = glfw.set_scroll_callback(self.window, None)
        self.imgui_key_callback = glfw.set_key_callback(self.window, None)
        self.imgui_char_callback = glfw.set_char_callback(self.window, None)

        glfw.set_mouse_button_callback(self.window, self.mouse_button_callback)
        glfw.set_cursor_pos_callback(self.window, self.cursor_pos_callback)
        glfw.set_scroll_callback(self.window, self.scroll_callback)
        glfw.set_key_callback(self.window, self.key_callback)
        glfw.set_char_callback(self.window, self.char_callback)
        glfw.set_framebuffer_size_callback(self.window, self.framebuffer_size_callback)

    def framebuffer_size_callback(self, window, width, height):
        # Debounce: just record the time, actual reload happens via request_reload flag
        self.pending_resize_time = time.time()

    def mouse_button_callback(self, window, button, action, mods):
        if self.imgui_mouse_callback:
            self.imgui_mouse_callback(window, button, action, mods)

        if imgui.get_io().want_capture_mouse:
            return

        if action != glfw.PRESS:
            return

        if button == glfw.MOUSE_BUTTON_LEFT:
            self._left_click_pending = True
        elif button == glfw.MOUSE_BUTTON_RIGHT:
            self._right_click_pending = True

    def cursor_pos_callback(self, window, xpos, ypos):
        if self.imgui_cursor_callback:
            self.imgui_cursor_callback(window, xpos, ypos)
        self._mouse_pos = (xpos, ypos)

    def scroll_callback(self, window, xoffset, yoffset):
        if self.imgui_scroll_callback:
            self.imgui_scroll_callback(window, xoffset, yoffset)

    def key_callback(self, window, key, scancode, action, mods):
        if self.imgui_key_callback:
            self.imgui_key_callback(window, key, scancode, action, mods)

        if imgui.get_io().want_capture_keyboard:
            return

        if action == glfw.PRESS:
            self._keys_pressed.add(key)
        elif action == glfw.RELEASE:
            self._keys_pressed.discard(key)

        # One-shot key commands
        if action == glfw.PRESS:
            if key == glfw.KEY_V:
                self._request_reload = True
            elif key == glfw.KEY_P:
                self._toggle_recording = True
            elif key == glfw.KEY_G:
                self.state.sim.going = not self.state.sim.going
            elif key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(window, True)
            elif key == glfw.KEY_F1:
                self.show_demo_window = not self.show_demo_window

    def char_callback(self, window, char):
        if self.imgui_char_callback:
            self.imgui_char_callback(window, char)

    def get_state(self) -> UIState:
        """Return current UI state for Orchestrator to read.

        Returns snapshot and resets one-shot flags.
        """
        # Check for pending resize (debounced)
        if self.pending_resize_time is not None:
            if time.time() - self.pending_resize_time >= self.resize_debounce_delay:
                self._request_reload = True
                self.pending_resize_time = None

        # Check for R/Z key holds (reset commands)
        if glfw.KEY_R in self._keys_pressed:
            self._request_reset = True
        if glfw.KEY_Z in self._keys_pressed:
            self._request_full_reset = True

        # Build state snapshot
        self.state.keys_pressed = self._keys_pressed.copy()
        self.state.mouse_pos = self._mouse_pos
        self.state.left_click_this_frame = self._left_click_pending
        self.state.right_click_this_frame = self._right_click_pending
        self.state.request_reload = self._request_reload
        self.state.request_reset = self._request_reset
        self.state.request_full_reset = self._request_full_reset
        self.state.toggle_recording = self._toggle_recording

        # Reset one-shot flags
        self._left_click_pending = False
        self._right_click_pending = False
        self._request_reload = False
        self._request_reset = False
        self._request_full_reset = False
        self._toggle_recording = False

        return self.state

    def update_display_info(self, info: dict) -> None:
        """Receive read-only info for display (time, frame_count, etc.)."""
        self._display_info = info

    def render(self):
        """Render ImGui widgets - modifies self.state based on widget interactions."""
        self.imgui_renderer.process_inputs()

        imgui.new_frame()

        self.render_main_window()

        if self.show_demo_window:
            imgui.show_demo_window()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def render_main_window(self):
        imgui.begin("Simulation Controls")

        # Display info from orchestrator
        sim_time = self._display_info.get('time', 0.0)
        frame_count = self._display_info.get('frame_count', 0)
        tex_size = self._display_info.get('tex_size', (1024, 1024))
        recording_active = self._display_info.get('recording_active', False)

        imgui.text(f"Simulation Time: {sim_time:.2f}, Frame: {frame_count}")

        # Amplitude slider
        _, self.state.camera.amplitude = imgui.slider_float(
            label="amp",
            v=self.state.camera.amplitude,
            v_min=0.0,
            v_max=4.0,
        )
        imgui.text(f"Texture Size: {tex_size[0]}x{tex_size[1]}")

        # Lock speedmult to 1 when recording video
        if recording_active:
            self.state.sim.speedmult = 1
            imgui.begin_disabled()
            imgui.slider_int(label="Speed Mult (locked)", v=1, v_min=1, v_max=6)
            imgui.end_disabled()
        else:
            _, self.state.sim.speedmult = imgui.slider_int(
                label="Speed Mult",
                v=self.state.sim.speedmult,
                v_min=1,
                v_max=6,
            )

        # View dropdown
        changed, self.state.sim.current_view_option = imgui.combo(
            label="Current View",
            current_item=self.state.sim.current_view_option,
            items=self.view_option_labels + ['cam_brush']
        )

        if changed:
            if self.state.sim.current_view_option == len(self.view_option_labels):
                self.state.camera.cam_brush_mode = True
            else:
                self.state.camera.cam_brush_mode = False
                print(f"Selected: {self.view_option_labels[self.state.sim.current_view_option]}")

        # DRAIN
        _, self.state.sim.DRAIN = imgui.slider_float(
            label="DRAIN",
            v=self.state.sim.DRAIN,
            v_min=0.0,
            v_max=1.0,
        )

        imgui.separator()
        imgui.text("Camera:")
        imgui.text(f"Position: ({self.state.camera.position[0]:.1f}, {self.state.camera.position[1]:.1f})")
        imgui.text(f"Zoom: {self.state.camera.zoom:.2f}")

        imgui.separator()
        imgui.text("Screen Recording (Must have speedmult == 1):")
        _, self.state.recording.max_frames = imgui.input_int('Max Frames', self.state.recording.max_frames)
        _, self.state.recording.motion_blur_samples = imgui.input_int('Motion Blur Samples', self.state.recording.motion_blur_samples)
        _, self.state.recording.supersample_k = imgui.input_int('Supersample Kernel Width', self.state.recording.supersample_k)

        imgui.separator()
        imgui.text("Controls:")
        imgui.text("WASD - Move camera")
        imgui.text("Q/E - Zoom out/in")
        imgui.text("F1 - Toggle ImGui Demo Window")
        imgui.text("ESC - Exit")

        imgui.end()

        imgui.begin('Sliders')
        s_labels = ['Axial Force', 'Lateral Force', 'Rule Sensitivity', 'Mutation Scale']
        for i in range(len(self.state.sim.generic_sliders)):
            _, self.state.sim.generic_sliders[i] = imgui.slider_float(
                label=s_labels[i],
                v=self.state.sim.generic_sliders[i],
                v_min=-1.0,
                v_max=1.0,
            )
        _, self.state.sim.DRAG = imgui.slider_float(
            label="DRAG",
            v=self.state.sim.DRAG,
            v_min=-1.0,
            v_max=1.0,
        )
        _, self.state.sim.STRAFE_SCALE = imgui.slider_float(
            label="STRAFE_SCALE",
            v=self.state.sim.STRAFE_SCALE,
            v_min=0,
            v_max=4.0,
        )
        _, self.state.sim.TAP_STRETCH = imgui.slider_float(
            label="TAP_STRETCH",
            v=self.state.sim.TAP_STRETCH,
            v_min=-3,
            v_max=3,
        )
        _, self.state.sim.RULE_OUTPUT_GAIN = imgui.slider_float(
            label="RULE_OUTPUT_GAIN",
            v=self.state.sim.RULE_OUTPUT_GAIN,
            v_min=0.0,
            v_max=5.0,
        )
        imgui.end()

    def cleanup(self):
        self.imgui_renderer.shutdown()
