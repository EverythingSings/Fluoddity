from dataclasses import dataclass, field, asdict
from pathlib import Path
import json


@dataclass
class PreferencesState:
    """User preferences that persist between program sessions."""

    # Slider range customizations (stores [min, max, default_min, default_max])
    slider_ranges: dict[str, list[float]] = field(default_factory=dict)

    # Camera/rendering preferences
    speedmult: int = 1
    motion_blur: bool = True
    rule_seed: float = 0.0
    brightness: float = 1.0  # Global brightness multiplier

    # UI preferences
    show_preferences_window: bool = True  # Whether preferences window is visible
    physics_tooltips_enabled: bool = True
    debug_arrows: bool = False  # Visual debug overlay for velocity field
    arrow_sensitivity: float = 9.0  # Velocity scale for debug arrows (pow(2, x))
    mouse_mode: str = "Select Particle"  # "Select Particle" or "Draw Trail"
    draw_size: float = 0.1  # Gaussian kernel width for trail drawing
    draw_power: float = 1.0  # Velocity strength when drawing trails

    # Physics slider group collapsed states (True = expanded/open, False = collapsed)
    physics_group_basics: bool = True  # Default: open (trail sensors + mutation)
    physics_group_forces: bool = True  # Default: open (global force mult, drag)
    physics_group_advanced: bool = False  # Default: collapsed

    # Parameter sweep settings (stores sweep state: 0.0=off, 1.0=normal, -1.0=inverse)
    x_sweeps: dict[str, float] = field(default_factory=dict)
    y_sweeps: dict[str, float] = field(default_factory=dict)
    cohort_sweeps: dict[str, float] = field(default_factory=dict)

    # Recording preferences
    max_frames: int = 1800  # 150 * 12
    motion_blur_samples: int = 12
    supersample_k: int = 2
    filename_prefix: str = ""


def save_preferences(prefs: PreferencesState, filepath: Path | str = "preferences.config") -> None:
    """Save preferences to a JSON file."""
    filepath = Path(filepath)
    data = asdict(prefs)
    filepath.write_text(json.dumps(data, indent=2))


def load_preferences(filepath: Path | str = "preferences.config") -> PreferencesState:
    """Load preferences from a JSON file. Returns default preferences if file doesn't exist."""
    filepath = Path(filepath)
    if not filepath.exists():
        return PreferencesState()

    try:
        data = json.loads(filepath.read_text())
        # Filter out any fields that are no longer in PreferencesState (backward compat)
        valid_fields = set(PreferencesState.__dataclass_fields__.keys())
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return PreferencesState(**filtered_data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Failed to load preferences from {filepath}: {e}")
        print("Using default preferences")
        return PreferencesState()
