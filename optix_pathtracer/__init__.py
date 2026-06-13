"""OptiX path tracer for Fluoddity.

Provides hardware-accelerated path-traced sphere rendering via NVIDIA OptiX,
with HDR accumulation and progressive sample refinement.

Usage:
    from optix_pathtracer import PathTracerRenderer

    if PathTracerRenderer.is_available():
        renderer = PathTracerRenderer(ctx, entity_buffer, entity_count)
        renderer.build_accel()
        tex = renderer.render_from_camera(
            width, height, cam_pos, cam_dir, cam_up, fov
        )
"""

from .renderer import PathTracerRenderer

__all__ = ["PathTracerRenderer"]
