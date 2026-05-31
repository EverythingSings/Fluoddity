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

import math
import os

import moderngl
import numpy as np

from .params import GridParams

_SHADER_DIR = os.path.join(os.path.dirname(__file__), "shaders")


def _tryset(prog: moderngl.Program, name: str, value):
    """Set a uniform if it exists (silently skip if optimized out)."""
    if name in prog:
        prog[name] = value

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

        # --- compile splat compute shader ---
        common_src = self._read_shader("common.glsl")
        splat_src = self._read_shader("splat.comp")
        # Prepend common.glsl after #version + #extension lines
        insert_pos = splat_src.find("\n", splat_src.find("#extension"))
        if insert_pos == -1:
            insert_pos = splat_src.find("\n")
        splat_src = splat_src[:insert_pos + 1] + common_src + splat_src[insert_pos + 1:]
        self._splat_program = ctx.compute_shader(splat_src)

        # Initial clear
        self.clear()

    # ------------------------------------------------------------------ clear
    def clear(self):
        """Zero density, outer-product, and majorant grids."""
        self.density.write(self._density_zeros)
        for tex in self.outer_product:
            tex.write(self._density_zeros)
        self.majorant.write(self._majorant_zeros)

    # ------------------------------------------------------------------ splat
    def splat(self, entity_buffer: moderngl.Buffer, entity_count: int):
        """Clear grids, then trilinear-splat entities into density (and OP)."""
        self.clear()

        prog = self._splat_program

        # Grid uniforms (use _tryset — some may be optimized out)
        _tryset(prog, 'u_bounds_min', tuple(self._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(self._bounds_max))
        _tryset(prog, 'u_resolution', tuple(self._resolution))
        _tryset(prog, 'u_voxel_volume', self._voxel_volume)
        _tryset(prog, 'u_entity_count', entity_count)
        _tryset(prog, 'u_splat_outer_product',
                bool(self.params.splat_outer_product
                     and len(self.outer_product) == 6))

        # Bind entity SSBO
        entity_buffer.bind_to_storage_buffer(0)

        # Bind density image
        self.density.bind_to_image(0, read=False, write=True)

        # Bind OP images (always bind something to avoid driver complaints)
        if self.outer_product:
            for i, tex in enumerate(self.outer_product):
                tex.bind_to_image(i + 1, read=False, write=True)
        else:
            # Bind density as a dummy to all 6 OP slots (won't be written)
            for i in range(6):
                self.density.bind_to_image(i + 1, read=False, write=True)

        # Dispatch
        group_size = 256
        num_groups = math.ceil(entity_count / group_size)
        prog.run(num_groups, 1, 1)

        # Memory barrier so subsequent reads see the writes
        self.ctx.memory_barrier()

    # ------------------------------------------------------- shader loading
    @staticmethod
    def _read_shader(name: str) -> str:
        path = os.path.join(_SHADER_DIR, name)
        with open(path, 'r') as f:
            return f.read()

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
