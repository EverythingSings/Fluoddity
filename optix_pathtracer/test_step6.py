"""Step 6 visual verification: Motion Blur + Realtime/Offline Split.

Tests:
1. Realtime mode: render_realtime() basic sanity
2. Offline static: 4 substeps x 8 spp with no entity motion
3. Offline motion blur: entities translate between substeps -> streaks
4. Offline motion blur + denoiser
5. Sharp reference at final positions for comparison

Usage:
    cd Fluoddity
    Scratch.venv\\Scripts\\python.exe -m optix_pathtracer.test_step6
"""

import time
import numpy as np
import moderngl
from PIL import Image

from optix_pathtracer import PathTracerRenderer


def create_test_entities(count=200, seed=42):
    """Generate random spheres with velocities for motion blur testing."""
    rng = np.random.default_rng(seed)
    entities = np.zeros((count, 8), dtype=np.float32)
    # Positions in [-2, 2]^3
    entities[:, 0:3] = rng.uniform(-2.0, 2.0, (count, 3))
    # Velocities: random directions for motion blur
    entities[:, 3:6] = rng.uniform(-2.0, 2.0, (count, 3))
    # Hue: spread across the color wheel
    entities[:, 6] = rng.uniform(0.0, 1.0, count)
    # Size: 0.1 to 0.35
    entities[:, 7] = rng.uniform(0.1, 0.35, count)
    return entities


def advance_entities(entities, dt=0.05):
    """Apply linear motion: pos += vel * dt."""
    entities[:, 0] += entities[:, 3] * dt
    entities[:, 1] += entities[:, 4] * dt
    entities[:, 2] += entities[:, 5] * dt


def make_camera(width, height):
    """Set up a camera looking at the origin from (0, 0.5, 5)."""
    eye = np.array([0.0, 0.5, 5.0], dtype=np.float32)
    look_at = np.array([0.0, 0.0, 0.0], dtype=np.float32)
    up = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    W = look_at - eye
    W = W / np.linalg.norm(W)
    U = np.cross(W, up)
    U = U / np.linalg.norm(U)
    V = np.cross(U, W)
    V = V / np.linalg.norm(V)

    fov_deg = 45.0
    aspect = width / height
    vlen = np.tan(0.5 * np.radians(fov_deg))
    U_scaled = U * vlen * aspect
    V_scaled = V * vlen

    return eye, U_scaled, V_scaled, W


def tex_to_image(tex, width, height):
    """Read a moderngl texture to a PIL Image."""
    raw = tex.read()
    img = Image.frombytes("RGBA", (width, height), raw)
    return img.convert("RGB")


def main():
    print("Step 6 Visual Verification: Motion Blur + Realtime/Offline Split")
    print("=" * 70)

    ctx = moderngl.create_standalone_context()
    print(f"ModernGL: {ctx.info['GL_RENDERER']}")

    width, height = 800, 600
    eye, U, V, W = make_camera(width, height)

    common_kwargs = dict(
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

    # ---------------------------------------------------------------
    # Test 1: Realtime mode sanity check
    # ---------------------------------------------------------------
    print(f"\n[1/5] Realtime mode sanity (5 frames)...")
    entities = create_test_entities(200)
    entity_buf = ctx.buffer(entities.tobytes())
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities))
    renderer.build_accel(radius_scale=1.0)
    print(f"  GAS build: {renderer.last_gas_ms:.2f} ms")

    t0 = time.perf_counter()
    for frame in range(5):
        # Simulate entity movement
        advance_entities(entities, dt=0.02)
        entity_buf.write(entities.tobytes())

        tex = renderer.render_realtime(
            width, height, eye, U, V, W,
            radius_scale=1.0,
            gas_rebuild_interval=30,
            denoise_enabled=False,
            **common_kwargs,
        )
    elapsed = time.perf_counter() - t0
    print(f"  5 frames in {elapsed:.2f}s")

    img = tex_to_image(tex, width, height)
    img.save("step6_realtime.png")
    print("  -> step6_realtime.png")

    renderer.cleanup()

    # ---------------------------------------------------------------
    # Test 2: Offline static (no motion, 4 substeps x 8 spp = 32 spp)
    # ---------------------------------------------------------------
    print(f"\n[2/5] Offline static (4 substeps x 8 spp, no motion)...")
    entities = create_test_entities(200)
    entity_buf = ctx.buffer(entities.tobytes())
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities))
    renderer.build_accel(radius_scale=1.0)

    total_substeps = 4
    spp_per_substep = 8

    t0 = time.perf_counter()
    renderer.render_offline_begin(
        width, height, total_substeps, spp_per_substep,
        denoise_enabled=False,
    )
    for substep in range(total_substeps):
        renderer.render_offline_substep(
            eye, U, V, W,
            radius_scale=1.0,
            **common_kwargs,
        )
    tex = renderer.render_offline_finish(exposure=1.5)
    elapsed = time.perf_counter() - t0
    total_spp = total_substeps * spp_per_substep
    print(f"  {total_spp} total spp in {elapsed:.2f}s")

    img = tex_to_image(tex, width, height)
    img.save("step6_offline_static.png")
    print("  -> step6_offline_static.png")

    renderer.cleanup()

    # ---------------------------------------------------------------
    # Test 3: Offline motion blur (entities translate between substeps)
    # ---------------------------------------------------------------
    print(f"\n[3/5] Offline motion blur (4 substeps x 8 spp, moving)...")
    entities = create_test_entities(200)
    entity_buf = ctx.buffer(entities.tobytes())
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities))
    renderer.build_accel(radius_scale=1.0)

    dt_per_substep = 0.04  # large enough to see streaks

    t0 = time.perf_counter()
    renderer.render_offline_begin(
        width, height, total_substeps, spp_per_substep,
        denoise_enabled=False,
    )
    for substep in range(total_substeps):
        if substep > 0:
            advance_entities(entities, dt=dt_per_substep)
            entity_buf.write(entities.tobytes())
        renderer.render_offline_substep(
            eye, U, V, W,
            radius_scale=1.0,
            **common_kwargs,
        )
    tex = renderer.render_offline_finish(exposure=1.5)
    elapsed = time.perf_counter() - t0
    print(f"  {total_spp} total spp in {elapsed:.2f}s")

    img = tex_to_image(tex, width, height)
    img.save("step6_motion_blur.png")
    print("  -> step6_motion_blur.png")

    # Save final entity positions for sharp reference
    entities_final = entities.copy()

    renderer.cleanup()

    # ---------------------------------------------------------------
    # Test 4: Motion blur + denoiser
    # ---------------------------------------------------------------
    print(f"\n[4/5] Offline motion blur + denoiser...")
    entities = create_test_entities(200)
    entity_buf = ctx.buffer(entities.tobytes())
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities))
    renderer.build_accel(radius_scale=1.0)

    t0 = time.perf_counter()
    renderer.render_offline_begin(
        width, height, total_substeps, spp_per_substep,
        denoise_enabled=True,
    )
    for substep in range(total_substeps):
        if substep > 0:
            advance_entities(entities, dt=dt_per_substep)
            entity_buf.write(entities.tobytes())
        renderer.render_offline_substep(
            eye, U, V, W,
            radius_scale=1.0,
            **common_kwargs,
        )
    tex = renderer.render_offline_finish(exposure=1.5)
    elapsed = time.perf_counter() - t0
    print(f"  {total_spp} total spp in {elapsed:.2f}s")

    img = tex_to_image(tex, width, height)
    img.save("step6_motion_blur_denoised.png")
    print("  -> step6_motion_blur_denoised.png")

    renderer.cleanup()

    # ---------------------------------------------------------------
    # Test 5: Sharp reference at final positions (no motion blur)
    # ---------------------------------------------------------------
    print(f"\n[5/5] Sharp reference (32 spp at final positions)...")
    entity_buf = ctx.buffer(entities_final.tobytes())
    renderer = PathTracerRenderer(ctx, entity_buf, len(entities_final))
    renderer.build_accel(radius_scale=1.0)

    renderer.reset_accumulation()
    t0 = time.perf_counter()
    for i in range(total_spp):
        tex = renderer.render(
            width, height, eye, U, V, W,
            radius_scale=1.0,
            denoise_enabled=False,
            **common_kwargs,
        )
    elapsed = time.perf_counter() - t0
    print(f"  {total_spp} spp in {elapsed:.2f}s")

    img = tex_to_image(tex, width, height)
    img.save("step6_sharp_reference.png")
    print("  -> step6_sharp_reference.png")

    renderer.cleanup()

    print(f"\nDone. 5 PNG files saved to project root.")
    print("Compare step6_motion_blur.png vs step6_sharp_reference.png")
    print("to see motion blur streaks vs sharp particles.")


if __name__ == "__main__":
    main()
