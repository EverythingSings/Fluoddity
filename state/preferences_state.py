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
    color_by_cohort: bool = False
    rule_seed: float = 0.0

    # UI preferences
    physics_tooltips_enabled: bool = True

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
        return PreferencesState(**data)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Failed to load preferences from {filepath}: {e}")
        print("Using default preferences")
        return PreferencesState()
