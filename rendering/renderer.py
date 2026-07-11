"""The `Renderer` protocol, the `RenderCamera` value object, and `VideoStrategy`.

Step 7 of the modularity refactor unifies Fluoddity's three 3D backends
(OptiX path tracer, volumetric tracer, GL-points) behind one structural
protocol so the orchestrator can drive any of them uniformly and the
`RendererHost` can own their lifecycle.

The protocol is a `typing.Protocol` (structural / duck-typed) to match the
codebase style — renderers conform by shape, not by inheritance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


# ---------------------------------------------------------------------------
#  RenderCamera — one value object replacing the divergent camera arg lists
# ---------------------------------------------------------------------------
@dataclass
class RenderCamera:
    """A snapshot of the 3D camera passed to a renderer for one frame.

    Backends consume this in different shapes: the OptiX path tracer reads
    ``pos``/``dir``/``up``/``fov`` directly; the volumetric tracer wants a
    precomputed ``view_proj`` plus a ``(right, up)`` basis for DOF; GL-points
    computes ``view_proj`` internally. This object carries the raw camera
    state and offers helpers so each renderer can take what it needs.

    The matrix math mirrors ``Camera.compute_fps_view_proj`` /
    ``Camera.compute_fps_camera_basis`` (kept identical to preserve behavior).
    """
    pos: np.ndarray
    dir: np.ndarray
    up: np.ndarray
    fov: float = 50.0
    aperture: float = 0.0
    focal_plane_depth: float = 5.0

    @classmethod
    def from_controller_cam(cls, cam, *, aperture: float = 0.0,
                            focal_plane_depth: float = 5.0,
                            fov: float | None = None) -> "RenderCamera":
        """Build a RenderCamera from a `ControllerCam` (the 3D FPS camera)."""
        return cls(
            pos=np.array(cam.pos, dtype=np.float32),
            dir=np.array(cam.dir, dtype=np.float32),
            up=np.array(cam.up, dtype=np.float32),
            fov=float(cam.fov if fov is None else fov),
            aperture=aperture,
            focal_plane_depth=focal_plane_depth,
        )

    # -- matrix helpers (identical math to Camera.* so results match) --------
    @staticmethod
    def _look_at(eye, target, up):
        f = target - eye
        f = f / np.linalg.norm(f)
        s = np.cross(f, up)
        s = s / np.linalg.norm(s)
        u = np.cross(s, f)
        m = np.eye(4, dtype=np.float32)
        m[0, 0:3] = s
        m[1, 0:3] = u
        m[2, 0:3] = -f
        m[0, 3] = -np.dot(s, eye)
        m[1, 3] = -np.dot(u, eye)
        m[2, 3] = np.dot(f, eye)
        return m

    @staticmethod
    def _perspective(fov_y, aspect, near, far):
        f = 1.0 / math.tan(fov_y / 2.0)
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = f / max(.0001, aspect)
        m[1, 1] = f
        m[2, 2] = (far + near) / (near - far)
        m[2, 3] = (2.0 * far * near) / (near - far)
        m[3, 2] = -1.0
        return m

    def view_proj(self, aspect: float) -> np.ndarray:
        """Combined view*projection matrix (proj @ view) for this camera."""
        eye = np.array(self.pos, dtype=np.float32)
        target = eye + np.array(self.dir, dtype=np.float32)
        view = self._look_at(eye, target, np.array(self.up, dtype=np.float32))
        proj = self._perspective(math.radians(self.fov), aspect, 0.01, 100.0)
        return proj @ view

    def basis(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (right, true_up) unit vectors — used for DOF lens offset."""
        f = np.array(self.dir, dtype=np.float32)
        f = f / np.linalg.norm(f)
        u = np.array(self.up, dtype=np.float32)
        right = np.cross(f, u)
        right = right / np.linalg.norm(right)
        true_up = np.cross(right, f)
        return right, true_up


# ---------------------------------------------------------------------------
#  VideoStrategy — a renderer's offline/motion-blur recording driver
# ---------------------------------------------------------------------------
class VideoStrategy(Protocol):
    """Per-renderer offline video driver.

    Each renderer that supports offline recording supplies one of these. The
    orchestrator calls ``run_frame`` once per app-frame; it advances the
    renderer's progressive/offline accumulation (running interleaved physics
    steps as needed) and returns a finished, tonemapped texture when an output
    video frame is complete, or ``None`` while still accumulating.

    This replaces the two renderer-specific paths that lived in
    ``simulation_runner`` (``run_tracer_video_frame`` / ``run_optix_pt_video_frame``).
    """

    def init_frame_state(self) -> None:
        """Reset per-recording frame state (called once when recording starts)."""
        ...

    def run_frame(self, ui_state):
        """Advance one app-frame; return the finished texture or None."""
        ...


# ---------------------------------------------------------------------------
#  Renderer — the structural protocol all backends conform to
# ---------------------------------------------------------------------------
@runtime_checkable
class Renderer(Protocol):
    """Structural contract for a 3D particle-cloud renderer.

    Conformance is by shape (duck typing) — a class satisfies this without
    inheriting from it. The `RendererHost` owns exactly one active renderer
    and always ``cleanup()``s the previous one when swapping.
    """

    # -- identity / availability --------------------------------------------
    @staticmethod
    def is_available() -> bool:
        """Whether this backend can run on the current machine."""
        ...

    def cleanup(self) -> None:
        """Release all owned GPU resources. Always present (fixes the leak)."""
        ...

    # -- realtime render: produce ONE finished frame for display ------------
    @property
    def display_texture(self):
        """The most recent finished texture for display, or None."""
        ...

    # -- accumulation / acceleration structure control ----------------------
    def reset_accumulation(self) -> None:
        """Reset any progressive accumulation (e.g. on camera move)."""
        ...

    def force_rebuild(self) -> None:
        """Force a full acceleration-structure rebuild next frame.

        No-op for backends without a GAS (GL-points, volumetric).
        """
        ...

    # -- telemetry (UI display); return 0 when not applicable ---------------
    @property
    def gas_time_ms(self) -> float: ...

    @property
    def render_time_ms(self) -> float: ...

    @property
    def sample_count(self) -> int: ...
