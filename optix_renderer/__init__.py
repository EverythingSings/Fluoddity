"""OptiX sphere renderer for Fluoddity.

Provides hardware-accelerated raytraced sphere rendering via NVIDIA OptiX,
using RT cores for BVH traversal and custom intersection programs for
analytic sphere tests.

Usage:
    from optix_renderer import OptiXSphereRenderer

    if OptiXSphereRenderer.is_available():
        renderer = OptiXSphereRenderer(ctx, entity_buffer, entity_count)
        renderer.build_accel()
        tex = renderer.render_from_camera(
            width, height, cam_pos, cam_dir, cam_up, fov
        )
"""

from .renderer import OptiXSphereRenderer

__all__ = ["OptiXSphereRenderer"]
