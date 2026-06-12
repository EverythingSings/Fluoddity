from dataclasses import dataclass, field
import numpy as np


@dataclass
class CameraState:
    """State for camera position and rendering mode."""
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0]))
    zoom: float = 1.0
    BRIGHTNESS: float = 1.  # Kept for backward compat, sourced from SimState
    cam_brush_mode: bool = True

    # 3D camera (driven by ControllerCam + joystick)
    render_3d: bool = True         # Toggle between 2D cam_brush and 3D point view
    orbit_center: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0]))  # World-space point to orbit around
    orbit_rate: float = 0.0        # Auto-orbit speed (rad/physics-frame)
    orbit_angle: float = 0.0       # Accumulated orbit yaw angle (radians)
    orbit_pitch: float = 0.0       # Orbit elevation angle (radians)
    fov: float = 50.0              # Field of view (degrees)
    aperture: float = 0.0          # DOF lens radius (0 = pinhole, no DOF)
    focal_plane_depth: float = 5.0 # DOF focal plane distance
    move_speed: float = 2.0        # Joystick movement speed
    rotate_speed: float = 2.0      # Joystick rotation speed
    optix_enabled: bool = False    # Use OptiX sphere raytracer instead of GL_POINTS
