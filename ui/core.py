"""Core UI class: initialization, GLFW callbacks, state management, render dispatch.

The UI class inherits from all mixin modules via multiple inheritance.
Each mixin provides render methods for specific windows/panels.
All methods share the same `self` for access to shared state.
"""
import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import moderngl
from dataclasses import dataclass
from state import UIState, SimState, CameraState, RecordingState, ConfigClipboardState
from services.config_saver import ConfigSaver, PhysicsConfig
from utilities.keybinding_management import KeybindingManager
from utilities.paths import get_user_physics_configs_dir, get_app_physics_configs_dir

from .popup_modals import PopupModalsMixin
from .help_windows import HelpWindowsMixin
from .slider_widgets import SliderWidgetsMixin
from .config_browser import ConfigBrowserMixin
from .config_clipboard_window import ConfigClipboardWindowMixin
from .physics_tooltip import PhysicsTooltipMixin
from .preferences_window import PreferencesWindowMixin
from .menu_bar import MenuBarMixin
from .physics_window import PhysicsWindowMixin
from .generics_window import GenericsWindowMixin
from .plotting import PlottingWindowMixin
from .render_settings_window import RenderSettingsWindowMixin
from .radio_window import RadioWindowMixin
from .scheduled_renders_window import ScheduledRendersWindowMixin


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
    ConfigClipboardWindowMixin,
    PhysicsTooltipMixin,
    ConfigBrowserMixin,
    SliderWidgetsMixin,
    GenericsWindowMixin,
    PlottingWindowMixin,
    RenderSettingsWindowMixin,
    RadioWindowMixin,
    ScheduledRendersWindowMixin,
):
    """Passive UI - renders widgets, exposes state, handles no logic."""

    def __init__(self, window, ctx: moderngl.Context,
                 param_lock_service=None, plotting_manager=None,
                 render_spec_service=None, editor_saver=None, simulation_saver=None,
                 viewer=None, tracer_sim=None, tracer_controller_cam=None,
                 tracer_camera=None):
        self.window = window
        self.ctx = ctx
        # Dependencies injected by App via constructor.
        self.param_lock_service = param_lock_service
        self.plotting_manager = plotting_manager
        self.render_spec_service = render_spec_service
        self.editor_saver = editor_saver
        self.simulation_saver = simulation_saver
        self.viewer = viewer  # Viewer window

        # Tracer references (for entity buffer and camera access)
        self._tracer_interface = None  # Lazily created inside RenderSettingsWindowMixin
        self.tracer_sim = tracer_sim
        self.tracer_controller_cam = tracer_controller_cam
        self.tracer_camera = tracer_camera

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
        self.show_sidebar = True  # Controls visibility of Physics Settings and Preferences windows

        # Config clipboard state (owned by the config_clipboard module; the UI
        # holds the reference so the window mixin + callbacks can reach it).
        self.clipboard_state = ConfigClipboardState()

        # File save/load state
        self.save_popup_open = False
        self.save_filename_buffer = ""

        # Editor / Simulation save popups + submenu open-tracking
        self.editor_save_popup_open = False
        self._save_editor_name_buffer = ""
        self._editor_load_submenu_was_open = False
        self.simulation_save_popup_open = False
        self._save_simulation_name_buffer = ""
        self._simulation_load_submenu_was_open = False
        # Physics configs: app dir for bundled (Core/Advanced), user dir for user-created
        self.app_configs_dir = get_app_physics_configs_dir()
        self.user_configs_dir = get_user_physics_configs_dir()
        self.config_saver = ConfigSaver()

        # Load submenu preview state
        self.config_files: list[str] = []  # List of available config filenames (DEPRECATED: use config_files_by_category)
        self.config_files_by_category: dict[str, list[str]] = {}  # Config filenames organized by category (Core/Custom/Advanced)
        self.cached_configs: dict[str, PhysicsConfig] = {}  # Cached decoded configs (keys: "Category/filename") — display + hover validity only
        self.load_submenu_was_open = False  # Track submenu open state
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
        self._last_applied_entity_count: int = 4000000
        self._last_applied_canvas_resolution: int = 256

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

        # Config clipboard flags (owned by ConfigClipboardWindowMixin)
        self._init_config_clipboard_flags()

        # Render-spec + render-queue flags are owned by ScheduledRendersWindowMixin
        # (initialized below in self._init_scheduled_renders_state()).

        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""  # Category for load operation
        self._delete_filename = ""
        self._delete_category = ""  # Category for delete operation
        self._preview_filename = ""
        self._preview_category = ""  # Category for preview operation
        self._preview_watercolor_override: bool | None = None  # Session watercolor mode for preview load/restore

        # Scheduled renders (render_spec_service injected via constructor above)
        self._init_scheduled_renders_state()

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

    def _viewer_hovered(self) -> bool:
        """Whether the pointer is over the Viewer window (clicks pass through).

        False before the Viewer is injected. Reflects the last built frame's
        hover state, which is what GLFW callbacks (firing before this frame's UI
        is built) should consult — the same latency the old capture gate had.
        """
        return self.viewer is not None and self.viewer.hovered

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

        # Only let clicks through to the sim when they land on the Viewer window
        # (not on a floating imgui panel). The Viewer is itself an imgui window
        # now, so `want_capture_mouse` is true over it too — gate on Viewer hover
        # instead. See Viewer.hovered.
        if not self._viewer_hovered():
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

        # Capture scroll for zoom-around-pointer only when over the Viewer
        if self._viewer_hovered():
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
                self.state.sim.watercolor_mode = not self.state.sim.watercolor_mode
            elif key == self.keybindings.get_key("reload_shaders"):
                # Reload shaders
                self._request_reload = True
            elif key == self.keybindings.get_key("toggle_help"):
                # Show tutorial
                self.state.preferences.ui_windows.show_tutorial_window = not self.state.preferences.ui_windows.show_tutorial_window
            elif shift_pressed and key == self.keybindings.get_key("record_screen"):
                # Screenshot (Shift+P)
                self._request_screenshot = True
            elif key == self.keybindings.get_key("record_screen"):
                self._toggle_recording = True
            elif key == self.keybindings.get_key("toggle_pause"):
                self.state.sim.going = not self.state.sim.going
            elif key == self.keybindings.get_key("randomize_mutations"):
                self._request_randomize_mutations = True
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
            elif key == self.keybindings.get_key("pick_focal_entity"):
                self._request_pick_focal = True
            elif key == self.keybindings.get_key("cycle_rt_mode"):
                r = self.state.preferences.rendering
                r.rt_mode = (r.rt_mode + 1) % 3
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

        # Continuous mouse state (for draw trail mode) - only over the Viewer
        viewer_hovered = self._viewer_hovered()
        left_button_pressed = glfw.get_mouse_button(self.window, glfw.MOUSE_BUTTON_LEFT) == glfw.PRESS
        self.state.mouse_left_held = left_button_pressed and viewer_hovered
        right_button_pressed = glfw.get_mouse_button(self.window, glfw.MOUSE_BUTTON_RIGHT) == glfw.PRESS
        self.state.mouse_right_held = right_button_pressed and viewer_hovered
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
        self.state.request_pick_focal = getattr(self, '_request_pick_focal', False)

        self.state.save_filename = self._save_filename
        self.state.load_filename = self._load_filename
        self.state.load_category = self._load_category
        self.state.delete_filename = self._delete_filename
        self.state.delete_category = self._delete_category
        self.state.preview_filename = self._preview_filename
        self.state.preview_category = self._preview_category
        self.state.preview_watercolor_override = self._preview_watercolor_override
        self.state.load_watercolor_override = self._load_watercolor_override

        self._marshal_config_clipboard_state(self.state)
        self._marshal_scheduled_renders_state(self.state)

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
        self._request_pick_focal = False
        self._save_filename = ""
        self._load_filename = ""
        self._load_category = ""
        self._delete_filename = ""
        self._delete_category = ""
        self._preview_filename = ""
        self._preview_category = ""
        self._preview_watercolor_override = None
        self._load_watercolor_override = None
        # Advanced-drawing, field-loader, config-clipboard, and render-spec/queue
        # one-shot flags are reset by their owning mixin's _marshal_*_state above.

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

        # Viewer window: always drawn (immune to the show/hide-windows button),
        # docked into the central node. Shows the renderer's finished frame with
        # display-only overlays. Injected by App after construction.
        if self.viewer is not None:
            self.viewer.render_window(dockspace_id)

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
        if self.show_sidebar and self.state.preferences.ui_windows.show_preferences_window:
            self.render_preferences_window()

        # Render Controls help window if visible
        if self.state.preferences.ui_windows.show_controls_window:
            self.render_controls_window()

        # Render Parameter Sweeps help window if visible
        if self.state.preferences.ui_windows.show_parameter_sweeps_window:
            self.render_parameter_sweeps_window()

        # Render Tutorial help window if visible
        if self.state.preferences.ui_windows.show_tutorial_window:
            self.render_tutorial_window()

        # Render Performance help window if visible
        if self.state.preferences.ui_windows.show_performance_window:
            self.render_performance_window()

        # Render Screen Recording window if visible (hidden when windows toggled off)
        if self.show_sidebar and self.state.preferences.ui_windows.show_video_recording_window:
            self.render_video_recording_window()

        # Render config clipboard window if visible (hidden when windows toggled off)
        if self.show_sidebar and self.state.preferences.ui_windows.show_config_clipboard_window:
            self.render_config_clipboard_window()

        # Render Generics window if enabled (hidden when windows toggled off)
        if self.show_sidebar and self.state.preferences.ui_windows.show_generics_window:
            self.render_generics_window()

        # Render Plotting window if enabled (not gated by sidebar — standalone data view)
        if self.state.preferences.ui_windows.show_plotting_window:
            self.render_plotting_window()

        # Render the unified Render settings window (active renderer's controls)
        if self.show_sidebar and self.state.preferences.ui_windows.show_render_settings_window:
            self.render_render_settings_window()

        # Render Radio window if enabled (hidden when windows toggled off)
        if self.show_sidebar and self.state.preferences.ui_windows.show_radio_window:
            self.render_radio_window()

        # Render Scheduled Renders window if enabled (hidden when windows toggled off)
        if self.show_sidebar and self.state.preferences.ui_windows.show_scheduled_renders_window:
            self.render_scheduled_renders_window()

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
