import numpy as np
import matplotlib.pyplot as plt

def display_brightness_histogram(array, k):
    """
    Display overlaid histograms of the x, y, z channels from a 4-channel f32 texture array.
    
    Parameters:
    array (numpy.ndarray): Flat array from moderngl texture.read() containing 4-channel f32 data
    k (int): Number of histogram buckets
    """
    # Reshape the flat array to have 4 channels per pixel
    # The array from texture.read() is flat: [r,g,b,a,r,g,b,a,...]
    pixels = array.reshape(-1, 4)
    # Extract individual channels (x, y, z correspond to r, g, b)
    x_channel = pixels[:, 0]  # Red/X channel
    y_channel = pixels[:, 1]  # Green/Y channel  
    x_channel = np.log((x_channel**2+y_channel**2)**.5+.001)
    z_channel = np.log(pixels[:, 2]+.001)  # Blue/Z channel
    
    # Create histogram
    plt.figure(figsize=(10, 6))
    
    # Plot overlaid histograms with 33% transparency
    plt.hist(x_channel, bins=k, alpha=0.33, color='red', label='X channel (Red)', edgecolor='darkred')
    #plt.hist(y_channel, bins=k, alpha=0.33, color='green', label='Y channel (Green)', edgecolor='darkgreen')
    plt.hist(z_channel, bins=k, alpha=0.33, color='blue', label='Z channel (Blue)', edgecolor='darkblue')
    
    # Customize the plot
    plt.title(f'Channel Histograms - X, Y, Z ({k} buckets)', fontsize=14, fontweight='bold')
    plt.xlabel('Channel Value', fontsize=12)
    plt.ylabel('Number of pixels', fontsize=12)
    plt.grid(True, alpha=0.3)
    
    # Add mean lines for each channel
    mean_x = np.mean(x_channel)
    mean_y = np.mean(y_channel)
    mean_z = np.mean(z_channel)
    
    #plt.axvline(mean_x, color='darkred', linestyle='--', linewidth=1.5, alpha=0.8)
    #plt.axvline(mean_y, color='darkgreen', linestyle='--', linewidth=1.5, alpha=0.8)
    #plt.axvline(mean_z, color='darkblue', linestyle='--', linewidth=1.5, alpha=0.8)
    
    # Add legend
    plt.legend()
    
    # Add statistics info
    info_text = f'Total pixels: {len(x_channel):,}\nMean X: {mean_x:.3f}\nMean Y: {mean_y:.3f}\nMean Z: {mean_z:.3f}'
    plt.text(0.02, 0.98, info_text, transform=plt.gca().transAxes, 
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    plt.tight_layout()
    plt.show()
    
    # Return some useful statistics
    return {
        'mean_x': mean_x,
        'mean_y': mean_y,
        'mean_z': mean_z,
        'max_x': np.max(x_channel),
        'max_y': np.max(y_channel),
        'max_z': np.max(z_channel),
        'min_x': np.min(x_channel),
        'min_y': np.min(y_channel),
        'min_z': np.min(z_channel),
        'total_pixels': len(x_channel)
    }

# Example usage:
# stats = display_brightness_histogram(texture_array, 50)