import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import random
import numpy as np
import moderngl
from pathlib import Path
from dataclasses import replace, dataclass
from state import UIState, SimState, CameraState, RecordingState
from services.config_saver import ConfigSaver, PhysicsConfig


@dataclass
class PhysicsDefaults:
    """Stores default physics values for reset functionality."""
    values: dict[str, float]
    source_filename: str | None  # None means program defaults



class UI:
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(self, window, ctx: moderngl.Context, view_option_labels: list[str]):
        self.window = window
        self.ctx = ctx
        self.view_option_labels = view_option_labels




        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        io = imgui.get_io()

        # Default font at normal size
        io.fonts.add_font_default()

        # Default font
        font_config = imgui.ImFontConfig()
        self.default_font = io.fonts.add_font_default(font_config)

        # Set up event callbacks
        self.setup_callbacks()

        # Create tooltip shader and texture
        self.tooltip_texture_size = 128
        self.setup_tooltip_shader()

        # UI-only state
        self.show_demo_window = False

        # Rule history window state
        self.show_history_window = False
        self.history_window_labels: list[tuple[int, str, str]] = []  # [(jersey_num, digit1_rgb, digit2_rgb), ...]
        self.currently_previewing_index: int | None = None

        # Tooltip state - track which slider was last hovered
        self.last_hovered_slider = None
        self.last_hovered_description = ""
        self.physics_window_interaction = False  # Track if we're interacting with sliders
        self.tooltip_start_time = time.time()  # Track time for animations

        # File save/load state
        self.save_popup_open = False
        self.save_filename_buffer = ""
        self.configs_dir = Path("physics_configs")
        self.config_saver = ConfigSaver()

        # Load submenu preview state
        self.config_files: list[str] = []  # List of available config filenames
        self.cached_configs: dict[str, PhysicsConfig] = {}  # Cached decoded configs
        self.load_submenu_was_open = False  # Track submenu open state
        self.base_sim_state: SimState | None = None  # State before preview
        self.currently_previewing: str | None = None  # Currently hovered config
        self.last_loaded_filename: str = ""  # For default save name

        # Delete confirmation state
        self.delete_confirm_filename: str | None = None

        # Overwrite confirmation state
        self.overwrite_confirm_filename: str | None = None

        # State containers (Orchestrator reads these each frame)
        self.state = UIState(
            sim=SimState(),
            camera=CameraState(),
            recording=RecordingState()
        )

        # Initialize physics defaults with program defaults
        self.current_physics_defaults = PhysicsDefaults(
            values={
                'AXIAL_FORCE': self.state.sim.AXIAL_FORCE,
                'LATERAL_FORCE': self.state.sim.LATERAL_FORCE,
                'SENSOR_GAIN': self.state.sim.SENSOR_GAIN,
                'MUTATION_SCALE': self.state.sim.MUTATION_SCALE,
                'DRAG': self.state.sim.DRAG,
                'STRAFE_POWER': self.state.sim.STRAFE_POWER,
                'SENSOR_ANGLE': self.state.sim.SENSOR_ANGLE,
                'GLOBAL_FORCE_MULT': self.state.sim.GLOBAL_FORCE_MULT,
                'SENSOR_DISTANCE': self.state.sim.SENSOR_DISTANCE,
                'TRAIL_PERSISTENCE': self.state.sim.TRAIL_PERSISTENCE,
            },
            source_filename=None
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
        self._request_delete_file = False
        self._request_preview_config = False
        self._request_clear_preview = False

        # Rule history window flags
        self._request_preview_history_rule = False
        self._request_clear_history_preview = False
        self._request_load_history_rule = False
        self._request_delete_history_rule = False
        self._history_preview_index = -1

        self._save_filename = ""
        self._load_filename = ""
        self._delete_filename = ""
        self._preview_filename = ""

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
            elif key == glfw.KEY_SPACE:
                self.state.preferences.rule_seed = random.random()
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
        self.state.request_delete_file = self._request_delete_file
        self.state.request_preview_config = self._request_preview_config
        self.state.request_clear_preview = self._request_clear_preview
        self.state.save_filename = self._save_filename
        self.state.load_filename = self._load_filename
        self.state.delete_filename = self._delete_filename
        self.state.preview_filename = self._preview_filename

        # Transfer history window flags
        self.state.request_preview_history_rule = self._request_preview_history_rule
        self.state.request_clear_history_preview = self._request_clear_history_preview
        self.state.request_load_history_rule = self._request_load_history_rule
        self.state.request_delete_history_rule = self._request_delete_history_rule
        self.state.history_preview_index = self._history_preview_index

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
        self._request_delete_file = False
        self._request_preview_config = False
        self._request_clear_preview = False
        self._save_filename = ""
        self._load_filename = ""
        self._delete_filename = ""
        self._preview_filename = ""

        # Reset history window flags
        self._request_preview_history_rule = False
        self._request_clear_history_preview = False
        self._request_load_history_rule = False
        self._request_delete_history_rule = False
        self._history_preview_index = -1

        return self.state

    def update_display_info(self, info: dict) -> None:
        """Receive read-only info for display (time, frame_count, etc.)."""
        self._display_info = info

    def set_clipboard(self, text: str) -> None:
        """Set clipboard content (used by orchestrator for config save)."""
        glfw.set_clipboard_string(self.window, text)

    def update_physics_defaults(self, filename: str) -> None:
        """Update current physics defaults from current sim state (called after file load)."""
        self.current_physics_defaults = PhysicsDefaults(
            values={
                'AXIAL_FORCE': self.state.sim.AXIAL_FORCE,
                'LATERAL_FORCE': self.state.sim.LATERAL_FORCE,
                'SENSOR_GAIN': self.state.sim.SENSOR_GAIN,
                'MUTATION_SCALE': self.state.sim.MUTATION_SCALE,
                'DRAG': self.state.sim.DRAG,
                'STRAFE_POWER': self.state.sim.STRAFE_POWER,
                'SENSOR_ANGLE': self.state.sim.SENSOR_ANGLE,
                'GLOBAL_FORCE_MULT': self.state.sim.GLOBAL_FORCE_MULT,
                'SENSOR_DISTANCE': self.state.sim.SENSOR_DISTANCE,
                'TRAIL_PERSISTENCE': self.state.sim.TRAIL_PERSISTENCE,
            },
            source_filename=filename
        )

    def render(self):
        """Render ImGui widgets - modifies self.state based on widget interactions."""
        self.imgui_renderer.process_inputs()

        imgui.new_frame()

        self.render_main_window()

        # Render history window if visible
        if self.show_history_window:
            self.render_history_window()

        if self.show_demo_window:
            imgui.show_demo_window()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def render_main_window(self):
        # Display info from orchestrator
        sim_time = self._display_info.get('time', 0.0)
        frame_count = self._display_info.get('frame_count', 0)
        tex_size = self._display_info.get('tex_size', (1024, 1024))
        recording_active = self._display_info.get('recording_active', False)

        # Apply red tint to window background when recording
        if recording_active:
            imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.3, 0.1, 0.1, 1.0))

        imgui.begin("Simulation Controls")

        imgui.text(f"Simulation Time: {sim_time:.2f}, Frame: {frame_count}")

        # Brightness slider
        _, self.state.camera.BRIGHTNESS = imgui.slider_float(
            label="Brightness",
            v=self.state.camera.BRIGHTNESS,
            v_min=0.0,
            v_max=4.0,
        )

        # Hue sensitivity slider
        _, self.state.camera.HUE_SENSITIVITY = imgui.slider_float(
            label="Hue Sensitivity",
            v=self.state.camera.HUE_SENSITIVITY,
            v_min=-1.0,
            v_max=1.0,
        )

        # Color by cohort checkbox
        _, self.state.preferences.color_by_cohort = imgui.checkbox(
            "Color by Cohort",
            self.state.preferences.color_by_cohort
        )

        # Randomize Rule Seed button
        if imgui.button("Randomize Rule Seed"):
            self.state.preferences.rule_seed = random.random()

        # Toggle History Window button
        if imgui.button("Toggle History Window"):
            self.show_history_window = not self.show_history_window

        imgui.text(f"Texture Size: {tex_size[0]}x{tex_size[1]}")

        # Lock speedmult to motion_blur_samples when recording video
        if recording_active:
            locked_value = self.state.preferences.motion_blur_samples
            imgui.begin_disabled()
            imgui.slider_int(
                label=f"Speed Mult (locked to {locked_value})",
                v=locked_value,
                v_min=1,
                v_max=6
            )
            imgui.end_disabled()
        else:
            _, self.state.preferences.speedmult = imgui.slider_int(
                label="Speed Mult",
                v=self.state.preferences.speedmult,
                v_min=1,
                v_max=6,
            )

        # Motion blur checkbox (lock during recording)
        if recording_active:
            imgui.begin_disabled()

        _, self.state.preferences.motion_blur = imgui.checkbox(
            "Motion Blur",
            self.state.preferences.motion_blur
        )

        if recording_active:
            imgui.end_disabled()

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
        _, self.state.preferences.physics_tooltips_enabled = imgui.checkbox("Physics tooltips", self.state.preferences.physics_tooltips_enabled)

        imgui.separator()
        imgui.text("Screen Recording (speedmult locked to motion blur samples):")
        _, self.state.preferences.max_frames = imgui.input_int('Max Frames', self.state.preferences.max_frames)

        # Lock motion_blur_samples during recording
        if recording_active:
            imgui.begin_disabled()

        _, self.state.preferences.motion_blur_samples = imgui.input_int(
            'Motion Blur Samples',
            self.state.preferences.motion_blur_samples
        )

        if recording_active:
            imgui.end_disabled()
            imgui.text_colored(
                imgui.ImVec4(1.0, 0.8, 0.0, 1.0),
                "(Locked during recording)"
            )

        _, self.state.preferences.supersample_k = imgui.input_int('Supersample Kernel Width', self.state.preferences.supersample_k)

        # Filename prefix input
        _, self.state.preferences.filename_prefix = imgui.input_text(
            'Filename Prefix (empty = "animation")',
            self.state.preferences.filename_prefix,
            256
        )

        imgui.separator()
        imgui.text("Controls:")
        imgui.text("WASD - Move camera")
        imgui.text("Q/E - Zoom out/in")
        imgui.text("Ctrl+C - Copy config to clipboard")
        imgui.text("Ctrl+V - Paste config from clipboard")
        imgui.text("Space - Randomize rule seed")
        imgui.text("F1 - Toggle ImGui Demo Window")
        imgui.text("ESC - Exit")

        imgui.end()

        # Restore normal window background color if it was changed
        if recording_active:
            imgui.pop_style_color()

        imgui.begin('Physics Settings', flags=imgui.WindowFlags_.menu_bar)

        # Menu bar
        load_submenu_open = False
        if imgui.begin_menu_bar():
            if imgui.begin_menu("File"):
                if imgui.menu_item("Save...", "", False)[0]:
                    self.save_popup_open = True
                    # Default to last loaded filename
                    self.save_filename_buffer = self.last_loaded_filename

                # Load submenu with preview
                if imgui.begin_menu("Load"):
                    load_submenu_open = True

                    # First frame submenu opens: cache configs and store base state
                    if not self.load_submenu_was_open:
                        self._cache_all_configs()
                        self.base_sim_state = replace(self.state.sim)
                        self.currently_previewing = None

                    if not self.config_files:
                        imgui.text_colored(imgui.ImVec4(1.0, 0.5, 0.5, 1.0), "No config files")
                    else:
                        # Calculate max filename width to size the submenu properly
                        max_text_width = 0.0
                        for fn in self.config_files:
                            text_size = imgui.calc_text_size(fn)
                            if text_size.x > max_text_width:
                                max_text_width = text_size.x

                        # Add padding for the X button (25px) and some margin
                        total_width = max_text_width + 40

                        hovered_this_frame = None
                        for filename in self.config_files:
                            # Selectable for filename with calculated width
                            clicked, _ = imgui.selectable(
                                filename, False,
                                imgui.SelectableFlags_.no_auto_close_popups,
                                imgui.ImVec2(max_text_width + 10, 0)
                            )

                            # Check if filename is hovered
                            if imgui.is_item_hovered():
                                hovered_this_frame = filename

                            # X button on same line (right after the selectable)
                            imgui.same_line()
                            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
                            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
                            if imgui.small_button(f"X##{filename}"):
                                self.delete_confirm_filename = filename
                            imgui.pop_style_color(2)

                            # Also check hover on X button for preview
                            if imgui.is_item_hovered():
                                hovered_this_frame = filename

                            if clicked:
                                # Finalize selection
                                self._load_filename = filename
                                self._request_load_file = True
                                self.last_loaded_filename = filename
                                self.base_sim_state = None
                                self.currently_previewing = None
                                imgui.close_current_popup()

                        # Handle preview on hover
                        if hovered_this_frame != self.currently_previewing:
                            # First, clear any existing preview
                            if self.currently_previewing:
                                self._request_clear_preview = True

                            if hovered_this_frame and hovered_this_frame in self.cached_configs:
                                # Apply preview config (physics locally, rule via orchestrator)
                                config = self.cached_configs[hovered_this_frame]
                                self._apply_config_to_sim_state(config)
                                self._request_preview_config = True
                                self._preview_filename = hovered_this_frame
                                self.currently_previewing = hovered_this_frame
                            elif hovered_this_frame is None and self.base_sim_state:
                                # Revert to base state
                                self._restore_base_sim_state()
                                self.currently_previewing = None

                    imgui.end_menu()

                imgui.end_menu()

            # Extras menu
            if imgui.begin_menu("Extras"):
                _, self.state.sim.DISABLE_SYMMETRY = imgui.checkbox(
                    "Disable Symmetry",
                    self.state.sim.DISABLE_SYMMETRY
                )
                _, self.state.sim.ABSOLUTE_ORIENTATION = imgui.checkbox(
                    "Absolute Orientation",
                    self.state.sim.ABSOLUTE_ORIENTATION
                )

                # Parameter Sweeps toggle
                changed, new_value = imgui.checkbox(
                    "Parameter Sweeps",
                    self.state.sim.parameter_sweeps_enabled
                )
                if changed:
                    self.state.sim.parameter_sweeps_enabled = new_value
                    # If disabling, turn off all sweeps
                    if not new_value:
                        for param in self.state.sim.x_sweeps.keys():
                            self.state.sim.x_sweeps[param] = False
                            self.state.sim.y_sweeps[param] = False
                            self.state.sim.cohort_sweeps[param] = False

                imgui.end_menu()

            imgui.end_menu_bar()

        # Handle submenu close without selection
        if self.load_submenu_was_open and not load_submenu_open:
            # Submenu just closed
            if self.base_sim_state:
                self._restore_base_sim_state()
            if self.currently_previewing:
                self._request_clear_preview = True
            self.base_sim_state = None
            self.currently_previewing = None
            self.cached_configs = {}

        self.load_submenu_was_open = load_submenu_open

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
                    filename = self.save_filename_buffer.strip()
                    filepath = self.configs_dir / f"{filename}.txt"
                    if filepath.exists():
                        # File exists, need overwrite confirmation
                        # Close save popup first, then open overwrite popup
                        self.overwrite_confirm_filename = filename
                        self.save_popup_open = False
                        imgui.close_current_popup()
                    else:
                        # File doesn't exist, save directly
                        self._save_filename = filename
                        self._request_save_file = True
                        self.save_popup_open = False
                        imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.end_popup()

        # Overwrite confirmation popup
        if self.overwrite_confirm_filename:
            imgui.open_popup("Overwrite?")

        if imgui.begin_popup_modal("Overwrite?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"File '{self.overwrite_confirm_filename}.txt' already exists.")
            imgui.text("Do you want to overwrite it?")
            imgui.separator()
            if imgui.button("Overwrite", imgui.ImVec2(120, 0)):
                self._save_filename = self.overwrite_confirm_filename
                self._request_save_file = True
                self.overwrite_confirm_filename = None
                self.save_popup_open = False
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.overwrite_confirm_filename = None
                imgui.close_current_popup()
            imgui.end_popup()

        # Delete confirmation popup
        if self.delete_confirm_filename:
            imgui.open_popup("Delete Config?")

        if imgui.begin_popup_modal("Delete Config?", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            imgui.text(f"Are you sure you want to delete '{self.delete_confirm_filename}.txt'?")
            imgui.separator()
            if imgui.button("Delete", imgui.ImVec2(120, 0)):
                self._delete_filename = self.delete_confirm_filename
                self._request_delete_file = True
                self.delete_confirm_filename = None
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                self.delete_confirm_filename = None
                imgui.close_current_popup()
            imgui.end_popup()

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Axial Force:")
            self.render_range_adjust_buttons("AXIAL_FORCE", "Axial Force", self.state.sim.AXIAL_FORCE, -1.0, 1.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("AXIAL_FORCE")
            imgui.same_line(spacing=8)

        _, self.state.sim.AXIAL_FORCE = self.slider_float_with_range_menu(
            label="Axial Force",
            param_name="AXIAL_FORCE",
            value=self.state.sim.AXIAL_FORCE,
            default_min=-1.0,
            default_max=1.0,
        )
        self.render_custom_tooltip("Axial Force",
            "Controls the strength of forces applied parallel to the direction of travel: acceleration and braking")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Lateral Force:")
            self.render_range_adjust_buttons("LATERAL_FORCE", "Lateral Force", self.state.sim.LATERAL_FORCE, -1.0, 1.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("LATERAL_FORCE")
            imgui.same_line(spacing=8)

        _, self.state.sim.LATERAL_FORCE = self.slider_float_with_range_menu(
            label="Lateral Force",
            param_name="LATERAL_FORCE",
            value=self.state.sim.LATERAL_FORCE,
            default_min=-1.0,
            default_max=1.0,
        )
        self.render_custom_tooltip("Lateral Force",
            "Controls the strength of forces applied perpendicular to the direction of travel: turning left and right.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Strafe Power:")
            self.render_range_adjust_buttons("STRAFE_POWER", "Strafe Power", self.state.sim.STRAFE_POWER, 0.0, 0.5)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("STRAFE_POWER")
            imgui.same_line(spacing=8)

        _, self.state.sim.STRAFE_POWER = self.slider_float_with_range_menu(
            label="Strafe Power",
            param_name="STRAFE_POWER",
            value=self.state.sim.STRAFE_POWER,
            default_min=0.0,
            default_max=0.5,
        )
        self.render_custom_tooltip("Strafe Power",
            "Controls particle movement without applying forces to velocity. Strafe acts as a vector added directly to position, like a little hop. Strafe power scales with Axial, Lateral, and Global force multipliers.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Global Force Mult:")
            self.render_range_adjust_buttons("GLOBAL_FORCE_MULT", "Global Force Mult", self.state.sim.GLOBAL_FORCE_MULT, 0.0, 2.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("GLOBAL_FORCE_MULT")
            imgui.same_line(spacing=8)

        _, self.state.sim.GLOBAL_FORCE_MULT = self.slider_float_with_range_menu(
            label="Global Force Mult",
            param_name="GLOBAL_FORCE_MULT",
            value=self.state.sim.GLOBAL_FORCE_MULT,
            default_min=0.0,
            default_max=2.0,
        )
        self.render_custom_tooltip("Global Force Mult",
            "Scales axial and lateral forces applied to particles, and scales strafe power. Often tuned in the opposite direction to Sensor Gain and Drag to offset exploding/vanishing particle speed.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Drag:")
            self.render_range_adjust_buttons("DRAG", "Drag", self.state.sim.DRAG, -1.0, 1.0, hard_min=-1.0, hard_max=1.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("DRAG")
            imgui.same_line(spacing=8)

        _, self.state.sim.DRAG = self.slider_float_with_range_menu(
            label="Drag",
            param_name="DRAG",
            value=self.state.sim.DRAG,
            default_min=-1.0,
            default_max=1.0,
        )
        self.render_custom_tooltip("Drag",
            "Each physics update, particle velocity is multiplied by drag like so:   vel = vel*drag + forces; So drag less than 1 means particles are being slowed down. Powerful (<0.5) drag values can prevent energetic systems from 'blowing up'")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Mutation Scale:")
            self.render_range_adjust_buttons("MUTATION_SCALE", "Mutation Scale", self.state.sim.MUTATION_SCALE, -0.5, 0.5)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("MUTATION_SCALE")
            imgui.same_line(spacing=8)

        _, self.state.sim.MUTATION_SCALE = self.slider_float_with_range_menu(
            label="Mutation Scale",
            param_name="MUTATION_SCALE",
            value=self.state.sim.MUTATION_SCALE,
            default_min=-.5,
            default_max=.5,
        )
        self.render_custom_tooltip("Mutation Scale",
            "Controls the size of the random mutations applied to a rule when a new particle is clicked. At 0, every cohort will behave exactly like the particle you clicked.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Sensor Gain:")
            self.render_range_adjust_buttons("SENSOR_GAIN", "Sensor Gain", self.state.sim.SENSOR_GAIN, 0.0, 5.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("SENSOR_GAIN")
            imgui.same_line(spacing=8)

        _, self.state.sim.SENSOR_GAIN = self.slider_float_with_range_menu(
            label="Sensor Gain",
            param_name="SENSOR_GAIN",
            value=self.state.sim.SENSOR_GAIN,
            default_min=0,
            default_max=5.0,
        )
        self.render_custom_tooltip("Sensor Gain",
            "Determines how strongly particles respond to sensor input. Higher values make particles more reactive to the trails they sense on the Canvas.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Sensor Angle:")
            self.render_range_adjust_buttons("SENSOR_ANGLE", "Sensor Angle", self.state.sim.SENSOR_ANGLE, -1.0, 1.0, hard_min=-1.0, hard_max=1.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("SENSOR_ANGLE")
            imgui.same_line(spacing=8)

        _, self.state.sim.SENSOR_ANGLE = self.slider_float_with_range_menu(
            label="Sensor Angle",
            param_name="SENSOR_ANGLE",
            value=self.state.sim.SENSOR_ANGLE,
            default_min=-1.0,
            default_max=1.0,
        )
        self.render_custom_tooltip("Sensor Angle",
            "Sets the angular offset of particle sensors from their forward direction. Determines whether particles are 'looking ahead' or 'looking behind'.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Sensor Distance:")
            self.render_range_adjust_buttons("SENSOR_DISTANCE", "Sensor Distance", self.state.sim.SENSOR_DISTANCE, 0.0, 4.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("SENSOR_DISTANCE")
            imgui.same_line(spacing=8)

        _, self.state.sim.SENSOR_DISTANCE = self.slider_float_with_range_menu(
            label="Sensor Distance",
            param_name="SENSOR_DISTANCE",
            value=self.state.sim.SENSOR_DISTANCE,
            default_min=0.0,
            default_max=4.0,
        )
        self.render_custom_tooltip("Sensor Distance",
            "Determines distance between a particle's center and where it reads the trail information from Canvas. Longer distances tend to create larger scale patterns.")

        if self.state.sim.parameter_sweeps_enabled:
            self.render_aligned_label("Trail Persistence:")
            self.render_range_adjust_buttons("TRAIL_PERSISTENCE", "Trail Persistence", self.state.sim.TRAIL_PERSISTENCE, 0.0, 1.0)
            imgui.same_line(spacing=2)
            self.render_sweep_buttons("TRAIL_PERSISTENCE")
            imgui.same_line(spacing=8)

        _, self.state.sim.TRAIL_PERSISTENCE = self.slider_float_with_range_menu(
            label="Trail Persistence",
            param_name="TRAIL_PERSISTENCE",
            value=self.state.sim.TRAIL_PERSISTENCE,
            default_min=0.0,
            default_max=1.0,
        )
        self.render_custom_tooltip("Trail Persistence",
            "Controls how long particle trails remain visible. Higher values create longer-lasting trails, lower values make trails fade quickly. Values close to 1.0 tend to create 'sharper' more stable patterns. ")

        imgui.separator()

        # Reset all slider values button
        if self.current_physics_defaults.source_filename:
            reset_button_label = f"Reset all slider values to '{self.current_physics_defaults.source_filename}'"
        else:
            reset_button_label = "Reset all slider values to defaults"

        if imgui.button(reset_button_label):
            # Reset all physics parameters to their default values
            for param_name, default_value in self.current_physics_defaults.values.items():
                setattr(self.state.sim, param_name, default_value)

        # Reset all slider ranges button
        if imgui.button("Reset all slider ranges to defaults"):
            # Clear all custom slider ranges, reverting to defaults
            self.state.preferences.slider_ranges.clear()

        # Render the tooltip if window is hovered
        self.render_physics_tooltip()

        imgui.end()

    def render_history_window(self):
        """Render rule history window with preview."""
        imgui.begin("Rule History")

        rule_history = self._display_info.get('rule_history', [])

        if not rule_history:
            imgui.text_colored(imgui.ImVec4(1.0, 0.5, 0.5, 1.0), "No rules in history")
            imgui.end()
            return

        # Sync metadata with rule history
        while len(self.history_window_labels) < len(rule_history):
            self.history_window_labels.append(self._generate_rule_label())
        while len(self.history_window_labels) > len(rule_history):
            self.history_window_labels.pop()

        # Determine how many rules to show (hide topmost if previewing)
        num_rules_to_show = len(rule_history)
        if self.currently_previewing_index is not None:
            # Previewing - hide the topmost element (it's the preview copy)
            num_rules_to_show -= 1

        # Render rules (newest first, but skip the preview if active)
        hovered_this_frame = None

        for i in range(num_rules_to_show - 1, -1, -1):
            # Get jersey number and colors
            jersey_number, color1_rgb, color2_rgb = self.history_window_labels[i]
            color1 = self._parse_rgb_color(color1_rgb)
            color2 = self._parse_rgb_color(color2_rgb)

            # Extract digits from jersey number
            digit1 = jersey_number // 10
            digit2 = jersey_number % 10

            # Render colored digits
            imgui.text_colored(imgui.ImVec4(*color1), str(digit1))
            imgui.same_line(spacing=0)
            imgui.text_colored(imgui.ImVec4(*color2), str(digit2))
            imgui.same_line(spacing=2)

            # Invisible selectable for click/hover detection
            clicked, _ = imgui.selectable(
                f"##{i}",
                False,
                imgui.SelectableFlags_.none,
                imgui.ImVec2(10, 0)  # Small width just for the hitbox
            )

            if imgui.is_item_hovered():
                hovered_this_frame = i

            # X button
            imgui.same_line()
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
            if imgui.small_button(f"X##history_{i}"):
                self._request_delete_history_rule = True
                self._history_preview_index = i
            imgui.pop_style_color(2)

            if imgui.is_item_hovered():
                hovered_this_frame = i

            if clicked:
                self._request_load_history_rule = True
                self._history_preview_index = i

        # Handle preview state changes
        if hovered_this_frame != self.currently_previewing_index:
            if self.currently_previewing_index is not None:
                self._request_clear_history_preview = True

            if hovered_this_frame is not None:
                self._request_preview_history_rule = True
                self._history_preview_index = hovered_this_frame
                self.currently_previewing_index = hovered_this_frame
            else:
                self.currently_previewing_index = None

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
        if not self.state.preferences.physics_tooltips_enabled:
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

    def _cache_all_configs(self):
        """Load and cache all config files for preview."""
        self._refresh_config_files()
        self.cached_configs = {}
        for filename in self.config_files:
            filepath = self.configs_dir / f"{filename}.txt"
            if filepath.exists():
                config_string = filepath.read_text()
                config = self.config_saver.decode_config(config_string)
                if config:
                    self.cached_configs[filename] = config

    def _apply_config_to_sim_state(self, config: PhysicsConfig):
        """Apply a config's physics settings to the current sim state."""
        self.state.sim.AXIAL_FORCE = config.axial_force
        self.state.sim.LATERAL_FORCE = config.lateral_force
        self.state.sim.SENSOR_GAIN = config.sensor_gain
        self.state.sim.MUTATION_SCALE = config.mutation_scale
        self.state.sim.DRAG = config.drag
        self.state.sim.STRAFE_POWER = config.strafe_power
        self.state.sim.SENSOR_ANGLE = config.sensor_angle
        self.state.sim.GLOBAL_FORCE_MULT = config.global_force_mult
        self.state.sim.SENSOR_DISTANCE = config.sensor_distance
        self.state.sim.TRAIL_PERSISTENCE = config.trail_persistence
        self.state.sim.DISABLE_SYMMETRY = config.disable_symmetry
        self.state.sim.ABSOLUTE_ORIENTATION = config.absolute_orientation

    def _restore_base_sim_state(self):
        """Restore sim state from saved base state."""
        if self.base_sim_state:
            self.state.sim.AXIAL_FORCE = self.base_sim_state.AXIAL_FORCE
            self.state.sim.LATERAL_FORCE = self.base_sim_state.LATERAL_FORCE
            self.state.sim.SENSOR_GAIN = self.base_sim_state.SENSOR_GAIN
            self.state.sim.MUTATION_SCALE = self.base_sim_state.MUTATION_SCALE
            self.state.sim.DRAG = self.base_sim_state.DRAG
            self.state.sim.STRAFE_POWER = self.base_sim_state.STRAFE_POWER
            self.state.sim.SENSOR_ANGLE = self.base_sim_state.SENSOR_ANGLE
            self.state.sim.GLOBAL_FORCE_MULT = self.base_sim_state.GLOBAL_FORCE_MULT
            self.state.sim.SENSOR_DISTANCE = self.base_sim_state.SENSOR_DISTANCE
            self.state.sim.TRAIL_PERSISTENCE = self.base_sim_state.TRAIL_PERSISTENCE
            self.state.sim.DISABLE_SYMMETRY = self.base_sim_state.DISABLE_SYMMETRY
            self.state.sim.ABSOLUTE_ORIENTATION = self.base_sim_state.ABSOLUTE_ORIENTATION

    def _generate_rule_label(self) -> tuple[int, str, str]:
        """Generate random jersey number with colored digits.

        Returns:
            tuple: (jersey_number, digit1_rgb_string, digit2_rgb_string)
                   e.g., (42, "255,128,64", "64,255,128")
        """
        import colorsys

        # Generate random jersey number (00-99)
        jersey_number = random.randint(0, 99)

        label_digits = []
        for _ in range(2):
            hue = random.randint(0, 255) / 255.0
            sat = random.randint(0, 150) / 255.0
            val = 1.0  # Brightness fixed at 255

            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            r_int, g_int, b_int = int(r * 255), int(g * 255), int(b * 255)
            label_digits.append(f"{r_int},{g_int},{b_int}")

        return (jersey_number, label_digits[0], label_digits[1])

    def _parse_rgb_color(self, rgb_string: str) -> tuple[float, float, float, float]:
        """Parse RGB string to ImVec4 color."""
        r, g, b = map(int, rgb_string.split(','))
        return (r / 255.0, g / 255.0, b / 255.0, 1.0)

    def slider_float_with_range_menu(self, label, param_name, value, default_min, default_max, format="%.3f"):
        """
        Create a slider with an adjustable min/max context menu and reset to defaults.
        Right-click the slider to adjust its range or reset value.

        Args:
            label: Display label for the slider
            param_name: Parameter name (key in current_physics_defaults.values)
            value: Current value
            default_min: Default minimum value
            default_max: Default maximum value
            format: Display format string

        Returns:
            tuple: (changed, new_value)
        """
        # Initialize or get current range
        if label not in self.state.preferences.slider_ranges:
            self.state.preferences.slider_ranges[label] = [default_min, default_max, default_min, default_max]

        min_val, max_val = self.state.preferences.slider_ranges[label][0], self.state.preferences.slider_ranges[label][1]

        # Create the slider
        changed, new_value = imgui.slider_float(label, value, min_val, max_val, format=format)

        # Add context menu
        _, _, reset_requested, _ = self.add_slider_context_menu(label, default_min, default_max)

        # If reset was requested, get the default value from current_physics_defaults
        if reset_requested:
            new_value = self.current_physics_defaults.values.get(param_name, value)
            changed = True

        return changed, new_value

    def add_slider_context_menu(self, slider_name, default_min, default_max):
        """
        Add a right-click context menu to adjust slider min/max values and reset to defaults.
        Call this immediately after imgui.slider_float().

        Args:
            slider_name: Unique identifier for this slider
            default_min: Default minimum value
            default_max: Default maximum value

        Returns:
            tuple: (current_min, current_max, reset_requested, range_changed)
        """
        # Initialize slider range if not exists
        if slider_name not in self.state.preferences.slider_ranges:
            self.state.preferences.slider_ranges[slider_name] = [default_min, default_max, default_min, default_max]

        min_val, max_val, def_min, def_max = self.state.preferences.slider_ranges[slider_name]
        range_changed = False
        reset_requested = False

        # Create context menu (right-click on the previous item)
        if imgui.begin_popup_context_item(f"{slider_name}_context"):
            imgui.text(f"Adjust Range: {slider_name}")
            imgui.separator()

            # Min/Max input fields
            changed_min, new_min = imgui.input_float(f"Min##{slider_name}", min_val)
            changed_max, new_max = imgui.input_float(f"Max##{slider_name}", max_val)

            if changed_min:
                self.state.preferences.slider_ranges[slider_name][0] = new_min
                range_changed = True
            if changed_max:
                self.state.preferences.slider_ranges[slider_name][1] = new_max
                range_changed = True

            imgui.separator()

            # Reset range to default button
            if imgui.button(f"Reset Range to Default##{slider_name}"):
                self.state.preferences.slider_ranges[slider_name][0] = def_min
                self.state.preferences.slider_ranges[slider_name][1] = def_max
                range_changed = True

            imgui.separator()

            # Reset value button (uses current_physics_defaults)
            if self.current_physics_defaults.source_filename:
                button_label = f"Reset value to '{self.current_physics_defaults.source_filename}'##{slider_name}"
            else:
                button_label = f"Reset value to defaults##{slider_name}"

            if imgui.button(button_label):
                reset_requested = True

            imgui.end_popup()

        return self.state.preferences.slider_ranges[slider_name][0], self.state.preferences.slider_ranges[slider_name][1], reset_requested, range_changed

    def render_aligned_label(self, label_text: str):
        """Render a right-justified label aligned to the longest label width for consistent button positioning.

        Args:
            label_text: The label text to display (e.g., "Axial Force:")
        """
        # Calculate the width of the longest label to ensure alignment
        longest_label = "Global Force Mult:"
        longest_width = imgui.calc_text_size(longest_label).x
        current_width = imgui.calc_text_size(label_text).x

        # Calculate where to start the label so it ends at the same X position (right-justified)
        label_start_x = imgui.get_style().window_padding.x + longest_width - current_width

        # Position cursor for right-justified label
        imgui.set_cursor_pos_x(label_start_x)
        imgui.text(label_text)
        imgui.same_line()

        # Position cursor at consistent X location for buttons
        target_x = imgui.get_style().window_padding.x + longest_width + 8
        imgui.set_cursor_pos_x(target_x)

    def render_sweep_buttons(self, param_name: str):
        """Render X, Y, C sweep toggle buttons for a parameter.

        Left-click cycles: off -> normal -> off
        Right-click cycles: off -> inverse -> off

        Sweep modes: 0.0 = off, 1.0 = normal (highlight), -1.0 = inverse (lowlight)

        Args:
            param_name: Name of the parameter (e.g., 'AXIAL_FORCE')
        """
        button_height = imgui.get_frame_height() * 1.75  # Slightly taller to give range buttons more room
        button_width = button_height * 1.  # Wider than tall

        # X button (Red)
        x_mode = self.state.sim.x_sweeps.get(param_name, 0.0)
        if x_mode == 1.0:  # Normal sweep - bright red (highlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.6, 0.15, 0.15, 1.0))
        elif x_mode == -1.0:  # Inverse sweep - dark red (lowlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.3*.3, 0.05*.3, 0.05*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.4*.3, 0.1*.3, 0.1*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.2, 0.03, 0.03, 1.0))
        else:  # Off - dim red
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.4, 0.1, 0.1, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.6, 0.15, 0.15, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.3, 0.08, 0.08, 1.0))

        imgui.button(f"X##{param_name}_x", imgui.ImVec2(button_width, button_height))
        if imgui.is_item_clicked(imgui.MouseButton_.left):
            self.state.sim.x_sweeps[param_name] = 1.0 if x_mode == 0.0 else 0.0
        elif imgui.is_item_clicked(imgui.MouseButton_.right):
            self.state.sim.x_sweeps[param_name] = -1.0 if x_mode == 0.0 else 0.0

        imgui.pop_style_color(3)
        imgui.same_line(spacing=2)

        # Y button (Green)
        y_mode = self.state.sim.y_sweeps.get(param_name, 0.0)
        if y_mode == 1.0:  # Normal sweep - bright green (highlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.2, 0.8, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.3, 1.0, 0.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.15, 0.6, 0.15, 1.0))
        elif y_mode == -1.0:  # Inverse sweep - dark green (lowlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.05*.3, 0.3*.3, 0.05*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.1*.3, 0.4*.3, 0.1*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.03, 0.2, 0.03, 1.0))
        else:  # Off - dim green
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.1, 0.4, 0.1, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.15, 0.6, 0.15, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.08, 0.3, 0.08, 1.0))

        imgui.button(f"Y##{param_name}_y", imgui.ImVec2(button_width, button_height))
        if imgui.is_item_clicked(imgui.MouseButton_.left):
            self.state.sim.y_sweeps[param_name] = 1.0 if y_mode == 0.0 else 0.0
        elif imgui.is_item_clicked(imgui.MouseButton_.right):
            self.state.sim.y_sweeps[param_name] = -1.0 if y_mode == 0.0 else 0.0

        imgui.pop_style_color(3)
        imgui.same_line(spacing=2)

        # C button (Yellow)
        c_mode = self.state.sim.cohort_sweeps.get(param_name, 0.0)
        if c_mode == 1.0:  # Normal sweep - bright yellow (highlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.9, 0.9, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 1.0, 0.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.7, 0.7, 0.15, 1.0))
        elif c_mode == -1.0:  # Inverse sweep - dark yellow/brown (lowlight)
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.3*.3, 0.3*.3, 0.05*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.4*.3, 0.4*.3, 0.1*.3, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.2*.3, 0.2*.3, 0.03*.3, 1.0))
        else:  # Off - dim yellow
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.4, 0.4, 0.1, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(0.6, 0.6, 0.15, 1.0))
            imgui.push_style_color(imgui.Col_.button_active, imgui.ImVec4(0.3, 0.3, 0.08, 1.0))

        imgui.button(f"C##{param_name}_c", imgui.ImVec2(button_width, button_height))
        if imgui.is_item_clicked(imgui.MouseButton_.left):
            self.state.sim.cohort_sweeps[param_name] = 1.0 if c_mode == 0.0 else 0.0
        elif imgui.is_item_clicked(imgui.MouseButton_.right):
            self.state.sim.cohort_sweeps[param_name] = -1.0 if c_mode == 0.0 else 0.0

        imgui.pop_style_color(3)

    def adjust_slider_range(self, slider_label: str, current_value: float, default_min: float, default_max: float, widen: bool, strength: float = 2.0, hard_min: float = None, hard_max: float = None):
        """Adjust the min/max range for a slider, widening or narrowing around current value.

        Args:
            slider_label: Label of the slider (e.g., 'Axial Force')
            current_value: Current slider value (x in the formula)
            default_min: Default minimum value
            default_max: Default maximum value
            widen: True to widen, False to narrow
            strength: Strength parameter (S in formula when widening, 1/S when narrowing)
            hard_min: Optional hard minimum limit (e.g., -1.0 for Drag/Sensor Angle)
            hard_max: Optional hard maximum limit (e.g., 1.0 for Drag/Sensor Angle)
        """
        # Get current range - handle both 2-element and 4-element formats
        if slider_label in self.state.preferences.slider_ranges:
            range_data = self.state.preferences.slider_ranges[slider_label]
            # slider_ranges can be [L, H] or [L, H, default_min, default_max]
            L, H = range_data[0], range_data[1]
        else:
            L, H = default_min, default_max

        # Calculate S based on widen/narrow
        x = current_value
        S = strength if widen else (1.0 / strength)

        # Apply the formulas
        # L' = x - S*( (x-L)/2. + (H-L)/4. )
        # H' = L' + S*(H-L)
        L_prime = x - S * ((x - L) / 2.0 + (H - L) / 4.0)
        H_prime = L_prime + S * (H - L)

        # Apply hard limits if specified (for sliders like Drag and Sensor Angle)
        if hard_min is not None:
            L_prime = max(L_prime, hard_min)
        if hard_max is not None:
            H_prime = min(H_prime, hard_max)

        # Update the range in preferences
        self.state.preferences.slider_ranges[slider_label] = [L_prime, H_prime,default_min,default_max]

    def render_range_adjust_buttons(self, param_name: str, slider_label: str, current_value: float, default_min: float, default_max: float, hard_min: float = None, hard_max: float = None):
        """Render widen/narrow buttons for adjusting slider range.

        Args:
            param_name: Name of the parameter (e.g., 'AXIAL_FORCE')
            slider_label: Label of the slider (e.g., 'Axial Force')
            current_value: Current slider value
            default_min: Default minimum value
            default_max: Default maximum value
            hard_min: Optional hard minimum limit (e.g., -1.0 for Drag/Sensor Angle)
            hard_max: Optional hard maximum limit (e.g., 1.0 for Drag/Sensor Angle)
        """
        # Match the height of the XYC sweep buttons (which are 1.35x frame height)
        total_height = imgui.get_frame_height() * 1.43
        button_height = total_height / 2.0  # Half height for stacked buttons
        button_width = imgui.get_frame_height() * 1.23  # Same width as sweep buttons

        # Begin a group to keep buttons together
        imgui.begin_group()
        imgui.push_font(self.default_font,12)
        # Widen button
        if imgui.button(f"^##widen_{param_name}", imgui.ImVec2(button_width, button_height)):
            self.adjust_slider_range(slider_label, current_value, default_min, default_max, widen=True, hard_min=hard_min, hard_max=hard_max)

        # Narrow button
        if imgui.button(f"v##narrow_{param_name}", imgui.ImVec2(button_width, button_height)):
            self.adjust_slider_range(slider_label, current_value, default_min, default_max, widen=False, hard_min=hard_min, hard_max=hard_max)
        imgui.pop_font()
        imgui.end_group()

    def cleanup(self):
        self.tooltip_fbo.release()
        self.tooltip_texture.release()
        self.tooltip_program.release()
        self.imgui_renderer.shutdown()
