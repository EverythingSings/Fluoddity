from utilities.vid_saver import VidSaver


class VideoRecorderService:
    """Wraps VidSaver, provides clean interface for Orchestrator."""

    def __init__(self):
        self.recorder = VidSaver()

    def is_active(self) -> bool:
        """Check if recording is active."""
        return self.recorder.active

    def start(self) -> None:
        """Start recording."""
        if not self.recorder.active:
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

    def process_frame(self, ctx, texture, max_frames: int,
                      mb_samples: int, ssk_w: int) -> None:
        """Process a frame if recording is active."""
        self.recorder.frame(ctx, texture, max_frames, mb_samples, ssk_w)

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self.recorder.active:
            self.recorder.finish()
