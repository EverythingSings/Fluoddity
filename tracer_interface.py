"""Tracer interface: bridges Fluoddity's entity buffer and camera to the volrender path tracer.

All logic for the Tracer window lives here. The UI mixin (ui/tracer_window.py)
renders ImGui controls and calls into this class for rendering.

Supports two modes:
  1. Interactive preview: "Re-render" button starts a progressive render,
     accumulating 1 SPP per app frame until num_samples is reached.
  2. Video recording (tracer mode): the orchestrator drives accumulation,
     interleaving physics steps at the correct cadence and sending resolved
     frames to the video recorder.
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from volrender import (
    VolumeRenderer, GridParams, MediumParams, SunParams, SkyParams, RenderParams
)
from volrender.renderer import _tryset


class TracerInterface:
    """Manages the volrender VolumeRenderer for the Tracer window.

    Created lazily on first render request. All GPU resources are allocated
    through the shared ModernGL context.
    """

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self._renderer: VolumeRenderer | None = None
        self._target_tex: moderngl.Texture | None = None   # rgba16f HDR result
        self._display_tex: moderngl.Texture | None = None   # rgba8 tonemapped for imgui
        self._display_size: tuple[int, int] = (0, 0)

        # Progressive render state
        self._rendering = False
        self._samples_done = 0
        self._render_view_proj = None
        self._render_target_spp = 0
        self._render_complete = False
        self._last_spp = 0

        # Default parameter state (matches demo defaults)
        self.extinction_rgb = [1.0, 1.0, 1.0]
        self.albedo_rgb = [0.8, 0.8, 0.8]
        self.density_scale = 0.0001
        self.sun_direction = [0.577, 0.577, 0.577]
        self.sun_color = [1.0, 0.95, 0.9]
        self.sun_intensity = 3.0
        self.sky_color = [0.5, 0.7, 1.0]
        self.sky_intensity = 1.0
        self.num_samples = 64
        self.exposure = 1.5

    # ------------------------------------------------------------------ setup
    def _ensure_renderer(self):
        """Lazily create the VolumeRenderer on first use."""
        if self._renderer is not None:
            return
        grid_params = GridParams(
            bounds_min=(-1.0, -1.0, -1.0),
            bounds_max=(1.0, 1.0, 1.0),
            resolution=(512, 512, 512),
            majorant_resolution=(16, 16, 16),
            splat_outer_product=False,
        )
        self._renderer = VolumeRenderer(self.ctx, grid_params)

    def _ensure_textures(self, width: int, height: int):
        """Allocate or reallocate HDR target and LDR display textures."""
        if self._display_size == (width, height):
            return
        if self._target_tex is not None:
            self._target_tex.release()
        if self._display_tex is not None:
            self._display_tex.release()
        self._target_tex = self.ctx.texture((width, height), 4, dtype='f2')
        self._target_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._display_tex = self.ctx.texture((width, height), 4)
        self._display_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._display_size = (width, height)

    # -------------------------------------------------------- progressive API

    def start_render(self, entity_buffer: moderngl.Buffer, entity_count: int,
                     view_proj: np.ndarray, width: int = 512, height: int = 512):
        """Begin a new progressive render: splat entities, reset accumulation, lock camera.

        After calling this, call tick() once per app frame to accumulate 1 SPP.
        """
        self._ensure_renderer()
        self._ensure_textures(width, height)

        # Splat entities into voxel grid + rebuild majorant
        self._renderer.splat(entity_buffer, entity_count)

        # Lock camera and target SPP for this render
        self._render_view_proj = view_proj.copy()
        self._render_target_spp = self.num_samples

        # Reset accumulation
        self._renderer.reset_accumulation()
        self._samples_done = 0
        self._rendering = True
        self._render_complete = False

    def tick(self) -> bool:
        """Accumulate 1 SPP and resolve for display. Returns True when all samples are done."""
        if not self._rendering:
            return False

        medium, sun, sky, render = self._build_params()

        self._renderer.accumulate(
            1, self._render_view_proj, self._target_tex,
            medium, sun, sky, render
        )
        self._samples_done += 1

        # Resolve current accumulation into target for display
        self._resolve_current()
        # Tonemap into display texture
        self._tonemap_to_display()

        if self._samples_done >= self._render_target_spp:
            self._rendering = False
            self._last_spp = self._samples_done
            self._render_complete = True
            return True

        return False

    # -------------------------------------------------- video recording API

    def start_video_render(self, entity_buffer: moderngl.Buffer, entity_count: int,
                           view_proj: np.ndarray, width: int, height: int):
        """Begin a progressive render sized for video output.

        Same as start_render but with caller-specified dimensions matching
        the app window.
        """
        self.start_render(entity_buffer, entity_count, view_proj, width, height)

    def tick_video(self) -> bool:
        """Accumulate 1 SPP for video. Returns True when this output frame is complete.

        Does NOT tonemap to display texture (the caller resolves to the
        HDR target and sends that to the video recorder).
        """
        if not self._rendering:
            return False

        medium, sun, sky, render = self._build_params()

        self._renderer.accumulate(
            1, self._render_view_proj, self._target_tex,
            medium, sun, sky, render
        )
        self._samples_done += 1

        if self._samples_done >= self._render_target_spp:
            # Resolve final accumulation into target
            self._resolve_current()
            self._rendering = False
            self._last_spp = self._samples_done
            self._render_complete = True
            return True

        return False

    def re_splat(self, entity_buffer: moderngl.Buffer, entity_count: int,
                 view_proj: np.ndarray):
        """Re-splat entities mid-accumulation for motion blur.

        Updates the density grid with new entity positions without resetting
        the accumulation buffer. Subsequent samples will use the new density,
        producing temporal averaging (motion blur) when resolved.
        """
        self._ensure_renderer()
        self._renderer.splat(entity_buffer, entity_count)
        self._render_view_proj = view_proj.copy()

    # --------------------------------------------------------- param building
    def _build_params(self):
        """Build volrender parameter dataclasses from current slider state."""
        sd = np.array(self.sun_direction, dtype=np.float64)
        norm = np.linalg.norm(sd)
        if norm > 1e-6:
            sd = sd / norm
        else:
            sd = np.array([0.0, 1.0, 0.0])

        medium = MediumParams(
            extinction_rgb=tuple(self.extinction_rgb),
            albedo_rgb=tuple(self.albedo_rgb),
            density_scale=self.density_scale,
        )
        sun = SunParams(
            direction=tuple(sd),
            color_rgb=tuple(self.sun_color),
            intensity=self.sun_intensity,
        )
        sky = SkyParams(
            color_rgb=tuple(self.sky_color),
            intensity=self.sky_intensity,
        )
        render = RenderParams(
            num_samples=self.num_samples,
            batch_spp=1,
            max_bounces=0,
            rr_start_depth=4,
            seed=0,
        )
        return medium, sun, sky, render

    # ------------------------------------------------------- resolve / tonemap
    def _resolve_current(self):
        """Resolve the accumulation buffer into target_tex."""
        if self._samples_done == 0:
            return
        w, h = self._target_tex.width, self._target_tex.height
        prog = self._renderer._resolve_program
        _tryset(prog, 'u_target_size', (w, h))
        _tryset(prog, 'u_sample_count', self._samples_done)

        self._renderer._accum_tex.bind_to_image(0, read=True, write=False)
        self._target_tex.bind_to_image(1, read=False, write=True)

        gx = math.ceil(w / 8)
        gy = math.ceil(h / 8)
        prog.run(gx, gy, 1)
        self.ctx.memory_barrier()

    def _tonemap_to_display(self):
        """Read back HDR target, apply exposure+reinhard+gamma, write to rgba8 display tex."""
        tex = self._target_tex
        raw = tex.read()
        expected_f16 = tex.height * tex.width * 4 * 2
        if len(raw) == expected_f16:
            hdr = np.frombuffer(raw, dtype=np.float16).astype(
                np.float32).reshape(tex.height, tex.width, 4)
        else:
            hdr = np.frombuffer(raw, dtype=np.float32).reshape(
                tex.height, tex.width, 4)

        rgb = hdr[:, :, :3].copy()

        # Exposure + Reinhard tonemap (matches demo shader)
        exposed = rgb * self.exposure
        ldr = exposed / (1.0 + exposed)

        # Gamma correction
        ldr = np.power(np.clip(ldr, 0.0, None), 1.0 / 2.2)

        # To uint8 RGBA
        alpha = np.ones((tex.height, tex.width, 1), dtype=np.float32)
        rgba = np.concatenate([ldr, alpha], axis=2)
        img_u8 = (np.clip(rgba, 0.0, 1.0) * 255).astype(np.uint8)

        # Flip vertically (OpenGL y=0 bottom -> imgui y=0 top)
        img_u8 = img_u8[::-1].copy()

        self._display_tex.write(img_u8.tobytes())

    def tonemap_for_video(self) -> moderngl.Texture:
        """Tonemap the resolved HDR target into the display texture and return it.

        Used by the video recording path to get a tonemapped frame for the
        video service. The display_tex is rgba8 which the vid_saver expects.
        """
        self._tonemap_to_display()
        return self._display_tex

    # ------------------------------------------------------------ properties
    @property
    def display_texture(self) -> moderngl.Texture | None:
        """The rgba8 tonemapped texture for imgui display, or None if no render yet."""
        if self._display_tex is not None and (self._rendering or self._render_complete):
            return self._display_tex
        return None

    @property
    def has_result(self) -> bool:
        """Whether a completed render is available for display."""
        return self._render_complete

    @property
    def is_rendering(self) -> bool:
        """Whether a progressive render is in progress."""
        return self._rendering

    @property
    def samples_done(self) -> int:
        """Number of samples accumulated so far in the current render."""
        return self._samples_done

    @property
    def last_spp(self) -> int:
        """The SPP count of the last completed render."""
        return self._last_spp

    @property
    def target_texture(self) -> moderngl.Texture | None:
        """The HDR target texture (rgba16f). Used by video recording for readback."""
        return self._target_tex
