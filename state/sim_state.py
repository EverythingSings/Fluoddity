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

    # Simulation settings (defaults ensure backward compatibility with old configs)
    boundary_conditions: int = 0  # 0=Bounce, 1=Reset, 2=Wrap (default: Bounce)
    initial_conditions: int = 0   # 0=Grid, 1=Random, 2=Ring (default: Grid)
    num_cohorts: int = 64         # Number of cohorts (1-144, default: 64)

    # Parameter sweep settings
    parameter_sweeps_enabled: bool = False
    # Dictionary mapping parameter names to their sweep modes
    # 0.0 = no sweep, 1.0 = normal sweep (min to max), -1.0 = inverse sweep (max to min)
    x_sweeps: dict[str, float] = field(default_factory=lambda: {
        'AXIAL_FORCE': 0.0,
        'LATERAL_FORCE': 0.0,
        'SENSOR_GAIN': 0.0,
        'MUTATION_SCALE': 0.0,
        'DRAG': 0.0,
        'STRAFE_POWER': 0.0,
        'SENSOR_ANGLE': 0.0,
        'GLOBAL_FORCE_MULT': 0.0,
        'SENSOR_DISTANCE': 0.0,
        'TRAIL_PERSISTENCE': 0.0,
    })
    y_sweeps: dict[str, float] = field(default_factory=lambda: {
        'AXIAL_FORCE': 0.0,
        'LATERAL_FORCE': 0.0,
        'SENSOR_GAIN': 0.0,
        'MUTATION_SCALE': 0.0,
        'DRAG': 0.0,
        'STRAFE_POWER': 0.0,
        'SENSOR_ANGLE': 0.0,
        'GLOBAL_FORCE_MULT': 0.0,
        'SENSOR_DISTANCE': 0.0,
        'TRAIL_PERSISTENCE': 0.0,
    })
    cohort_sweeps: dict[str, float] = field(default_factory=lambda: {
        'AXIAL_FORCE': 0.0,
        'LATERAL_FORCE': 0.0,
        'SENSOR_GAIN': 0.0,
        'MUTATION_SCALE': 0.0,
        'DRAG': 0.0,
        'STRAFE_POWER': 0.0,
        'SENSOR_ANGLE': 0.0,
        'GLOBAL_FORCE_MULT': 0.0,
        'SENSOR_DISTANCE': 0.0,
        'TRAIL_PERSISTENCE': 0.0,
    })
