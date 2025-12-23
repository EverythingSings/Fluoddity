import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import numpy as np
import moderngl
from pathlib import Path
from state import UIState, SimState, CameraState, RecordingState


def create_test_pattern(size=128):
    """Create a simple test pattern texture data."""
    data = np.zeros((size, size, 4), dtype=np.uint8)

    # Create a checkerboard pattern with colored squares
    square_size = size // 8
    for y in range(size):
        for x in range(size):
            square_x = x // square_size
            square_y = y // square_size

            if (square_x + square_y) % 2 == 0:
                # Red squares
                data[y, x] = [255, 0, 0, 255]
            else:
                # Blue squares
                data[y, x] = [0, 0, 255, 255]

    # Add a green border
    data[0, :] = [0, 255, 0, 255]  # Top
    data[-1, :] = [0, 255, 0, 255]  # Bottom
    data[:, 0] = [0, 255, 0, 255]  # Left
    data[:, -1] = [0, 255, 0, 255]  # Right

    return data


class UI:
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(self, window, ctx: moderngl.Context, view_option_labels: list[str]):
        self.window = window
        self.ctx = ctx
        self.view_option_labels = view_option_labels

        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        # Set up event callbacks
        self.setup_callbacks()

        # Create tooltip shader and texture
        self.tooltip_texture_size = 128
        self.setup_tooltip_shader()

        # UI-only state
        self.show_demo_window = False
        self.physics_tooltips_enabled = True  # Control tooltip visibility

        # Tooltip state - track which slider was last hovered
        self.last_hovered_slider = None
        self.last_hovered_description = ""
        self.physics_window_interaction = False  # Track if we're interacting with sliders
        self.tooltip_start_time = time.time()  # Track time for animations

        # File save/load popup state
        self.save_popup_open = False
        self.load_popup_open = False
        self.save_filename_buffer = ""
        self.config_files: list[str] = []  # List of available config files
        self.configs_dir = Path("physics_configs")

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
        self._request_save_config = False
        self._request_load_config = False
        self._request_save_file = False
        self._request_load_file = False
        self._save_filename = ""
        self._load_filename = ""

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

    def setup_tooltip_shader(self):
        """Create shader program and texture for tooltip graphics."""
        # Simple vertex shader for full-screen quad
        vert_shader = """
        #version 150
        in vec2 in_vert;
        out vec2 texcoord;
        void main() {
            texcoord = in_vert * 0.5 + 0.5;
            gl_Position = vec4(in_vert, 0.0, 1.0);
        }
        """

        # Load fragment shader
        with open('shaders/tooltip_graphic.frag', 'r') as f:
            frag_shader = f.read()

        # Create shader program
        self.tooltip_program = self.ctx.program(
            vertex_shader=vert_shader,
            fragment_shader=frag_shader
        )

        # Create full-screen quad
        vertices = np.array([
            -1.0, -1.0,
             1.0, -1.0,
             1.0,  1.0,
            -1.0,  1.0,
        ], dtype='f4')

        vbo = self.ctx.buffer(vertices.tobytes())
        self.tooltip_vao = self.ctx.vertex_array(
            self.tooltip_program,
            [(vbo, '2f', 'in_vert')]
        )

        # Create framebuffer and texture for rendering
        self.tooltip_texture = self.ctx.texture(
            size=(self.tooltip_texture_size, self.tooltip_texture_size),
            components=4
        )
        self.tooltip_fbo = self.ctx.framebuffer(color_attachments=[self.tooltip_texture])
        self.tooltip_texture_id = imgui.ImTextureRef(self.tooltip_texture.glo)

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
            ctrl_pressed = mods & glfw.MOD_CONTROL

            # Config save/load with Ctrl+C/Ctrl+V
            if ctrl_pressed and key == glfw.KEY_C:
                self._request_save_config = True
            elif ctrl_pressed and key == glfw.KEY_V:
                self._request_load_config = True
            elif key == glfw.KEY_V:
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
        self.state.request_save_config = self._request_save_config
        self.state.request_load_config = self._request_load_config
        self.state.request_save_file = self._request_save_file
        self.state.request_load_file = self._request_load_file
        self.state.save_filename = self._save_filename
        self.state.load_filename = self._load_filename

        # Read clipboard content if load is requested
        if self._request_load_config:
            clipboard = glfw.get_clipboard_string(self.window)
            self.state.clipboard_text = clipboard if clipboard else ""
        else:
            self.state.clipboard_text = ""

        # Reset one-shot flags
        self._left_click_pending = False
        self._right_click_pending = False
        self._request_reload = False
        self._request_reset = False
        self._request_full_reset = False
        self._toggle_recording = False
        self._request_save_config = False
        self._request_load_config = False
        self._request_save_file = False
        self._request_load_file = False
        self._save_filename = ""
        self._load_filename = ""

        return self.state

    def update_display_info(self, info: dict) -> None:
        """Receive read-only info for display (time, frame_count, etc.)."""
        self._display_info = info

    def set_clipboard(self, text: str) -> None:
        """Set clipboard content (used by orchestrator for config save)."""
        glfw.set_clipboard_string(self.window, text)

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

        # Brightness slider
        _, self.state.camera.BRIGHTNESS = imgui.slider_float(
            label="Brightness",
            v=self.state.camera.BRIGHTNESS,
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

        imgui.separator()
        imgui.text("Camera:")
        imgui.text(f"Position: ({self.state.camera.position[0]:.1f}, {self.state.camera.position[1]:.1f})")
        imgui.text(f"Zoom: {self.state.camera.zoom:.2f}")

        imgui.separator()
        _, self.physics_tooltips_enabled = imgui.checkbox("Physics tooltips", self.physics_tooltips_enabled)

        imgui.separator()
        imgui.text("Screen Recording (Must have speedmult == 1):")
        _, self.state.recording.max_frames = imgui.input_int('Max Frames', self.state.recording.max_frames)
        _, self.state.recording.motion_blur_samples = imgui.input_int('Motion Blur Samples', self.state.recording.motion_blur_samples)
        _, self.state.recording.supersample_k = imgui.input_int('Supersample Kernel Width', self.state.recording.supersample_k)

        imgui.separator()
        imgui.text("Controls:")
        imgui.text("WASD - Move camera")
        imgui.text("Q/E - Zoom out/in")
        imgui.text("Ctrl+C - Copy config to clipboard")
        imgui.text("Ctrl+V - Paste config from clipboard")
        imgui.text("F1 - Toggle ImGui Demo Window")
        imgui.text("ESC - Exit")

        imgui.end()

        imgui.begin('Physics Settings', flags=imgui.WindowFlags_.menu_bar)

        # Menu bar
        if imgui.begin_menu_bar():
            if imgui.begin_menu("File"):
                if imgui.menu_item("Save...", "", False)[0]:
                    self.save_popup_open = True
                    self.save_filename_buffer = ""
                if imgui.menu_item("Load...", "", False)[0]:
                    self.load_popup_open = True
                    self._refresh_config_files()
                imgui.end_menu()
            imgui.end_menu_bar()

        # Save popup modal
        if self.save_popup_open:
            imgui.open_popup("Save Config")

        if imgui.begin_popup_modal("Save Config", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text("Enter filename (without extension):")
            _, self.save_filename_buffer = imgui.input_text(
                "##filename",
                self.save_filename_buffer,
            )

            imgui.separator()
            if imgui.button("Save", imgui.ImVec2(120, 0)):
                if self.save_filename_buffer.strip():
                    self._save_filename = self.save_filename_buffer.strip()
                    self._request_save_file = True
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        # Load popup modal
        if self.load_popup_open:
            imgui.open_popup("Load Config")

        if imgui.begin_popup_modal("Load Config", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text("Select a config file:")
            imgui.separator()

            if not self.config_files:
                imgui.text_colored(imgui.ImVec4(1.0, 0.5, 0.5, 1.0), "No config files found")
            else:
                for filename in self.config_files:
                    if imgui.selectable(filename, False)[0]:
                        self._load_filename = filename
                        self._request_load_file = True
                        self.load_popup_open = False
                        imgui.close_current_popup()
                        break

            imgui.separator()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.load_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        _, self.state.sim.AXIAL_FORCE = imgui.slider_float(
            label="Axial Force",
            v=self.state.sim.AXIAL_FORCE,
            v_min=-1.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Axial Force",
            "Controls the force applied in the direction particles are facing. Positive values push particles forward, negative values pull them backward.")

        _, self.state.sim.LATERAL_FORCE = imgui.slider_float(
            label="Lateral Force",
            v=self.state.sim.LATERAL_FORCE,
            v_min=-1.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Lateral Force",
            "Controls the force applied perpendicular to the direction particles are facing. Affects sideways movement and strafing behavior.")

        _, self.state.sim.SENSOR_GAIN = imgui.slider_float(
            label="Sensor Gain",
            v=self.state.sim.SENSOR_GAIN,
            v_min=-1.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Sensor Gain",
            "Determines how strongly particles respond to sensor input. Higher values make particles more reactive to their neighbors.")

        _, self.state.sim.MUTATION_SCALE = imgui.slider_float(
            label="Mutation Scale",
            v=self.state.sim.MUTATION_SCALE,
            v_min=-1.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Mutation Scale",
            "Controls the amount of random variation in particle behavior. Higher values introduce more chaos and unpredictability.")

        _, self.state.sim.DRAG = imgui.slider_float(
            label="Drag",
            v=self.state.sim.DRAG,
            v_min=-1.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Drag",
            "Simulates air resistance and friction. Higher values slow particles down more quickly, lower values allow particles to maintain momentum.")

        _, self.state.sim.STRAFE_POWER = imgui.slider_float(
            label="Strafe Power",
            v=self.state.sim.STRAFE_POWER,
            v_min=0,
            v_max=4.0,
        )
        self.render_custom_tooltip("Strafe Power",
            "Amplifies the lateral movement force. Higher values enable more aggressive sideways motion and circular patterns.")

        _, self.state.sim.SENSOR_ANGLE = imgui.slider_float(
            label="Sensor Angle",
            v=self.state.sim.SENSOR_ANGLE,
            v_min=-3,
            v_max=3,
        )
        self.render_custom_tooltip("Sensor Angle",
            "Sets the angular offset of particle sensors from their forward direction. Affects how particles perceive their surroundings.")

        _, self.state.sim.GLOBAL_FORCE_MULT = imgui.slider_float(
            label="Global Force Multiplier",
            v=self.state.sim.GLOBAL_FORCE_MULT,
            v_min=0.0,
            v_max=5.0,
        )
        self.render_custom_tooltip("Global Force Multiplier",
            "Scales all forces applied to particles. Acts as a master speed control - higher values create faster, more energetic simulations.")

        _, self.state.sim.SENSOR_DISTANCE = imgui.slider_float(
            label="Sensor Distance",
            v=self.state.sim.SENSOR_DISTANCE,
            v_min=0.0,
            v_max=5.0,
        )
        self.render_custom_tooltip("Sensor Distance",
            "Determines how far ahead particles can sense their environment. Longer distances enable more anticipatory behavior.")

        _, self.state.sim.TRAIL_PERSISTENCE = imgui.slider_float(
            label="Trail Persistence",
            v=self.state.sim.TRAIL_PERSISTENCE,
            v_min=0.0,
            v_max=1.0,
        )
        self.render_custom_tooltip("Trail Persistence",
            "Controls how long particle trails remain visible. Higher values create longer-lasting trails, lower values make trails fade quickly.")

        # Render the tooltip if window is hovered
        self.render_physics_tooltip()

        imgui.end()

    def update_tooltip_texture(self):
        """Render the tooltip graphic to texture using shader."""
        # Set time uniform for animations
        current_time = time.time() - self.tooltip_start_time
        self.tooltip_program['time'] = current_time * 3.0  # Speed up animation a bit

        # Set sensor angle (raw value, not normalized)
        self.tooltip_program['SENSOR_ANGLE'] = self.state.sim.SENSOR_ANGLE

        # Set MODE bools based on which slider is hovered
        self.tooltip_program['AXIAL_MODE'] = (self.last_hovered_slider == "Axial Force")
        self.tooltip_program['LATERAL_MODE'] = (self.last_hovered_slider == "Lateral Force")
        self.tooltip_program['SENSOR_MODE'] = (self.last_hovered_slider == "Sensor Gain")
        self.tooltip_program['DRAG_MODE'] = (self.last_hovered_slider == "Drag")
        self.tooltip_program['ANGLE_MODE'] = (self.last_hovered_slider == "Sensor Angle")
        self.tooltip_program['DISTANCE_MODE'] = (self.last_hovered_slider == "Sensor Distance")
        self.tooltip_program['TRAIL_MODE'] = (self.last_hovered_slider == "Trail Persistence")
        self.tooltip_program['GLOBAL_MODE'] = (self.last_hovered_slider == "Global Force Multiplier")
        self.tooltip_program['STRAFE_MODE'] = (self.last_hovered_slider == "Strafe Power")
        self.tooltip_program['MUTATION_MODE'] = (self.last_hovered_slider == "Mutation Scale")

        # Render to framebuffer
        self.tooltip_fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.tooltip_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
        self.ctx.screen.use()  # Return to default framebuffer

    def render_custom_tooltip(self, label: str, description: str):
        """Render a custom tooltip anchored to the right edge of a window.

        Args:
            label: The label of the slider
            description: Description text to display in the tooltip
        """
        # Track which slider is currently hovered
        if imgui.is_item_hovered():
            self.last_hovered_slider = label
            self.last_hovered_description = description

        # Track if any item is being actively manipulated (dragged)
        if imgui.is_item_active():
            self.physics_window_interaction = True

    def render_physics_tooltip(self):
        """Render the tooltip if mouse is over the Physics Settings window."""
        # Early exit if tooltips are disabled
        if not self.physics_tooltips_enabled:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        # Check if physics settings window is hovered or if we're actively interacting with it
        physics_window_hovered = imgui.is_window_hovered()

        # First, check if we should show the tooltip at all
        # We need to render it at least once to check if IT is hovered
        should_show = (physics_window_hovered or
                      self.physics_window_interaction or
                      self.last_hovered_slider is not None)

        if not should_show:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        if self.last_hovered_slider is None:
            self.physics_window_interaction = False
            return

        # Update the tooltip texture with current slider values
        self.update_tooltip_texture()

        # Get the position and size of the anchor window
        window_pos = imgui.get_window_pos()
        window_size = imgui.get_window_size()

        # Calculate tooltip position (right edge of the anchor window)
        tooltip_x = window_pos.x + window_size.x
        tooltip_y = window_pos.y

        # Set next window position
        imgui.set_next_window_pos(imgui.ImVec2(tooltip_x, tooltip_y))

        # Begin a borderless, no-move, no-focus tooltip window
        # Note: no_focus_on_appearing allows clicking to gain focus, just not automatic focus
        imgui.begin(
            "##SliderTooltip",
            flags=(
                imgui.WindowFlags_.no_title_bar |
                imgui.WindowFlags_.no_move |
                imgui.WindowFlags_.no_resize |
                imgui.WindowFlags_.always_auto_resize |
                imgui.WindowFlags_.no_focus_on_appearing |
                imgui.WindowFlags_.no_nav
            )
        )

        # Display the shader-rendered tooltip graphic
        imgui.image(
            self.tooltip_texture_id,
            imgui.ImVec2(self.tooltip_texture_size, self.tooltip_texture_size)
        )

        # Display slider name and description
        imgui.separator()
        imgui.text(f"Parameter: {self.last_hovered_slider}")
        imgui.separator()
        imgui.text_wrapped(self.last_hovered_description)

        # Check if tooltip itself is hovered (must be after content is rendered)
        tooltip_hovered = imgui.is_window_hovered()

        imgui.end()

        # Now decide if we should keep the tooltip visible next frame
        # Keep it if: physics window hovered, tooltip hovered, or actively dragging
        if not physics_window_hovered and not tooltip_hovered and not self.physics_window_interaction:
            self.last_hovered_slider = None

        # Reset interaction flag for next frame
        self.physics_window_interaction = False

    def _refresh_config_files(self):
        """Scan physics_configs directory for .txt files."""
        self.config_files = []
        if self.configs_dir.exists():
            for f in sorted(self.configs_dir.glob("*.txt")):
                # Store just the stem (filename without extension)
                self.config_files.append(f.stem)

    def cleanup(self):
        self.tooltip_fbo.release()
        self.tooltip_texture.release()
        self.tooltip_program.release()
        self.imgui_renderer.shutdown()
