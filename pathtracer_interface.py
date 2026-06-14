"""Path tracer interface: bridges Fluoddity's entity buffer and camera to the OptiX path tracer.

Manages PathTracerRenderer lifecycle (lazy creation, cleanup), entity buffer
change detection, and per-frame error recovery. Supports both realtime
(1spp + denoise per frame) and offline (multi-substep motion-blur) rendering.

NOTE for host/UI integration: the host must route the UI's volrender entry to
this renderer. The registration/dispatch-site discovery and rewiring is left
to a future host-side session. This interface exposes the same render_frame()
pattern as OptiXInterface so the host can drive it identically.
"""
from __future__ import annotations

import numpy as np
import moderngl

from optix_pathtracer import PathTracerRenderer
from optix_pathtracer.renderer import _camera_basis_from_vectors


class PathTracerInterface:
    """Manages the PathTracerRenderer for the 3D camera view.

    Created lazily on first render request. All GPU resources are allocated
    through the shared ModernGL context. If an OptiX error occurs during
    rendering, the interface auto-disables and reports failure via the
    ``failed`` property.
    """

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self._renderer: PathTracerRenderer | None = None
        self._display_tex: moderngl.Texture | None = None

        # Entity buffer tracking (for change detection)
        self._entity_buffer_glo: int = 0
        self._entity_count: int = 0

        # Error recovery state
        self._failed: bool = False
        self._fail_reason: str = ""

        # Timing (updated each frame from renderer)
        self._gas_time_ms: float = 0.0
        self._render_time_ms: float = 0.0

        # --- Public attributes (wired to UI via preferences) ---

        # Lighting
        self.sun_direction: tuple[float, float, float] = (0.577, 0.577, 0.577)
        self.sun_color: tuple[float, float, float] = (1.0, 0.95, 0.85)
        self.sun_intensity: float = 3.0
        self.sun_sampling: bool = True
        self.sky_color_top: tuple[float, float, float] = (0.45, 0.62, 0.85)
        self.sky_color_bottom: tuple[float, float, float] = (0.08, 0.08, 0.10)

        # Geometry
        self.radius_scale: float = 1.0
        self.gas_rebuild_interval: int = 30

        # Tonemapping / camera
        self.exposure: float = 1.5
        self.aperture: float = 0.0
        self.focal_plane_depth: float = 10.0

        # Bounce control
        self.max_bounces: int = 8
        self.rr_start_depth: int = 3
        self.firefly_clamp: bool = True
        self.firefly_clamp_max: float = 50.0

        # Material
        self.global_material: int = 0  # 0=Lambert, 1=Glossy, 2=Mirror
        self.glossy_ior: float = 1.5

        # Denoiser
        self.denoise_enabled: bool = False

    # ------------------------------------------------------------------ core API

    def render_frame(
        self,
        entity_buffer: moderngl.Buffer,
        entity_count: int,
        cam_pos: np.ndarray,
        cam_dir: np.ndarray,
        cam_up: np.ndarray,
        fov: float,
        width: int,
        height: int,
    ) -> moderngl.Texture | None:
        """Render one realtime path-traced frame (1spp, optional denoise).

        Handles lazy init, entity buffer change detection, and per-frame
        error recovery. On failure, cleans up and returns None.

        Args:
            entity_buffer: ModernGL buffer (SSBO binding 0, 8-float stride).
            entity_count: Number of entities in the buffer.
            cam_pos: Camera position (3,) from ControllerCam.pos.
            cam_dir: Unit look direction (3,) from ControllerCam.dir.
            cam_up: Unit up vector (3,) from ControllerCam.up.
            fov: Vertical field of view in degrees.
            width: Output image width.
            height: Output image height.

        Returns:
            moderngl.Texture (rgba8) or None if OptiX unavailable/failed.
        """
        if self._failed:
            return None

        try:
            return self._render_frame_inner(
                entity_buffer, entity_count,
                cam_pos, cam_dir, cam_up, fov,
                width, height,
            )
        except Exception as e:
            self._failed = True
            self._fail_reason = str(e)
            print(f"PathTracer render error (auto-disabling): {e}")
            self.cleanup()
            return None

    def _render_frame_inner(
        self,
        entity_buffer, entity_count,
        cam_pos, cam_dir, cam_up, fov,
        width, height,
    ):
        """Inner render logic, called from render_frame() with error wrapping."""
        # 1. Lazy initialization
        if self._renderer is None:
            self._renderer = PathTracerRenderer(
                self.ctx, entity_buffer, entity_count
            )
            self._entity_buffer_glo = int(entity_buffer.glo)
            self._entity_count = entity_count

        # 2. Entity buffer change detection
        current_glo = int(entity_buffer.glo)
        if (current_glo != self._entity_buffer_glo
                or entity_count != self._entity_count):
            self._renderer.update_entity_buffer(entity_buffer, entity_count)
            self._entity_buffer_glo = current_glo
            self._entity_count = entity_count
            # update_entity_buffer sets _gas_handle = None, which forces
            # render_realtime to do a full build on the next call

        # 3. Camera basis conversion
        aspect = width / max(height, 1)
        eye, U, V, W = _camera_basis_from_vectors(
            cam_pos, cam_dir, cam_up, fov, aspect
        )

        # Compute normalized cam_right and cam_up for DOF lens sampling
        cam_dir_arr = np.asarray(cam_dir, dtype=np.float32)
        cam_up_arr = np.asarray(cam_up, dtype=np.float32)
        cam_right_vec = np.cross(cam_dir_arr, cam_up_arr)
        cam_right_vec = cam_right_vec / max(np.linalg.norm(cam_right_vec), 1e-8)
        cam_up_vec = np.cross(cam_right_vec, cam_dir_arr)
        cam_up_vec = cam_up_vec / max(np.linalg.norm(cam_up_vec), 1e-8)

        # 4. Normalize sun direction
        sd = np.array(self.sun_direction, dtype=np.float64)
        length = max(np.linalg.norm(sd), 1e-8)
        sun_dir_norm = tuple((sd / length).astype(np.float32))

        # 5. Render (render_realtime handles GAS scheduling internally)
        self._display_tex = self._renderer.render_realtime(
            width, height, eye, U, V, W,
            radius_scale=self.radius_scale,
            gas_rebuild_interval=self.gas_rebuild_interval,
            denoise_enabled=self.denoise_enabled,
            sun_direction=sun_dir_norm,
            sun_intensity=self.sun_intensity,
            sun_color=self.sun_color,
            sun_sampling=self.sun_sampling,
            exposure=self.exposure,
            sky_color_top=self.sky_color_top,
            sky_color_bottom=self.sky_color_bottom,
            aperture=self.aperture,
            focal_plane_depth=self.focal_plane_depth,
            cam_right=cam_right_vec,
            cam_up=cam_up_vec,
            max_bounces=self.max_bounces,
            rr_start_depth=self.rr_start_depth,
            firefly_clamp=self.firefly_clamp,
            firefly_clamp_max=self.firefly_clamp_max,
            global_material=self.global_material,
            glossy_ior=self.glossy_ior,
        )

        # 6. Read timing from renderer
        self._gas_time_ms = self._renderer.last_gas_ms
        self._render_time_ms = self._renderer.last_render_ms

        return self._display_tex

    # -------------------------------------------------------------- offline API

    def start_offline_render(
        self,
        entity_buffer: moderngl.Buffer,
        entity_count: int,
        width: int,
        height: int,
        total_substeps: int,
        spp_per_substep: int,
    ) -> None:
        """Begin an offline motion-blur render.

        Initializes the renderer (if needed), handles entity buffer changes,
        builds the GAS, and starts the offline accumulation sequence.

        After calling this, call offline_substep() for each temporal sub-step
        (updating entity positions between calls), then finish_offline_render()
        to get the final tonemapped image.

        Args:
            entity_buffer: ModernGL buffer with entity data.
            entity_count: Number of entities.
            width: Output image width.
            height: Output image height.
            total_substeps: Number of temporal sub-steps for motion blur.
            spp_per_substep: Samples per pixel per sub-step.
        """
        if self._failed:
            raise RuntimeError(f"PathTracer failed: {self._fail_reason}")

        # Lazy initialization
        if self._renderer is None:
            self._renderer = PathTracerRenderer(
                self.ctx, entity_buffer, entity_count
            )
            self._entity_buffer_glo = int(entity_buffer.glo)
            self._entity_count = entity_count

        # Entity buffer change detection
        current_glo = int(entity_buffer.glo)
        if (current_glo != self._entity_buffer_glo
                or entity_count != self._entity_count):
            self._renderer.update_entity_buffer(entity_buffer, entity_count)
            self._entity_buffer_glo = current_glo
            self._entity_count = entity_count

        # Full GAS build before starting offline render
        self._renderer.build_accel(self.radius_scale)

        # Begin offline accumulation
        self._renderer.render_offline_begin(
            width, height, total_substeps, spp_per_substep,
            denoise_enabled=self.denoise_enabled,
        )

    def offline_substep(
        self,
        cam_pos: np.ndarray,
        cam_dir: np.ndarray,
        cam_up: np.ndarray,
        fov: float,
    ) -> None:
        """Trace one temporal sub-step of an offline motion-blur render.

        The caller must update entity positions (via physics step) and ensure
        the entity buffer reflects the new state BEFORE calling. The GAS is
        refitted internally to match the updated positions.

        Args:
            cam_pos: Camera position (3,).
            cam_dir: Unit look direction (3,).
            cam_up: Unit up vector (3,).
            fov: Vertical FOV in degrees.
        """
        if self._renderer is None:
            raise RuntimeError(
                "Call start_offline_render() before offline_substep()."
            )

        # Camera basis conversion
        w = self._renderer._offline_width
        h = self._renderer._offline_height
        aspect = w / max(h, 1)
        eye, U, V, W = _camera_basis_from_vectors(
            cam_pos, cam_dir, cam_up, fov, aspect
        )

        # DOF basis
        cam_dir_arr = np.asarray(cam_dir, dtype=np.float32)
        cam_up_arr = np.asarray(cam_up, dtype=np.float32)
        cam_right_vec = np.cross(cam_dir_arr, cam_up_arr)
        cam_right_vec = cam_right_vec / max(np.linalg.norm(cam_right_vec), 1e-8)
        cam_up_vec = np.cross(cam_right_vec, cam_dir_arr)
        cam_up_vec = cam_up_vec / max(np.linalg.norm(cam_up_vec), 1e-8)

        # Normalize sun direction
        sd = np.array(self.sun_direction, dtype=np.float64)
        length = max(np.linalg.norm(sd), 1e-8)
        sun_dir_norm = tuple((sd / length).astype(np.float32))

        self._renderer.render_offline_substep(
            eye, U, V, W,
            radius_scale=self.radius_scale,
            sun_direction=sun_dir_norm,
            sun_intensity=self.sun_intensity,
            sun_color=self.sun_color,
            sun_sampling=self.sun_sampling,
            exposure=self.exposure,
            sky_color_top=self.sky_color_top,
            sky_color_bottom=self.sky_color_bottom,
            aperture=self.aperture,
            focal_plane_depth=self.focal_plane_depth,
            cam_right=cam_right_vec,
            cam_up=cam_up_vec,
            max_bounces=self.max_bounces,
            rr_start_depth=self.rr_start_depth,
            firefly_clamp=self.firefly_clamp,
            firefly_clamp_max=self.firefly_clamp_max,
            global_material=self.global_material,
            glossy_ior=self.glossy_ior,
        )

        # Read timing
        self._gas_time_ms = self._renderer.last_gas_ms
        self._render_time_ms = self._renderer.last_render_ms

    def finish_offline_render(self) -> moderngl.Texture | None:
        """Denoise (if enabled) and tonemap the fully-accumulated offline frame.

        Must be called after all sub-steps are complete.

        Returns:
            moderngl.Texture (rgba8) with the final tonemapped image,
            or None on failure.
        """
        if self._renderer is None:
            return None

        try:
            self._display_tex = self._renderer.render_offline_finish(
                exposure=self.exposure,
            )
            return self._display_tex
        except Exception as e:
            self._failed = True
            self._fail_reason = str(e)
            print(f"PathTracer offline finish error: {e}")
            return None

    # --------------------------------------------------------------- scheduling

    def force_rebuild(self):
        """Force a full GAS rebuild on the next frame.

        Call after sim reset or any event that moves all entities at once.
        """
        if self._renderer is not None:
            self._renderer._gas_handle = None
            self._renderer._frame_counter = 0

    # ---------------------------------------------------------------- properties

    @property
    def display_texture(self) -> moderngl.Texture | None:
        """The rgba8 rendered texture for display, or None if no render yet."""
        return self._display_tex

    @property
    def gas_time_ms(self) -> float:
        """Time in ms for the most recent GAS build/refit."""
        return self._gas_time_ms

    @property
    def render_time_ms(self) -> float:
        """Time in ms for the most recent render (trace + denoise + tonemap)."""
        return self._render_time_ms

    @property
    def failed(self) -> bool:
        """True if the path tracer encountered a fatal error and auto-disabled."""
        return self._failed

    @property
    def fail_reason(self) -> str:
        """Human-readable reason for the failure, or empty string."""
        return self._fail_reason

    # ---------------------------------------------------------------- lifecycle

    def cleanup(self):
        """Release all OptiX/CUDA resources."""
        if self._renderer is not None:
            try:
                self._renderer.cleanup()
            except Exception:
                pass
            self._renderer = None
        self._display_tex = None
        self._entity_buffer_glo = 0
        self._entity_count = 0

    # -------------------------------------------------------------- availability

    @staticmethod
    def is_available() -> bool:
        """Check if OptiX/CUDA/RTX hardware is available."""
        return PathTracerRenderer.is_available()
