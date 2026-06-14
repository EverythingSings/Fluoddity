"""OptiX interface: bridges Fluoddity's entity buffer and camera to the OptiX sphere renderer.

Manages OptiXSphereRenderer lifecycle (lazy creation, cleanup), GAS rebuild/refit
scheduling, entity buffer change detection, and per-frame error recovery.
"""
from __future__ import annotations

import moderngl
import numpy as np

from optix_renderer import OptiXSphereRenderer


class OptiXInterface:
    """Manages the OptiXSphereRenderer for the 3D camera view.

    Created lazily on first render request. All GPU resources are allocated
    through the shared ModernGL context. If an OptiX error occurs during
    rendering, the interface auto-disables and reports failure via the
    ``failed`` property.
    """

    def __init__(self, ctx: moderngl.Context):
        self.ctx = ctx
        self._renderer: OptiXSphereRenderer | None = None
        self._display_tex: moderngl.Texture | None = None

        # Entity buffer tracking (for change detection)
        self._entity_buffer_glo: int = 0
        self._entity_count: int = 0

        # GAS scheduling state
        self._frame_counter: int = 0
        self._gas_exists: bool = False

        # Error recovery state
        self._failed: bool = False
        self._fail_reason: str = ""

        # Timing (updated each frame from renderer)
        self._gas_time_ms: float = 0.0
        self._render_time_ms: float = 0.0

        # --- Public attributes (wired to UI via preferences) ---
        self.gas_rebuild_interval: int = 30
        self.light_dir: tuple[float, float, float] = (0.577, 0.577, 0.577)
        self.ambient: float = 0.12
        self.radius_scale: float = 1.0
        self.shadows_enabled: bool = True
        self.light_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
        self.light_intensity: float = 1.0
        self.sky_color_top: tuple[float, float, float] = (0.45, 0.62, 0.85)
        self.sky_color_bottom: tuple[float, float, float] = (0.08, 0.08, 0.10)
        self.ao_enabled: bool = False
        self.ao_num_rays: int = 2
        self.ao_radius: float = 0.5
        self.albedo_saturation: float = 0.8
        self.albedo_brightness: float = 1.0
        self.sphere_size_jitter: float = 0.0

        # AO frame counter for jitter (internal, incremented each frame)
        self._ao_frame_index: int = 0

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
        """Render one frame of OptiX raytraced spheres.

        Handles lazy init, entity buffer change detection, GAS scheduling,
        and per-frame error recovery. On failure, cleans up and returns None.

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
            print(f"OptiX render error (auto-disabling): {e}")
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
            self._renderer = OptiXSphereRenderer(
                self.ctx, entity_buffer, entity_count
            )
            self._entity_buffer_glo = int(entity_buffer.glo)
            self._entity_count = entity_count
            self._gas_exists = False
            self._frame_counter = 0

        # 2. Entity buffer change detection
        current_glo = int(entity_buffer.glo)
        if (current_glo != self._entity_buffer_glo
                or entity_count != self._entity_count):
            self._renderer.update_entity_buffer(entity_buffer, entity_count)
            self._entity_buffer_glo = current_glo
            self._entity_count = entity_count
            self._gas_exists = False
            self._frame_counter = 0
            self._ao_frame_index = 0

        # 3. GAS scheduling (radius_scale must match intersection shader)
        if not self._gas_exists:
            # First frame or after buffer change: full build required
            self._renderer.build_accel(self.radius_scale, self.sphere_size_jitter)
            self._gas_exists = True
            self._frame_counter = 0
        elif self._frame_counter >= self.gas_rebuild_interval:
            # Periodic full rebuild for BVH quality
            self._renderer.build_accel(self.radius_scale, self.sphere_size_jitter)
            self._frame_counter = 0
        else:
            # Fast in-place refit
            self._renderer.refit_accel(self.radius_scale, self.sphere_size_jitter)

        self._frame_counter += 1

        # 4. Render (delegates camera basis conversion to renderer)
        # Normalize light direction (UI drag_float3 can produce non-unit vectors)
        ld = np.array(self.light_dir, dtype=np.float64)
        length = max(np.linalg.norm(ld), 1e-8)
        light_dir_norm = tuple((ld / length).astype(np.float32))

        self._display_tex = self._renderer.render_from_camera(
            width, height, cam_pos, cam_dir, cam_up, fov,
            light_dir=light_dir_norm,
            ambient=self.ambient,
            radius_scale=self.radius_scale,
            shadows_enabled=self.shadows_enabled,
            light_color=self.light_color,
            light_intensity=self.light_intensity,
            sky_color_top=self.sky_color_top,
            sky_color_bottom=self.sky_color_bottom,
            ao_enabled=self.ao_enabled,
            ao_num_rays=self.ao_num_rays,
            ao_radius=self.ao_radius,
            ao_frame_index=self._ao_frame_index,
            albedo_saturation=self.albedo_saturation,
            albedo_brightness=self.albedo_brightness,
            sphere_size_jitter=self.sphere_size_jitter,
        )
        self._ao_frame_index += 1

        # 5. Read timing from renderer
        self._gas_time_ms = self._renderer.last_gas_ms
        self._render_time_ms = self._renderer.last_render_ms

        return self._display_tex

    # --------------------------------------------------------------- scheduling

    def force_rebuild(self):
        """Force a full GAS rebuild on the next frame.

        Call after sim reset or any event that moves all entities at once.
        Avoids the slow refit path on scrambled BVH data.
        """
        self._gas_exists = False

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
        """Time in ms for the most recent OptiX render launch."""
        return self._render_time_ms

    @property
    def failed(self) -> bool:
        """True if OptiX encountered a fatal error and auto-disabled."""
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
        self._gas_exists = False
        self._frame_counter = 0
        self._entity_buffer_glo = 0
        self._entity_count = 0
        self._ao_frame_index = 0

    # -------------------------------------------------------------- availability

    @staticmethod
    def is_available() -> bool:
        """Check if OptiX/CUDA/RTX hardware is available."""
        return OptiXSphereRenderer.is_available()
