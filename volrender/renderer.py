from __future__ import annotations

import moderngl
import numpy as np

from .params import GridParams, MediumParams, SunParams, SkyParams, RenderParams
from .grid import VoxelGrid


class VolumeRenderer:
    """Offline volumetric path tracer.

    Ingests a moderngl Buffer of Entity structs, splats them into a dense
    voxel grid, and path-traces an isotropic participating medium with
    colored extinction, single-scattering albedo, ratio-tracked direct sun
    lighting, and uniform sky illumination.

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

    def __init__(self, ctx: moderngl.Context, grid_params: GridParams):
        self.ctx = ctx
        self.grid_params = grid_params
        self.grid = VoxelGrid(ctx, grid_params)

    def splat(self, entity_buffer: moderngl.Buffer, entity_count: int):
        """Deposit entities into the voxel grid (trilinear atomic splat)."""
        self.grid.splat(entity_buffer, entity_count)

    def reset_accumulation(self):
        """Zero the accumulation buffer and sample counter."""
        raise NotImplementedError("VolumeRenderer.reset_accumulation — implemented in Step 9")

    def accumulate(self, n_spp: int, view_proj, target,
                   medium: MediumParams, sun: SunParams, sky: SkyParams,
                   render: RenderParams):
        """Dispatch n_spp path-traced samples and add to the accumulator."""
        raise NotImplementedError("VolumeRenderer.accumulate — implemented in Step 9")

    def render_to_completion(self, view_proj, target,
                             medium: MediumParams, sun: SunParams, sky: SkyParams,
                             render: RenderParams):
        """Blocking render: reset, accumulate num_samples, resolve to target."""
        raise NotImplementedError("VolumeRenderer.render_to_completion — implemented in Step 9")

    def read_frame(self) -> np.ndarray:
        """Read back the current frame as a numpy array (H, W, 4) float32."""
        raise NotImplementedError("VolumeRenderer.read_frame — implemented in Step 9")
