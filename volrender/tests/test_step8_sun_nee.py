"""Tests for volrender Step 8 -- ratio-tracked sun NEE.

Run from project root:
    python -m volrender.tests.test_step8_sun_nee

Tests:
 (a) Sun adds light: sun-on interior brighter than sun-off.
 (b) Sun behind medium: thick slab between sun and camera -> mostly occluded.
 (c) Colored shadow: colored extinction + white sun -> colored transmittance.
 (d) Furnace still holds: albedo=1, sun_intensity=0, white sky -> (1,1,1).
 (e) Empty grid + sun: no collisions -> pure sky (sun is NEE-only, not visible disk).
 (f) No NaN / inf / negative with sun enabled.
 (g) Sun intensity scaling: 2x intensity -> approximately 2x sun contribution.
 (h) Sun direction matters: top-lit vs side-lit produce different images.
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
# CPU reference helpers (same as Step 7 tests)
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

    Bypasses splat for exact control -- writes raw_density = physical_density
    * voxel_volume uniformly, then rebuilds the majorant grid.
    """
    res = renderer.grid.params.resolution
    raw = physical_density * renderer.grid.voxel_volume
    data = np.full(res[0] * res[1] * res[2], raw, dtype=np.float32)
    renderer.grid.density.write(data.tobytes())
    renderer.majorant_builder.build(renderer.grid)


def _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                       render_params, num_samples, sun=None):
    """Dispatch num_samples bounce-loop passes and return the CPU-averaged image."""
    w, h = target_tex.width, target_tex.height
    accum = np.zeros((h, w, 4), dtype=np.float64)
    for i in range(num_samples):
        renderer.render_bounce_test(vp, target_tex, medium, sky,
                                    render_params, sample_index=i,
                                    sun=sun)
        accum += _readback_target(target_tex).astype(np.float64)
    return (accum / num_samples).astype(np.float32)


# ------------------------------------------------------------------
# (a) Sun adds light: sun-on brighter than sun-off
# ------------------------------------------------------------------
def test_sun_adds_light(ctx: moderngl.Context) -> bool:
    print("\n--- (a) sun-on interior brighter than sun-off ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

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
                          albedo_rgb=(0.8, 0.8, 0.8),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(0.0, 0.0, 0.0), intensity=0.0)  # no sky
    render = RenderParams(max_bounces=8, rr_start_depth=4)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=3.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 64
    margin = width // 4

    # Sun ON
    mean_on = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                 render, num_samples, sun=sun)
    interior_on = np.mean(mean_on[margin:height-margin, margin:width-margin, :3])

    # Sun OFF (sun=None)
    mean_off = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples, sun=None)
    interior_off = np.mean(mean_off[margin:height-margin, margin:width-margin, :3])

    # With black sky and no sun, interior should be ~0.
    # With sun on, interior should be noticeably brighter.
    if interior_on <= interior_off + 0.01:
        return _fail(f"sun-on ({interior_on:.4f}) not brighter than "
                     f"sun-off ({interior_off:.4f})")

    return _ok(f"sun-on={interior_on:.4f}, sun-off={interior_off:.4f}")


# ------------------------------------------------------------------
# (b) Sun behind thick medium: mostly occluded
# ------------------------------------------------------------------
def test_sun_occlusion(ctx: moderngl.Context) -> bool:
    print("\n--- (b) thick slab occludes sun ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    # Single bounce isolates one NEE evaluation per path, so the only
    # variable between thin/thick is the shadow transmittance.
    # With multiple bounces a thick medium can actually appear brighter
    # because more scattering events each add NEE.
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.9, 0.9, 0.9),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(0.0, 0.0, 0.0), intensity=0.0)
    render = RenderParams(max_bounces=1, rr_start_depth=100)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=3.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 64
    margin = width // 4

    # Thin medium -> high transmittance to sun
    _fill_constant_density(renderer, 0.1)
    mean_thin = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                   render, num_samples, sun=sun)
    interior_thin = np.mean(mean_thin[margin:height-margin, margin:width-margin, :3])

    # Thick medium -> low transmittance to sun
    _fill_constant_density(renderer, 3.0)
    mean_thick = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                    render, num_samples, sun=sun)
    interior_thick = np.mean(mean_thick[margin:height-margin, margin:width-margin, :3])

    # With single bounce, thin medium should be brighter because
    # sun transmittance is higher at the single scatter vertex.
    if interior_thin <= interior_thick:
        return _fail(f"thin ({interior_thin:.4f}) not brighter than "
                     f"thick ({interior_thick:.4f})")

    return _ok(f"thin={interior_thin:.4f}, thick={interior_thick:.4f}")


# ------------------------------------------------------------------
# (c) Colored shadow: colored extinction + white sun
# ------------------------------------------------------------------
def test_colored_shadow(ctx: moderngl.Context) -> bool:
    print("\n--- (c) colored extinction -> colored shadows ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

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

    # Test that colored extinction produces channel-asymmetric output,
    # confirming ratio tracking carries RGB independently through shadows.
    # We compare against a white-extinction baseline (same scalar strength).
    # The colored case should produce a measurably different channel ratio
    # than the white case (where R == G == B by symmetry).
    sky = SkyParams(color_rgb=(0.0, 0.0, 0.0), intensity=0.0)
    render = RenderParams(max_bounces=1, rr_start_depth=100)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=5.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 128
    margin = width // 4

    # White extinction baseline: all channels equal
    medium_white = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                                albedo_rgb=(1.0, 1.0, 1.0),
                                density_scale=1.0)
    mean_white = _multi_sample_mean(renderer, vp, target_tex, medium_white, sky,
                                    render, num_samples, sun=sun)
    interior_white = mean_white[margin:height-margin, margin:width-margin, :]

    # Colored extinction: red high, green/blue low
    medium_color = MediumParams(extinction_rgb=(3.0, 0.5, 0.5),
                                albedo_rgb=(1.0, 1.0, 1.0),
                                density_scale=1.0)
    mean_color = _multi_sample_mean(renderer, vp, target_tex, medium_color, sky,
                                    render, num_samples, sun=sun)

    if np.any(np.isnan(mean_color)):
        return _fail("NaN in output")

    interior_color = mean_color[margin:height-margin, margin:width-margin, :]
    cr = np.mean(interior_color[:, :, 0])
    cg = np.mean(interior_color[:, :, 1])
    cb = np.mean(interior_color[:, :, 2])

    # With white extinction, G and B should be roughly equal
    wr = np.mean(interior_white[:, :, 0])
    wg = np.mean(interior_white[:, :, 1])

    # Green and blue channels should be equal (symmetric extinction)
    if abs(cg - cb) > 0.02:
        return _fail(f"G and B should be ~equal with symmetric extinction "
                     f"but got G={cg:.4f}, B={cb:.4f}")

    # The colored case should differ from white: R/G ratio should change
    white_ratio = wr / max(wg, 1e-8)  # ~1.0 for white
    color_ratio = cr / max(cg, 1e-8)  # != 1.0 for colored
    ratio_diff = abs(color_ratio - white_ratio)

    if ratio_diff < 0.1:
        return _fail(f"colored extinction didn't change R/G ratio: "
                     f"white={white_ratio:.4f}, colored={color_ratio:.4f}")

    return _ok(f"colored R={cr:.4f}, G={cg:.4f}, B={cb:.4f}, "
               f"R/G ratio: white={white_ratio:.4f} vs colored={color_ratio:.4f}")


# ------------------------------------------------------------------
# (d) Furnace still holds with sun_intensity=0
# ------------------------------------------------------------------
def test_furnace_with_sun_off(ctx: moderngl.Context) -> bool:
    print("\n--- (d) furnace: albedo=1, sun_intensity=0, white sky -> (1,1,1) ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

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
                          albedo_rgb=(1.0, 1.0, 1.0),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=2)
    # Sun present but zero intensity
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=0.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 128

    mean_img = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples, sun=sun)

    if np.any(np.isnan(mean_img)):
        return _fail("NaN in output")

    margin = width // 4
    interior = mean_img[margin:height-margin, margin:width-margin, :3]
    interior_mean = np.mean(interior, axis=(0, 1))

    max_dev = np.max(np.abs(interior_mean - 1.0))
    if max_dev > 0.08:
        return _fail(f"furnace interior mean {interior_mean} deviates from "
                     f"(1,1,1) by {max_dev:.4f} (tolerance 0.08)")

    return _ok(f"furnace interior mean {interior_mean}, max_dev={max_dev:.4f}")


# ------------------------------------------------------------------
# (e) Empty grid + sun: no collisions -> pure sky (no visible sun disk)
# ------------------------------------------------------------------
def test_empty_grid_sun_no_disk(ctx: moderngl.Context) -> bool:
    print("\n--- (e) empty grid + sun -> pure sky (no visible disk) ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (8, 8, 8)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)
    # No splat -> grid is all zeros

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
    # Strong sun -- should NOT appear in output (NEE-only, no visible disk)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=10.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                sample_index=0, sun=sun)

    img = _readback_target(target_tex)
    max_diff = np.max(np.abs(img[:, :, :3] - sky_rgb))

    # Sun is NEE-only (no visible disk): escaped rays should show only sky.
    if max_diff > 0.01:
        return _fail(f"not pure sky: max diff from sky = {max_diff:.6f}")

    return _ok(f"all pixels are sky (max diff = {max_diff:.6f})")


# ------------------------------------------------------------------
# (f) No NaN / inf / negative with sun enabled
# ------------------------------------------------------------------
def test_no_nans_with_sun(ctx: moderngl.Context) -> bool:
    print("\n--- (f) no NaN/inf/negative with sun enabled ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Non-trivial cloud
    rng = np.random.default_rng(456)
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

    medium = MediumParams(extinction_rgb=(3.0, 0.5, 1.5),
                          albedo_rgb=(0.7, 0.9, 0.3),
                          density_scale=10.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    render = RenderParams(max_bounces=0, rr_start_depth=3)
    sun = SunParams(direction=(0.577, 0.577, 0.577),
                    color_rgb=(1.0, 0.95, 0.9), intensity=5.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')

    for si in range(4):
        renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                    sample_index=si, sun=sun)
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
# (g) Sun intensity scaling: 2x intensity -> ~2x sun contribution
# ------------------------------------------------------------------
def test_sun_intensity_scaling(ctx: moderngl.Context) -> bool:
    print("\n--- (g) 2x sun intensity -> ~2x sun contribution ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

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
                          albedo_rgb=(0.8, 0.8, 0.8),
                          density_scale=1.0)
    sky = SkyParams(color_rgb=(0.0, 0.0, 0.0), intensity=0.0)  # no sky
    render = RenderParams(max_bounces=4, rr_start_depth=4)
    num_samples = 128
    target_tex = ctx.texture((width, height), 4, dtype='f2')
    margin = width // 4

    # Intensity 1
    sun1 = SunParams(direction=(0.0, 1.0, 0.0),
                     color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    mean1 = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                               render, num_samples, sun=sun1)
    val1 = np.mean(mean1[margin:height-margin, margin:width-margin, :3])

    # Intensity 2
    sun2 = SunParams(direction=(0.0, 1.0, 0.0),
                     color_rgb=(1.0, 1.0, 1.0), intensity=2.0)
    mean2 = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                               render, num_samples, sun=sun2)
    val2 = np.mean(mean2[margin:height-margin, margin:width-margin, :3])

    # With black sky, all light comes from sun.
    # The NEE contribution is linear in sun intensity, so val2/val1 ~ 2.
    # Multiple scattering also contributes (sun -> scatter -> sun), which
    # is also linear, so the ratio should hold.
    if val1 < 1e-6:
        return _fail(f"intensity=1 produced near-zero image ({val1:.6f})")

    ratio = val2 / val1
    if abs(ratio - 2.0) > 0.3:
        return _fail(f"ratio = {ratio:.4f}, expected ~2.0 "
                     f"(val1={val1:.4f}, val2={val2:.4f})")

    return _ok(f"ratio={ratio:.4f} (val1={val1:.4f}, val2={val2:.4f})")


# ------------------------------------------------------------------
# (h) Sun direction matters: top-lit vs side-lit
# ------------------------------------------------------------------
def test_sun_direction_matters(ctx: moderngl.Context) -> bool:
    print("\n--- (h) sun direction matters: different directions -> different images ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

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
    sky = SkyParams(color_rgb=(0.0, 0.0, 0.0), intensity=0.0)
    render = RenderParams(max_bounces=4, rr_start_depth=4)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    num_samples = 64

    # Top-lit
    sun_top = SunParams(direction=(0.0, 1.0, 0.0),
                        color_rgb=(1.0, 1.0, 1.0), intensity=3.0)
    mean_top = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                  render, num_samples, sun=sun_top)

    # Side-lit
    sun_side = SunParams(direction=(1.0, 0.0, 0.0),
                         color_rgb=(1.0, 1.0, 1.0), intensity=3.0)
    mean_side = _multi_sample_mean(renderer, vp, target_tex, medium, sky,
                                   render, num_samples, sun=sun_side)

    # For a uniform density cube, different sun directions should produce
    # different spatial distributions of light (even if overall mean is similar).
    diff = np.max(np.abs(mean_top[:, :, :3] - mean_side[:, :, :3]))
    if diff < 0.01:
        return _fail(f"top-lit and side-lit images are too similar "
                     f"(max pixel diff = {diff:.4f})")

    return _ok(f"images differ by direction (max pixel diff = {diff:.4f})")


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
        test_sun_adds_light,
        test_sun_occlusion,
        test_colored_shadow,
        test_furnace_with_sun_off,
        test_empty_grid_sun_no_disk,
        test_no_nans_with_sun,
        test_sun_intensity_scaling,
        test_sun_direction_matters,
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
