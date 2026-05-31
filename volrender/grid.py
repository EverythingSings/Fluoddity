"""Voxel grid allocation, clear, and world-to-grid coordinate transforms.

VRAM accounting (per r32f 3D texture = 4 * Nx * Ny * Nz bytes):

    256^3 density                          =  67 MB
    256^3 x 6 outer-product channels       = 402 MB
    32^3  majorant                         = 128 KB
    Total (256^3, OP on)                  ~= 0.47 GB

    512^3 density                          = 537 MB
    512^3 x 6 outer-product channels       = 3.22 GB
    32^3  majorant                         = 128 KB
    Total (512^3, OP on)                  ~= 3.75 GB  (fits 8 GB with room)
"""
from __future__ import annotations

import moderngl
import numpy as np

from .params import GridParams

# Outer-product channel order (symmetric 3x3 → 6 components)
OP_CHANNELS = ("xx", "yy", "zz", "xy", "xz", "yz")


class VoxelGrid:
    """GPU-resident voxel grids: density, outer-product, and majorant.

    All textures are r32f so they can be bound as images for atomicAdd
    in the splat pass and sampled as sampler3D in the transport pass.
    """

    def __init__(self, ctx: moderngl.Context, params: GridParams):
        self.ctx = ctx
        self.params = params

        res = params.resolution
        maj = params.majorant_resolution
        bmin = np.array(params.bounds_min, dtype=np.float32)
        bmax = np.array(params.bounds_max, dtype=np.float32)

        self._bounds_min = bmin
        self._bounds_max = bmax
        self._resolution = np.array(res, dtype=np.float32)
        self._extent = bmax - bmin
        self._voxel_size = self._extent / self._resolution
        self._voxel_volume = float(np.prod(self._voxel_size))

        # --- density texture (linear filtering for trilinear reconstruction) ---
        self.density = ctx.texture3d(res, 1, dtype='f4')
        self.density.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.density.repeat_x = False
        self.density.repeat_y = False
        self.density.repeat_z = False

        # --- outer-product textures (6 channels, linear filtering) ---
        self.outer_product: list[moderngl.Texture3D] = []
        if params.splat_outer_product:
            for _ in OP_CHANNELS:
                tex = ctx.texture3d(res, 1, dtype='f4')
                tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
                tex.repeat_x = False
                tex.repeat_y = False
                tex.repeat_z = False
                self.outer_product.append(tex)

        # --- majorant texture (nearest filtering, coarse resolution) ---
        self.majorant = ctx.texture3d(maj, 1, dtype='f4')
        self.majorant.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.majorant.repeat_x = False
        self.majorant.repeat_y = False
        self.majorant.repeat_z = False

        # Pre-compute zero data for clears
        self._density_zeros = bytes(res[0] * res[1] * res[2] * 4)
        self._majorant_zeros = bytes(maj[0] * maj[1] * maj[2] * 4)

        # Initial clear
        self.clear()

    # ------------------------------------------------------------------ clear
    def clear(self):
        """Zero density, outer-product, and majorant grids."""
        self.density.write(self._density_zeros)
        for tex in self.outer_product:
            tex.write(self._density_zeros)
        self.majorant.write(self._majorant_zeros)

    # --------------------------------------------------------- Python helpers
    @property
    def voxel_volume(self) -> float:
        """Volume of a single voxel in world units^3."""
        return self._voxel_volume

    def world_to_grid(self, world_pos: np.ndarray) -> np.ndarray:
        """Map world-space position(s) to continuous grid coordinates.

        bounds_min -> (0, 0, 0), bounds_max -> resolution.
        Input/output shapes: (3,) or (N, 3).
        """
        return (world_pos - self._bounds_min) / self._extent * self._resolution

    def grid_to_world(self, grid_pos: np.ndarray) -> np.ndarray:
        """Map continuous grid coordinates to world-space position(s).

        (0, 0, 0) -> bounds_min, resolution -> bounds_max.
        Input/output shapes: (3,) or (N, 3).
        """
        return grid_pos / self._resolution * self._extent + self._bounds_min
