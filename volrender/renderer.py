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
    colored extinction, per-voxel hue-derived albedo, ratio-tracked direct
    sun lighting, and uniform sky illumination.

    Global conventions
    ------------------
    Entity buffer layout (std430, 32 bytes / 8 floats per entity):
        float px, py, pz   — position (world space)
        float vx, vy, vz   — velocity (unused by splat)
        float hue           — per-particle hue, splatted as circular-mean
        float size          — IGNORED
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

        # Compile pathtrace compute shader
        # Prepend common.glsl then volume_scene.glsl after #version line.
        # Order matters: common provides RNG + sample_sphere,
        # volume_scene uses those and provides scene/BRDF functions,
        # pathtrace.comp uses everything.
        common_src = _read_shader("common.glsl")
        scene_src = _read_shader("volume_scene.glsl")
        pt_src = _read_shader("pathtrace.comp")
        insert_pos = pt_src.find("\n")
        pt_src = pt_src[:insert_pos + 1] + common_src + scene_src + pt_src[insert_pos + 1:]
        self._pathtrace_program = ctx.compute_shader(pt_src)

        # Compile resolve compute shader (Step 9) — no common.glsl needed
        resolve_src = _read_shader("resolve.comp")
        self._resolve_program = ctx.compute_shader(resolve_src)

        # Accumulation state (lazily allocated to match target resolution)
        self._accum_tex: moderngl.Texture | None = None
        self._accum_size: tuple[int, int] = (0, 0)
        self._accum_sample_count: int = 0
        self._last_target: moderngl.Texture | None = None

    def reload_shaders(self):
        """Recompile pathtrace and resolve compute shaders from disk."""
        try:
            common_src = _read_shader("common.glsl")
            scene_src = _read_shader("volume_scene.glsl")
            pt_src = _read_shader("pathtrace.comp")
            insert_pos = pt_src.find("\n")
            pt_src = pt_src[:insert_pos + 1] + common_src + scene_src + pt_src[insert_pos + 1:]
            new_pt = self.ctx.compute_shader(pt_src)

            resolve_src = _read_shader("resolve.comp")
            new_resolve = self.ctx.compute_shader(resolve_src)

            # Only swap after both compile successfully
            self._pathtrace_program = new_pt
            self._resolve_program = new_resolve
            print("VolumeRenderer shaders reloaded")
        except Exception as e:
            print(f"VolumeRenderer shader reload failed: {e}")

    def splat(self, entity_buffer: moderngl.Buffer, entity_count: int):
        """Deposit entities into the voxel grid and rebuild the majorant."""
        self.grid.splat(entity_buffer, entity_count)
        self.majorant_builder.build(self.grid)

    # -------------------------------------------------------- accumulation
    def _ensure_accum_buffer(self, width: int, height: int):
        """Allocate or reallocate the rgba32f accumulation buffer if needed."""
        if self._accum_tex is not None and self._accum_size == (width, height):
            return
        if self._accum_tex is not None:
            self._accum_tex.release()
        self._accum_tex = self.ctx.texture((width, height), 4, dtype='f4')
        self._accum_size = (width, height)
        # Pre-allocate zero buffer for accumulation resets (screen-sized, not grid-sized)
        self._accum_zeros = bytes(width * height * 4 * 4)

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
        _tryset(prog, 'u_accumulate', False)
        _tryset(prog, 'u_sdf_enabled', False)

        # Medium
        _tryset(prog, 'u_extinction_rgb', medium.extinction_rgb)
        _tryset(prog, 'u_density_scale', medium.density_scale)
        _tryset(prog, 'u_colored_extinction', medium.colored_extinction)
        _tryset(prog, 'u_albedo_saturation', medium.albedo_saturation)
        _tryset(prog, 'u_albedo_brightness',
                min(medium.albedo_brightness, 1.0) if medium.colored_extinction
                else medium.albedo_brightness)

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

        # Hue-color accumulation samplers (needed for colored extinction)
        self.grid.color_x.use(location=2)
        _tryset(prog, 'u_color_x', 2)
        self.grid.color_y.use(location=3)
        _tryset(prog, 'u_color_y', 3)

        # Bind output target as image (binding 0)
        target.bind_to_image(0, read=False, write=True)

        # Dispatch
        gx = math.ceil(target.width / self._PT_WG_X)
        gy = math.ceil(target.height / self._PT_WG_Y)
        prog.run(gx, gy, 1)

        self.ctx.memory_barrier()

    # --------------------------------------------------------- delta test
    def render_delta_test(self, view_proj, target: moderngl.Texture,
                          medium: MediumParams, sky: SkyParams):
        """Dispatch delta-tracked free flight for visual validation.

        Writes linear HDR into ``target`` (expected rgba16f or rgba32f).
        Single-sample, non-accumulating dispatch.  Real collisions are
        rendered white, escapes as sky color.

        This is the Step 6 validation entry point.  Steps 7–9 fold
        the delta-tracking call into the full bounce loop.

        Args:
            view_proj: 4x4 numpy array (proj @ view).
            target:    moderngl Texture (2D, rgba16f/rgba32f) to write into.
            medium:    MediumParams (extinction_rgb, density_scale used).
            sky:       SkyParams (color_rgb, intensity used).
        """
        self.camera.set_view_proj(view_proj)

        prog = self._pathtrace_program

        # Camera
        self.camera.upload(prog)

        # Target size
        _tryset(prog, 'u_target_size', (target.width, target.height))

        # Debug mode OFF — use the real delta-tracking path
        _tryset(prog, 'u_debug_raymarch', False)
        # Step 6 visual validation mode (white/sky, no bounce loop)
        _tryset(prog, 'u_debug_delta_only', True)
        _tryset(prog, 'u_accumulate', False)
        _tryset(prog, 'u_sdf_enabled', False)

        # Medium
        _tryset(prog, 'u_extinction_rgb', medium.extinction_rgb)
        _tryset(prog, 'u_density_scale', medium.density_scale)
        _tryset(prog, 'u_colored_extinction', medium.colored_extinction)
        _tryset(prog, 'u_albedo_saturation', medium.albedo_saturation)
        _tryset(prog, 'u_albedo_brightness',
                min(medium.albedo_brightness, 1.0) if medium.colored_extinction
                else medium.albedo_brightness)

        # Sky
        _tryset(prog, 'u_sky_color', sky.color_rgb)
        _tryset(prog, 'u_sky_intensity', sky.intensity)

        # Grid uniforms
        _tryset(prog, 'u_bounds_min', tuple(self.grid._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(self.grid._bounds_max))
        _tryset(prog, 'u_resolution', tuple(self.grid._resolution))
        _tryset(prog, 'u_voxel_volume', self.grid._voxel_volume)

        # Density sampler (trilinear filtered) on texture unit 0
        self.grid.density.use(location=0)
        _tryset(prog, 'u_density', 0)

        # Majorant sampler (nearest filtered) on texture unit 1
        self.grid.majorant.use(location=1)
        _tryset(prog, 'u_majorant', 1)

        # Majorant resolution
        _tryset(prog, 'u_majorant_resolution',
                self.grid.params.majorant_resolution)

        # Hue-color accumulation samplers (needed for colored extinction)
        self.grid.color_x.use(location=2)
        _tryset(prog, 'u_color_x', 2)
        self.grid.color_y.use(location=3)
        _tryset(prog, 'u_color_y', 3)

        # Bind output target as image (binding 0)
        target.bind_to_image(0, read=False, write=True)

        # Dispatch
        gx = math.ceil(target.width / self._PT_WG_X)
        gy = math.ceil(target.height / self._PT_WG_Y)
        prog.run(gx, gy, 1)

        self.ctx.memory_barrier()

    # --------------------------------------------------------- bounce test
    def render_bounce_test(self, view_proj, target: moderngl.Texture,
                           medium: MediumParams, sky: SkyParams,
                           render: RenderParams, sample_index: int = 0,
                           sun: SunParams | None = None,
                           sdf_enabled: bool = False):
        """Dispatch the bounce-loop integrator (single sample).

        Writes linear HDR into ``target`` (expected rgba16f or rgba32f).
        Single-sample, non-accumulating dispatch.  Escaped rays contribute
        sky radiance; real collisions add ratio-tracked sun NEE (Step 8)
        and scatter isotropically with albedo.

        Args:
            view_proj:    4x4 numpy array (proj @ view).
            target:       moderngl Texture (2D, rgba16f/rgba32f) to write into.
            medium:       MediumParams (extinction_rgb, density_scale, albedo_saturation/brightness).
            sky:          SkyParams (color_rgb, intensity).
            render:       RenderParams (max_bounces, rr_start_depth).
            sample_index: Per-sample seed offset for RNG decorrelation.
            sun:          SunParams or None.  None = no direct sun (Step 7 compat).
        """
        self.camera.set_view_proj(view_proj)

        prog = self._pathtrace_program

        # Camera
        self.camera.upload(prog)

        # Target size
        _tryset(prog, 'u_target_size', (target.width, target.height))

        # Mode flags
        _tryset(prog, 'u_debug_raymarch', False)
        _tryset(prog, 'u_debug_delta_only', False)
        _tryset(prog, 'u_accumulate', False)
        _tryset(prog, 'u_sdf_enabled', sdf_enabled)

        # Medium
        _tryset(prog, 'u_extinction_rgb', medium.extinction_rgb)
        _tryset(prog, 'u_density_scale', medium.density_scale)
        _tryset(prog, 'u_colored_extinction', medium.colored_extinction)
        _tryset(prog, 'u_albedo_saturation', medium.albedo_saturation)
        _tryset(prog, 'u_albedo_brightness',
                min(medium.albedo_brightness, 1.0) if medium.colored_extinction
                else medium.albedo_brightness)

        # Sky
        _tryset(prog, 'u_sky_color', sky.color_rgb)
        _tryset(prog, 'u_sky_intensity', sky.intensity)

        # Sun (Step 8)
        if sun is not None:
            _tryset(prog, 'u_sun_direction', sun.direction)
            _tryset(prog, 'u_sun_color', sun.color_rgb)
            _tryset(prog, 'u_sun_intensity', sun.intensity)
        else:
            _tryset(prog, 'u_sun_direction', (0.0, 1.0, 0.0))
            _tryset(prog, 'u_sun_color', (0.0, 0.0, 0.0))
            _tryset(prog, 'u_sun_intensity', 0.0)

        # Bounce loop control
        _tryset(prog, 'u_max_bounces', render.max_bounces)
        _tryset(prog, 'u_rr_start_depth', render.rr_start_depth)
        _tryset(prog, 'u_sample_index', sample_index)

        # Grid uniforms
        _tryset(prog, 'u_bounds_min', tuple(self.grid._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(self.grid._bounds_max))
        _tryset(prog, 'u_resolution', tuple(self.grid._resolution))
        _tryset(prog, 'u_voxel_volume', self.grid._voxel_volume)

        # Density sampler (trilinear filtered) on texture unit 0
        self.grid.density.use(location=0)
        _tryset(prog, 'u_density', 0)

        # Majorant sampler (nearest filtered) on texture unit 1
        self.grid.majorant.use(location=1)
        _tryset(prog, 'u_majorant', 1)

        # Majorant resolution
        _tryset(prog, 'u_majorant_resolution',
                self.grid.params.majorant_resolution)

        # Hue-color accumulation samplers (trilinear filtered) on units 2, 3
        self.grid.color_x.use(location=2)
        _tryset(prog, 'u_color_x', 2)
        self.grid.color_y.use(location=3)
        _tryset(prog, 'u_color_y', 3)

        # Bind output target as image (binding 0)
        target.bind_to_image(0, read=False, write=True)

        # Dispatch
        gx = math.ceil(target.width / self._PT_WG_X)
        gy = math.ceil(target.height / self._PT_WG_Y)
        prog.run(gx, gy, 1)

        self.ctx.memory_barrier()

    # -------------------------------------------------------- public API (Step 9)
    def reset_accumulation(self):
        """Zero the accumulation buffer and sample counter."""
        if self._accum_tex is not None:
            self._accum_tex.write(self._accum_zeros)
        self._accum_sample_count = 0

    def accumulate(self, n_spp: int, view_proj, target,
                   medium: MediumParams, sun: SunParams, sky: SkyParams,
                   render: RenderParams, sdf_enabled: bool = False):
        """Dispatch n_spp path-traced samples and add to the accumulator.

        Dispatches one sample per compute pass with a memory barrier after
        each to avoid read-after-write hazards on the accumulation buffer.
        The ``render.batch_spp`` field is preserved for future granularity
        control; currently each sample is an independent dispatch.

        COMMENT FLAG: batch_spp — dispatch granularity (TDR avoidance)
        COMMENT FLAG: seed — deterministic RNG base

        Args:
            n_spp:    Number of samples to accumulate.
            view_proj: 4×4 numpy array (proj @ view).
            target:   moderngl Texture — used for sizing the accumulation
                      buffer and bound to image 0 (unused placeholder).
            medium:   MediumParams.
            sun:      SunParams.
            sky:      SkyParams.
            render:   RenderParams (batch_spp, max_bounces, rr_start_depth,
                      seed).
        """
        w, h = target.width, target.height
        self._ensure_accum_buffer(w, h)
        self._last_target = target

        self.camera.set_view_proj(view_proj)
        prog = self._pathtrace_program

        # Camera
        self.camera.upload(prog)

        # Target size
        _tryset(prog, 'u_target_size', (w, h))

        # Mode flags
        _tryset(prog, 'u_debug_raymarch', False)
        _tryset(prog, 'u_debug_delta_only', False)
        _tryset(prog, 'u_accumulate', True)
        _tryset(prog, 'u_sdf_enabled', sdf_enabled)

        # Medium
        _tryset(prog, 'u_extinction_rgb', medium.extinction_rgb)
        _tryset(prog, 'u_density_scale', medium.density_scale)
        _tryset(prog, 'u_colored_extinction', medium.colored_extinction)
        _tryset(prog, 'u_albedo_saturation', medium.albedo_saturation)
        _tryset(prog, 'u_albedo_brightness',
                min(medium.albedo_brightness, 1.0) if medium.colored_extinction
                else medium.albedo_brightness)

        # Sky
        _tryset(prog, 'u_sky_color', sky.color_rgb)
        _tryset(prog, 'u_sky_intensity', sky.intensity)

        # Sun
        _tryset(prog, 'u_sun_direction', sun.direction)
        _tryset(prog, 'u_sun_color', sun.color_rgb)
        _tryset(prog, 'u_sun_intensity', sun.intensity)

        # Bounce loop control
        # COMMENT FLAG: max_bounces — 0 = unbounded (RR only)
        _tryset(prog, 'u_max_bounces', render.max_bounces)
        # COMMENT FLAG: rr_start_depth — Russian roulette onset
        _tryset(prog, 'u_rr_start_depth', render.rr_start_depth)

        # Grid uniforms
        _tryset(prog, 'u_bounds_min', tuple(self.grid._bounds_min))
        _tryset(prog, 'u_bounds_max', tuple(self.grid._bounds_max))
        _tryset(prog, 'u_resolution', tuple(self.grid._resolution))
        _tryset(prog, 'u_voxel_volume', self.grid._voxel_volume)

        # Density sampler (trilinear filtered) on texture unit 0
        self.grid.density.use(location=0)
        _tryset(prog, 'u_density', 0)

        # Majorant sampler (nearest filtered) on texture unit 1
        self.grid.majorant.use(location=1)
        _tryset(prog, 'u_majorant', 1)

        # Majorant resolution
        _tryset(prog, 'u_majorant_resolution',
                self.grid.params.majorant_resolution)

        # Hue-color accumulation samplers (trilinear filtered) on units 2, 3
        self.grid.color_x.use(location=2)
        _tryset(prog, 'u_color_x', 2)
        self.grid.color_y.use(location=3)
        _tryset(prog, 'u_color_y', 3)

        # Bind accumulation buffer to image binding 1 (read + write)
        self._accum_tex.bind_to_image(1, read=True, write=True)

        # Bind target to image binding 0 (placeholder — not written when
        # u_accumulate is true, but avoids an unbound image unit)
        target.bind_to_image(0, read=False, write=True)

        # Dispatch grid
        gx = math.ceil(w / self._PT_WG_X)
        gy = math.ceil(h / self._PT_WG_Y)

        # Dispatch one sample at a time with a barrier after each to ensure
        # the read-modify-write on img_accum is consistent.
        for i in range(n_spp):
            sample_idx = render.seed + self._accum_sample_count + i
            _tryset(prog, 'u_sample_index', sample_idx)
            prog.run(gx, gy, 1)
            self.ctx.memory_barrier()

        self._accum_sample_count += n_spp

    def render_to_completion(self, view_proj, target,
                             medium: MediumParams, sun: SunParams, sky: SkyParams,
                             render: RenderParams, sdf_enabled: bool = False):
        """Blocking render: reset, accumulate num_samples, resolve to target.

        Calls ``reset_accumulation``, then ``accumulate`` for
        ``render.num_samples`` samples, then resolves (divides by sample
        count) into the caller's ``target`` texture.

        Args:
            view_proj: 4×4 numpy array (proj @ view).
            target:   moderngl Texture (2D, rgba16f/rgba32f) to receive the
                      resolved linear HDR image.
            medium:   MediumParams.
            sun:      SunParams.
            sky:      SkyParams.
            render:   RenderParams (num_samples, batch_spp, max_bounces,
                      rr_start_depth, seed).
        """
        w, h = target.width, target.height
        self._ensure_accum_buffer(w, h)
        self.reset_accumulation()
        self.accumulate(render.num_samples, view_proj, target,
                        medium, sun, sky, render, sdf_enabled)

        # Resolve: divide accumulation by sample count, write to target
        prog = self._resolve_program
        _tryset(prog, 'u_target_size', (w, h))
        _tryset(prog, 'u_sample_count', self._accum_sample_count)

        self._accum_tex.bind_to_image(0, read=True, write=False)
        target.bind_to_image(1, read=False, write=True)

        gx = math.ceil(w / self._PT_WG_X)
        gy = math.ceil(h / self._PT_WG_Y)
        prog.run(gx, gy, 1)

        self.ctx.memory_barrier()
        self._last_target = target

    def read_frame(self) -> np.ndarray:
        """Read back the current frame as a numpy array (H, W, 4) float32.

        Returns the last resolved target texture written by
        ``render_to_completion``.  Automatically handles rgba16f and
        rgba32f target formats.
        """
        if self._last_target is None:
            raise RuntimeError(
                "No frame to read — call render_to_completion first")
        tex = self._last_target
        raw = tex.read()
        expected_f32 = tex.height * tex.width * 4 * 4
        expected_f16 = tex.height * tex.width * 4 * 2
        if len(raw) == expected_f32:
            data = np.frombuffer(raw, dtype=np.float32)
        elif len(raw) == expected_f16:
            data = np.frombuffer(raw, dtype=np.float16).astype(np.float32)
        else:
            raise RuntimeError(
                f"Unexpected read size {len(raw)} for "
                f"{tex.width}x{tex.height} texture")
        return data.reshape(tex.height, tex.width, 4)
