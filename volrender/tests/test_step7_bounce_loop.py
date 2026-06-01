"""Tests for volrender Step 7 — isotropic scattering + full path loop.

Run from project root:
    python -m volrender.tests.test_step7_bounce_loop

Tests:
 (a) Furnace test: albedo=1, uniform white sky -> medium is invisible.
 (b) Absorbing albedo: albedo<1 -> interior uniformly darker than sky.
 (c) Colored albedo: R>G>B ordering in interior pixels.
 (d) Empty grid -> pure sky (no collisions through bounce loop).
 (e) No NaN, inf, or negative values in output.
 (f) max_bounces=1 produces darker image than unbounded.
 (g) RR unbiased: early vs late rr_start_depth converge to same mean.
 (h) Different sample_index values produce different images.
"""
from __future__ import annotations

import math
import sys

import numpy as np
import moderngl


def _fail(msg: str):
    print(f"  FAIL  {msg}")
    return False


def _ok(msg: str):
    print(f"  OK    {msg}")
    return True


# ------------------------------------------------------------------
# CPU reference helpers (reused from Step 6 tests)
# ------------------------------------------------------------------

def cpu_look_at(eye, target, up):
    """Build a 4x4 view matrix (row-major storage, OpenGL convention)."""
    eye = np.array(eye, dtype=np.float64)
    target = np.array(target, dtype=np.float64)
    up = np.array(up, dtype=np.float64)
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float64)
    m[0, 0:3] = s
    m[1, 0:3] = u
    m[2, 0:3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def cpu_perspective(fov_y_rad, aspect, near, far):
    """Build a 4x4 perspective projection matrix."""
    f = 1.0 / math.tan(fov_y_rad / 2.0)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def cpu_view_proj(eye, target, up, fov_deg, aspect):
    """Build view_proj = proj @ view (matching main camera convention)."""
    view = cpu_look_at(eye, target, up)
    proj = cpu_perspective(math.radians(fov_deg), aspect, 0.01, 100.0)
    return (proj @ view).astype(np.float32)


def _readback_target(target: moderngl.Texture) -> np.ndarray:
    """Read back an rgba16f target as (H, W, 4) float32."""
    raw = target.read()
    data = np.frombuffer(raw, dtype=np.float16)
    return data.reshape(target.height, target.width, 4).astype(np.float32)


def _fill_constant_density(renderer, physical_density: float):
    """Write uniform physical density into the grid and rebuild majorant.

    Bypasses splat for exact control — writes raw_density = physical_density
    * voxel_volume uniformly, then rebuilds the majorant grid.
    """
    res = renderer.grid.params.resolution
    raw = physical_density * renderer.grid.voxel_volume
    data = np.full(res[0] * res[1] * res[2], raw, dtype=np.float32)
    renderer.grid.density.write(data.tobytes())
    renderer.majorant_builder.build(renderer.grid)


def _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                       render_params, num_samples):
    """Dispatch num_samples bounce-loop passes and return the CPU-averaged image."""
    w, h = target_tex.width, target_tex.height
    accum = np.zeros((h, w, 4), dtype=np.float64)
    for i in range(num_samples):
        renderer.render_bounce_test(vp, target_tex, medium, sky,
                                    render_params, sample_index=i)
        accum += _readback_target(target_tex).astype(np.float64)
    return (accum / num_samples).astype(np.float32)


# ------------------------------------------------------------------
# (a) Furnace test: albedo=1, uniform white sky -> medium invisible
# ------------------------------------------------------------------
def test_furnace_white_albedo(ctx: moderngl.Context) -> bool:
    print("\n--- (a) furnace test: albedo=1, white sky -> medium invisible ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (32, 32, 32)
    bmin, bmax = (-1, -1, -1), (1, 1, 1)
    params = GridParams(bounds_min=bmin, bounds_max=bmax,
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    # Moderate constant density so rays scatter several times
    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    # Camera far away, narrow FOV -> approximately parallel rays
    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    # Furnace: albedo=1, uniform white sky
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(1.0, 1.0, 1.0),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=2)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 128

    mean_img = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples)

    if np.any(np.isnan(mean_img)):
        return _fail("NaN in output")

    # Interior region (central 50%) — rays that definitely traverse the medium
    margin = width // 4
    interior = mean_img[margin:height-margin, margin:width-margin, :3]
    interior_mean = np.mean(interior, axis=(0, 1))

    # In a perfect furnace test, interior should be exactly (1, 1, 1).
    # Allow tolerance for Monte Carlo noise.
    max_dev = np.max(np.abs(interior_mean - 1.0))
    if max_dev > 0.08:
        return _fail(f"furnace interior mean {interior_mean} deviates from "
                     f"(1,1,1) by {max_dev:.4f} (tolerance 0.08)")

    # Also check no pixel is wildly wrong (systematic bug)
    pixel_max_dev = np.max(np.abs(interior - 1.0))
    if pixel_max_dev > 0.6:
        return _fail(f"furnace pixel max deviation {pixel_max_dev:.4f} "
                     f"(tolerance 0.6 — suggests systematic bug)")

    return _ok(f"furnace interior mean {interior_mean}, "
               f"max_dev={max_dev:.4f}, pixel_max_dev={pixel_max_dev:.4f}")


# ------------------------------------------------------------------
# (b) Absorbing albedo: interior darker than sky
# ------------------------------------------------------------------
def test_absorbing_albedo(ctx: moderngl.Context) -> bool:
    print("\n--- (b) absorbing albedo: interior darker than sky ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    # albedo < 1: absorbing medium
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.5, 0.5, 0.5),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=2)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 64

    mean_img = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples)

    if np.any(np.isnan(mean_img)):
        return _fail("NaN in output")

    margin = width // 4
    interior = mean_img[margin:height-margin, margin:width-margin, :3]
    interior_mean = np.mean(interior)

    # Corner pixels (miss the box) should be sky = (1, 1, 1)
    corner_mean = np.mean(mean_img[0, 0, :3])

    if interior_mean >= corner_mean - 0.02:
        return _fail(f"interior ({interior_mean:.4f}) not darker than "
                     f"corner ({corner_mean:.4f})")

    if interior_mean >= 1.0 - 0.02:
        return _fail(f"interior ({interior_mean:.4f}) not visibly darkened")

    return _ok(f"interior_mean={interior_mean:.4f}, corner_mean={corner_mean:.4f}")


# ------------------------------------------------------------------
# (c) Colored albedo: R > G > B ordering
# ------------------------------------------------------------------
def test_colored_albedo(ctx: moderngl.Context) -> bool:
    print("\n--- (c) colored albedo: R > G > B in interior ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    # Colored albedo: R scatters most, B least
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.9, 0.5, 0.2),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=2)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 64

    mean_img = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples)

    if np.any(np.isnan(mean_img)):
        return _fail("NaN in output")

    margin = width // 4
    interior = mean_img[margin:height-margin, margin:width-margin, :]
    mean_r = np.mean(interior[:, :, 0])
    mean_g = np.mean(interior[:, :, 1])
    mean_b = np.mean(interior[:, :, 2])

    if not (mean_r > mean_g > mean_b):
        return _fail(f"expected R > G > B but got R={mean_r:.4f}, "
                     f"G={mean_g:.4f}, B={mean_b:.4f}")

    return _ok(f"R={mean_r:.4f} > G={mean_g:.4f} > B={mean_b:.4f}")


# ------------------------------------------------------------------
# (d) Empty grid -> pure sky
# ------------------------------------------------------------------
def test_empty_grid_pure_sky(ctx: moderngl.Context) -> bool:
    print("\n--- (d) empty grid -> pure sky ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (8, 8, 8)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)
    # No splat — grid is all zeros

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.8, 0.8, 0.8),
                          density_scale=5.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)
    render = RenderParams(max_bounces=0, rr_start_depth=4)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                sample_index=0)

    img = _readback_target(target_tex)
    max_diff = np.max(np.abs(img[:, :, :3] - sky_rgb))

    if max_diff > 0.01:
        return _fail(f"not pure sky: max diff from sky = {max_diff:.6f}")

    return _ok(f"all pixels are sky (max diff = {max_diff:.6f})")


# ------------------------------------------------------------------
# (e) No NaN / inf / negative values
# ------------------------------------------------------------------
def test_no_nans(ctx: moderngl.Context) -> bool:
    print("\n--- (e) no NaN/inf/negative in output ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Use a non-trivial cloud
    rng = np.random.default_rng(123)
    positions = rng.normal(0.0, 0.3, size=(1000, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    n = len(positions)
    data = np.zeros((n, 8), dtype=np.float32)
    data[:, 0:3] = positions
    buf = ctx.buffer(data.tobytes())
    renderer.splat(buf, n)

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    # Colored extinction + non-trivial albedo to stress the loop
    medium = MediumParams(extinction_rgb=(3.0, 0.5, 1.5),
                          albedo_rgb=(0.7, 0.9, 0.3),
                          density_scale=10.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=3)

    target_tex = ctx.texture((width, height), 4, dtype='f2')

    # Check several samples
    for si in range(4):
        renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                    sample_index=si)
        img = _readback_target(target_tex)

        if np.any(np.isnan(img)):
            nan_count = np.sum(np.isnan(img))
            return _fail(f"sample {si}: {nan_count} NaN values")
        if np.any(np.isinf(img)):
            inf_count = np.sum(np.isinf(img))
            return _fail(f"sample {si}: {inf_count} inf values")
        if np.any(img[:, :, :3] < -1e-6):
            neg_min = float(np.min(img[:, :, :3]))
            return _fail(f"sample {si}: negative value min = {neg_min:.6f}")

    return _ok("no NaN, inf, or negative values across 4 samples")


# ------------------------------------------------------------------
# (f) max_bounces=1 darker than unbounded
# ------------------------------------------------------------------
def test_max_bounces_darkens(ctx: moderngl.Context) -> bool:
    print("\n--- (f) max_bounces=1 darker than unbounded ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.8, 0.8, 0.8),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    num_samples = 64
    target_tex = ctx.texture((width, height), 4, dtype='f2')
    margin = width // 4

    # max_bounces=1: paths terminate after one collision
    render_1 = RenderParams(max_bounces=1, rr_start_depth=100)
    mean_1 = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                render_1, num_samples)
    interior_1 = np.mean(mean_1[margin:height-margin, margin:width-margin, :3])

    # Unbounded: full multiple scattering
    render_unb = RenderParams(max_bounces=0, rr_start_depth=2)
    mean_unb = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render_unb, num_samples)
    interior_unb = np.mean(mean_unb[margin:height-margin, margin:width-margin, :3])

    if interior_1 >= interior_unb - 0.01:
        return _fail(f"max_bounces=1 ({interior_1:.4f}) not darker than "
                     f"unbounded ({interior_unb:.4f})")

    return _ok(f"max_bounces=1: {interior_1:.4f}, unbounded: {interior_unb:.4f}")


# ------------------------------------------------------------------
# (g) RR unbiased: early vs late rr_start_depth -> same mean
# ------------------------------------------------------------------
def test_rr_unbiased(ctx: moderngl.Context) -> bool:
    print("\n--- (g) RR unbiased: early vs late rr_start_depth ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.3
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.7, 0.7, 0.7),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    num_samples = 128
    target_tex = ctx.texture((width, height), 4, dtype='f2')
    margin = width // 4

    # Early RR (depth 1)
    render_early = RenderParams(max_bounces=0, rr_start_depth=1)
    mean_early = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                    render_early, num_samples)
    val_early = np.mean(mean_early[margin:height-margin, margin:width-margin, :3])

    # Late RR (depth 10)
    render_late = RenderParams(max_bounces=0, rr_start_depth=10)
    mean_late = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                   render_late, num_samples)
    val_late = np.mean(mean_late[margin:height-margin, margin:width-margin, :3])

    diff = abs(val_early - val_late)
    # Both should converge to the same value (RR is unbiased)
    if diff > 0.08:
        return _fail(f"RR early ({val_early:.4f}) vs late ({val_late:.4f}) "
                     f"differ by {diff:.4f} (tolerance 0.08)")

    return _ok(f"RR early={val_early:.4f}, late={val_late:.4f}, diff={diff:.4f}")


# ------------------------------------------------------------------
# (h) Different sample_index -> different images
# ------------------------------------------------------------------
def test_sample_index_decorrelation(ctx: moderngl.Context) -> bool:
    print("\n--- (h) different sample_index -> different images ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.8, 0.8, 0.8),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=4)

    target_tex = ctx.texture((width, height), 4, dtype='f2')

    # Sample 0
    renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                sample_index=0)
    img0 = _readback_target(target_tex).copy()

    # Sample 1
    renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                sample_index=1)
    img1 = _readback_target(target_tex).copy()

    # They should NOT be identical (different RNG streams)
    max_diff = np.max(np.abs(img0 - img1))
    if max_diff < 1e-6:
        return _fail("sample_index 0 and 1 produced identical images")

    return _ok(f"images differ (max pixel diff = {max_diff:.4f})")


# ------------------------------------------------------------------
# runner
# ------------------------------------------------------------------
def main():
    try:
        ctx = moderngl.create_standalone_context(require=430)
    except Exception as e:
        print(f"FAIL: could not create GL 4.3 standalone context: {e}")
        sys.exit(1)

    tests = [
        test_furnace_white_albedo,
        test_absorbing_albedo,
        test_colored_albedo,
        test_empty_grid_pure_sky,
        test_no_nans,
        test_max_bounces_darkens,
        test_rr_unbiased,
        test_sample_index_decorrelation,
    ]
    results = [(t.__name__, t(ctx)) for t in tests]
    passed = sum(1 for _, r in results if r)
    total = len(results)

    print(f"\n{'='*40}")
    print(f"  {passed}/{total} tests passed")
    for name, r in results:
        print(f"  {'PASS' if r else 'FAIL'}  {name}")
    print(f"{'='*40}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
