"""Step 3 visual verification: render path-traced spheres to PNG.

Renders three material modes (Lambert, Glossy, Mirror) and a DOF test,
saving PNG images to disk for visual inspection.

Usage:
    cd Fluoddity
    Scratch.venv/Scripts/python.exe -m optix_pathtracer.test_step3
"""

import sys
import time
import numpy as np
import moderngl
from PIL import Image

from optix_pathtracer import PathTracerRenderer


def create_test_entities(count=200, seed=42):
    """Generate random spheres in a bounding box."""
    rng = np.random.default_rng(seed)
    entities = np.zeros((count, 8), dtype=np.float32)
    # Positions in [-2, 2]^3
    entities[:, 0:3] = rng.uniform(-2.0, 2.0, (count, 3))
    # Velocities = 0 (columns 3-5 already zero)
    # Hue: spread across the color wheel
    entities[:, 6] = rng.uniform(0.0, 1.0, count)
    # Size: 0.1 to 0.35
    entities[:, 7] = rng.uniform(0.1, 0.35, count)
    return entities


def render_to_image(renderer, width, height, spp, **render_kwargs):
    """Accumulate spp samples and read back as PIL Image."""
    renderer.reset_accumulation()
    t0 = time.perf_counter()
    for i in range(spp):
        tex = renderer.render(width, height, **render_kwargs)
    elapsed = time.perf_counter() - t0
    print(f"  {spp} spp in {elapsed:.2f}s ({spp/elapsed:.1f} spp/s)")

    # Read texture data (RGBA, already Y-flipped by tonemap kernel)
    raw = tex.read()
    img = Image.frombytes("RGBA", (width, height), raw)
    return img.convert("RGB")


def main():
    print("Step 3 Visual Verification: Monte Carlo + Three Materials")
    print("=" * 60)

    # Create standalone ModernGL context (headless)
    ctx = moderngl.create_standalone_context()
    print(f"ModernGL: {ctx.info['GL_RENDERER']}")

    # Create entity buffer
    entities = create_test_entities(200)
    entity_buf = ctx.buffer(entities.tobytes())
    print(f"Entities: {len(entities)} spheres")

    # Create renderer
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities))
    renderer.build_accel(radius_scale=1.0)
    print(f"GAS build: {renderer.last_gas_ms:.2f} ms")

    # Camera setup: look at origin from (0, 0.5, 5)
    eye = np.array([0.0, 0.5, 5.0], dtype=np.float32)
    look_at = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    W = look_at - eye
    W = W / np.linalg.norm(W)
    U = np.cross(W, up)
    U = U / np.linalg.norm(U)
    V = np.cross(U, W)
    V = V / np.linalg.norm(V)

    # Normalized basis vectors (for DOF)
    cam_right = U.copy()
    cam_up_vec = V.copy()

    # Scale U, V by FOV
    fov_deg = 45.0
    fov_rad = np.radians(fov_deg)
    vlen = np.tan(0.5 * fov_rad)
    width, height = 800, 600
    aspect = width / height
    U_scaled = U * vlen * aspect
    V_scaled = V * vlen

    common_kwargs = dict(
        eye=eye, U=U_scaled, V=V_scaled, W=W,
        exposure=1.5,
        sky_color_top=(0.45, 0.62, 0.85),
        sky_color_bottom=(0.08, 0.08, 0.10),
        max_bounces=8,
        rr_start_depth=3,
        firefly_clamp=True,
        firefly_clamp_max=50.0,
    )

    spp = 128

    # 1. Lambert (MAT_DIFFUSE = 0)
    print(f"\n[1/4] Rendering Lambert (diffuse), {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=0, **common_kwargs)
    img.save("step3_lambert.png")
    print("  -> step3_lambert.png")

    # 2. Glossy (MAT_GLOSSY = 1)
    print(f"\n[2/4] Rendering Glossy (plastic), {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=1, glossy_ior=1.5,
                          **common_kwargs)
    img.save("step3_glossy.png")
    print("  -> step3_glossy.png")

    # 3. Mirror (MAT_MIRROR = 2)
    print(f"\n[3/4] Rendering Mirror, {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=2, **common_kwargs)
    img.save("step3_mirror.png")
    print("  -> step3_mirror.png")

    # 4. DOF test (Lambert + aperture)
    print(f"\n[4/4] Rendering DOF test (Lambert + aperture=0.15), {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=0,
                          aperture=0.15,
                          focal_plane_depth=5.0,
                          cam_right=cam_right,
                          cam_up=cam_up_vec,
                          **common_kwargs)
    img.save("step3_dof.png")
    print("  -> step3_dof.png")

    renderer.cleanup()
    print(f"\nDone. 4 PNG files saved to project root.")


if __name__ == "__main__":
    main()
