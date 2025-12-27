from dataclasses import dataclass, field


@dataclass
class SimState:
    """State for simulation parameters that UI controls."""
    going: bool = True
    current_view_option: int = 2  # 0=can, 1=brush_tex, 2=cam_brush

    # Physics parameters
    AXIAL_FORCE: float = 0.371
    LATERAL_FORCE: float = -0.707
    SENSOR_GAIN: float = 0.116
    MUTATION_SCALE: float = 0.0
    DRAG: float = 0.504
    STRAFE_POWER: float = 0.224
    SENSOR_ANGLE: float = .45
    GLOBAL_FORCE_MULT: float = 1.0
    SENSOR_DISTANCE: float = 1.0
    TRAIL_PERSISTENCE: float = 0.938

    # Extra options
    DISABLE_SYMMETRY: bool = False
    ABSOLUTE_ORIENTATION: bool = False

    # Parameter sweep settings
    parameter_sweeps_enabled: bool = False
    # Dictionary mapping parameter names to their sweep states (x, y, cohort)
    x_sweeps: dict[str, bool] = field(default_factory=lambda: {
        'AXIAL_FORCE': False,
        'LATERAL_FORCE': False,
        'SENSOR_GAIN': False,
        'MUTATION_SCALE': False,
        'DRAG': False,
        'STRAFE_POWER': False,
        'SENSOR_ANGLE': False,
        'GLOBAL_FORCE_MULT': False,
        'SENSOR_DISTANCE': False,
    })
    y_sweeps: dict[str, bool] = field(default_factory=lambda: {
        'AXIAL_FORCE': False,
        'LATERAL_FORCE': False,
        'SENSOR_GAIN': False,
        'MUTATION_SCALE': False,
        'DRAG': False,
        'STRAFE_POWER': False,
        'SENSOR_ANGLE': False,
        'GLOBAL_FORCE_MULT': False,
        'SENSOR_DISTANCE': False,
    })
    cohort_sweeps: dict[str, bool] = field(default_factory=lambda: {
        'AXIAL_FORCE': False,
        'LATERAL_FORCE': False,
        'SENSOR_GAIN': False,
        'MUTATION_SCALE': False,
        'DRAG': False,
        'STRAFE_POWER': False,
        'SENSOR_ANGLE': False,
        'GLOBAL_FORCE_MULT': False,
        'SENSOR_DISTANCE': False,
    })
