from dataclasses import dataclass, field


@dataclass
class SimState:
    """State for simulation parameters that UI controls."""
    going: bool = True
    current_view_option: int = 1  # 0=can, 1=cam_brush, 2=tiled, 3=force, 4=strafe

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
    TRAIL_DIFFUSION: float = 1.0
    HAZARD_RATE: float = 0.0

    # Extra options
    DISABLE_SYMMETRY: bool = False
    ABSOLUTE_ORIENTATION: int = 0  # 0=Off, 1=Y axis, 2=Radial
    ORIENTATION_MIX: float = 1.0

    # Radio feature (visibility filter by frequency band)
    RADIO_ENABLED: int = 0         # 0=Off, >0 = mode (int for future modes)
    RADIO_TARGET_FREQ: float = 0.0 # Target frequency [-15, 15]
    RADIO_BANDWIDTH: float = 0.5   # Bandwidth [0, 2]

    # Simulation settings (defaults ensure backward compatibility with old configs)
    boundary_conditions: int = 0  # 0=Bounce, 1=Reset, 2=Wrap (default: Bounce)
    initial_conditions: int = 0   # 0=Grid, 1=Random, 2=Ring (default: Grid)
    num_cohorts: int = 64         # Number of cohorts (1-144, default: 64)
    rule_seed: float = 0.42       # Seed for procedural rule generation (fixed default for reproducibility)

    # Appearance settings (saved with physics config)
    ink_weight: float = 1.0  # Watercolor mode: controls optical density in exp()
    hue_sensitivity: float = 0.5
    color_by_cohort: bool = True  # Default True so old saves use cohort coloring
    watercolor_mode: bool = False

    # User notes (saved with physics config)
    notes: str = ""

    # Slider range customizations: [current_min, current_max, default_min, default_max]
    slider_ranges: dict[str, list[float]] = field(default_factory=dict)

    # Parameter sweep settings
    parameter_sweeps_enabled: bool = False
    # Sweep preview: right-click temporarily disables sweeps, next click re-enables
    sweep_preview_pending_restore: bool = False
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
        'TRAIL_DIFFUSION': 0.0,
        'HAZARD_RATE': 0.0,
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
        'TRAIL_DIFFUSION': 0.0,
        'HAZARD_RATE': 0.0,
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
        'TRAIL_DIFFUSION': 0.0,
        'HAZARD_RATE': 0.0,
    })
    # 3D simulation settings
    canvas_3d_depth: int = 256       # Z-depth of 3D canvas (256 = full 3D resolution)
    TESTING_MODE: bool = False       # Lock z=0, XY plane only, 4-neighbor blur
    PLANE_SAMPLES: int = 1           # Number of random plane samples per entity per frame
    canvas_3d_view_slice: int = 0    # Which z-slice to show in the debug canvas view

    # Jitter settings: per-parameter temporal randomness (0.0-2.0)
    # Jitter is proportional: 0.5 means ±50% random variation per frame
    jitters: dict[str, float] = field(default_factory=lambda: {
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
        'TRAIL_DIFFUSION': 0.0,
        'HAZARD_RATE': 0.0,
    })
