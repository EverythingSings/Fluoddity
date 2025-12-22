import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import sim
import numpy as np
from utilities.gl_helpers import readback_rule, set_rule_uniform, tryset
from utilities.vid_saver import VidSaver

class UI:
    def __init__(self, sim: sim.Sim, camera, window):
        self.sim = sim
        self.camera = camera
        self.window = window
        self.mouse_pos = (0, 0)

        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        # Set up event callbacks
        self.setup_callbacks()

        # UI state
        self.show_demo_window = False

        # History
        self.rule_history = []

        # Key tracking
        self.keys_pressed = set()
        self.last_update_time = time.time()

        # Screen recording
        self.recorder_max_frames = 150 * 12
        self.motion_blur_samps = 12
        self.supersample_k = 2
        self.recorder = VidSaver()

        # Resize debouncing
        self.pending_resize_time = None
        self.resize_debounce_delay = 0.15  # seconds

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
        # Debounce: just record the time, actual reload happens in render()
        self.pending_resize_time = time.time()

    def full_reload(self):
        """Reload shaders and restore rule uniform."""
        self.sim.reload()
        if len(self.rule_history) > 0:
            set_rule_uniform(self.sim.entity_update_program, self.rule_history[-1])
        self.camera.reload()

    def mouse_button_callback(self, window, button, action, mods):
        if self.imgui_mouse_callback:
            self.imgui_mouse_callback(window, button, action, mods)

        if imgui.get_io().want_capture_mouse:
            return

        if action != glfw.PRESS:
            return

        if button == glfw.MOUSE_BUTTON_LEFT:
            ent_cache = np.frombuffer(self.sim.entities.read(), dtype=np.float32)
            tmouse = self.camera.screen_to_tex(self.mouse_pos)
            xs = ent_cache[::12].copy()
            ys = ent_cache[1::12].copy()
            xs = xs / 2. + .5
            ys = ys / 2. + .5
            xs -= tmouse[0]
            ys -= tmouse[1]
            xs = xs ** 2
            ys = ys ** 2
            xs += ys
            focused_id = xs.argmin()
            print(focused_id)
            targ_rule = readback_rule(self.sim.rule_buffer, focused_id)
            self.rule_history.append(targ_rule)
            set_rule_uniform(self.sim.entity_update_program, targ_rule)
        elif button == glfw.MOUSE_BUTTON_RIGHT:
            if len(self.rule_history) > 1:
                self.rule_history.pop()
                prev_rule = self.rule_history[-1]
                set_rule_uniform(self.sim.entity_update_program, prev_rule)
            else:
                self.rule_history = []
                set_rule_uniform(self.sim.entity_update_program, np.zeros((10, 8), dtype=np.float32))

    def cursor_pos_callback(self, window, xpos, ypos):
        if self.imgui_cursor_callback:
            self.imgui_cursor_callback(window, xpos, ypos)
        self.mouse_pos = (xpos, ypos)

    def scroll_callback(self, window, xoffset, yoffset):
        if self.imgui_scroll_callback:
            self.imgui_scroll_callback(window, xoffset, yoffset)

    def key_callback(self, window, key, scancode, action, mods):
        if self.imgui_key_callback:
            self.imgui_key_callback(window, key, scancode, action, mods)

        if imgui.get_io().want_capture_keyboard:
            return

        if action == glfw.PRESS:
            self.keys_pressed.add(key)
        elif action == glfw.RELEASE:
            self.keys_pressed.discard(key)

        if key == glfw.KEY_V and action == glfw.PRESS:
            self.full_reload()

        if key == glfw.KEY_P and action == glfw.PRESS:
            if self.recorder.active:
                self.recorder.finish()
            else:
                self.recorder.active = True

        if key == glfw.KEY_G and action == glfw.PRESS:
            self.sim.going = not self.sim.going

        if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
            glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_F1 and action == glfw.PRESS:
            self.show_demo_window = not self.show_demo_window

    def char_callback(self, window, char):
        if self.imgui_char_callback:
            self.imgui_char_callback(window, char)

    def update_cam(self):
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time

        move_speed = 2.0 * dt
        zoom_speed = 2.6 * dt

        move_speed *= self.camera.zoom

        if glfw.KEY_W in self.keys_pressed:
            self.camera.position[1] -= move_speed
        if glfw.KEY_S in self.keys_pressed:
            self.camera.position[1] += move_speed
        if glfw.KEY_A in self.keys_pressed:
            self.camera.position[0] -= move_speed
        if glfw.KEY_D in self.keys_pressed:
            self.camera.position[0] += move_speed

        if glfw.KEY_E in self.keys_pressed:
            self.camera.zoom *= (1.0 - zoom_speed)
        if glfw.KEY_Q in self.keys_pressed:
            self.camera.zoom *= (1.0 + zoom_speed)

        if glfw.KEY_R in self.keys_pressed:
            self.sim.reset()
        if glfw.KEY_Z in self.keys_pressed:
            self.sim.reset()
            self.rule_history = []
            set_rule_uniform(self.sim.entity_update_program, np.zeros((10, 8), dtype=np.float32))

    def render(self):
        self.update_cam()

        # Check for pending resize (debounced)
        if self.pending_resize_time is not None:
            if time.time() - self.pending_resize_time >= self.resize_debounce_delay:
                self.full_reload()
                self.pending_resize_time = None

        self.imgui_renderer.process_inputs()

        imgui.new_frame()

        self.render_main_window()

        if self.show_demo_window:
            imgui.show_demo_window()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def render_main_window(self):
        imgui.begin("Simulation Controls")
        imgui.text(f"Simulation Time: {self.sim.time:.2f}, Frame: {self.sim.frame_count}")

        width, height = self.sim.view_tex.size
        _, self.camera.amplitude = imgui.slider_float(
            label="amp",
            v=self.camera.amplitude,
            v_min=0.0,
            v_max=4.0,
        )
        imgui.text(f"Texture Size: {width}x{height}")

        _, self.sim.speedmult = imgui.slider_int(
            label="Speed Mult",
            v=self.sim.speedmult,
            v_min=1,
            v_max=6,
        )

        # Camera dropdown
        changed, self.sim.current_view_option = imgui.combo(
            label="Current View",
            current_item=self.sim.current_view_option,
            items=self.sim.view_option_labels + ['cam_brush']
        )

        if changed:
            if self.sim.current_view_option == len(self.sim.view_option_labels):
                self.camera.cam_brush_mode = True
            else:
                self.camera.cam_brush_mode = False
                print(f"Selected: {self.sim.view_option_labels[self.sim.current_view_option]}")
                self.sim.view_tex = self.sim.view_options[self.sim.current_view_option]

        # DRAIN
        _, self.sim.DRAIN = imgui.slider_float(
            label="DRAIN",
            v=self.sim.DRAIN,
            v_min=0.0,
            v_max=1.0,
        )

        imgui.separator()
        imgui.text("Camera:")
        imgui.text(f"Position: ({self.camera.position[0]:.1f}, {self.camera.position[1]:.1f})")
        imgui.text(f"Zoom: {self.camera.zoom:.2f}")

        imgui.separator()
        imgui.text("Screen Recording (Must have speedmult == 1):")
        _, self.recorder_max_frames = imgui.input_int('Max Frames', self.recorder_max_frames)
        _, self.motion_blur_samps = imgui.input_int('Motion Blur Samples', self.motion_blur_samps)
        _, self.supersample_k = imgui.input_int('Supersample Kernel Width', self.supersample_k)

        imgui.separator()
        imgui.text("Controls:")
        imgui.text("WASD - Move camera")
        imgui.text("Q/E - Zoom out/in")
        imgui.text("F1 - Toggle ImGui Demo Window")
        imgui.text("ESC - Exit")

        imgui.end()

        imgui.begin('Sliders')
        s_labels = ['Axial Force', 'Lateral Force', 'Rule Sensitivity', 'Mutation Scale']
        for i in range(len(self.sim.generic_sliders)):
            _, self.sim.generic_sliders[i] = imgui.slider_float(
                label=s_labels[i],
                v=self.sim.generic_sliders[i],
                v_min=-1.0,
                v_max=1.0,
            )
        _, self.sim.DRAG = imgui.slider_float(
            label=f"DRAG",
            v=self.sim.DRAG,
            v_min=-1.0,
            v_max=1.0,
        )
        _, self.sim.STRAFE_SCALE = imgui.slider_float(
            label=f"STRAFE_SCALE",
            v=self.sim.STRAFE_SCALE,
            v_min=0,
            v_max=4.0,
        )
        _, self.sim.TAP_STRETCH = imgui.slider_float(
            label=f"TAP_STRETCH",
            v=self.sim.TAP_STRETCH,
            v_min=-3,
            v_max=3,
        )
        _, self.sim.RULE_OUTPUT_GAIN = imgui.slider_float(
            label=f"RULE_OUTPUT_GAIN",
            v=self.sim.RULE_OUTPUT_GAIN,
            v_min=0.0,
            v_max=5.0,
        )
        imgui.end()

    def cleanup(self):
        self.imgui_renderer.shutdown()
        if self.recorder.active:
            self.recorder.finish()
