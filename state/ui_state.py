from dataclasses import dataclass, field
from .sim_state import SimState
from .camera_state import CameraState
from .recording_state import RecordingState
from .preferences_state import PreferencesState


@dataclass
class UIState:
    """Aggregate state that UI exposes to Orchestrator each frame."""
    sim: SimState = field(default_factory=SimState)
    camera: CameraState = field(default_factory=CameraState)
    recording: RecordingState = field(default_factory=RecordingState)
    preferences: PreferencesState = field(default_factory=PreferencesState)

    # Input state (updated by callbacks)
    keys_pressed: set = field(default_factory=set)
    mouse_pos: tuple = (0.0, 0.0)

    # One-shot click events (reset after get_state)
    left_click_this_frame: bool = False
    right_click_this_frame: bool = False

    # Any click events (includes clicks on imgui elements, for sweep restore)
    any_left_click_this_frame: bool = False
    any_right_click_this_frame: bool = False

    # Continuous mouse state (respects imgui capture)
    mouse_left_held: bool = False
    mouse_right_held: bool = False

    # Canvas clear (menu-driven, one-shot; reset by the runner after acting)
    request_clear_canvas: bool = False  # Clear trails/canvas textures

    # Scroll input (for zoom-around-pointer)
    scroll_delta: float = 0.0

    # One-shot command flags (reset after get_state)
    request_reload: bool = False
    request_reset: bool = False
    request_full_reset: bool = False
    request_randomize_mutations: bool = False
    toggle_recording: bool = False
    request_screenshot: bool = False
    request_world_size_change: bool = False
    request_camera_reset: bool = False
    request_pick_focal: bool = False  # N key: set focal plane to nearest entity

    # Config save/load (Ctrl+C/Ctrl+V)
    request_save_config: bool = False
    request_load_config: bool = False
    clipboard_text: str = ""  # For passing clipboard content to orchestrator

    # File save/load/delete (menu bar)
    request_save_file: bool = False
    request_load_file: bool = False
    request_delete_file: bool = False
    save_filename: str = ""  # Filename to save to (without extension)
    load_filename: str = ""  # Filename to load from (without extension)
    load_category: str = ""  # Category for load operation (Core, Custom, Advanced)
    delete_filename: str = ""  # Filename to delete (without extension)
    delete_category: str = ""  # Category for delete operation (Core, Custom, Advanced)

    # Config preview (for Load submenu hover). Preview loads a config to live
    # state remembering the original to restore; it never touches the undo stack.
    request_preview_config: bool = False  # Load hovered config as a preview
    request_clear_preview: bool = False  # Restore the remembered original
    preview_filename: str = ""  # Filename to preview
    preview_category: str = ""  # Category for preview operation

    # Config clipboard flags
    request_preview_clipboard_config: bool = False
    request_clear_clipboard_preview: bool = False
    request_load_clipboard_config: bool = False
    request_delete_clipboard_config: bool = False
    clipboard_config_index: int = -1

    # Render spec save
    request_save_render_spec: bool = False
    save_render_spec_name: str = ""

    # Render spec preview (destructive apply from Scheduled Renders window)
    request_preview_render_spec: bool = False
    preview_render_spec_path: str = ""  # Path to .frs directory to preview

    # Render queue execution
    request_execute_render_queue: bool = False
    render_queue_paths: list = field(default_factory=list)
    render_queue_names: list = field(default_factory=list)
    request_cancel_render_queue: bool = False

    # Editor settings save/load (non-physics editor state + imgui layout)
    request_save_editor: bool = False
    save_editor_name: str = ""
    request_load_editor: bool = False
    load_editor_path: str = ""  # Path to .editor.json file to load

    # Simulation state save/load (entity + canvas GPU buffers)
    request_save_simulation: bool = False
    save_simulation_name: str = ""
    request_load_simulation: bool = False
    load_simulation_path: str = ""  # Path to .fsim directory to load
