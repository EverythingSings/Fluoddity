"""OptiX interface: bridges Fluoddity's entity buffer and camera to the OptiX sphere renderer.

Manages OptiXSphereRenderer lifecycle (lazy creation, cleanup), GAS rebuild/refit
scheduling, and entity buffer change detection.
"""
from __future__ import annotations

import moderngl
import numpy as np

from optix_renderer import OptiXSphereRenderer


class OptiXInterface:
    """Manages the OptiXSphereRenderer for the 3D camera view.

    Created lazily on first render request. All GPU resources are allocated
    through the shared ModernGL context.
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

        # --- Public attributes (wired to UI in Steps 3/4) ---
        self.gas_rebuild_interval: int = 30
        self.light_dir: tuple[float, float, float] = (0.577, 0.577, 0.577)
        self.ambient: float = 0.12
        self.radius_scale: float = 1.0
        self.shadows_enabled: bool = True

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

        Handles lazy init, entity buffer change detection, and GAS scheduling.

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
            moderngl.Texture (rgba8) or None if OptiX unavailable.
        """
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

        # 3. GAS scheduling
        if not self._gas_exists:
            # First frame or after buffer change: full build required
            self._renderer.build_accel()
            self._gas_exists = True
            self._frame_counter = 0
        elif self._frame_counter >= self.gas_rebuild_interval:
            # Periodic full rebuild for BVH quality
            self._renderer.build_accel()
            self._frame_counter = 0
        else:
            # Fast in-place refit
            self._renderer.refit_accel()

        self._frame_counter += 1

        # 4. Render (delegates camera basis conversion to renderer)
        self._display_tex = self._renderer.render_from_camera(
            width, height, cam_pos, cam_dir, cam_up, fov,
            light_dir=self.light_dir,
            ambient=self.ambient,
            radius_scale=self.radius_scale,
            shadows_enabled=self.shadows_enabled,
        )

        return self._display_tex

    # ---------------------------------------------------------------- properties

    @property
    def display_texture(self) -> moderngl.Texture | None:
        """The rgba8 rendered texture for display, or None if no render yet."""
        return self._display_tex

    # ---------------------------------------------------------------- lifecycle

    def cleanup(self):
        """Release all OptiX/CUDA resources."""
        if self._renderer is not None:
            self._renderer.cleanup()
            self._renderer = None
        self._display_tex = None
        self._gas_exists = False
        self._frame_counter = 0
        self._entity_buffer_glo = 0
        self._entity_count = 0

    # -------------------------------------------------------------- availability

    @staticmethod
    def is_available() -> bool:
        """Check if OptiX/CUDA/RTX hardware is available."""
        return OptiXSphereRenderer.is_available()
