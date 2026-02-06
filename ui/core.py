"""Core UI class: initialization, GLFW callbacks, state management, render dispatch.

The UI class inherits from all mixin modules via multiple inheritance.
Each mixin provides render methods for specific windows/panels.
All methods share the same `self` for access to shared state.
"""
import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import numpy as np
import moderngl
from dataclasses import dataclass
from state import UIState, SimState, CameraState, RecordingState
from services.config_saver import ConfigSaver, PhysicsConfig
from utilities.keybinding_management import KeybindingManager
from utilities.paths import get_user_physics_configs_dir, get_app_physics_configs_dir

from .popup_modals import PopupModalsMixin
from .help_windows import HelpWindowsMixin
from .slider_widgets import SliderWidgetsMixin
from .config_browser import ConfigBrowserMixin
from .history_window import HistoryWindowMixin
from .preferences_window import PreferencesWindowMixin
from .menu_bar import MenuBarMixin
from .physics_window import PhysicsWindowMixin


@dataclass
class PhysicsDefaults:
    """Stores default physics values for reset functionality."""
    values: dict[str, float]
    source_filename: str | None  # None means program defaults


class UI(
    MenuBarMixin,
    PreferencesWindowMixin,
    HelpWindowsMixin,
    PopupModalsMixin,
    PhysicsWindowMixin,
    HistoryWindowMixin,
    ConfigBrowserMixin,
    SliderWidgetsMixin,
):
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(self, window, ctx: moderngl.Context, view_option_labels: list[str], multi_load_service=None):
        self.window = window
        self.ctx = ctx
        self.view_option_labels = view_option_labels
        self.multi_load_service = multi_load_service

        # Initialize keybinding manager
        self.keybindings = KeybindingManager()

        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable  # Enable docking

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
        self.show_physics_settings_window = True  # Physics settings window (always visible, but can be hidden with sidebar)
        self.show_video_recording_window = False  # Video recording controls window
        self.show_sidebar = True  # Controls visibility of Physics Settings and Preferences windows

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
        # Physics configs: app dir for bundled (Core/Advanced), user dir for user-created
        self.app_configs_dir = get_app_physics_configs_dir()
        self.user_configs_dir = get_user_physics_configs_dir()
        self.config_saver = ConfigSaver()

        # Load submenu preview state
        self.config_files: list[str] = []  # List of available config filenames (DEPRECATED: use config_files_by_category)
        self.config_files_by_category: dict[str, list[str]] = {}  # Config filenames organized by category (Core/Custom/Advanced)
        self.cached_configs: dict[str, PhysicsConfig] = {}  # Cached decoded configs (keys: "Category/filename")
        self.load_submenu_was_open = False  # Track submenu open state
        self.cached_config: str | None = None  # JSON string of config when menu opened
        self.preview_rule_pushed: bool = False  # Whether we pushed a preview rule
        self.currently_previewing: str | None = None  # Currently hovered config filename
        self.currently_previewing_category: str | None = None  # Category of currently hovered config
        self.currently_open_project: str = "_Default"  # Currently open project name
        # Track which load menu is open: None=neither, False=standard, True=watercolor
        self.load_menu_watercolor_mode: bool | None = None
        self._load_watercolor_override: bool | None = None  # Override for load operation

        # Delete confirmation state
        self.delete_confirm_filename: str | None = None
        self.delete_confirm_category: str | None = None  # Category for delete confirmation

        # Overwrite confirmation state
        self.overwrite_confirm_filename: str | None = None

        # Menu auto-close state
        self.main_menu_bar_has_open_menu: bool = False  # Track if main menu bar has open menus
        self.physics_menu_bar_has_open_menu: bool = False  # Track if physics menu bar has open menus
        self.force_close_main_menus: bool = False  # Signal to close main menu bar menus
        self.force_close_physics_menus: bool = False  # Signal to close physics menu bar menus

        # Track last applied world size to detect changes
        self._last_applied_world_size: float = 1.0

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
                'TRAIL_DIFFUSION': self.state.sim.TRAIL_DIFFUSION,
            },
            source_filename=None
        )

        # Input state (updated by callbacks)
        self._keys_pressed = set()
        self._mouse_pos = (0.0, 0.0)

        # One-shot flags (reset after get_state)
        self._left_click_pending = False
        self._right_click_pending = False
        self._any_left_click_pending = False  # Includes imgui clicks
        self._any_right_click_pending = False  # Includes imgui clicks
        self._scroll_delta = 0.0
        self._request_reload = False
        self._request_reset = False
        self._request_full_reset = False
        self._request_randomize_mutations = False
        self._toggle_recording = False
        self._request_screenshot = False
        self._request_save_config = False
        self._request_load_config = False
        self._request_save_file = False
        self._request_load_file = False
        self._request_delete_file = False
        self._request_preview_config = False
        self._request_clear_preview = False
        self._request_world_size_change = False

        # Rule history window flags
        self._request_preview_history_rule = False
        self._request_clear_history_preview = False
        self._request_load_history_rule = False
        self._request_delete_history_rule = False
        self._history_preview_index = -1

        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""  # Category for load operation
        self._delete_filename = ""
        self._delete_category = ""  # Category for delete operation
        self._preview_filename = ""
        self._preview_category = ""  # Category for preview operation

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

        if action != glfw.PRESS:
            return

        # Track ALL clicks (including imgui) for sweep preview restore
        if button == glfw.MOUSE_BUTTON_LEFT:
            self._any_left_click_pending = True
        elif button == glfw.MOUSE_BUTTON_RIGHT:
            self._any_right_click_pending = True

        # Only track non-imgui clicks for normal interactions
        if imgui.get_io().want_capture_mouse:
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

        # Capture scroll for zoom-around-pointer (if imgui doesn't want it)
        if not imgui.get_io().want_capture_mouse:
            self._scroll_delta += yoffset

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
            shift_pressed = mods & glfw.MOD_SHIFT

            # Config save/load with Ctrl+C/Ctrl+V
            if ctrl_pressed and key == self.keybindings.get_key("copy_config_with_ctrl"):
                self._request_save_config = True
            elif ctrl_pressed and key == self.keybindings.get_key("paste_config_with_ctrl"):
                self._request_load_config = True
            elif key == self.keybindings.get_key("toggle_watercolor"):
                # Toggle watercolor mode
                self.state.sim.watercolor_mode = not self.state.sim.watercolor_mode
            elif key == self.keybindings.get_key("reload_shaders"):
                # Reload shaders
                self._request_reload = True
            elif key == self.keybindings.get_key("toggle_help"):
                # Show tutorial
                self.state.preferences.show_tutorial_window = not self.state.preferences.show_tutorial_window
            elif shift_pressed and key == self.keybindings.get_key("record_screen"):
                # Screenshot (Shift+P)
                self._request_screenshot = True
            elif key == self.keybindings.get_key("record_screen"):
                self._toggle_recording = True
            elif key == self.keybindings.get_key("toggle_pause"):
                self.state.sim.going = not self.state.sim.going
            elif key == self.keybindings.get_key("randomize_mutations"):
                self._request_randomize_mutations = True
            elif key == self.keybindings.get_key("toggle_mouse_mode"):
                # Toggle mouse mode between Select Particle and Draw Trail
                if self.state.preferences.mouse_mode == "Select Particle":
                    self.state.preferences.mouse_mode = "Draw Trail"
                else:
                    self.state.preferences.mouse_mode = "Select Particle"
            elif key == self.keybindings.get_key("toggle_parameter_sweep"):
                # Toggle parameter sweeps
                self.state.sim.parameter_sweeps_enabled = not self.state.sim.parameter_sweeps_enabled
                # If re-enabling sweeps while in preview mode, clear the preview flag
                if self.state.sim.parameter_sweeps_enabled and self.state.sim.sweep_preview_pending_restore:
                    self.state.sim.sweep_preview_pending_restore = False
            elif key == self.keybindings.get_key("randomize_rules"):
                # Full reset (one-shot, not hold)
                self._request_full_reset = True
            elif key == self.keybindings.get_key("toggle_sidebar"):
                # Toggle sidebar (Physics Settings and Preferences windows)
                self.show_sidebar = not self.show_sidebar
            elif key == self.keybindings.get_key("exit_keybinding"):
                glfw.set_window_should_close(window, True)
            #elif key == self.keybindings.get_key("toggle_tooltips"):
            #    self.show_demo_window = not self.show_demo_window

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

        # Check for R key hold (reset command - continuous)
        reset_key = self.keybindings.get_key("reset_keybinding")
        if reset_key and reset_key in self._keys_pressed:
            self._request_reset = True

        # Build state snapshot
        self.state.keys_pressed = self._keys_pressed.copy()
        self.state.mouse_pos = self._mouse_pos
        self.state.left_click_this_frame = self._left_click_pending
        self.state.right_click_this_frame = self._right_click_pending
        self.state.any_left_click_this_frame = self._any_left_click_pending
        self.state.any_right_click_this_frame = self._any_right_click_pending

        # Continuous mouse state (for draw trail mode) - respects imgui capture
        left_button_pressed = glfw.get_mouse_button(self.window, glfw.MOUSE_BUTTON_LEFT) == glfw.PRESS
        self.state.mouse_left_held = left_button_pressed and not imgui.get_io().want_capture_mouse
        self.state.scroll_delta = self._scroll_delta
        self.state.request_reload = self._request_reload
        self.state.request_reset = self._request_reset
        self.state.request_full_reset = self._request_full_reset
        self.state.request_randomize_mutations = self._request_randomize_mutations
        self.state.toggle_recording = self._toggle_recording
        self.state.request_screenshot = self._request_screenshot
        self.state.request_save_config = self._request_save_config
        self.state.request_load_config = self._request_load_config
        self.state.request_save_file = self._request_save_file
        self.state.request_load_file = self._request_load_file
        self.state.request_delete_file = self._request_delete_file
        self.state.request_preview_config = self._request_preview_config
        self.state.request_clear_preview = self._request_clear_preview
        self.state.request_world_size_change = self._request_world_size_change
        self.state.save_filename = self._save_filename
        self.state.load_filename = self._load_filename
        self.state.load_category = self._load_category
        self.state.delete_filename = self._delete_filename
        self.state.delete_category = self._delete_category
        self.state.preview_filename = self._preview_filename
        self.state.preview_category = self._preview_category
        self.state.load_watercolor_override = self._load_watercolor_override

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
        self._any_left_click_pending = False
        self._any_right_click_pending = False
        self._scroll_delta = 0.0
        self._request_reload = False
        self._request_reset = False
        self._request_full_reset = False
        self._request_randomize_mutations = False
        self._toggle_recording = False
        self._request_screenshot = False
        self._request_save_config = False
        self._request_load_config = False
        self._request_save_file = False
        self._request_load_file = False
        self._request_delete_file = False
        self._request_preview_config = False
        self._request_clear_preview = False
        self._request_world_size_change = False
        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""
        self._delete_filename = ""
        self._delete_category = ""
        self._preview_filename = ""
        self._preview_category = ""
        self._load_watercolor_override = None

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
        """Update current physics defaults from current sim state (called after file load/save)."""
        self.currently_open_project = filename
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
                'TRAIL_DIFFUSION': self.state.sim.TRAIL_DIFFUSION,
            },
            source_filename=filename
        )

    def render(self):
        """Render ImGui widgets - modifies self.state based on widget interactions."""
        self.imgui_renderer.process_inputs()

        imgui.new_frame()

        # Create a full-window dockspace
        viewport = imgui.get_main_viewport()
        imgui.set_next_window_pos(viewport.work_pos)
        imgui.set_next_window_size(viewport.work_size)
        imgui.set_next_window_viewport(viewport.id_)

        dockspace_window_flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_nav_focus
            | imgui.WindowFlags_.no_background
        )

        imgui.push_style_var(imgui.StyleVar_.window_rounding, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_border_size, 0.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0.0, 0.0))

        imgui.begin("DockSpace Window", None, dockspace_window_flags)
        imgui.pop_style_var(3)

        # Create the dockspace
        dockspace_id = imgui.get_id("MainDockSpace")
        imgui.dock_space(dockspace_id, imgui.ImVec2(0.0, 0.0), imgui.DockNodeFlags_.passthru_central_node)

        # Apply global color tinting based on mode
        recording_active = self._display_info.get('recording_active', False)
        video_pending = self._display_info.get('video_pending', False)
        sweeps_active = self.state.sim.parameter_sweeps_enabled
        color_push_count = 0

        if recording_active or video_pending:
            # Red tint for video recording mode
            imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.3, 0.1, 0.1, 0.94))
            imgui.push_style_color(imgui.Col_.menu_bar_bg, imgui.ImVec4(0.35, 0.12, 0.12, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg, imgui.ImVec4(0.25, 0.08, 0.08, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg_active, imgui.ImVec4(0.4, 0.13, 0.13, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg_collapsed, imgui.ImVec4(0.25, 0.08, 0.08, 0.5))
            imgui.push_style_color(imgui.Col_.popup_bg, imgui.ImVec4(0.3, 0.1, 0.1, 0.94))
            imgui.push_style_color(imgui.Col_.header, imgui.ImVec4(0.4, 0.13, 0.13, 0.45))
            imgui.push_style_color(imgui.Col_.header_hovered, imgui.ImVec4(0.45, 0.15, 0.15, 0.8))
            imgui.push_style_color(imgui.Col_.header_active, imgui.ImVec4(0.5, 0.17, 0.17, 1.0))
            color_push_count = 9
        elif sweeps_active:
            # Yellow tint for parameter sweeps mode (30% less intense)
            imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.205, 0.19, 0.13, 0.94))
            imgui.push_style_color(imgui.Col_.menu_bar_bg, imgui.ImVec4(0.245, 0.231, 0.161, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg, imgui.ImVec4(0.17, 0.161, 0.119, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg_active, imgui.ImVec4(0.28, 0.266, 0.161, 1.0))
            imgui.push_style_color(imgui.Col_.title_bg_collapsed, imgui.ImVec4(0.17, 0.161, 0.119, 0.5))
            imgui.push_style_color(imgui.Col_.popup_bg, imgui.ImVec4(0.205, 0.19, 0.13, 0.94))
            imgui.push_style_color(imgui.Col_.header, imgui.ImVec4(0.28, 0.266, 0.161, 0.45))
            imgui.push_style_color(imgui.Col_.header_hovered, imgui.ImVec4(0.325, 0.3115, 0.175, 0.8))
            imgui.push_style_color(imgui.Col_.header_active, imgui.ImVec4(0.37, 0.357, 0.189, 1.0))
            color_push_count = 9

        # Main application menu bar
        self.render_main_menu_bar()

        # Render popup modals (Save, Overwrite, Delete) - always rendered regardless of sidebar
        self.render_popup_modals()

        # Render Physics Settings window if sidebar is visible
        if self.show_sidebar:
            self.render_physics_settings_window()

        # Render Preferences window if sidebar is visible AND preferences are enabled
        if self.show_sidebar and self.state.preferences.show_preferences_window:
            self.render_preferences_window()

        # Render Controls help window if visible
        if self.state.preferences.show_controls_window:
            self.render_controls_window()

        # Render Parameter Sweeps help window if visible
        if self.state.preferences.show_parameter_sweeps_window:
            self.render_parameter_sweeps_window()

        # Render Tutorial help window if visible
        if self.state.preferences.show_tutorial_window:
            self.render_tutorial_window()

        # Render Performance help window if visible
        if self.state.preferences.show_performance_window:
            self.render_performance_window()

        # Render Screen Recording window if visible
        if self.show_video_recording_window:
            self.render_video_recording_window()

        # Render history window if visible
        if self.show_history_window:
            self.render_history_window()

        if self.show_demo_window:
            imgui.show_demo_window()

        # Restore normal colors if we pushed any
        if color_push_count > 0:
            imgui.pop_style_color(color_push_count)

        # End dockspace window
        imgui.end()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def _delayed_tooltip(self, text: str):
        """Show tooltip with delay, requiring mouse to be stationary."""
        # HoveredFlags_.delay_normal provides medium delay, stationary provides "mouse must be still"
        if imgui.is_item_hovered(imgui.HoveredFlags_.delay_normal | imgui.HoveredFlags_.stationary):
            imgui.set_tooltip(text)

    def cleanup(self):
        self.tooltip_fbo.release()
        self.tooltip_texture.release()
        self.tooltip_program.release()
        self.imgui_renderer.shutdown()
