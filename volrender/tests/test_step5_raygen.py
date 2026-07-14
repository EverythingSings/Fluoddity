"""Tests for volrender Step 5 — primary ray generation, AABB, debug raymarch.

Run from project root:
    python -m volrender.tests.test_step5_raygen

Tests:
 (a) CPU AABB slab intersection correctness (hit, miss, inside-box cases).
 (b) Camera inverse round-trip: inv(view_proj) * view_proj ≈ identity.
 (c) Debug raymarch: known cloud produces silhouette (non-sky pixels where
     expected, sky pixels elsewhere).
 (d) Camera pointed away from grid → pure sky.
 (e) Increasing density_scale darkens the image monotonically.
 (f) Colored extinction produces expected per-channel tint.
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
# CPU reference helpers
# ------------------------------------------------------------------

def cpu_look_at(eye, target, up):
    """Build a 4×4 view matrix (row-major storage, OpenGL convention)."""
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
    """Build a 4×4 perspective projection matrix."""
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


def cpu_intersect_aabb(origin, direction, box_min, box_max):
    """CPU AABB slab intersection.  Returns (hit, t_near, t_far)."""
    origin = np.array(origin, dtype=np.float64)
    direction = np.array(direction, dtype=np.float64)
    box_min = np.array(box_min, dtype=np.float64)
    box_max = np.array(box_max, dtype=np.float64)

    with np.errstate(divide='ignore', invalid='ignore'):
        inv_dir = np.float64(1.0) / direction  # inf/-inf for zero components (IEEE)
        t0 = (box_min - origin) * inv_dir
        t1 = (box_max - origin) * inv_dir
        # NaN can appear when 0 * inf (origin on a slab face); treat as no constraint
        tmin = np.fmin(t0, t1)   # fmin ignores NaN
        tmax = np.fmax(t0, t1)   # fmax ignores NaN
    t_near = float(np.max(tmin))
    t_far = float(np.min(tmax))
    hit = t_far >= max(t_near, 0.0)
    return hit, t_near, t_far


def _make_entity_buffer(ctx: moderngl.Context,
                        positions: np.ndarray) -> moderngl.Buffer:
    """Pack positions into an 8-float-stride entity buffer."""
    n = len(positions)
    data = np.zeros((n, 8), dtype=np.float32)
    data[:, 0:3] = positions
    return ctx.buffer(data.tobytes())


def _readback_target(target: moderngl.Texture) -> np.ndarray:
    """Read back an rgba16f target as (H, W, 4) float32."""
    raw = target.read()
    # rgba16f → 2 bytes per component × 4 components = 8 bytes per pixel
    data = np.frombuffer(raw, dtype=np.float16)
    return data.reshape(target.height, target.width, 4).astype(np.float32)


# ------------------------------------------------------------------
# (a) CPU AABB slab intersection correctness
# ------------------------------------------------------------------
def test_aabb_intersection_cpu(ctx: moderngl.Context) -> bool:
    print("\n--- (a) CPU AABB slab intersection correctness ---")

    box_min = (-1, -1, -1)
    box_max = (1, 1, 1)

    # Ray hits box from outside
    hit, tn, tf = cpu_intersect_aabb([0, 0, -5], [0, 0, 1], box_min, box_max)
    if not hit:
        return _fail("expected hit for ray toward box")
    if not (abs(tn - 4.0) < 1e-6 and abs(tf - 6.0) < 1e-6):
        return _fail(f"expected t_near=4, t_far=6, got {tn:.6f}, {tf:.6f}")

    # Ray misses box (parallel, offset)
    hit, _, _ = cpu_intersect_aabb([5, 0, -5], [0, 0, 1], box_min, box_max)
    if hit:
        return _fail("expected miss for ray parallel and offset")

    # Ray origin inside box
    hit, tn, tf = cpu_intersect_aabb([0, 0, 0], [0, 0, 1], box_min, box_max)
    if not hit:
        return _fail("expected hit for origin inside box")
    if tn >= 0:
        return _fail(f"expected t_near < 0 for origin inside box, got {tn:.6f}")
    if tf <= 0:
        return _fail(f"expected t_far > 0 for origin inside box, got {tf:.6f}")

    # Ray pointing away from box
    hit, _, _ = cpu_intersect_aabb([0, 0, -5], [0, 0, -1], box_min, box_max)
    if hit:
        return _fail("expected miss for ray pointing away from box")

    # Diagonal ray
    d = np.array([1, 1, 1], dtype=np.float64)
    d = d / np.linalg.norm(d)
    hit, tn, tf = cpu_intersect_aabb([-5, -5, -5], d, box_min, box_max)
    if not hit:
        return _fail("expected hit for diagonal ray")

    return _ok("all AABB intersection cases correct")


# ------------------------------------------------------------------
# (b) Camera inverse round-trip
# ------------------------------------------------------------------
def test_camera_inverse_roundtrip(ctx: moderngl.Context) -> bool:
    print("\n--- (b) camera inverse round-trip ---")
    from volrender.camera import Camera

    eye = [0, 0, 5]
    target = [0, 0, 0]
    up = [0, 1, 0]
    vp = cpu_view_proj(eye, target, up, 60.0, 1.0)

    cam = Camera()
    cam.set_view_proj(vp)
    inv = cam.inv_view_proj

    # vp @ inv should ≈ identity
    product = np.array(vp, dtype=np.float64) @ np.array(inv, dtype=np.float64)
    err = np.max(np.abs(product - np.eye(4)))
    if err > 1e-4:
        return _fail(f"round-trip error = {err:.6f}, expected < 1e-4")

    return _ok(f"round-trip max error = {err:.8f}")


# ------------------------------------------------------------------
# (c) Debug raymarch: known cloud produces silhouette
# ------------------------------------------------------------------
def test_debug_raymarch_silhouette(ctx: moderngl.Context) -> bool:
    print("\n--- (c) debug raymarch silhouette ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Dense cloud at center
    rng = np.random.default_rng(42)
    positions = rng.normal(0.0, 0.2, size=(500, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    # Camera looking at center from +Z
    eye = [0, 0, 5]
    target = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target, up, 60.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=5.0)
    sky = SkyParams(color_top=(0.5, 0.7, 1.0), color_bottom=(0.5, 0.7, 1.0), intensity=1.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_debug(vp, target_tex, medium, sky, debug_steps=128)

    img = _readback_target(target_tex)

    # Sky color (linear HDR)
    sky_rgb = np.array([0.5 * 1.0, 0.7 * 1.0, 1.0 * 1.0], dtype=np.float32)

    # Check center pixels differ from sky (cloud is there)
    center = img[height // 2, width // 2, :3]
    center_diff = np.max(np.abs(center - sky_rgb))
    if center_diff < 0.01:
        return _fail(f"center pixel matches sky (diff={center_diff:.6f}), expected cloud")

    # Check corner pixels are sky (cloud is centered, camera far enough)
    corner = img[0, 0, :3]
    corner_diff = np.max(np.abs(corner - sky_rgb))
    if corner_diff > 0.01:
        return _fail(f"corner pixel differs from sky by {corner_diff:.6f}, expected sky")

    # Check NaN
    if np.any(np.isnan(img)):
        return _fail("NaNs detected in output")

    return _ok(f"silhouette correct: center diff={center_diff:.4f}, corner diff={corner_diff:.6f}")


# ------------------------------------------------------------------
# (d) Camera pointed away → pure sky
# ------------------------------------------------------------------
def test_camera_away_pure_sky(ctx: moderngl.Context) -> bool:
    print("\n--- (d) camera pointed away -> pure sky ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (8, 8, 8)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)

    # Splat some particles
    positions = np.array([[0, 0, 0]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, 1)

    # Camera looking AWAY from the box (positioned at +Z, looking further +Z)
    eye = [0, 0, 5]
    target = [0, 0, 10]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target, up, 60.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=5.0)
    sky = SkyParams(color_top=(0.5, 0.7, 1.0), color_bottom=(0.5, 0.7, 1.0), intensity=1.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_debug(vp, target_tex, medium, sky, debug_steps=64)

    img = _readback_target(target_tex)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)

    max_diff = np.max(np.abs(img[:, :, :3] - sky_rgb))
    if max_diff > 0.01:
        return _fail(f"not pure sky: max diff from sky = {max_diff:.6f}")

    return _ok(f"all pixels are sky (max diff = {max_diff:.6f})")


# ------------------------------------------------------------------
# (e) Increasing density_scale darkens monotonically
# ------------------------------------------------------------------
def test_density_scale_monotonic(ctx: moderngl.Context) -> bool:
    print("\n--- (e) increasing density_scale darkens monotonically ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Dense centered cloud
    rng = np.random.default_rng(42)
    positions = rng.normal(0.0, 0.2, size=(500, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    eye = [0, 0, 5]
    target = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target, up, 60.0, width / height)
    sky = SkyParams(color_top=(0.5, 0.7, 1.0), color_bottom=(0.5, 0.7, 1.0), intensity=1.0)

    means = []
    for scale in [1.0, 2.0, 5.0, 10.0]:
        medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=scale)
        target_tex = ctx.texture((width, height), 4, dtype='f2')
        renderer.render_debug(vp, target_tex, medium, sky, debug_steps=128)
        img = _readback_target(target_tex)
        means.append(float(np.mean(img[:, :, :3])))

    # Each should be <= previous (darker with more density)
    for i in range(1, len(means)):
        if means[i] > means[i - 1] + 1e-4:
            return _fail(f"brightness increased at scale index {i}: "
                         f"{means[i]:.6f} > {means[i-1]:.6f}")

    return _ok(f"monotonic darkening: means = {[f'{m:.4f}' for m in means]}")


# ------------------------------------------------------------------
# (f) Colored extinction produces expected tint
# ------------------------------------------------------------------
def test_colored_extinction_tint(ctx: moderngl.Context) -> bool:
    print("\n--- (f) colored extinction tint ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Dense centered cloud
    rng = np.random.default_rng(42)
    positions = rng.normal(0.0, 0.2, size=(500, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    eye = [0, 0, 5]
    target = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target, up, 60.0, width / height)
    sky = SkyParams(color_top=(1.0, 1.0, 1.0), color_bottom=(1.0, 1.0, 1.0), intensity=1.0)

    # High red extinction → red absorbed more → red channel darker
    medium = MediumParams(extinction_rgb=(3.0, 0.5, 0.5), density_scale=5.0)
    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_debug(vp, target_tex, medium, sky, debug_steps=128)
    img = _readback_target(target_tex)

    # Look at center region where cloud is densest
    cy, cx = height // 2, width // 2
    r = 4
    patch = img[cy - r:cy + r, cx - r:cx + r, :3]
    mean_rgb = np.mean(patch, axis=(0, 1))

    # Red should be darker (lower) than green and blue because it's
    # absorbed more.  The sky is white (1,1,1) so transmittance alone
    # determines color.  exp(-3*tau) < exp(-0.5*tau) for tau > 0.
    if mean_rgb[0] >= mean_rgb[1]:
        return _fail(f"red ({mean_rgb[0]:.4f}) >= green ({mean_rgb[1]:.4f}), "
                     f"expected red darker")
    if mean_rgb[0] >= mean_rgb[2]:
        return _fail(f"red ({mean_rgb[0]:.4f}) >= blue ({mean_rgb[2]:.4f}), "
                     f"expected red darker")

    return _ok(f"colored tint correct: R={mean_rgb[0]:.4f} < G={mean_rgb[1]:.4f}, "
               f"B={mean_rgb[2]:.4f}")


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
        test_aabb_intersection_cpu,
        test_camera_inverse_roundtrip,
        test_debug_raymarch_silhouette,
        test_camera_away_pure_sky,
        test_density_scale_monotonic,
        test_colored_extinction_tint,
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
