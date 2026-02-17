import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

# Load and binarize
img = np.array(Image.open("rawtext.png").convert("L"))
# Nonzero pixels = text (foreground). EDT needs 0 at foreground.
binary = (img == 0).astype(np.uint8)  # 1 where empty, 0 where text

# Exact euclidean distance transform (distance from each empty pixel to nearest text pixel)
dist = distance_transform_edt(binary)

# Normalize: 1.0 = max(width, height)
max_dist = max(img.shape[0], img.shape[1])
dist_norm = np.clip(dist / max_dist, 0.0, 1.0)

# Save as 8-bit grayscale
out = (dist_norm * 255.0).astype(np.uint8)
Image.fromarray(out, mode="L").save("dftext.png")

print(f"Input:  {img.shape[1]}x{img.shape[0]}")
print(f"Max raw distance: {dist.max():.1f} px")
print(f"Normalization divisor: {max_dist} px")
print(f"Saved dftext.png")
