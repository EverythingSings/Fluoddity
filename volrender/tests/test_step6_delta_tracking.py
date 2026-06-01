"""Tests for volrender Step 6 — delta-tracked free flight (weighted null-scattering, RGB).

Run from project root:
    python -m volrender.tests.test_step6_delta_tracking

Tests:
 (a) Constant-density box: collision fraction matches analytic 1 - exp(-sigma_t * L).
 (b) Higher extinction -> higher collision fraction.
 (c) Empty grid -> pure sky (no collisions).
 (d) Camera pointed away from grid -> pure sky.
 (e) Dense centered cloud: white center pixels, sky corners (silhouette shape).
 (f) No NaN, inf, or negative values in output.
 (g) Increasing density_scale -> monotonically increasing collision fraction.
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


def _collision_fraction(img: np.ndarray, sky_rgb: np.ndarray) -> float:
    """Count the fraction of pixels that differ from sky (i.e. collided).

    In Step 6 visual mode, collisions are white (1,1,1) and escapes are sky.
    We classify a pixel as 'collided' if its max-channel distance from sky > 0.1.
    """
    diff = np.max(np.abs(img[:, :, :3] - sky_rgb), axis=2)
    return float(np.mean(diff > 0.1))


# ------------------------------------------------------------------
# (a) Constant-density collision fraction vs analytic
# ------------------------------------------------------------------
def test_constant_density_collision_fraction(ctx: moderngl.Context) -> bool:
    print("\n--- (a) constant-density collision fraction vs analytic ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (32, 32, 32)
    bmin, bmax = (-1, -1, -1), (1, 1, 1)
    params = GridParams(bounds_min=bmin, bounds_max=bmax,
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    # Choose physical_density so collision probability is in a testable range.
    # Box depth along Z = 2.0.  sigma_t = extinction * density_scale * phys_dens.
    # With extinction=1, density_scale=1, phys_dens=0.5:
    #   sigma_t = 0.5, L = 2.0, P(collision) = 1 - exp(-1.0) ≈ 0.632
    physical_density = 0.5
    _fill_constant_density(renderer, physical_density)

    extinction = (1.0, 1.0, 1.0)
    density_scale = 1.0
    sigma_t_scalar = 1.0 * density_scale * physical_density  # = 0.5
    L = 2.0  # box depth
    expected_p = 1.0 - math.exp(-sigma_t_scalar * L)

    # Camera far away on +Z axis, narrow FOV → approximately parallel rays
    # all traversing the full box depth.
    eye = [0, 0, 20]
    target = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 256, 256
    vp = cpu_view_proj(eye, target, up, 6.0, width / height)

    medium = MediumParams(extinction_rgb=extinction, density_scale=density_scale)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_delta_test(vp, target_tex, medium, sky)

    img = _readback_target(target_tex)

    if np.any(np.isnan(img)):
        return _fail("NaN in output")

    # Count collision fraction — but with a narrow FOV from far away,
    # only pixels whose rays actually hit the box contribute.
    # First identify which pixels hit the box (non-sky).
    # Actually with such a narrow FOV (6 deg) from distance 20, the box
    # subtends about 2/20 = 0.1 rad ≈ 5.7 deg, so the box fills most of
    # the 6-deg FOV.  Some edge pixels will miss.
    # We'll only count "interior" pixels that definitely hit the box.
    # Use a central region.
    margin = width // 4
    interior = img[margin:height-margin, margin:width-margin, :]
    n_pixels = interior.shape[0] * interior.shape[1]

    # Classify: white (>0.9 all channels) = collision, sky-colored = escape
    r, g, b = interior[:, :, 0], interior[:, :, 1], interior[:, :, 2]
    is_collision = (r > 0.9) & (g > 0.9) & (b > 0.9)
    measured_p = float(np.sum(is_collision)) / n_pixels

    # Binomial confidence: 4 sigma
    sigma = math.sqrt(expected_p * (1 - expected_p) / n_pixels)
    tolerance = 4 * sigma

    diff = abs(measured_p - expected_p)
    if diff > tolerance:
        return _fail(f"collision fraction {measured_p:.4f} differs from analytic "
                     f"{expected_p:.4f} by {diff:.4f} (tolerance {tolerance:.4f})")

    return _ok(f"collision fraction {measured_p:.4f} ~ analytic {expected_p:.4f} "
               f"(diff {diff:.4f}, tolerance {tolerance:.4f})")


# ------------------------------------------------------------------
# (b) Higher extinction -> higher collision fraction
# ------------------------------------------------------------------
def test_higher_extinction_more_collisions(ctx: moderngl.Context) -> bool:
    print("\n--- (b) higher extinction -> more collisions ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.3
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 128, 128
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)

    fractions = []
    for ext_val in [0.5, 2.0]:
        medium = MediumParams(extinction_rgb=(ext_val, ext_val, ext_val),
                              density_scale=1.0)
        target_tex = ctx.texture((width, height), 4, dtype='f2')
        renderer.render_delta_test(vp, target_tex, medium, sky)
        img = _readback_target(target_tex)

        margin = width // 4
        interior = img[margin:height-margin, margin:width-margin, :]
        r, g, b = interior[:, :, 0], interior[:, :, 1], interior[:, :, 2]
        is_collision = (r > 0.9) & (g > 0.9) & (b > 0.9)
        fractions.append(float(np.mean(is_collision)))

    if fractions[1] <= fractions[0]:
        return _fail(f"higher extinction did not produce more collisions: "
                     f"ext=0.5 -> {fractions[0]:.4f}, ext=2.0 -> {fractions[1]:.4f}")

    return _ok(f"ext=0.5 -> {fractions[0]:.4f}, ext=2.0 -> {fractions[1]:.4f}")


# ------------------------------------------------------------------
# (c) Empty grid -> pure sky
# ------------------------------------------------------------------
def test_empty_grid_pure_sky(ctx: moderngl.Context) -> bool:
    print("\n--- (c) empty grid -> pure sky ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (8, 8, 8)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)
    # No splat — grid is all zeros from initialization

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=5.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_delta_test(vp, target_tex, medium, sky)

    img = _readback_target(target_tex)
    max_diff = np.max(np.abs(img[:, :, :3] - sky_rgb))

    if max_diff > 0.01:
        return _fail(f"not pure sky: max diff from sky = {max_diff:.6f}")

    return _ok(f"all pixels are sky (max diff = {max_diff:.6f})")


# ------------------------------------------------------------------
# (d) Camera pointed away -> pure sky
# ------------------------------------------------------------------
def test_camera_away_pure_sky(ctx: moderngl.Context) -> bool:
    print("\n--- (d) camera pointed away -> pure sky ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (8, 8, 8)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)

    # Splat some particles so grid is non-empty
    positions = np.array([[0, 0, 0]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, 1)

    # Camera looking AWAY (at +Z, looking further +Z)
    eye = [0, 0, 5]
    target_pt = [0, 0, 10]
    up = [0, 1, 0]
    width, height = 32, 32
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=5.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_delta_test(vp, target_tex, medium, sky)

    img = _readback_target(target_tex)
    max_diff = np.max(np.abs(img[:, :, :3] - sky_rgb))

    if max_diff > 0.01:
        return _fail(f"not pure sky: max diff from sky = {max_diff:.6f}")

    return _ok(f"all pixels are sky (max diff = {max_diff:.6f})")


# ------------------------------------------------------------------
# (e) Silhouette shape: white center, sky corners
# ------------------------------------------------------------------
def test_silhouette_shape(ctx: moderngl.Context) -> bool:
    print("\n--- (e) silhouette shape (white center, sky corners) ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    # Dense centered cloud
    rng = np.random.default_rng(42)
    positions = rng.normal(0.0, 0.15, size=(2000, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    # High density_scale so center is almost certainly a collision
    medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0), density_scale=50.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)
    sky_rgb = np.array([0.5, 0.7, 1.0], dtype=np.float32)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_delta_test(vp, target_tex, medium, sky)

    img = _readback_target(target_tex)

    # Center pixels should be white (collision)
    cy, cx = height // 2, width // 2
    center = img[cy, cx, :3]
    center_is_white = np.all(center > 0.9)
    if not center_is_white:
        return _fail(f"center pixel is not white: {center}")

    # Corner pixels should be sky
    corner = img[0, 0, :3]
    corner_diff = np.max(np.abs(corner - sky_rgb))
    if corner_diff > 0.01:
        return _fail(f"corner pixel differs from sky by {corner_diff:.6f}")

    return _ok(f"center is white, corner is sky (corner diff = {corner_diff:.6f})")


# ------------------------------------------------------------------
# (f) No NaN, inf, or negative values
# ------------------------------------------------------------------
def test_no_nans(ctx: moderngl.Context) -> bool:
    print("\n--- (f) no NaN/inf/negative in output ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (16, 16, 16)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    rng = np.random.default_rng(123)
    positions = rng.normal(0.0, 0.3, size=(1000, 3)).astype(np.float32)
    positions = np.clip(positions, -0.99, 0.99)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    eye = [0, 0, 5]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 64, 64
    vp = cpu_view_proj(eye, target_pt, up, 60.0, width / height)

    # Colored extinction + high density_scale to stress the tracker
    medium = MediumParams(extinction_rgb=(3.0, 0.5, 1.5), density_scale=10.0)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)

    target_tex = ctx.texture((width, height), 4, dtype='f2')
    renderer.render_delta_test(vp, target_tex, medium, sky)

    img = _readback_target(target_tex)

    if np.any(np.isnan(img)):
        nan_count = np.sum(np.isnan(img))
        return _fail(f"{nan_count} NaN values detected")
    if np.any(np.isinf(img)):
        inf_count = np.sum(np.isinf(img))
        return _fail(f"{inf_count} inf values detected")
    if np.any(img[:, :, :3] < -1e-6):
        neg_min = float(np.min(img[:, :, :3]))
        return _fail(f"negative value detected: min = {neg_min:.6f}")

    return _ok("no NaN, inf, or negative values")


# ------------------------------------------------------------------
# (g) Increasing density_scale -> more collisions
# ------------------------------------------------------------------
def test_density_scale_monotonic(ctx: moderngl.Context) -> bool:
    print("\n--- (g) density_scale monotonic collision increase ---")
    from volrender import VolumeRenderer, GridParams, MediumParams, SkyParams

    res = (32, 32, 32)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(8, 8, 8))
    renderer = VolumeRenderer(ctx, params)

    physical_density = 0.3
    _fill_constant_density(renderer, physical_density)

    eye = [0, 0, 20]
    target_pt = [0, 0, 0]
    up = [0, 1, 0]
    width, height = 128, 128
    vp = cpu_view_proj(eye, target_pt, up, 6.0, width / height)
    sky = SkyParams(color_rgb=(0.5, 0.7, 1.0), intensity=1.0)

    scales = [0.5, 1.0, 2.0, 5.0]
    fractions = []

    for scale in scales:
        medium = MediumParams(extinction_rgb=(1.0, 1.0, 1.0),
                              density_scale=scale)
        target_tex = ctx.texture((width, height), 4, dtype='f2')
        renderer.render_delta_test(vp, target_tex, medium, sky)
        img = _readback_target(target_tex)

        margin = width // 4
        interior = img[margin:height-margin, margin:width-margin, :]
        r, g, b = interior[:, :, 0], interior[:, :, 1], interior[:, :, 2]
        is_collision = (r > 0.9) & (g > 0.9) & (b > 0.9)
        fractions.append(float(np.mean(is_collision)))

    # Each should be >= previous (more collisions with higher density_scale)
    for i in range(1, len(fractions)):
        if fractions[i] < fractions[i - 1] - 0.01:  # small tolerance for noise
            return _fail(f"collision fraction decreased at scale={scales[i]}: "
                         f"{fractions[i]:.4f} < {fractions[i-1]:.4f}")

    labels = [f"scale={s}: {f:.4f}" for s, f in zip(scales, fractions)]
    return _ok(f"monotonic: {', '.join(labels)}")


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
        test_constant_density_collision_fraction,
        test_higher_extinction_more_collisions,
        test_empty_grid_pure_sky,
        test_camera_away_pure_sky,
        test_silhouette_shape,
        test_no_nans,
        test_density_scale_monotonic,
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
