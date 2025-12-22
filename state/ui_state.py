from dataclasses import dataclass, field
from .sim_state import SimState
from .camera_state import CameraState
from .recording_state import RecordingState


@dataclass
class UIState:
    """Aggregate state that UI exposes to Orchestrator each frame."""
    sim: SimState = field(default_factory=SimState)
    camera: CameraState = field(default_factory=CameraState)
    recording: RecordingState = field(default_factory=RecordingState)

    # Input state (updated by callbacks)
    keys_pressed: set = field(default_factory=set)
    mouse_pos: tuple = (0.0, 0.0)

    # One-shot click events (reset after get_state)
    left_click_this_frame: bool = False
    right_click_this_frame: bool = False

    # One-shot command flags (reset after get_state)
    request_reload: bool = False
    request_reset: bool = False
    request_full_reset: bool = False
    toggle_recording: bool = False
