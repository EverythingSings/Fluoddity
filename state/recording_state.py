from dataclasses import dataclass


@dataclass
class RecordingState:
    """State for video recording parameters."""
    max_frames: int = 150 * 12
    motion_blur_samples: int = 12
    supersample_k: int = 2
