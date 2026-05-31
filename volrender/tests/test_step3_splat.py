"""Tests for volrender Step 3 — trilinear atomic splat.

Run from project root:
    python -m volrender.tests.test_step3_splat

Tests:
 (a) Single particle at voxel center -> that voxel = 1, neighbors = 0.
 (b) Single particle on a voxel corner -> 8-way split matches CPU reference.
 (c) Small random cloud -> GPU readback matches CPU reference within tolerance,
     total deposited weight ~= entity count (minus out-of-bounds).
 (d) OP spot-check: all velocities = +x -> xx mirrors density, others ~= 0.
"""
from __future__ import annotations

import struct
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
# CPU reference trilinear splat
# ------------------------------------------------------------------
def cpu_trilinear_splat(positions: np.ndarray,
                        bounds_min: np.ndarray,
                        bounds_max: np.ndarray,
                        resolution: tuple[int, int, int]) -> np.ndarray:
    """CPU reference: trilinear-splat positions into a density grid.

    Returns an (Rz, Ry, Rx) float32 array (matches texture3d readback order).
    """
    res = np.array(resolution, dtype=np.float64)
    extent = bounds_max - bounds_min
    grid = np.zeros(resolution[::-1], dtype=np.float64)  # (Z, Y, X)

    for pos in positions:
        # Skip out-of-bounds (matching shader: < min or >= max)
        if np.any(pos < bounds_min) or np.any(pos >= bounds_max):
            continue

        # Continuous grid coordinate
        gc = (pos - bounds_min) / extent * res

        # Shift by -0.5 to center on voxels, then floor
        gc_shifted = gc - 0.5
        i0 = np.floor(gc_shifted).astype(int)
        f = gc_shifted - i0

        # 8 corners with trilinear weights
        for dz in (0, 1):
            for dy in (0, 1):
                for dx in (0, 1):
                    ix = i0[0] + dx
                    iy = i0[1] + dy
                    iz = i0[2] + dz

                    # Clamp check
                    if (ix < 0 or ix >= resolution[0] or
                        iy < 0 or iy >= resolution[1] or
                        iz < 0 or iz >= resolution[2]):
                        continue

                    wx = f[0] if dx else (1.0 - f[0])
                    wy = f[1] if dy else (1.0 - f[1])
                    wz = f[2] if dz else (1.0 - f[2])
                    w = wx * wy * wz

                    grid[iz, iy, ix] += w

    return grid.astype(np.float32)


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


def _readback_op(tex, resolution) -> np.ndarray:
    """Read an OP texture back as (Z, Y, X) float32 array."""
    raw = tex.read()
    return np.frombuffer(raw, dtype=np.float32).reshape(resolution[2], resolution[1], resolution[0])


# ------------------------------------------------------------------
# (a) Single particle at voxel center
# ------------------------------------------------------------------
def test_center_particle(ctx: moderngl.Context) -> bool:
    print("\n--- (a) single particle at voxel center ---")
    from volrender import GridParams, VoxelGrid

    res = (8, 8, 8)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1), resolution=res)
    grid = VoxelGrid(ctx, params)

    # Voxel (4,4,4) center in grid coords = (4.5, 4.5, 4.5)
    # In world coords: (4.5/8, 4.5/8, 4.5/8) = (0.5625, 0.5625, 0.5625)
    world_pos = np.array([[0.5625, 0.5625, 0.5625]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, world_pos)
    grid.splat(buf, 1)

    density = _readback_density(grid)
    total = density.sum()

    # The particle is at the exact center of voxel (4,4,4),
    # so all weight should land on that voxel alone.
    center_val = density[4, 4, 4]
    rest = total - center_val

    if not np.isclose(center_val, 1.0, atol=1e-5):
        return _fail(f"center voxel = {center_val}, expected 1.0")
    if not np.isclose(rest, 0.0, atol=1e-5):
        return _fail(f"non-center total = {rest}, expected 0.0")

    return _ok(f"center voxel = {center_val:.6f}, rest = {rest:.6f}")


# ------------------------------------------------------------------
# (b) Single particle on voxel corner -> 8-way split
# ------------------------------------------------------------------
def test_corner_particle(ctx: moderngl.Context) -> bool:
    print("\n--- (b) single particle on voxel corner ---")
    from volrender import GridParams, VoxelGrid

    res = (8, 8, 8)
    bmin = np.array([0, 0, 0], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1), resolution=res)
    grid = VoxelGrid(ctx, params)

    # Place particle at the corner shared by voxels (3,3,3)-(4,4,4).
    # That corner in grid coords is (4.0, 4.0, 4.0).
    # gc_shifted = (3.5, 3.5, 3.5), i0 = (3,3,3), f = (0.5, 0.5, 0.5)
    # -> uniform 1/8 split across 8 voxels.
    # World pos: (4.0/8, 4.0/8, 4.0/8) = (0.5, 0.5, 0.5)
    world_pos = np.array([[0.5, 0.5, 0.5]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, world_pos)
    grid.splat(buf, 1)

    density_gpu = _readback_density(grid)
    density_cpu = cpu_trilinear_splat(world_pos, bmin, bmax, res)

    # Check total
    total = density_gpu.sum()
    if not np.isclose(total, 1.0, atol=1e-4):
        return _fail(f"total weight = {total}, expected 1.0")

    # Check the 8 corner voxels each ~= 0.125
    ok = True
    for dz in (3, 4):
        for dy in (3, 4):
            for dx in (3, 4):
                gpu_val = density_gpu[dz, dy, dx]
                cpu_val = density_cpu[dz, dy, dx]
                if not np.isclose(gpu_val, cpu_val, atol=1e-5):
                    ok = _fail(f"voxel ({dx},{dy},{dz}): GPU={gpu_val:.6f} CPU={cpu_val:.6f}")

    if ok:
        _ok("8-way split matches CPU reference (each ~= 0.125)")
    return ok


# ------------------------------------------------------------------
# (c) Random cloud -> GPU vs CPU reference
# ------------------------------------------------------------------
def test_random_cloud(ctx: moderngl.Context) -> bool:
    print("\n--- (c) random cloud GPU vs CPU ---")
    from volrender import GridParams, VoxelGrid

    res = (16, 16, 16)
    bmin = np.array([-1, -1, -1], dtype=np.float64)
    bmax = np.array([1, 1, 1], dtype=np.float64)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1), resolution=res)
    grid = VoxelGrid(ctx, params)

    rng = np.random.default_rng(123)
    # 500 particles, some deliberately out of bounds
    positions = rng.uniform(-1.5, 1.5, size=(500, 3)).astype(np.float32)

    buf = _make_entity_buffer(ctx, positions)
    grid.splat(buf, len(positions))

    density_gpu = _readback_density(grid)
    density_cpu = cpu_trilinear_splat(positions.astype(np.float64), bmin, bmax, res)

    # Total weight should match
    gpu_total = density_gpu.sum()
    cpu_total = density_cpu.sum()

    # Count in-bounds particles (matching shader: >= min and < max)
    in_bounds = np.all((positions >= bmin) & (positions < bmax), axis=1).sum()

    if not np.isclose(gpu_total, cpu_total, rtol=1e-3):
        return _fail(f"total: GPU={gpu_total:.4f}, CPU={cpu_total:.4f}")

    # Total may be less than in_bounds due to boundary clipping of trilinear
    # corners, but should not exceed it.
    if gpu_total > in_bounds + 0.1:
        return _fail(f"total={gpu_total:.4f} exceeds in_bounds={in_bounds}")

    # Per-voxel comparison
    max_err = np.max(np.abs(density_gpu - density_cpu))
    if max_err > 0.01:
        return _fail(f"max per-voxel error = {max_err:.6f}")

    return _ok(f"total={gpu_total:.1f} (in_bounds={in_bounds}), max_err={max_err:.6f}")


# ------------------------------------------------------------------
# (d) OP spot-check: velocity = +x -> xx mirrors density, others ~= 0
# ------------------------------------------------------------------
def test_op_velocity_x(ctx: moderngl.Context) -> bool:
    print("\n--- (d) OP spot-check: all velocity = +x ---")
    from volrender import GridParams, VoxelGrid

    res = (8, 8, 8)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, splat_outer_product=True)
    grid = VoxelGrid(ctx, params)

    rng = np.random.default_rng(42)
    n = 100
    positions = rng.uniform(0.05, 0.95, size=(n, 3)).astype(np.float32)
    velocities = np.zeros((n, 3), dtype=np.float32)
    velocities[:, 0] = 1.0  # all +x

    buf = _make_entity_buffer(ctx, positions, velocities)
    grid.splat(buf, n)

    density = _readback_density(grid)
    # n = normalize(vel) = (1,0,0) for all
    # -> xx = 1*1 = 1, yy = 0, zz = 0, xy = 0, xz = 0, yz = 0
    # So OP xx should == density, others should be 0.

    op_xx = _readback_op(grid.outer_product[0], res)
    op_yy = _readback_op(grid.outer_product[1], res)
    op_zz = _readback_op(grid.outer_product[2], res)
    op_xy = _readback_op(grid.outer_product[3], res)
    op_xz = _readback_op(grid.outer_product[4], res)
    op_yz = _readback_op(grid.outer_product[5], res)

    ok = True

    # xx should match density
    max_err_xx = np.max(np.abs(op_xx - density))
    if max_err_xx > 1e-4:
        ok = _fail(f"op_xx vs density max_err = {max_err_xx:.6f}")
    else:
        _ok(f"op_xx matches density (max_err={max_err_xx:.6f})")

    # Others should be ~0
    for name, arr in [("yy", op_yy), ("zz", op_zz), ("xy", op_xy), ("xz", op_xz), ("yz", op_yz)]:
        max_val = np.max(np.abs(arr))
        if max_val > 1e-5:
            ok = _fail(f"op_{name} max = {max_val:.6f}, expected ~0")
        else:
            _ok(f"op_{name} ~= 0 (max={max_val:.6f})")

    return ok


# ------------------------------------------------------------------
# (e) VolumeRenderer.splat works (no longer raises)
# ------------------------------------------------------------------
def test_renderer_splat(ctx: moderngl.Context) -> bool:
    print("\n--- (e) VolumeRenderer.splat ---")
    from volrender import VolumeRenderer, GridParams

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=(8, 8, 8), majorant_resolution=(2, 2, 2))
    renderer = VolumeRenderer(ctx, params)

    positions = np.array([[0.5, 0.5, 0.5]], dtype=np.float32)
    buf = _make_entity_buffer(ctx, positions)

    try:
        renderer.splat(buf, 1)
    except NotImplementedError:
        return _fail("VolumeRenderer.splat still raises NotImplementedError")
    except Exception as e:
        return _fail(f"VolumeRenderer.splat raised {type(e).__name__}: {e}")

    # Verify something was splatted
    density = _readback_density(renderer.grid)
    if density.sum() < 0.9:
        return _fail(f"density sum = {density.sum()}, expected ~1.0")
    return _ok(f"VolumeRenderer.splat works, density sum = {density.sum():.4f}")


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
        test_center_particle,
        test_corner_particle,
        test_random_cloud,
        test_op_velocity_x,
        test_renderer_splat,
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
