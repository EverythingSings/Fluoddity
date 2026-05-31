"""Camera helper — inverts the caller's view_proj and uploads to shaders.

Accepts the 4×4 view_proj (= proj @ view) from the main camera, inverts
it on the CPU, and uploads as ``u_inv_view_proj`` for primary ray generation
in ``pathtrace.comp``.
"""
from __future__ import annotations

import numpy as np


def _tryset_mat4(prog, name: str, mat: np.ndarray):
    """Upload a 4×4 float32 matrix as a mat4 uniform (column-major).

    Silently skips if the uniform is optimized out.
    """
    if name in prog:
        # moderngl expects column-major bytes for mat4.write()
        prog[name].write(mat.T.astype(np.float32).tobytes())


class Camera:
    """Caches the inverse view-projection matrix for GPU upload.

    Usage::

        cam = Camera()
        cam.set_view_proj(view_proj)   # numpy 4×4
        cam.upload(pathtrace_program)  # sets u_inv_view_proj uniform
    """

    def __init__(self):
        self._inv_view_proj = np.eye(4, dtype=np.float32)

    def set_view_proj(self, view_proj: np.ndarray):
        """Invert the 4×4 view_proj on CPU and cache the result.

        Inversion is done in float64 for numerical stability, then
        cast to float32 for GPU upload.
        """
        mat = np.array(view_proj, dtype=np.float64)
        self._inv_view_proj = np.linalg.inv(mat).astype(np.float32)

    @property
    def inv_view_proj(self) -> np.ndarray:
        """The cached inverse view-projection matrix (4×4, float32)."""
        return self._inv_view_proj

    def upload(self, prog):
        """Upload ``u_inv_view_proj`` to the given compute program."""
        _tryset_mat4(prog, 'u_inv_view_proj', self._inv_view_proj)
