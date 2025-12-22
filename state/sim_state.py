from dataclasses import dataclass, field


@dataclass
class SimState:
    """State for simulation parameters that UI controls."""
    going: bool = True
    speedmult: int = 1
    generic_sliders: list = field(default_factory=lambda: [0.371, -0.707, 0.116, 0.0])
    current_view_option: int = 2  # 0=can, 1=brush_tex, 2=cam_brush

    # Physics parameters
    DRAIN: float = 0.938
    DRAG: float = 0.504
    STRAFE_SCALE: float = 0.224
    TAP_STRETCH: float = 0.2
    RULE_OUTPUT_GAIN: float = 1.0
