"""Step 4 visual verification: Sun NEE + shadow rays.

Renders scenes with sun on vs off to verify directional lighting,
shadow rays, and the enhanced sky with sun glow.

Usage:
    cd Fluoddity
    Scratch.venv\\Scripts\\python.exe -m optix_pathtracer.test_step4
"""

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
    print("Step 4 Visual Verification: Sun NEE + Shadow Rays")
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

    # Scale U, V by FOV
    fov_deg = 45.0
    vlen = np.tan(0.5 * np.radians(fov_deg))
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
        sun_direction=(0.577, 0.577, 0.577),
        sun_color=(1.0, 0.95, 0.85),
        sun_intensity=3.0,
    )

    spp = 128

    # 1. Sun ON (Lambert) -- directional shadows visible
    print(f"\n[1/4] Sun ON + Lambert, {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=0, sun_sampling=True,
                          **common_kwargs)
    img.save("step4_sun_on_lambert.png")
    print("  -> step4_sun_on_lambert.png")

    # 2. Sun OFF (Lambert) -- sky-only illumination, no directional shadows
    print(f"\n[2/4] Sun OFF + Lambert, {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=0, sun_sampling=False,
                          **common_kwargs)
    img.save("step4_sun_off_lambert.png")
    print("  -> step4_sun_off_lambert.png")

    # 3. Sun ON (Glossy) -- specular highlights from sun
    print(f"\n[3/4] Sun ON + Glossy, {spp} spp...")
    img = render_to_image(renderer, width, height, spp,
                          global_material=1, glossy_ior=1.5,
                          sun_sampling=True, **common_kwargs)
    img.save("step4_sun_on_glossy.png")
    print("  -> step4_sun_on_glossy.png")

    # 4. Sky glow test -- camera looking toward the sun direction
    print(f"\n[4/4] Sky glow test (camera toward sun), {spp} spp...")
    sun_dir = np.array([0.577, 0.577, 0.577], dtype=np.float32)
    eye2 = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    W2 = sun_dir / np.linalg.norm(sun_dir)
    U2 = np.cross(W2, up)
    U2 = U2 / max(np.linalg.norm(U2), 1e-8)
    V2 = np.cross(U2, W2)
    V2 = V2 / max(np.linalg.norm(V2), 1e-8)
    U2_scaled = U2 * vlen * aspect
    V2_scaled = V2 * vlen
    img = render_to_image(renderer, width, height, spp,
                          eye=eye2, U=U2_scaled, V=V2_scaled, W=W2,
                          global_material=0, sun_sampling=True,
                          exposure=1.5,
                          sky_color_top=(0.45, 0.62, 0.85),
                          sky_color_bottom=(0.08, 0.08, 0.10),
                          max_bounces=8, rr_start_depth=3,
                          firefly_clamp=True, firefly_clamp_max=50.0,
                          sun_direction=(0.577, 0.577, 0.577),
                          sun_color=(1.0, 0.95, 0.85),
                          sun_intensity=3.0)
    img.save("step4_sky_glow.png")
    print("  -> step4_sky_glow.png")

    renderer.cleanup()
    print(f"\nDone. 4 PNG files saved to project root.")


if __name__ == "__main__":
    main()
