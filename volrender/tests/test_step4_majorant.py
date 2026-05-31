"""Tests for volrender Step 4 — majorant grid build (dilated max-pool).

Run from project root:
    python -m volrender.tests.test_step4_majorant

Tests:
 (a) GPU majorant >= CPU reference per coarse cell (upper-bound guarantee).
 (b) GPU majorant is a tight bound (matches CPU reference within float tol).
 (c) Critical regression: trilinearly-filtered density at random points inside
     each coarse cell never exceeds that cell's majorant.
 (d) Empty grid -> majorant is all zeros.
 (e) Single spike at coarse-cell boundary -> guard band propagates to neighbors.
 (f) Non-integer fine/coarse ratio (12^3 / 5^3 = 2.4) -> still a valid bound.
 (g) VolumeRenderer.splat() automatically populates majorant.
"""
from __future__ import annotations

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
# CPU reference: majorant (dilated max-pool)
# ------------------------------------------------------------------
def cpu_majorant(density_grid: np.ndarray,
                 bounds_min: np.ndarray,
                 bounds_max: np.ndarray,
                 fine_resolution: tuple[int, int, int],
                 majorant_resolution: tuple[int, int, int],
                 voxel_volume: float) -> np.ndarray:
    """CPU reference: build majorant grid from fine density.

    Args:
        density_grid: (Rz, Ry, Rx) raw density values from GPU readback.
        bounds_min, bounds_max: world-space AABB corners.
        fine_resolution: (Rx, Ry, Rz) fine grid dimensions.
        majorant_resolution: (Mx, My, Mz) coarse grid dimensions.
        voxel_volume: volume of a single fine voxel.

    Returns:
        (Mz, My, Mx) float32 majorant grid (physical density).
    """
    fine_res = np.array(fine_resolution, dtype=np.float64)
    maj_res = np.array(majorant_resolution, dtype=np.int32)
    extent = bounds_max - bounds_min
    result = np.zeros(majorant_resolution[::-1], dtype=np.float64)  # (Mz, My, Mx)

    for cz in range(maj_res[2]):
        for cy in range(maj_res[1]):
            for cx in range(maj_res[0]):
                # World-space bounds of this coarse cell
                cell_min = bounds_min + np.array([cx, cy, cz], dtype=np.float64) / maj_res * extent
                cell_max = bounds_min + np.array([cx + 1, cy + 1, cz + 1], dtype=np.float64) / maj_res * extent

                # Map to fine grid coords
                fine_lo_f = (cell_min - bounds_min) / extent * fine_res
                fine_hi_f = (cell_max - bounds_min) / extent * fine_res

                # Floor low, ceil high
                fine_lo = np.floor(fine_lo_f).astype(int)
                fine_hi = np.ceil(fine_hi_f).astype(int)

                # Guard band
                fine_lo -= 1
                fine_hi += 1

                # Clamp
                fine_lo = np.maximum(fine_lo, 0)
                fine_hi = np.minimum(fine_hi, np.array(fine_resolution) - 1)

                # Max physical density
                max_phys = 0.0
                for fz in range(fine_lo[2], fine_hi[2] + 1):
                    for fy in range(fine_lo[1], fine_hi[1] + 1):
                        for fx in range(fine_lo[0], fine_hi[0] + 1):
                            raw = float(density_grid[fz, fy, fx])
                            phys = raw / voxel_volume
                            max_phys = max(max_phys, phys)

                result[cz, cy, cx] = max_phys

    return result.astype(np.float32)


# ------------------------------------------------------------------
# CPU trilinear sampler (matches GL_LINEAR + GL_CLAMP_TO_EDGE)
# ------------------------------------------------------------------
def cpu_trilinear_sample(density_grid: np.ndarray,
                         bounds_min: np.ndarray,
                         bounds_max: np.ndarray,
                         fine_resolution: tuple[int, int, int],
                         world_pos: np.ndarray) -> float:
    """Sample the density grid trilinearly at world_pos.

    Matches OpenGL GL_LINEAR filtering with GL_CLAMP_TO_EDGE wrapping.
    """
    extent = bounds_max - bounds_min
    res = np.array(fine_resolution, dtype=np.float64)

    # World -> normalized texture coords [0, 1]
    uv = (world_pos - bounds_min) / extent

    # Normalized -> texel space (texel i is centered at (i+0.5)/N)
    texel = uv * res - 0.5

    i0 = np.floor(texel).astype(int)
    frac = texel - i0

    result = 0.0
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                ix = max(0, min(int(res[0]) - 1, i0[0] + dx))
                iy = max(0, min(int(res[1]) - 1, i0[1] + dy))
                iz = max(0, min(int(res[2]) - 1, i0[2] + dz))

                wx = frac[0] if dx else (1.0 - frac[0])
                wy = frac[1] if dy else (1.0 - frac[1])
                wz = frac[2] if dz else (1.0 - frac[2])

                result += wx * wy * wz * float(density_grid[iz, iy, ix])

    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _make_entity_buffer(ctx: moderngl.Context,
                        positions: np.ndarray,
                        velocities: np.ndarray | None = None) -> moderngl.Buffer:
    """Pack positions (and optional velocities) into an 8-float-stride entity buffer."""
    n = len(positions)
    data = np.zeros((n, 8), dtype=np.float32)
    data[:, 0:3] = positions
    if velocities is not None:
        data[:, 3:6] = velocities
    return ctx.buffer(data.tobytes())


def _readback_density(grid) -> np.ndarray:
    """Read density texture back as (Z, Y, X) float32 array."""
    res = grid.params.resolution
    raw = grid.density.read()
    return np.frombuffer(raw, dtype=np.float32).reshape(res[2], res[1], res[0])


def _readback_majorant(grid) -> np.ndarray:
    """Read majorant texture back as (Mz, My, Mx) float32 array."""
    maj = grid.params.majorant_resolution
    raw = grid.majorant.read()
    return np.frombuffer(raw, dtype=np.float32).reshape(maj[2], maj[1], maj[0])


# ------------------------------------------------------------------
# (a) GPU majorant >= CPU reference (upper-bound guarantee)
# ------------------------------------------------------------------
def test_majorant_ge_cpu(ctx: moderngl.Context) -> bool:
    print("\n--- (a) GPU majorant >= CPU reference ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (16, 16, 16)
    maj_res = (4, 4, 4)
    bmin = np.array([-1, -1, -1], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    # Splat a random cloud
    rng = np.random.default_rng(42)
    positions = rng.uniform(-0.9, 0.9, size=(200, 3)).astype(np.float32)
    buf = _make_entity_buffer(ctx, positions)
    grid.splat(buf, len(positions))
    builder.build(grid)

    density = _readback_density(grid)
    majorant_gpu = _readback_majorant(grid)
    majorant_cpu = cpu_majorant(density, bmin, bmax, res, maj_res, grid.voxel_volume)

    # Every GPU cell must be >= CPU reference
    violations = np.sum(majorant_gpu < majorant_cpu - 1e-4)
    if violations > 0:
        diff = majorant_cpu - majorant_gpu
        worst = np.max(diff)
        return _fail(f"{violations} cells where GPU < CPU (worst deficit = {worst:.6f})")

    nonzero = np.sum(majorant_gpu > 0)
    return _ok(f"all {maj_res} cells satisfy GPU >= CPU ({nonzero} nonzero)")


# ------------------------------------------------------------------
# (b) Tight bound (GPU ~= CPU, not wildly inflated)
# ------------------------------------------------------------------
def test_majorant_tight(ctx: moderngl.Context) -> bool:
    print("\n--- (b) majorant is a tight bound ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (16, 16, 16)
    maj_res = (4, 4, 4)
    bmin = np.array([-1, -1, -1], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    rng = np.random.default_rng(42)
    positions = rng.uniform(-0.9, 0.9, size=(200, 3)).astype(np.float32)
    buf = _make_entity_buffer(ctx, positions)
    grid.splat(buf, len(positions))
    builder.build(grid)

    density = _readback_density(grid)
    majorant_gpu = _readback_majorant(grid)
    majorant_cpu = cpu_majorant(density, bmin, bmax, res, maj_res, grid.voxel_volume)

    # GPU should not exceed CPU by more than float tolerance
    excess = majorant_gpu - majorant_cpu
    max_excess = np.max(excess)
    if max_excess > 1e-3:
        return _fail(f"GPU exceeds CPU by up to {max_excess:.6f} (expected tight match)")

    max_err = np.max(np.abs(excess))
    return _ok(f"tight bound: max |GPU - CPU| = {max_err:.6f}")


# ------------------------------------------------------------------
# (c) Critical: trilinear samples never exceed majorant
# ------------------------------------------------------------------
def test_trilinear_never_exceeds_majorant(ctx: moderngl.Context) -> bool:
    print("\n--- (c) trilinear density never exceeds majorant ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (16, 16, 16)
    maj_res = (4, 4, 4)
    bmin = np.array([-1, -1, -1], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    extent = bmax - bmin
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    # Splat a cloud concentrated near the center (high density variance)
    rng = np.random.default_rng(99)
    positions = rng.normal(0.0, 0.3, size=(500, 3)).astype(np.float32)
    # Clip to bounds
    positions = np.clip(positions, -0.999, 0.999)
    buf = _make_entity_buffer(ctx, positions)
    grid.splat(buf, len(positions))
    builder.build(grid)

    density = _readback_density(grid)
    majorant = _readback_majorant(grid)
    voxel_volume = grid.voxel_volume

    # Sample many random points inside each coarse cell
    n_samples_per_cell = 50
    violations = 0
    worst_excess = 0.0
    tested = 0

    for cz in range(maj_res[2]):
        for cy in range(maj_res[1]):
            for cx in range(maj_res[0]):
                maj_val = majorant[cz, cy, cx]
                if maj_val <= 0:
                    continue

                cell_min = bmin + np.array([cx, cy, cz], dtype=np.float64) / np.array(maj_res) * extent
                cell_max = bmin + np.array([cx + 1, cy + 1, cz + 1], dtype=np.float64) / np.array(maj_res) * extent

                for _ in range(n_samples_per_cell):
                    # Random point inside this coarse cell
                    t = rng.uniform(0, 1, size=3)
                    world_pos = cell_min + t * (cell_max - cell_min)

                    sampled_raw = cpu_trilinear_sample(density, bmin, bmax, res, world_pos)
                    sampled_phys = sampled_raw / voxel_volume

                    if sampled_phys > maj_val + 1e-4:
                        violations += 1
                        worst_excess = max(worst_excess, sampled_phys - maj_val)

                    tested += 1

    if violations > 0:
        return _fail(f"{violations}/{tested} samples exceeded majorant "
                     f"(worst excess = {worst_excess:.6f})")

    return _ok(f"{tested} trilinear samples all <= majorant")


# ------------------------------------------------------------------
# (d) Empty grid -> majorant all zeros
# ------------------------------------------------------------------
def test_empty_grid(ctx: moderngl.Context) -> bool:
    print("\n--- (d) empty grid -> majorant all zeros ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (8, 8, 8)
    maj_res = (2, 2, 2)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    # Build majorant on a cleared (empty) grid
    builder.build(grid)

    majorant = _readback_majorant(grid)
    if np.any(majorant != 0.0):
        max_val = np.max(majorant)
        return _fail(f"expected all zeros, max = {max_val}")

    return _ok("majorant is all zeros on empty grid")


# ------------------------------------------------------------------
# (e) Guard band: spike at coarse-cell boundary propagates
# ------------------------------------------------------------------
def test_spike_guard_band(ctx: moderngl.Context) -> bool:
    print("\n--- (e) guard band: spike at boundary propagates ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (8, 8, 8)
    maj_res = (2, 2, 2)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    # Place particle at the exact boundary between coarse cells (0,0,0) and (1,1,1).
    # Coarse cell boundary in world space = 0.5 for 2^3 majorant on [0,1].
    # Fine voxel 4 is centered at (4+0.5)/8 = 0.5625, which is in coarse cell 1.
    # But the guard band should cause coarse cell 0 to also cover voxel 4.
    # Place particle near the boundary (world 0.5) — it will splat into
    # fine voxels 3 and 4, straddling the coarse cell boundary.
    world_pos = np.array([[0.5, 0.5, 0.5]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, world_pos)
    grid.splat(buf, 1)
    builder.build(grid)

    majorant = _readback_majorant(grid)

    # Both coarse cells along each axis at the boundary should be nonzero
    cell_000 = majorant[0, 0, 0]
    cell_111 = majorant[1, 1, 1]

    if cell_000 <= 0:
        return _fail(f"coarse cell (0,0,0) = {cell_000}, expected > 0 (guard band)")
    if cell_111 <= 0:
        return _fail(f"coarse cell (1,1,1) = {cell_111}, expected > 0")

    return _ok(f"guard band works: cell(0,0,0)={cell_000:.4f}, cell(1,1,1)={cell_111:.4f}")


# ------------------------------------------------------------------
# (f) Non-integer fine/coarse ratio (12^3 / 5^3)
# ------------------------------------------------------------------
def test_nonuniform_resolution(ctx: moderngl.Context) -> bool:
    print("\n--- (f) non-integer ratio 12^3 / 5^3 ---")
    from volrender import GridParams, VoxelGrid
    from volrender.majorant import MajorantBuilder

    res = (12, 12, 12)
    maj_res = (5, 5, 5)
    bmin = np.array([0, 0, 0], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    grid = VoxelGrid(ctx, params)
    builder = MajorantBuilder(ctx)

    rng = np.random.default_rng(77)
    positions = rng.uniform(0.05, 0.95, size=(100, 3)).astype(np.float32)
    buf = _make_entity_buffer(ctx, positions)
    grid.splat(buf, len(positions))
    builder.build(grid)

    density = _readback_density(grid)
    majorant_gpu = _readback_majorant(grid)
    majorant_cpu = cpu_majorant(density, bmin, bmax, res, maj_res, grid.voxel_volume)

    # Upper bound check
    violations = np.sum(majorant_gpu < majorant_cpu - 1e-4)
    if violations > 0:
        return _fail(f"{violations} cells where GPU < CPU")

    # Tight bound check
    max_err = np.max(np.abs(majorant_gpu - majorant_cpu))
    if max_err > 1e-3:
        return _fail(f"max |GPU - CPU| = {max_err:.6f}")

    return _ok(f"non-integer ratio: max |GPU - CPU| = {max_err:.6f}")


# ------------------------------------------------------------------
# (g) VolumeRenderer.splat() populates majorant automatically
# ------------------------------------------------------------------
def test_renderer_splat_populates_majorant(ctx: moderngl.Context) -> bool:
    print("\n--- (g) VolumeRenderer.splat() populates majorant ---")
    from volrender import VolumeRenderer, GridParams

    res = (8, 8, 8)
    maj_res = (2, 2, 2)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=maj_res)
    renderer = VolumeRenderer(ctx, params)

    positions = np.array([[0.25, 0.25, 0.25],
                          [0.75, 0.75, 0.75]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, positions)
    renderer.splat(buf, len(positions))

    majorant = _readback_majorant(renderer.grid)
    nonzero = np.sum(majorant > 0)

    if nonzero == 0:
        return _fail("majorant is all zeros after VolumeRenderer.splat()")

    # Verify the global max diagnostic matches readback
    global_max = renderer.majorant_builder.read_global_max(renderer.grid)
    readback_max = float(majorant.max())
    if not np.isclose(global_max, readback_max, atol=1e-5):
        return _fail(f"read_global_max={global_max} != readback max={readback_max}")

    return _ok(f"majorant populated: {nonzero} nonzero cells, max={readback_max:.4f}")


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
        test_majorant_ge_cpu,
        test_majorant_tight,
        test_trilinear_never_exceeds_majorant,
        test_empty_grid,
        test_spike_guard_band,
        test_nonuniform_resolution,
        test_renderer_splat_populates_majorant,
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
