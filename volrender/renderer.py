from __future__ import annotations

import math
import os

import moderngl
import numpy as np

from .params import GridParams, MediumParams, SunParams, SkyParams, RenderParams
from .grid import VoxelGrid
from .majorant import MajorantBuilder
from .camera import Camera

_SHADER_DIR = os.path.join(os.path.dirname(__file__), "shaders")


def _tryset(prog: moderngl.Program, name: str, value):
    """Set a uniform if it exists (silently skip if optimized out)."""
    if name in prog:
        prog[name] = value


def _read_shader(name: str) -> str:
    path = os.path.join(_SHADER_DIR, name)
    with open(path, 'r') as f:
        return f.read()


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

    # Workgroup size for pathtrace.comp (must match layout in shader)
    _PT_WG_X = 8
    _PT_WG_Y = 8

    def __init__(self, ctx: moderngl.Context, grid_params: GridParams):
        self.ctx = ctx
        self.grid_params = grid_params
        self.grid = VoxelGrid(ctx, grid_params)
        self.majorant_builder = MajorantBuilder(ctx)
        self.camera = Camera()

        # Compile pathtrace compute shader (prepend common.glsl after #version)
        common_src = _read_shader("common.glsl")
        pt_src = _read_shader("pathtrace.comp")
        insert_pos = pt_src.find("\n")
        pt_src = pt_src[:insert_pos + 1] + common_src + pt_src[insert_pos + 1:]
        self._pathtrace_program = ctx.compute_shader(pt_src)

    def splat(self, entity_buffer: moderngl.Buffer, entity_count: int):
        """Deposit entities into the voxel grid and rebuild the majorant."""
        self.grid.splat(entity_buffer, entity_count)
        self.majorant_builder.build(self.grid)

    # ------------------------------------------------------------------ debug
    def render_debug(self, view_proj, target: moderngl.Texture,
                     medium: MediumParams, sky: SkyParams,
                     debug_steps: int = 256):
        """Dispatch the debug fixed-step raymarch for visual validation.

        Writes linear HDR into ``target`` (expected rgba16f or rgba32f).
        This is a single-pass, non-accumulating dispatch.

        Args:
            view_proj: 4×4 numpy array (proj @ view), same as from the
                       main camera's ``compute_fps_view_proj``.
            target:    moderngl Texture (2D, rgba16f/rgba32f) to write into.
            medium:    MediumParams (extinction_rgb, density_scale used).
            sky:       SkyParams (color_rgb, intensity used).
            debug_steps: Number of fixed march steps along each ray.
        """
        self.camera.set_view_proj(view_proj)

        prog = self._pathtrace_program

        # Camera
        self.camera.upload(prog)

        # Target size
        _tryset(prog, 'u_target_size', (target.width, target.height))

        # Debug mode
        _tryset(prog, 'u_debug_raymarch', True)
        _tryset(prog, 'u_debug_steps', debug_steps)

        # Medium
        _tryset(prog, 'u_extinction_rgb', medium.extinction_rgb)
        _tryset(prog, 'u_density_scale', medium.density_scale)

        # Sky
        _tryset(prog, 'u_sky_color', sky.color_rgb)
        _tryset(prog, 'u_sky_intensity', sky.intensity)

        # Grid uniforms
        _tryset(prog, 'u_bounds_min', tuple(self.grid._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(self.grid._bounds_max))
        _tryset(prog, 'u_resolution', tuple(self.grid._resolution))
        _tryset(prog, 'u_voxel_volume', self.grid._voxel_volume)

        # Bind density as sampler3D (trilinear filtered) on texture unit 0
        self.grid.density.use(location=0)
        _tryset(prog, 'u_density', 0)

        # Bind output target as image (binding 0)
        target.bind_to_image(0, read=False, write=True)

        # Dispatch
        gx = math.ceil(target.width / self._PT_WG_X)
        gy = math.ceil(target.height / self._PT_WG_Y)
        prog.run(gx, gy, 1)

        self.ctx.memory_barrier()

    # ------------------------------------------------------------------ stubs
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
