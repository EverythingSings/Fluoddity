from save_frame_gpu import save_frame_gpu, reset_gpu_frame_counter, clear_gpu_frame_cache
from ffmpeg_recorder import FFmpegVideoRecorder
from datetime import datetime

class VidSaver:
    def __init__(self):
        self.active = False
        self.current_frame = 0
        self.recorder = None
        self.mb_samples = 3
        self.ssk_w = 2

    def frame(self, ctx, tex, max_frames=-1, mb_samples=3, ssk_w=2):
        if not self.active:
            return

        # Calculate current output dimensions
        width, height = tex.size
        output_width = width // ssk_w
        output_height = height // ssk_w

        # Initialize recorder on first frame OR if dimensions/settings changed
        # Compare against input dimensions (not padded dimensions)
        if self.recorder is None or (
            self.recorder.input_width != output_width or
            self.recorder.input_height != output_height or
            self.mb_samples != mb_samples or
            self.ssk_w != ssk_w
        ):
            # If recorder exists but settings changed, close it and warn user
            if self.recorder is not None:
                print(f"WARNING: Recording settings changed mid-recording!")
                print(f"  Old: {self.recorder.input_width}x{self.recorder.input_height}, mb={self.mb_samples}, ssk={self.ssk_w}")
                print(f"  New: {output_width}x{output_height}, mb={mb_samples}, ssk={ssk_w}")
                print(f"  Finishing current video and starting new one...")
                self.recorder.close()

            # Create timestamped filename
            timestamp = datetime.now().strftime('%H-%M-%S')
            output_path = f"animation-{timestamp}.mp4"

            self.recorder = FFmpegVideoRecorder(
                width=output_width,
                height=output_height,
                fps=50,  # Default fps, can be made configurable
                output_path=output_path,
                realtime=False
            )
            self.mb_samples = mb_samples
            self.ssk_w = ssk_w
            self.current_frame = 0  # Reset frame counter for new recording

        # Process frame with GPU (motion blur + supersample)
        # Use return_array=True to get numpy array instead of saving PNG
        frame_array = save_frame_gpu(tex, ctx, motion_blur_samples=mb_samples,
                                     supersample_k=ssk_w, return_array=True)

        # If we got a completed frame (not still accumulating), write it to video
        if frame_array is not None:
            self.recorder.write_frame_from_array(frame_array)
            self.current_frame += 1

            if max_frames > 0 and self.current_frame >= max_frames:
                self.finish()

    def finish(self):
        '''Save video and reset everything for another recording'''

        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None

        reset_gpu_frame_counter()
        clear_gpu_frame_cache()
        self.current_frame = 0
        self.active = False
                