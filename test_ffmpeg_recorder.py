"""
Simple test to verify ffmpeg_recorder works correctly.
This creates a test video with colored frames to ensure the pipeline is working.
"""

import numpy as np
from ffmpeg_recorder import FFmpegVideoRecorder

def create_test_frame(width, height, frame_num, total_frames):
    """Create a test frame with a color gradient that changes over time."""
    # Create RGB frame
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Create a gradient that changes color over time
    progress = frame_num / total_frames

    # Red channel: horizontal gradient
    frame[:, :, 0] = (np.linspace(0, 255, width) * (1 - progress) +
                      np.linspace(255, 0, width) * progress).astype(np.uint8)

    # Green channel: vertical gradient
    frame[:, :, 1] = (np.linspace(0, 255, height)[:, np.newaxis] * progress).astype(np.uint8)

    # Blue channel: diagonal effect
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)[:, np.newaxis]
    frame[:, :, 2] = ((x + y) * 127.5 * (1 - progress)).astype(np.uint8)

    return frame

def test_recorder():
    """Test the FFmpegVideoRecorder with synthetic frames."""
    width, height = 640, 480
    fps = 30
    num_frames = 90  # 3 seconds at 30fps

    print(f"Creating test video: {width}x{height} @ {fps}fps for {num_frames} frames")

    with FFmpegVideoRecorder(width, height, fps, "test_output.mp4", realtime=True) as recorder:
        for i in range(num_frames):
            frame = create_test_frame(width, height, i, num_frames)
            recorder.write_frame_from_array(frame)

            if (i + 1) % 10 == 0:
                print(f"Processed {i + 1}/{num_frames} frames")

    print("Test complete! Check test_output.mp4")

if __name__ == "__main__":
    test_recorder()
