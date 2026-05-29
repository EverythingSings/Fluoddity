from dataclasses import dataclass, field
import numpy as np


@dataclass
class CameraState:
    """State for camera position and rendering mode."""
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0]))
    zoom: float = 1.0
    BRIGHTNESS: float = 1.  # Kept for backward compat, sourced from SimState
    cam_brush_mode: bool = True

    # 3D orbital camera
    render_3d: bool = False        # Toggle between 2D cam_brush and 3D point view
    orbit_distance: float = 3.0    # Distance from target
    orbit_yaw: float = 0.0         # Horizontal rotation (radians)
    orbit_pitch: float = 0.3       # Vertical rotation (radians, slightly above horizon)
    orbit_target: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))
