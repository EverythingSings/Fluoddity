"""Majorant grid builder — dilated max-pool from fine density to coarse majorant.

Dispatches majorant.comp: one invocation per coarse cell, finds the max
physical_density (raw / voxel_volume) across covered fine voxels plus
a one-fine-voxel guard band, writes into the majorant texture.
"""
from __future__ import annotations

import math
import os

import moderngl
import numpy as np

_SHADER_DIR = os.path.join(os.path.dirname(__file__), "shaders")


def _tryset(prog: moderngl.Program, name: str, value):
    """Set a uniform if it exists (silently skip if optimized out)."""
    if name in prog:
        prog[name] = value


class MajorantBuilder:
    """Compiles and dispatches the majorant compute shader.

    Constructed once (e.g. in VolumeRenderer.__init__), called after
    each splat to rebuild the coarse majorant grid.
    """

    # Workgroup size must match the layout in majorant.comp
    _WG_SIZE = 4  # local_size_x = local_size_y = local_size_z = 4

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx

        # Read and prepend common.glsl (same pattern as grid.py for splat.comp)
        common_src = self._read_shader("common.glsl")
        majorant_src = self._read_shader("majorant.comp")

        # Insert common.glsl after #version line (majorant.comp has no #extension)
        insert_pos = majorant_src.find("\n")
        majorant_src = (majorant_src[:insert_pos + 1]
                        + common_src
                        + majorant_src[insert_pos + 1:])

        self._program = ctx.compute_shader(majorant_src)

    def build(self, grid) -> None:
        """Build the majorant grid from the current density texture.

        Args:
            grid: A VoxelGrid instance.  Reads grid.density, writes
                  grid.majorant.  Also reads grid params for bounds,
                  resolution, and voxel_volume.
        """
        prog = self._program

        # Grid uniforms (common.glsl)
        _tryset(prog, 'u_bounds_min', tuple(grid._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(grid._bounds_max))
        _tryset(prog, 'u_resolution', tuple(grid._resolution))
        _tryset(prog, 'u_voxel_volume', grid._voxel_volume)

        # Majorant-specific uniforms
        _tryset(prog, 'u_majorant_resolution', grid.params.majorant_resolution)

        # Bind density as read-only image (binding 0)
        grid.density.bind_to_image(0, read=True, write=False)

        # Bind majorant as write-only image (binding 1)
        grid.majorant.bind_to_image(1, read=False, write=True)

        # Dispatch: ceil(maj_res / WG_SIZE) in each dimension
        maj = grid.params.majorant_resolution
        wg = self._WG_SIZE
        prog.run(math.ceil(maj[0] / wg),
                 math.ceil(maj[1] / wg),
                 math.ceil(maj[2] / wg))

        self.ctx.memory_barrier()

    def cleanup(self):
        """Release the compute program."""
        if getattr(self, '_program', None) is not None:
            self._program.release()
            self._program = None

    def read_global_max(self, grid) -> float:
        """CPU readback of the global maximum majorant value (diagnostic).

        Returns the maximum physical density across all coarse cells.
        """
        raw = grid.majorant.read()
        data = np.frombuffer(raw, dtype=np.float32)
        return float(data.max()) if data.size > 0 else 0.0

    @staticmethod
    def _read_shader(name: str) -> str:
        path = os.path.join(_SHADER_DIR, name)
        with open(path, 'r') as f:
            return f.read()
