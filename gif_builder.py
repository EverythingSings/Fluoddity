from pygifsicle import optimize, gifsicle
import glob

# Method 1: Create GIF from individual frames
def create_gif_from_frames(frame_dir="frames", output="animation.gif", fps=50,reverse_it=False):
    # Get all frame files in order
    frame_files = sorted(glob.glob(f"{frame_dir}/frame_*.gif"))
    #print(f"Found files: {frame_files}")
    # Create GIF using gifsicle
    option_set=[f"--delay={100//fps}",# Delay in centiseconds
                 "--loop"
                 ]
    #if reverse_it:
        #option_set.append("--reverse")
    gifsicle(
        sources=frame_files,
        destination=output,
        optimize=False,  # We'll optimize separately if needed
        colors=256,
        options=option_set
    )
    
    # Optimize the GIF
    optimize(output)

# Method 2: More control with custom options
def create_optimized_gif(frame_dir="frames", output="animation_opt.gif", fps=50):
    frame_files = sorted(glob.glob(f"{frame_dir}/frame_*.gif"))
    
    gifsicle(
        sources=frame_files,
        destination=output,
        optimize=True,
        colors=128,  # Reduce colors for smaller file
        options=[
            f"--delay={100//fps}",
            "--loop",  # Loop forever
            #"--scale=0.8",  # Scale down if needed
            "--lossy=30"  # Lossy compression for smaller files
        ]
    )

# Usage
#create_gif_from_frames()
#create_optimized_gif()