"""Volumetric point-cloud path tracer.

Standalone offline renderer.  Ingests a moderngl Buffer of Entity structs,
splats them into a dense voxel grid, and path-traces an isotropic
participating medium with colored extinction, single-scattering albedo,
ratio-tracked direct sun lighting, and uniform sky illumination.

Global conventions
------------------
Entity buffer layout (std430, 32 bytes / 8 floats per entity):
    float px, py, pz   — position (world space)
    float vx, vy, vz   — velocity (orientation for outer product)
    float hue           — IGNORED in v1
    float size          — IGNORED in v1
Bind as a flat float[] array with stride 8 (base = id*8).

Sun direction:
    Unit vector pointing FROM the scene TOWARD the sun.
    Light arrives along -sun.direction.  NEE-only (no visible disk).

Density normalization:
    physical_density(x) = raw_density(x) / voxel_volume
    Applied in transport AND majorant build — nowhere else.
"""

from .params import GridParams, MediumParams, SunParams, SkyParams, RenderParams
from .grid import VoxelGrid
from .renderer import VolumeRenderer

__all__ = [
    'GridParams',
    'MediumParams',
    'SunParams',
    'SkyParams',
    'RenderParams',
    'VoxelGrid',
    'VolumeRenderer',
]
