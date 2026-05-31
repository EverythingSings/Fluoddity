"""Tests for volrender Step 2 — voxel grid allocation, clear, and transforms.

Run from project root:
    python -m volrender.tests.test_step2_grid

Tests:
 1. Allocate at 16^3 and 256^3, log VRAM.
 2. clear() then read back slices and assert all zeros.
 3. world_to_grid / grid_to_world round-trip.
 4. Boundary mapping: bounds_min->(0,0,0), bounds_max->resolution.
 5. VolumeRenderer.__init__ no longer raises (creates grid).
 6. Step 1 stubs still raise NotImplementedError.
"""
from __future__ import annotations

import sys
import struct

import numpy as np
import moderngl


def _fail(msg: str):
    print(f"  FAIL  {msg}")
    return False


def _ok(msg: str):
    print(f"  OK    {msg}")
    return True


def _vram_bytes(res: tuple[int, int, int], n_textures: int = 1) -> int:
    return 4 * res[0] * res[1] * res[2] * n_textures


# ------------------------------------------------------------------
# 1. Allocation at 16^3 and 256^3
# ------------------------------------------------------------------
def test_allocation_small(ctx: moderngl.Context) -> bool:
    print("\n--- allocation 16^3 ---")
    from volrender import GridParams, VoxelGrid

    res = (16, 16, 16)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(4, 4, 4))
    grid = VoxelGrid(ctx, params)

    # Density
    if grid.density.size != (16, 16, 16):
        return _fail(f"density size {grid.density.size}, expected (16,16,16)")

    # Outer-product (6 textures)
    if len(grid.outer_product) != 6:
        return _fail(f"outer_product count {len(grid.outer_product)}, expected 6")
    for i, tex in enumerate(grid.outer_product):
        if tex.size != (16, 16, 16):
            return _fail(f"OP[{i}] size {tex.size}")

    # Majorant
    if grid.majorant.size != (4, 4, 4):
        return _fail(f"majorant size {grid.majorant.size}, expected (4,4,4)")

    density_vram = _vram_bytes(res)
    op_vram = _vram_bytes(res, 6)
    maj_vram = _vram_bytes((4, 4, 4))
    total = density_vram + op_vram + maj_vram
    print(f"  INFO  16^3 VRAM: density={density_vram} + OP={op_vram} + maj={maj_vram} = {total} bytes ({total/1024:.1f} KB)")
    return _ok("16^3 allocation correct")


def test_allocation_256(ctx: moderngl.Context) -> bool:
    print("\n--- allocation 256^3 ---")
    from volrender import GridParams, VoxelGrid

    res = (256, 256, 256)
    params = GridParams(bounds_min=(-1, -1, -1), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(32, 32, 32))
    grid = VoxelGrid(ctx, params)

    if grid.density.size != (256, 256, 256):
        return _fail(f"density size {grid.density.size}")
    if len(grid.outer_product) != 6:
        return _fail(f"OP count {len(grid.outer_product)}")
    if grid.majorant.size != (32, 32, 32):
        return _fail(f"majorant size {grid.majorant.size}")

    density_vram = _vram_bytes(res)
    op_vram = _vram_bytes(res, 6)
    maj_vram = _vram_bytes((32, 32, 32))
    total = density_vram + op_vram + maj_vram
    print(f"  INFO  256^3 VRAM: density={density_vram/1e6:.0f} MB + OP={op_vram/1e6:.0f} MB + maj={maj_vram/1e3:.0f} KB = {total/1e6:.0f} MB")
    return _ok("256^3 allocation correct")


def test_no_outer_product(ctx: moderngl.Context) -> bool:
    print("\n--- allocation without outer product ---")
    from volrender import GridParams, VoxelGrid

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=(16, 16, 16), majorant_resolution=(4, 4, 4),
                        splat_outer_product=False)
    grid = VoxelGrid(ctx, params)

    if len(grid.outer_product) != 0:
        return _fail(f"OP count {len(grid.outer_product)}, expected 0 when disabled")
    return _ok("no OP textures when splat_outer_product=False")


# ------------------------------------------------------------------
# 2. Clear and readback
# ------------------------------------------------------------------
def test_clear_readback(ctx: moderngl.Context) -> bool:
    print("\n--- clear + readback ---")
    from volrender import GridParams, VoxelGrid

    res = (8, 8, 8)
    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=res, majorant_resolution=(2, 2, 2))
    grid = VoxelGrid(ctx, params)

    # Read back entire density texture
    data = grid.density.read()
    n_voxels = res[0] * res[1] * res[2]
    values = struct.unpack(f'{n_voxels}f', data)
    if any(v != 0.0 for v in values):
        return _fail("density not all zeros after init")

    # Check OP textures
    for i, tex in enumerate(grid.outer_product):
        data = tex.read()
        values = struct.unpack(f'{n_voxels}f', data)
        if any(v != 0.0 for v in values):
            return _fail(f"OP[{i}] not all zeros after init")

    # Check majorant
    maj_voxels = 2 * 2 * 2
    data = grid.majorant.read()
    values = struct.unpack(f'{maj_voxels}f', data)
    if any(v != 0.0 for v in values):
        return _fail("majorant not all zeros after init")

    return _ok("all grids zero after clear")


# ------------------------------------------------------------------
# 3. Coordinate round-trip
# ------------------------------------------------------------------
def test_coordinate_roundtrip(ctx: moderngl.Context) -> bool:
    print("\n--- coordinate round-trip ---")
    from volrender import GridParams, VoxelGrid

    params = GridParams(bounds_min=(-2.0, -3.0, -1.0), bounds_max=(4.0, 5.0, 7.0),
                        resolution=(64, 128, 32))
    grid = VoxelGrid(ctx, params)

    rng = np.random.default_rng(42)
    # Random world points inside bounds
    world_pts = rng.uniform(
        low=params.bounds_min,
        high=params.bounds_max,
        size=(100, 3),
    ).astype(np.float32)

    grid_pts = grid.world_to_grid(world_pts)
    world_back = grid.grid_to_world(grid_pts)

    if not np.allclose(world_pts, world_back, atol=1e-5):
        max_err = np.max(np.abs(world_pts - world_back))
        return _fail(f"round-trip error {max_err}")

    return _ok("world->grid->world round-trip within 1e-5")


# ------------------------------------------------------------------
# 4. Boundary mapping
# ------------------------------------------------------------------
def test_boundary_mapping(ctx: moderngl.Context) -> bool:
    print("\n--- boundary mapping ---")
    from volrender import GridParams, VoxelGrid

    params = GridParams(bounds_min=(-1.0, -2.0, -3.0), bounds_max=(5.0, 4.0, 3.0),
                        resolution=(100, 200, 50))
    grid = VoxelGrid(ctx, params)

    bmin = np.array(params.bounds_min, dtype=np.float32)
    bmax = np.array(params.bounds_max, dtype=np.float32)
    res = np.array(params.resolution, dtype=np.float32)
    ok = True

    g_min = grid.world_to_grid(bmin)
    if not np.allclose(g_min, [0, 0, 0], atol=1e-6):
        ok = _fail(f"bounds_min -> grid = {g_min}, expected [0,0,0]")

    g_max = grid.world_to_grid(bmax)
    if not np.allclose(g_max, res, atol=1e-4):
        ok = _fail(f"bounds_max -> grid = {g_max}, expected {res}")

    # Midpoint
    mid = (bmin + bmax) / 2.0
    g_mid = grid.world_to_grid(mid)
    if not np.allclose(g_mid, res / 2.0, atol=1e-4):
        ok = _fail(f"midpoint -> grid = {g_mid}, expected {res/2}")

    if ok:
        _ok("bounds_min->(0,0,0), bounds_max->resolution, midpoint->res/2")
    return ok


# ------------------------------------------------------------------
# 5. Voxel volume
# ------------------------------------------------------------------
def test_voxel_volume(ctx: moderngl.Context) -> bool:
    print("\n--- voxel volume ---")
    from volrender import GridParams, VoxelGrid

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(6.0, 4.0, 2.0),
                        resolution=(60, 40, 20))
    grid = VoxelGrid(ctx, params)

    # voxel_size = (6/60, 4/40, 2/20) = (0.1, 0.1, 0.1)
    # voxel_volume = 0.001
    expected = 0.1 * 0.1 * 0.1
    if not np.isclose(grid.voxel_volume, expected, rtol=1e-6):
        return _fail(f"voxel_volume = {grid.voxel_volume}, expected {expected}")
    return _ok(f"voxel_volume = {grid.voxel_volume}")


# ------------------------------------------------------------------
# 6. VolumeRenderer creates grid
# ------------------------------------------------------------------
def test_renderer_creates_grid(ctx: moderngl.Context) -> bool:
    print("\n--- VolumeRenderer creates grid ---")
    from volrender import VolumeRenderer, GridParams, VoxelGrid

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=(16, 16, 16), majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)

    if not hasattr(renderer, 'grid'):
        return _fail("renderer has no 'grid' attribute")
    if not isinstance(renderer.grid, VoxelGrid):
        return _fail(f"renderer.grid is {type(renderer.grid)}, expected VoxelGrid")
    return _ok("VolumeRenderer.__init__ creates VoxelGrid")


# ------------------------------------------------------------------
# 7. Step 1 stubs still raise
# ------------------------------------------------------------------
def test_stubs_still_raise(ctx: moderngl.Context) -> bool:
    print("\n--- Step 1 stubs still raise ---")
    from volrender import VolumeRenderer, GridParams

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=(16, 16, 16), majorant_resolution=(4, 4, 4))
    renderer = VolumeRenderer(ctx, params)
    ok = True

    # splat is implemented as of Step 3 — only check remaining stubs
    stub_calls = [
        ("reset_accumulation", ()),
        ("accumulate", (1, None, None, None, None, None, None)),
        ("render_to_completion", (None, None, None, None, None, None)),
        ("read_frame", ()),
    ]
    for name, args in stub_calls:
        try:
            getattr(renderer, name)(*args)
            ok = _fail(f"{name} did not raise")
        except NotImplementedError:
            _ok(f"{name} still raises NotImplementedError")
        except Exception as e:
            ok = _fail(f"{name} raised {type(e).__name__}: {e}")
    return ok


# ------------------------------------------------------------------
# 8. Texture filter modes
# ------------------------------------------------------------------
def test_filter_modes(ctx: moderngl.Context) -> bool:
    print("\n--- texture filter modes ---")
    from volrender import GridParams, VoxelGrid

    params = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1),
                        resolution=(8, 8, 8), majorant_resolution=(2, 2, 2))
    grid = VoxelGrid(ctx, params)
    ok = True

    # Density should be linear
    if grid.density.filter != (moderngl.LINEAR, moderngl.LINEAR):
        ok = _fail(f"density filter = {grid.density.filter}, expected LINEAR")
    else:
        _ok("density filter is LINEAR")

    # Majorant should be nearest
    if grid.majorant.filter != (moderngl.NEAREST, moderngl.NEAREST):
        ok = _fail(f"majorant filter = {grid.majorant.filter}, expected NEAREST")
    else:
        _ok("majorant filter is NEAREST")

    # OP textures should be linear
    for i, tex in enumerate(grid.outer_product):
        if tex.filter != (moderngl.LINEAR, moderngl.LINEAR):
            ok = _fail(f"OP[{i}] filter = {tex.filter}, expected LINEAR")

    if ok and grid.outer_product:
        _ok("OP textures filter is LINEAR")
    return ok


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
        test_allocation_small,
        test_allocation_256,
        test_no_outer_product,
        test_clear_readback,
        test_coordinate_roundtrip,
        test_boundary_mapping,
        test_voxel_volume,
        test_renderer_creates_grid,
        test_stubs_still_raise,
        test_filter_modes,
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
