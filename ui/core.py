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
from services.trial_prompts import trial_action_hints, trial_action_prompt_specs
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
from .advanced_drawing_window import AdvancedDrawingWindowMixin
from .field_loader_window import FieldLoaderWindowMixin


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
    AdvancedDrawingWindowMixin,
    FieldLoaderWindowMixin,
):
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(
        self,
        window,
        ctx: moderngl.Context,
        view_option_labels: list[str],
        multi_load_service=None,
        ui_scale: float = 1.0,
    ):
        self.window = window
        self.ctx = ctx
        self.view_option_labels = view_option_labels
        self.multi_load_service = multi_load_service
        self.param_lock_service = None  # Set by App after construction
        self.game_editor_enabled = True

        # Initialize keybinding manager
        self.keybindings = KeybindingManager()

        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)

        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable  # Enable docking
        io.config_flags |= imgui.ConfigFlags_.nav_enable_keyboard
        io.config_flags |= imgui.ConfigFlags_.nav_enable_gamepad
        if hasattr(io, "font_global_scale"):
            io.font_global_scale = ui_scale

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

        # Config clipboard state
        self.show_history_window = False  # Toggled by Extras menu
        self.config_clipboard: list[tuple] = []  # [(PhysicsConfig, display_label, field_snapshot), ...]
        self.clipboard_counter: int = 0  # Global jersey counter (00, 01, 02...)
        self.clipboard_previewing_index: int | None = None
        self._clipboard_renaming_index: int | None = None  # Which entry is being renamed
        self._clipboard_rename_buffer: str = ""  # Text input buffer for rename

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

        # Advanced drawing one-shot flags
        self._request_fill_operation = False
        self._fill_direction_type = 0
        self._request_clear_force_field = False
        self._request_clear_strafe_field = False
        self._request_clear_canvas = False
        self._request_camera_reset = False
        self._request_clear_canvas_and_fields = False
        self._request_trial_start = False
        self._request_trial_retry = False
        self._request_trial_next = False
        self._request_trial_restart_sequence = False
        self._request_trial_pause = False
        self._request_revert_strain = False
        self._request_exit = False

        # Config clipboard flags
        self._request_preview_clipboard_config = False
        self._request_clear_clipboard_preview = False
        self._request_load_clipboard_config = False
        self._request_delete_clipboard_config = False
        self._request_import_clipboard_to_multiload = False
        self._clipboard_config_index = -1

        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""  # Category for load operation
        self._delete_filename = ""
        self._delete_category = ""  # Category for delete operation
        self._preview_filename = ""
        self._preview_category = ""  # Category for preview operation

        # Field loader one-shot flags
        self._request_load_force_field_image = False
        self._request_load_strafe_field_image = False
        self._field_load_image_path = ""
        self._init_field_loader_state()

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

        self.state.input_scheme = "keyboard_mouse"

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
            self.state.input_scheme = "keyboard_mouse"
            ctrl_pressed = mods & glfw.MOD_CONTROL
            shift_pressed = mods & glfw.MOD_SHIFT

            if self.state.trial.game_mode and self._handle_game_keypress(key):
                return
            if not self._editor_tools_visible():
                return

            # Config save/load with Ctrl+C/Ctrl+V
            if ctrl_pressed and key == self.keybindings.get_key("copy_config_with_ctrl"):
                self._request_save_config = True
            elif ctrl_pressed and key == self.keybindings.get_key("paste_config_with_ctrl"):
                self._request_load_config = True
            elif key == self.keybindings.get_key("toggle_watercolor"):
                # Toggle watercolor mode (only in camera views, not field views)
                if self.state.sim.current_view_option in (2, 3):
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
                # Toggle windows (Physics Settings, Preferences, Drawing Controls, Config Clipboard, Screen Recording)
                self.show_sidebar = not self.show_sidebar
            elif key == self.keybindings.get_key("exit_keybinding"):
                glfw.set_window_should_close(window, True)
            #elif key == self.keybindings.get_key("toggle_tooltips"):
            #    self.show_demo_window = not self.show_demo_window

    def _handle_game_keypress(self, key):
        """Handle Trial Dish one-shot keys, with fallbacks for existing user configs."""
        trial = self.state.trial
        confirm_key = self.keybindings.get_key("game_confirm")
        retry_key = self.keybindings.get_key("game_retry")
        next_key = self.keybindings.get_key("game_next")
        tool_key = self.keybindings.get_key("game_tool")
        revert_key = self.keybindings.get_key("game_revert")
        pause_key = self.keybindings.get_key("game_pause")
        exit_key = self.keybindings.get_key("game_exit")

        if key == confirm_key or key == glfw.KEY_ENTER:
            if trial.briefing_active:
                self._request_trial_start = True
            elif trial.won:
                if trial.final_trial:
                    self._request_trial_restart_sequence = True
                else:
                    self._request_trial_next = True
            elif trial.failed:
                self._request_trial_retry = True
            return True

        if key == retry_key or key == glfw.KEY_BACKSPACE:
            self._request_trial_retry = True
            return True

        if key == pause_key or key == glfw.KEY_ESCAPE:
            if not trial.briefing_active and not trial.won and not trial.failed:
                self._request_trial_pause = True
            return True

        if key == exit_key or key == glfw.KEY_Q:
            if trial.paused:
                self._request_exit = True
            return True

        if key == next_key or key == glfw.KEY_N:
            if trial.won:
                if trial.final_trial:
                    self._request_trial_restart_sequence = True
                else:
                    self._request_trial_next = True
            return True

        if (
            key == tool_key
            or key == glfw.KEY_G
            or key == self.keybindings.get_key("randomize_mutations")
        ):
            if not trial.briefing_active and not trial.won and not trial.failed and trial.irradiation_ready:
                self._request_randomize_mutations = True
            return True

        if key == revert_key or key == glfw.KEY_C:
            if not trial.briefing_active and not trial.won and not trial.failed and trial.revert_ready:
                self._request_revert_strain = True
            return True

        return False

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
        right_button_pressed = glfw.get_mouse_button(self.window, glfw.MOUSE_BUTTON_RIGHT) == glfw.PRESS
        self.state.mouse_right_held = right_button_pressed and not imgui.get_io().want_capture_mouse
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

        # Transfer advanced drawing flags
        self.state.request_fill_operation = self._request_fill_operation
        self.state.fill_direction_type = self._fill_direction_type
        self.state.request_clear_force_field = self._request_clear_force_field
        self.state.request_clear_strafe_field = self._request_clear_strafe_field
        self.state.request_clear_canvas = self._request_clear_canvas
        self.state.request_camera_reset = self._request_camera_reset
        self.state.request_clear_canvas_and_fields = self._request_clear_canvas_and_fields
        self.state.request_trial_start = self._request_trial_start
        self.state.request_trial_retry = self._request_trial_retry
        self.state.request_trial_next = self._request_trial_next
        self.state.request_trial_restart_sequence = self._request_trial_restart_sequence
        self.state.request_trial_pause = self._request_trial_pause
        self.state.request_revert_strain = self._request_revert_strain
        self.state.request_exit = self._request_exit

        # Transfer field loader flags
        self.state.request_load_force_field_image = self._request_load_force_field_image
        self.state.request_load_strafe_field_image = self._request_load_strafe_field_image
        self.state.field_load_image_path = self._field_load_image_path

        self.state.save_filename = self._save_filename
        self.state.load_filename = self._load_filename
        self.state.load_category = self._load_category
        self.state.delete_filename = self._delete_filename
        self.state.delete_category = self._delete_category
        self.state.preview_filename = self._preview_filename
        self.state.preview_category = self._preview_category
        self.state.load_watercolor_override = self._load_watercolor_override

        # Transfer config clipboard flags
        self.state.request_preview_clipboard_config = self._request_preview_clipboard_config
        self.state.request_clear_clipboard_preview = self._request_clear_clipboard_preview
        self.state.request_load_clipboard_config = self._request_load_clipboard_config
        self.state.request_delete_clipboard_config = self._request_delete_clipboard_config
        self.state.request_import_clipboard_to_multiload = self._request_import_clipboard_to_multiload
        self.state.clipboard_config_index = self._clipboard_config_index

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
        self._request_fill_operation = False
        self._fill_direction_type = 0
        self._request_clear_force_field = False
        self._request_clear_strafe_field = False
        self._request_clear_canvas = False
        self._request_camera_reset = False
        self._request_clear_canvas_and_fields = False
        self._request_trial_start = False
        self._request_trial_retry = False
        self._request_trial_next = False
        self._request_trial_restart_sequence = False
        self._request_trial_pause = False
        self._request_revert_strain = False
        self._request_exit = False
        self._request_load_force_field_image = False
        self._request_load_strafe_field_image = False
        self._field_load_image_path = ""
        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""
        self._delete_filename = ""
        self._delete_category = ""
        self._preview_filename = ""
        self._preview_category = ""
        self._load_watercolor_override = None

        # Reset config clipboard flags
        self._request_preview_clipboard_config = False
        self._request_clear_clipboard_preview = False
        self._request_load_clipboard_config = False
        self._request_delete_clipboard_config = False
        self._request_import_clipboard_to_multiload = False
        self._clipboard_config_index = -1

        return self.state

    def update_display_info(self, info: dict) -> None:
        """Receive read-only info for display (time, frame_count, etc.)."""
        self._display_info = info

    def set_clipboard(self, text: str) -> None:
        """Set clipboard content (used by orchestrator for config save)."""
        glfw.set_clipboard_string(self.window, text)

    def add_to_config_clipboard(self, config, filename: str, field_snapshot=None) -> None:
        """Add a config snapshot to the config clipboard.

        Args:
            field_snapshot: Optional numpy float32 array of field texture data.
        """
        label = f"{filename}*{self.clipboard_counter:02d}"
        self.config_clipboard.append((config, label, field_snapshot))
        self.clipboard_counter += 1

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

        # Render popup modals (Save, Overwrite, Delete) when editor tools are exposed.
        if not self.state.trial.game_mode or self.game_editor_enabled:
            self.render_popup_modals()

        # Render Physics Settings window if sidebar is visible
        show_editor_panels = self.show_sidebar and self._editor_tools_visible()
        if show_editor_panels:
            self.render_physics_settings_window()

        # Render Preferences window if sidebar is visible AND preferences are enabled
        if show_editor_panels and self.state.preferences.show_preferences_window:
            self.render_preferences_window()

        show_support_windows = self._editor_tools_visible()

        # Render Controls help window if visible
        if show_support_windows and self.state.preferences.show_controls_window:
            self.render_controls_window()

        # Render Parameter Sweeps help window if visible
        if show_support_windows and self.state.preferences.show_parameter_sweeps_window:
            self.render_parameter_sweeps_window()

        # Render Tutorial help window if visible
        if show_support_windows and self.state.preferences.show_tutorial_window:
            self.render_tutorial_window()

        # Render Performance help window if visible
        if show_support_windows and self.state.preferences.show_performance_window:
            self.render_performance_window()

        # Render Screen Recording window if visible (hidden when windows toggled off)
        if show_editor_panels and self.show_video_recording_window:
            self.render_video_recording_window()

        # Render history window if visible (hidden when windows toggled off)
        if show_editor_panels and self.show_history_window:
            self.render_history_window()

        # Render Advanced Drawing window if enabled (hidden when windows toggled off)
        if show_editor_panels and self.state.preferences.advanced_drawing_enabled:
            self.render_advanced_drawing_window()

        # Render field loader window (transient editor tool, not part of player shell)
        if show_support_windows:
            self.render_field_loader_window()

        if self.state.trial.game_mode:
            self.render_trial_hazard_overlay()
            self.render_trial_rival_overlay()
            self.render_trial_zone_overlay()
            self.render_game_cursor_overlay()
            self.render_trial_hud()

        if self.show_demo_window:
            imgui.show_demo_window()

        # Restore normal colors if we pushed any
        if color_push_count > 0:
            imgui.pop_style_color(color_push_count)

        # End dockspace window
        imgui.end()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def _editor_tools_visible(self) -> bool:
        """Whether raw editor windows and shortcuts are available in this shell."""
        return not self.state.trial.game_mode or self.game_editor_enabled

    def render_trial_hud(self):
        """Render the first game-mode Trial Dish HUD."""
        trial = self.state.trial
        viewport = imgui.get_main_viewport()
        margin = 16.0
        width = min(430.0, max(320.0, viewport.work_size.x * 0.34))
        imgui.set_next_window_pos(
            imgui.ImVec2(viewport.work_pos.x + margin, viewport.work_pos.y + margin),
            imgui.Cond_.always,
        )
        imgui.set_next_window_size(imgui.ImVec2(width, 0.0), imgui.Cond_.always)
        flags = (
            imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_saved_settings
        )
        imgui.begin("Trial Dish", None, flags)
        imgui.text(trial.title)
        imgui.same_line()
        imgui.text_disabled(f"{trial.trial_index + 1}/{trial.trial_count}")
        imgui.separator()
        imgui.text_wrapped(trial.objective)
        imgui.spacing()
        if trial.briefing_active:
            if trial.station_line:
                imgui.text_disabled(trial.station_line)
                imgui.spacing()
            if trial.story_line:
                imgui.text_wrapped(trial.story_line)
                imgui.spacing()
            imgui.text_wrapped(trial.briefing)
            imgui.spacing()
            for step in trial.protocol_steps:
                imgui.text_wrapped(f"- {step}")
            imgui.spacing()
            if trial.guidance_message:
                imgui.text_disabled(trial.guidance_title)
                imgui.text_wrapped(trial.guidance_message)
                imgui.spacing()
            if imgui.button("Start Experiment"):
                self._request_trial_start = True
            self._render_trial_action_hints(trial)
            imgui.end()
            return

        if not trial.won and not trial.failed:
            self._render_trial_tools(trial)
        if trial.paused:
            imgui.spacing()
            imgui.text_colored(imgui.ImVec4(1.0, 0.82, 0.35, 1.0), "Assay Paused")
            imgui.text_wrapped("The dish is held in station stasis.")
            if imgui.button("Resume"):
                self._request_trial_pause = True
            imgui.same_line()
            if imgui.button("Retry"):
                self._request_trial_retry = True
            imgui.same_line()
            if imgui.button("Exit"):
                self._request_exit = True
            self._render_trial_action_hints(trial)
            imgui.end()
            return

        intro_trial = trial.trial_id == "bloom"
        if trial.hazard_enabled:
            if trial.trial_id == "antibiotic_band":
                imgui.text(f"Counterforce: {trial.hazard_name}")
            else:
                imgui.text(f"Hazard: {trial.hazard_name} ({int(trial.hazard_strength * 100)}%)")
        if trial.rival_enabled:
            imgui.text(
                f"Rival pressure: culture {trial.player_controlled_zones} sites / "
                f"rival {trial.rival_controlled_zones}"
            )
        if trial.tool_feedback and trial.tool_feedback_seconds > 0.0:
            imgui.text_disabled(trial.tool_feedback)
        if not intro_trial:
            imgui.text(f"Time: {trial.elapsed_seconds:05.1f}s / {trial.failure_seconds:05.1f}s")
        if trial.objective_status:
            imgui.text_wrapped(trial.objective_status)
        progress_label = (
            f"Stability {int(trial.progress * 100)}%"
            if intro_trial
            else f"{int(trial.progress * 100)}%"
        )
        imgui.progress_bar(trial.progress, imgui.ImVec2(-1.0, 0.0), progress_label)
        show_guidance = (
            trial.guidance_message
            and not trial.won
            and not trial.failed
        )
        if show_guidance:
            imgui.spacing()
            imgui.text_disabled(trial.guidance_title)
            imgui.text_wrapped(trial.guidance_message)
            imgui.spacing()

        if not intro_trial:
            zone_labels = []
            for zone in trial.zones:
                if zone.rival_controlled:
                    state = "rival"
                else:
                    state = "active" if zone.active else "dormant"
                zone_labels.append(f"{zone.name}:{state}")
            imgui.text("Sites: " + "  ".join(zone_labels))

        if trial.won:
            imgui.spacing()
            imgui.text_colored(imgui.ImVec4(0.35, 1.0, 0.65, 1.0), trial.result_title or "Culture Stabilized")
            if trial.result_grade:
                imgui.text(f"Readout: {trial.result_grade}")
            if trial.result_summary:
                imgui.text_wrapped(trial.result_summary)
            if trial.result_next_step:
                imgui.spacing()
                imgui.text_wrapped(trial.result_next_step)
            if not trial.final_trial:
                if imgui.button("Next Trial"):
                    self._request_trial_next = True
                imgui.same_line()
            else:
                if imgui.button("Restart Sequence"):
                    self._request_trial_restart_sequence = True
                imgui.same_line()
            if imgui.button("Retry"):
                self._request_trial_retry = True
            self._render_trial_action_hints(trial)
        elif trial.failed:
            imgui.spacing()
            imgui.text_colored(imgui.ImVec4(1.0, 0.35, 0.35, 1.0), trial.result_title or "Culture Failed")
            if trial.result_grade:
                imgui.text(f"Readout: {trial.result_grade}")
            if trial.result_summary:
                imgui.text_wrapped(trial.result_summary)
            if trial.result_next_step:
                imgui.spacing()
                imgui.text_wrapped(trial.result_next_step)
            if imgui.button("Retry Trial"):
                self._request_trial_retry = True
            self._render_trial_action_hints(trial)
        else:
            imgui.spacing()
            if not intro_trial:
                imgui.text_wrapped(trial.running_hint)
            self._render_trial_action_hints(trial)

        imgui.end()

    @staticmethod
    def trial_action_hints(trial, keybindings=None, input_scheme: str = "hybrid") -> list[str]:
        return trial_action_hints(trial, keybindings, input_scheme)

    @staticmethod
    def trial_action_prompt_specs(trial, keybindings=None, input_scheme: str = "hybrid"):
        return trial_action_prompt_specs(trial, keybindings, input_scheme)

    @staticmethod
    def trial_tool_status_labels(trial) -> dict[str, str]:
        """Return compact readiness labels for active lab tools."""
        labels = {}
        if trial.irradiation_unlocked:
            if trial.irradiation_charges <= 0:
                labels["irradiation"] = (
                    f"0/{trial.irradiation_max_charges} depleted"
                )
            elif trial.irradiation_cooldown_remaining > 0.0:
                labels["irradiation"] = (
                    f"{trial.irradiation_charges}/{trial.irradiation_max_charges} "
                    f"recharge {trial.irradiation_cooldown_remaining:.1f}s"
                )
            else:
                labels["irradiation"] = (
                    f"{trial.irradiation_charges}/{trial.irradiation_max_charges} ready"
                )

        if trial.revert_unlocked:
            if trial.revert_charges <= 0:
                state = "spent"
            elif trial.preserved_strain_available:
                state = "archive ready"
            else:
                state = "no archive"
            labels["revert"] = f"{trial.revert_charges}/{trial.revert_max_charges} {state}"
        return labels

    def _render_trial_action_hints(self, trial) -> None:
        prompts = self.trial_action_prompt_specs(trial, self.keybindings, self.state.input_scheme)
        if not prompts:
            return
        imgui.spacing()
        imgui.separator()
        imgui.text_disabled("Controls")
        for prompt in prompts:
            self._render_trial_prompt(prompt)

    @staticmethod
    def _render_trial_prompt(prompt) -> None:
        rendered_input = UI._render_trial_prompt_input(prompt)
        if not rendered_input:
            imgui.text_wrapped(prompt.label)
            return

        imgui.same_line()
        imgui.text_wrapped(f": {prompt.label}")

    @staticmethod
    def _render_trial_prompt_input(prompt) -> bool:
        """Render the input side of a Trial Dish prompt.

        Controller prompts use chip-like text backed by glyph metadata. The
        official Steam/Deck glyph renderer can replace this without changing
        the prompt selection logic.
        """
        if prompt.input_scheme == "keyboard_mouse" or not prompt.has_controller_glyphs:
            input_text = prompt.render_input_text()
            if not input_text:
                return False
            imgui.text_colored(imgui.ImVec4(0.58, 0.82, 1.0, 1.0), input_text)
            return True

        for index, label in enumerate(prompt.controller_labels):
            if index > 0:
                imgui.same_line()
                imgui.text_disabled("+")
                imgui.same_line()
            imgui.text_colored(imgui.ImVec4(0.72, 0.90, 1.0, 1.0), f"[{label}]")

        if prompt.input_scheme == "hybrid" and prompt.keyboard_labels:
            imgui.same_line()
            imgui.text_disabled("/")
            imgui.same_line()
            imgui.text_colored(
                imgui.ImVec4(0.58, 0.82, 1.0, 1.0),
                " + ".join(prompt.keyboard_labels),
            )
        return True

    def _render_trial_tools(self, trial):
        """Render compact game-facing lab tool controls for the current trial."""
        tool_status = self.trial_tool_status_labels(trial)
        imgui.text("Tools:")
        imgui.text_disabled("Nutrient Gel")

        if not trial.irradiation_unlocked:
            return

        is_running = not trial.briefing_active and not trial.won and not trial.failed and not trial.paused
        can_irradiate = is_running and trial.irradiation_ready
        if not can_irradiate:
            imgui.begin_disabled()
        if imgui.button("Irradiate Strain"):
            self._request_randomize_mutations = True
        if not can_irradiate:
            imgui.end_disabled()
        imgui.same_line()
        imgui.text_disabled(tool_status.get("irradiation", ""))

        if not trial.revert_unlocked:
            return

        can_revert = is_running and trial.revert_ready
        if not can_revert:
            imgui.begin_disabled()
        if imgui.button("Revert Strain"):
            self._request_revert_strain = True
        if not can_revert:
            imgui.end_disabled()
        imgui.same_line()
        imgui.text_disabled(tool_status.get("revert", ""))

    def render_trial_zone_overlay(self):
        """Draw objective zone circles over the simulation view."""
        overlays = self._display_info.get('trial_zone_overlays', [])
        if not overlays:
            return

        draw_list = imgui.get_foreground_draw_list()
        show_labels = len(overlays) > 1
        for zone in overlays:
            center = imgui.ImVec2(zone['center'][0], zone['center'][1])
            radius = zone['radius']
            if zone.get('rival_controlled'):
                color = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.22, 0.82, 0.95))
                fill = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.95, 0.10, 0.65, 0.14))
            elif zone['active']:
                color = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.25, 1.0, 0.62, 0.95))
                fill = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.10, 0.80, 0.35, 0.13))
            else:
                color = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.82, 0.25, 0.88))
                fill = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.55, 0.10, 0.09))
            draw_list.add_circle_filled(center, radius, fill, 48)
            draw_list.add_circle(center, radius, color, 48, 2.0)
            if show_labels:
                label_pos = imgui.ImVec2(center.x - 5.0, center.y - radius - 18.0)
                draw_list.add_text(label_pos, color, zone['name'])

    def render_trial_rival_overlay(self):
        """Draw the rival culture source over the simulation view."""
        rival = self._display_info.get('trial_rival_overlay')
        if not rival:
            return

        draw_list = imgui.get_foreground_draw_list()
        center = imgui.ImVec2(rival['center'][0], rival['center'][1])
        radius = rival['radius']
        fill = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.95, 0.08, 0.65, 0.12))
        edge = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.22, 0.82, 0.76))
        text = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.45, 0.86, 0.95))
        draw_list.add_circle_filled(center, radius, fill, 64)
        draw_list.add_circle(center, radius, edge, 64, 2.0)
        draw_list.add_text(
            imgui.ImVec2(center.x - radius, center.y + radius + 8.0),
            text,
            rival['name'],
        )

    def render_trial_hazard_overlay(self):
        """Draw the antibiotic band counterforce over the simulation view."""
        hazard = self._display_info.get('trial_hazard_overlay')
        if not hazard:
            return

        draw_list = imgui.get_foreground_draw_list()
        min_pos = imgui.ImVec2(hazard['min'][0], hazard['min'][1])
        max_pos = imgui.ImVec2(hazard['max'][0], hazard['max'][1])
        fill = imgui.color_convert_float4_to_u32(imgui.ImVec4(0.9, 0.18, 0.28, 0.16))
        edge = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.25, 0.35, 0.72))
        text = imgui.color_convert_float4_to_u32(imgui.ImVec4(1.0, 0.48, 0.55, 0.95))
        draw_list.add_rect_filled(min_pos, max_pos, fill, 0.0)
        draw_list.add_rect(min_pos, max_pos, edge, 0.0, 2.0, 0)
        draw_list.add_text(
            imgui.ImVec2(min_pos.x + 8.0, min_pos.y + 28.0),
            text,
            hazard['name'],
        )

    def render_game_cursor_overlay(self):
        """Draw the controller lab applicator cursor."""
        cursor = self._display_info.get('game_cursor')
        if not cursor:
            return

        draw_list = imgui.get_foreground_draw_list()
        pos = cursor['pos']
        center = imgui.ImVec2(pos[0], pos[1])
        drawing = cursor.get('drawing', False)
        edge = imgui.color_convert_float4_to_u32(
            imgui.ImVec4(0.30, 1.0, 0.66, 0.95)
            if drawing
            else imgui.ImVec4(0.70, 0.92, 1.0, 0.82)
        )
        fill = imgui.color_convert_float4_to_u32(
            imgui.ImVec4(0.12, 0.85, 0.40, 0.18)
            if drawing
            else imgui.ImVec4(0.25, 0.55, 0.95, 0.08)
        )
        radius = 16.0 if drawing else 12.0
        draw_list.add_circle_filled(center, radius, fill, 32)
        draw_list.add_circle(center, radius, edge, 32, 2.0)
        draw_list.add_line(
            imgui.ImVec2(center.x - radius - 5.0, center.y),
            imgui.ImVec2(center.x - 4.0, center.y),
            edge,
            1.5,
        )
        draw_list.add_line(
            imgui.ImVec2(center.x + 4.0, center.y),
            imgui.ImVec2(center.x + radius + 5.0, center.y),
            edge,
            1.5,
        )
        draw_list.add_line(
            imgui.ImVec2(center.x, center.y - radius - 5.0),
            imgui.ImVec2(center.x, center.y - 4.0),
            edge,
            1.5,
        )
        draw_list.add_line(
            imgui.ImVec2(center.x, center.y + 4.0),
            imgui.ImVec2(center.x, center.y + radius + 5.0),
            edge,
            1.5,
        )

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
