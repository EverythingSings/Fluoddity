from utilities.vid_saver import VidSaver


class VideoRecorderService:
    """Wraps VidSaver, provides clean interface for Orchestrator."""

    def __init__(self):
        self.recorder = VidSaver()

    def is_active(self) -> bool:
        """Check if recording is active."""
        return self.recorder.active

    def finished_naturally(self) -> bool:
        """Check if recording ended by reaching max_frames (not manual stop)."""
        return self.recorder.finished_naturally

    @property
    def current_frame(self) -> int:
        """Current recording frame count."""
        return self.recorder.current_frame

    def start(self, stereo: bool = False) -> None:
        """Start recording.

        Args:
            stereo: If True, the current camera is in stereogram mode, so the
                video is routed to Videos/Stereo and a left/right-swapped copy
                is written to Videos/Stereo/Flipped when recording finishes.
        """
        if not self.recorder.active:
            self.recorder.finished_naturally = False
            self.recorder.stereo = stereo
            self.recorder.active = True

    def stop(self) -> None:
        """Stop recording and save video."""
        if self.recorder.active:
            self.recorder.finish()

    def toggle(self) -> None:
        """Toggle recording state."""
        if self.recorder.active:
            self.stop()
        else:
            self.start()

    def process_frame(self, ctx, texture, max_frames: int, ssk_w: int,
                      filename_prefix: str = "", flip_y: bool = True) -> None:
        """Process a frame if recording is active.

        Args:
            texture: Already assembled and gamma-corrected texture
            max_frames: Maximum frames to record
            ssk_w: Spatial supersample kernel width
            filename_prefix: Custom filename prefix (empty = use "animation")
            flip_y: Whether to flip vertically (False for 3D view mode)
        """
        self.recorder.frame(ctx, texture, max_frames, ssk_w, filename_prefix, flip_y=flip_y)

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self.recorder.active:
            self.recorder.finish()
