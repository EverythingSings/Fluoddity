"""Step 5 visual verification: OptiX AI Denoiser with guide buffers.

Renders scenes with and without the denoiser to verify:
- 1 spp noisy baseline
- 1 spp denoised (dramatic cleanup)
- 4 spp denoised (better input quality)
- 64 spp denoised (convergence quality)
- Albedo and normal guide buffer dumps

Usage:
    cd Fluoddity
    Scratch.venv\\Scripts\\python.exe -m optix_pathtracer.test_step5
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


def save_guide_buffers(renderer):
    """Save albedo and normal guide buffers as diagnostic PNGs."""
    albedo, normal = renderer.get_guide_buffers()
    if albedo is None:
        print("  Guide buffers not available (render with denoise_enabled first)")
        return

    # Albedo: already [0,1] range, just clamp and convert
    albedo_rgb = np.clip(albedo[:, :, :3], 0.0, 1.0)
    albedo_img = Image.fromarray((albedo_rgb * 255).astype(np.uint8))
    albedo_img.save("step5_guide_albedo.png")
    print("  -> step5_guide_albedo.png")

    # Normal: remap from [-1,1] to [0,1] for visualization
    normal_rgb = np.clip(normal[:, :, :3] * 0.5 + 0.5, 0.0, 1.0)
    normal_img = Image.fromarray((normal_rgb * 255).astype(np.uint8))
    normal_img.save("step5_guide_normal.png")
    print("  -> step5_guide_normal.png")


def main():
    print("Step 5 Visual Verification: OptiX AI Denoiser")
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
    width, height = 800, 600
    aspect = width / height
    vlen = np.tan(0.5 * np.radians(fov_deg))
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
        global_material=0,
        sun_sampling=True,
    )

    # 1. Noisy 1 spp (no denoiser) -- baseline
    print(f"\n[1/6] Noisy 1 spp (no denoiser)...")
    img = render_to_image(renderer, width, height, 1,
                          denoise_enabled=False, **common_kwargs)
    img.save("step5_noisy_1spp.png")
    print("  -> step5_noisy_1spp.png")

    # 2. Denoised 1 spp -- dramatic AI cleanup
    print(f"\n[2/6] Denoised 1 spp...")
    img = render_to_image(renderer, width, height, 1,
                          denoise_enabled=True, **common_kwargs)
    img.save("step5_denoised_1spp.png")
    print("  -> step5_denoised_1spp.png")

    # 3. Guide buffer diagnostic (from the last denoised render)
    print(f"\n[3/6] Guide buffer dumps...")
    save_guide_buffers(renderer)

    # 4. Denoised 4 spp -- better input quality
    print(f"\n[4/6] Denoised 4 spp...")
    img = render_to_image(renderer, width, height, 4,
                          denoise_enabled=True, **common_kwargs)
    img.save("step5_denoised_4spp.png")
    print("  -> step5_denoised_4spp.png")

    # 5. Denoised 64 spp -- convergence quality
    print(f"\n[5/6] Denoised 64 spp...")
    img = render_to_image(renderer, width, height, 64,
                          denoise_enabled=True, **common_kwargs)
    img.save("step5_denoised_64spp.png")
    print("  -> step5_denoised_64spp.png")

    # 6. Noisy 64 spp reference (no denoiser) -- for comparison
    print(f"\n[6/6] Noisy 64 spp (no denoiser, reference)...")
    img = render_to_image(renderer, width, height, 64,
                          denoise_enabled=False, **common_kwargs)
    img.save("step5_noisy_64spp.png")
    print("  -> step5_noisy_64spp.png")

    renderer.cleanup()
    print(f"\nDone. 6 PNG files + 2 guide buffer PNGs saved to project root.")


if __name__ == "__main__":
    main()
