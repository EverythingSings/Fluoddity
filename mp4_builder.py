import cv2
import glob

def create_mp4_from_frames(frame_dir="frames", output="animation.mp4", fps=50, reverse_it=False):
    """
    DEPRECATED: Use ffmpeg_recorder.FFmpegVideoRecorder instead for better performance.

    Create high-quality MP4 from individual PNG frames using OpenCV.
    This method is I/O wasteful as it writes PNGs to disk then reads them back.

    Args:
        frame_dir: Directory containing frame files
        output: Output MP4 filename
        fps: Frames per second
        reverse_it: If True, reverse the frame order
    """
    
    # Get all frame files in order - assuming PNG format now
    frame_files = sorted(glob.glob(f"{frame_dir}/frame_*.png"))
    
    if not frame_files:
        print(f"No frame files found in {frame_dir}")
        return
    
    print(f"Found {len(frame_files)} frames")
    
    # Reverse order if requested
    if reverse_it:
        frame_files = frame_files[::-1]
    
    # Read first frame to get dimensions
    first_frame = cv2.imread(frame_files[0])
    if first_frame is None:
        print(f"Could not read first frame: {frame_files[0]}")
        return
        
    height, width, channels = first_frame.shape
    
    # Codec and quality settings for high-quality creative coding animations
    # H264 codec provides excellent compression with high quality
    # Alternative: use 'XVID' for slightly larger files but broader compatibility
    fourcc = cv2.VideoWriter_fourcc(*'avc1')  
    
    # Create VideoWriter object
    # Note: OpenCV quality is controlled by the codec choice and bitrate
    # H264 automatically uses high quality settings for the given resolution
    video_writer = cv2.VideoWriter(
        output, 
        fourcc, 
        fps, 
        (width, height),
        isColor=True  # Set to True for color videos, False for grayscale
    )
    
    if not video_writer.isOpened():
        print("Error: Could not open video writer")
        return
    
    # Write each frame to the video
    for i, frame_file in enumerate(frame_files):
        frame = cv2.imread(frame_file)
        if frame is None:
            print(f"Warning: Could not read frame {frame_file}")
            continue
            
        # Ensure frame dimensions match (in case of inconsistent frame sizes)
        if frame.shape[:2] != (height, width):
            frame = cv2.resize(frame, (width, height))
        
        video_writer.write(frame)
        
        # Optional: Progress indicator for long sequences
        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(frame_files)} frames")
    
    # Clean up
    video_writer.release()
    cv2.destroyAllWindows()
    

# Usage examples:
#create_mp4_from_frames()  # Basic usage
# create_mp4_from_frames(fps=60, reverse_it=True)  # Higher fps with reverse
# create_mp4_from_frames("my_frames", "my_animation.mp4", fps=30)  # Custom paths