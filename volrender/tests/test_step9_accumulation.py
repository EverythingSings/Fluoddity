"""Tests for volrender Step 9 -- progressive accumulation + public API.

Run from project root:
    python -m volrender.tests.test_step9_accumulation

Tests:
 (a) Convergence: 4x more samples -> roughly 4x less inter-run variance.
 (b) Reset clears: no ghosting between renders of different scenes.
 (c) No TDR crash: render_to_completion with default batch_spp completes.
 (d) read_frame: shape (H,W,4) float32, no NaN/inf/negative.
 (e) Edit without re-splat: changing medium/sun params produces different images.
 (f) Furnace via accumulation: albedo=1, white sky, no sun -> (1,1,1).
 (g) Accumulated mean matches CPU average of single-sample renders.
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
# CPU reference helpers (same as earlier steps)
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


# ------------------------------------------------------------------
# (a) Convergence: 4x more samples -> less inter-run variance
# ------------------------------------------------------------------
def test_convergence(ctx: moderngl.Context) -> bool:
    print("\n--- (a) convergence: 4x more samples -> ~4x less variance ---")
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
    sky = SkyParams(color_top=(0.5, 0.7, 1.0), color_bottom=(0.5, 0.7, 1.0), intensity=1.0)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=3.0)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    n_runs = 4
    spp_lo = 8
    spp_hi = 32  # 4x more

    # Collect independent renders at low spp
    images_lo = []
    for r in range(n_runs):
        render = RenderParams(num_samples=spp_lo, seed=r * 10000)
        renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
        images_lo.append(_readback_target(target_tex).astype(np.float64))

    # Collect independent renders at high spp
    images_hi = []
    for r in range(n_runs):
        render = RenderParams(num_samples=spp_hi, seed=r * 10000)
        renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
        images_hi.append(_readback_target(target_tex).astype(np.float64))

    # Compute per-pixel variance across runs, then average
    stack_lo = np.stack(images_lo, axis=0)
    stack_hi = np.stack(images_hi, axis=0)
    var_lo = np.mean(np.var(stack_lo[:, :, :, :3], axis=0))
    var_hi = np.mean(np.var(stack_hi[:, :, :, :3], axis=0))

    if var_lo < 1e-10:
        return _fail(f"low-spp variance is near zero ({var_lo:.2e})")

    ratio = var_lo / max(var_hi, 1e-20)
    # Expect ratio ~ 4 (since spp_hi = 4 * spp_lo).
    # Allow wide tolerance: ratio should be between 1.5 and 16.
    if ratio < 1.5:
        return _fail(f"variance ratio = {ratio:.2f} (expected ~4, too low)")

    return _ok(f"variance ratio lo/hi = {ratio:.2f} (expect ~4)")


# ------------------------------------------------------------------
# (b) Reset clears: no ghosting between renders
# ------------------------------------------------------------------
def test_reset_clears(ctx: moderngl.Context) -> bool:
    print("\n--- (b) reset clears: no ghosting between renders ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    # Render A: bright scene (dense medium, strong sun)
    _fill_constant_density(renderer, 0.5)
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.9, 0.9, 0.9), density_scale=1.0)
    sky = SkyParams(color_top=(1.0, 1.0, 1.0), color_bottom=(1.0, 1.0, 1.0), intensity=1.0)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=5.0)
    render = RenderParams(num_samples=16)
    renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
    img_a = _readback_target(target_tex)
    mean_a = np.mean(img_a[:, :, :3])

    # Render B: dark scene (empty grid, black sky, no sun)
    renderer.grid.clear()
    renderer.majorant_builder.build(renderer.grid)
    sky_dark = SkyParams(color_top=(0.0, 0.0, 0.0), color_bottom=(0.0, 0.0, 0.0), intensity=0.0)
    sun_off = SunParams(direction=(0.0, 1.0, 0.0),
                        color_rgb=(0.0, 0.0, 0.0), intensity=0.0)
    renderer.render_to_completion(vp, target_tex, medium, sun_off, sky_dark, render)
    img_b = _readback_target(target_tex)
    mean_b = np.mean(img_b[:, :, :3])

    # Scene B should be near-zero (no ghosting from scene A)
    if mean_b > 0.01:
        return _fail(f"dark scene mean = {mean_b:.4f} (expected ~0, "
                     f"ghosting from bright scene A mean = {mean_a:.4f})")

    return _ok(f"bright scene mean = {mean_a:.4f}, "
               f"dark scene mean = {mean_b:.6f} (no ghosting)")


# ------------------------------------------------------------------
# (c) No TDR crash with default batch_spp
# ------------------------------------------------------------------
def test_no_tdr_crash(ctx: moderngl.Context) -> bool:
    print("\n--- (c) render_to_completion with batch_spp=1 completes ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)
    _fill_constant_density(renderer, 0.3)

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    medium = MediumParams()
    sky = SkyParams()
    sun = SunParams(direction=(0.0, 1.0, 0.0))
    # COMMENT FLAG: batch_spp — dispatch granularity (TDR avoidance)
    render = RenderParams(num_samples=32, batch_spp=1)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    try:
        renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
    except Exception as e:
        return _fail(f"render_to_completion raised: {e}")

    img = _readback_target(target_tex)
    if np.any(np.isnan(img)):
        return _fail("NaN in output")

    return _ok("32 spp render completed without crash or NaN")


# ------------------------------------------------------------------
# (d) read_frame shape, dtype, no NaN/inf/negative
# ------------------------------------------------------------------
def test_read_frame(ctx: moderngl.Context) -> bool:
    print("\n--- (d) read_frame returns (H,W,4) float32, no NaN/inf/neg ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)
    _fill_constant_density(renderer, 0.3)

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 48, 32
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    medium = MediumParams()
    sky = SkyParams()
    sun = SunParams(direction=(0.0, 1.0, 0.0))
    render = RenderParams(num_samples=8)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
    frame = renderer.read_frame()

    # Shape
    if frame.shape != (height, width, 4):
        return _fail(f"shape = {frame.shape}, expected ({height}, {width}, 4)")

    # Dtype
    if frame.dtype != np.float32:
        return _fail(f"dtype = {frame.dtype}, expected float32")

    # NaN
    if np.any(np.isnan(frame)):
        return _fail(f"{np.sum(np.isnan(frame))} NaN values")

    # Inf
    if np.any(np.isinf(frame)):
        return _fail(f"{np.sum(np.isinf(frame))} inf values")

    # Negative (allow tiny floating-point undershoot)
    if np.any(frame[:, :, :3] < -1e-4):
        return _fail(f"negative values: min = {np.min(frame[:, :, :3]):.6f}")

    return _ok(f"shape={frame.shape}, dtype={frame.dtype}, "
               f"range=[{np.min(frame[:,:,:3]):.4f}, {np.max(frame[:,:,:3]):.4f}]")


# ------------------------------------------------------------------
# (e) Edit without re-splat: different params -> different images
# ------------------------------------------------------------------
def test_edit_without_resplat(ctx: moderngl.Context) -> bool:
    print("\n--- (e) edit medium/sun without re-splat -> different images ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)
    # Use higher density for a stronger signal
    _fill_constant_density(renderer, 0.5)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    sky = SkyParams(color_top=(0.0, 0.0, 0.0), color_bottom=(0.0, 0.0, 0.0), intensity=0.0)
    render = RenderParams(num_samples=64)
    margin = width // 4

    # Render with sun intensity 1
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.8, 0.8, 0.8), density_scale=1.0)
    sun1 = SunParams(direction=(0.0, 1.0, 0.0),
                     color_rgb=(1.0, 1.0, 1.0), intensity=1.0)
    renderer.render_to_completion(vp, target_tex, medium, sun1, sky, render)
    img1 = _readback_target(target_tex)
    val1 = np.mean(img1[margin:height-margin, margin:width-margin, :3])

    # Render with sun intensity 5 — NO re-splat
    sun5 = SunParams(direction=(0.0, 1.0, 0.0),
                     color_rgb=(1.0, 1.0, 1.0), intensity=5.0)
    renderer.render_to_completion(vp, target_tex, medium, sun5, sky, render)
    img5 = _readback_target(target_tex)
    val5 = np.mean(img5[margin:height-margin, margin:width-margin, :3])

    if abs(val1 - val5) < 0.01:
        return _fail(f"images too similar: intensity=1 mean={val1:.4f}, "
                     f"intensity=5 mean={val5:.4f}")

    # Also test medium change: compare per-channel means to detect
    # colored extinction shifting the channel balance (more robust than
    # comparing scalar means which can be close even when channels shift).
    medium2 = MediumParams(extinction_rgb=(3.0, 0.5, 0.5),
                           albedo_rgb=(0.8, 0.8, 0.8), density_scale=1.0)
    renderer.render_to_completion(vp, target_tex, medium2, sun1, sky, render)
    img_ext = _readback_target(target_tex)
    interior1 = img1[margin:height-margin, margin:width-margin, :3]
    interior_ext = img_ext[margin:height-margin, margin:width-margin, :3]

    # With white extinction, R==G==B.  With (3,0.5,0.5), R channel should
    # differ from G/B.  Check the max per-channel difference.
    ch_means_orig = np.mean(interior1, axis=(0, 1))
    ch_means_ext = np.mean(interior_ext, axis=(0, 1))
    max_ch_diff = np.max(np.abs(ch_means_orig - ch_means_ext))

    if max_ch_diff < 0.005:
        return _fail(f"extinction change had no effect: "
                     f"orig channels={ch_means_orig}, "
                     f"changed channels={ch_means_ext}")

    return _ok(f"sun intensity: {val1:.4f} vs {val5:.4f}; "
               f"extinction max channel diff: {max_ch_diff:.4f}")


# ------------------------------------------------------------------
# (f) Furnace via accumulation: albedo=1, white sky -> (1,1,1)
# ------------------------------------------------------------------
def test_furnace_accumulated(ctx: moderngl.Context) -> bool:
    print("\n--- (f) furnace: albedo=1, white sky, no sun -> (1,1,1) ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)
    _fill_constant_density(renderer, 0.5)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(1.0, 1.0, 1.0),
                          density_scale=1.0)
    sky = SkyParams(color_top=(1.0, 1.0, 1.0), color_bottom=(1.0, 1.0, 1.0), intensity=1.0)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=0.0)  # sun OFF
    render = RenderParams(num_samples=128, max_bounces=0, rr_start_depth=2)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    renderer.render_to_completion(vp, target_tex, medium, sun, sky, render)
    img = _readback_target(target_tex)

    if np.any(np.isnan(img)):
        return _fail("NaN in output")

    margin = width // 4
    interior = img[margin:height-margin, margin:width-margin, :3]
    interior_mean = np.mean(interior, axis=(0, 1))

    max_dev = np.max(np.abs(interior_mean - 1.0))
    if max_dev > 0.08:
        return _fail(f"furnace interior mean {interior_mean} deviates from "
                     f"(1,1,1) by {max_dev:.4f} (tolerance 0.08)")

    return _ok(f"furnace interior mean {interior_mean}, max_dev={max_dev:.4f}")


# ------------------------------------------------------------------
# (g) Accumulated mean matches CPU-averaged single-sample renders
# ------------------------------------------------------------------
def test_accumulated_matches_cpu_average(ctx: moderngl.Context) -> bool:
    print("\n--- (g) accumulated mean matches CPU-averaged single-sample renders ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams, RenderParams, SunParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)
    _fill_constant_density(renderer, 0.3)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                          albedo_rgb=(0.8, 0.8, 0.8), density_scale=1.0)
    sky = SkyParams(color_top=(0.5, 0.7, 1.0), color_bottom=(0.5, 0.7, 1.0), intensity=1.0)
    sun = SunParams(direction=(0.0, 1.0, 0.0),
                    color_rgb=(1.0, 1.0, 1.0), intensity=3.0)
    render = RenderParams(max_bounces=8, rr_start_depth=4, seed=0)
    target_tex = ctx.texture((width, height), 4, dtype='f2')

    num_samples = 32

    # Method 1: GPU accumulation via render_to_completion
    render_acc = RenderParams(num_samples=num_samples, max_bounces=8,
                              rr_start_depth=4, seed=0)
    renderer.render_to_completion(vp, target_tex, medium, sun, sky, render_acc)
    img_gpu = _readback_target(target_tex).astype(np.float64)

    # Method 2: CPU averaging of single-sample renders (render_bounce_test)
    accum_cpu = np.zeros((height, width, 4), dtype=np.float64)
    for i in range(num_samples):
        renderer.render_bounce_test(vp, target_tex, medium, sky, render,
                                    sample_index=i, sun=sun)
        accum_cpu += _readback_target(target_tex).astype(np.float64)
    img_cpu = accum_cpu / num_samples

    # The images should be very close (same RNG seeds, same sample indices)
    max_diff = np.max(np.abs(img_gpu[:, :, :3] - img_cpu[:, :, :3]))
    mean_diff = np.mean(np.abs(img_gpu[:, :, :3] - img_cpu[:, :, :3]))

    # Allow some tolerance for float16 quantization and accumulation order
    if max_diff > 0.1:
        return _fail(f"max diff = {max_diff:.4f} (tolerance 0.1)")

    if mean_diff > 0.02:
        return _fail(f"mean diff = {mean_diff:.6f} (tolerance 0.02)")

    return _ok(f"max_diff={max_diff:.4f}, mean_diff={mean_diff:.6f}")


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
        test_convergence,
        test_reset_clears,
        test_no_tdr_crash,
        test_read_frame,
        test_edit_without_resplat,
        test_furnace_accumulated,
        test_accumulated_matches_cpu_average,
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
