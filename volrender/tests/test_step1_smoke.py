"""Smoke test for volrender Step 1 scaffold.

Run from project root:
    python -m volrender.tests.test_step1_smoke

Pass = imports clean, context creates at 4.3, dataclass defaults match,
VolumeRenderer instantiates, all method signatures match, all stubs raise
NotImplementedError.
"""
from __future__ import annotations

import inspect
import sys


def _fail(msg: str):
    print(f"  FAIL  {msg}")
    return False


def _ok(msg: str):
    print(f"  OK    {msg}")
    return True


# ------------------------------------------------------------------
# 1. Imports
# ------------------------------------------------------------------
def test_imports() -> bool:
    print("\n--- imports ---")
    try:
        from volrender import (
            GridParams, MediumParams, SunParams, SkyParams, RenderParams,
            VolumeRenderer,
        )
        return _ok("all public names imported")
    except Exception as e:
        return _fail(f"import error: {e}")


# ------------------------------------------------------------------
# 2. Dataclass defaults
# ------------------------------------------------------------------
def test_dataclass_defaults() -> bool:
    print("\n--- dataclass defaults ---")
    from volrender import GridParams, MediumParams, SunParams, SkyParams, RenderParams
    ok = True

    # GridParams — requires bounds_min / bounds_max
    g = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1))
    if g.resolution != (256, 256, 256):
        ok = _fail(f"GridParams.resolution default {g.resolution}")
    if g.majorant_resolution != (32, 32, 32):
        ok = _fail(f"GridParams.majorant_resolution default {g.majorant_resolution}")
    if g.splat_outer_product is not True:
        ok = _fail(f"GridParams.splat_outer_product default {g.splat_outer_product}")

    # MediumParams — all defaults
    m = MediumParams()
    if m.extinction_rgb != (1.0, 1.0, 1.0):
        ok = _fail(f"MediumParams.extinction_rgb default {m.extinction_rgb}")
    if m.albedo_rgb != (0.8, 0.8, 0.8):
        ok = _fail(f"MediumParams.albedo_rgb default {m.albedo_rgb}")
    if m.density_scale != 1.0:
        ok = _fail(f"MediumParams.density_scale default {m.density_scale}")

    # SunParams — requires direction
    s = SunParams(direction=(0, 1, 0))
    if s.color_rgb != (1.0, 0.95, 0.9):
        ok = _fail(f"SunParams.color_rgb default {s.color_rgb}")
    if s.intensity != 3.0:
        ok = _fail(f"SunParams.intensity default {s.intensity}")

    # SkyParams — all defaults
    sk = SkyParams()
    if sk.color_rgb != (0.5, 0.7, 1.0):
        ok = _fail(f"SkyParams.color_rgb default {sk.color_rgb}")
    if sk.intensity != 1.0:
        ok = _fail(f"SkyParams.intensity default {sk.intensity}")

    # RenderParams — all defaults
    r = RenderParams()
    if r.num_samples != 64:
        ok = _fail(f"RenderParams.num_samples default {r.num_samples}")
    if r.batch_spp != 1:
        ok = _fail(f"RenderParams.batch_spp default {r.batch_spp}")
    if r.max_bounces != 0:
        ok = _fail(f"RenderParams.max_bounces default {r.max_bounces}")
    if r.rr_start_depth != 4:
        ok = _fail(f"RenderParams.rr_start_depth default {r.rr_start_depth}")
    if r.seed != 0:
        ok = _fail(f"RenderParams.seed default {r.seed}")

    if ok:
        _ok("all dataclass defaults match spec")
    return ok


# ------------------------------------------------------------------
# 3. Explicit construction
# ------------------------------------------------------------------
def test_dataclass_explicit() -> bool:
    print("\n--- dataclass explicit values ---")
    from volrender import GridParams, MediumParams, SunParams, SkyParams, RenderParams

    try:
        GridParams(
            bounds_min=(-5.0, -5.0, -5.0),
            bounds_max=(5.0, 5.0, 5.0),
            resolution=(128, 128, 128),
            majorant_resolution=(16, 16, 16),
            splat_outer_product=False,
        )
        MediumParams(extinction_rgb=(0.5, 0.6, 0.7), albedo_rgb=(0.9, 0.9, 0.9), density_scale=2.0)
        SunParams(direction=(0.577, 0.577, 0.577), color_rgb=(1, 1, 1), intensity=5.0)
        SkyParams(color_rgb=(0.3, 0.4, 0.5), intensity=0.5)
        RenderParams(num_samples=128, batch_spp=4, max_bounces=8, rr_start_depth=2, seed=42)
        return _ok("all dataclasses accept explicit values")
    except Exception as e:
        return _fail(f"explicit construction error: {e}")


# ------------------------------------------------------------------
# 4. VolumeRenderer instantiation (needs a real GL context)
# ------------------------------------------------------------------
def test_renderer_instantiation() -> bool:
    print("\n--- VolumeRenderer instantiation ---")
    import moderngl
    from volrender import VolumeRenderer, GridParams

    try:
        ctx = moderngl.create_standalone_context(require=430)
    except Exception as e:
        return _fail(f"could not create GL 4.3 standalone context: {e}")

    grid = GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1))
    try:
        renderer = VolumeRenderer(ctx, grid)
    except NotImplementedError:
        return _fail("__init__ should NOT raise NotImplementedError")
    except Exception as e:
        return _fail(f"__init__ raised unexpected error: {e}")

    if renderer.ctx is not ctx:
        return _fail("renderer.ctx not stored")
    if renderer.grid_params is not grid:
        return _fail("renderer.grid_params not stored")

    return _ok("VolumeRenderer instantiates and stores ctx + grid_params")


# ------------------------------------------------------------------
# 5. Method signatures
# ------------------------------------------------------------------
def test_method_signatures() -> bool:
    print("\n--- method signatures ---")
    from volrender import VolumeRenderer
    ok = True

    expected = {
        "__init__":              ["self", "ctx", "grid_params"],
        "splat":                 ["self", "entity_buffer", "entity_count"],
        "reset_accumulation":    ["self"],
        "accumulate":            ["self", "n_spp", "view_proj", "target",
                                  "medium", "sun", "sky", "render"],
        "render_to_completion":  ["self", "view_proj", "target",
                                  "medium", "sun", "sky", "render"],
        "read_frame":            ["self"],
    }

    for name, params in expected.items():
        method = getattr(VolumeRenderer, name, None)
        if method is None:
            ok = _fail(f"missing method: {name}")
            continue
        sig = inspect.signature(method)
        actual = list(sig.parameters.keys())
        if actual != params:
            ok = _fail(f"{name}: expected {params}, got {actual}")
        else:
            _ok(f"{name}{sig}")

    return ok


# ------------------------------------------------------------------
# 6. Stubs raise NotImplementedError
# ------------------------------------------------------------------
def test_stubs_raise() -> bool:
    print("\n--- stubs raise NotImplementedError ---")
    import moderngl
    from volrender import VolumeRenderer, GridParams

    try:
        ctx = moderngl.create_standalone_context(require=430)
    except Exception as e:
        return _fail(f"could not create GL context: {e}")

    renderer = VolumeRenderer(ctx, GridParams(bounds_min=(0, 0, 0), bounds_max=(1, 1, 1)))
    ok = True

    # splat is implemented as of Step 3 — only check remaining stubs
    stub_calls: list[tuple[str, tuple]] = [
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
            _ok(f"{name} raises NotImplementedError")
        except Exception as e:
            ok = _fail(f"{name} raised unexpected {type(e).__name__}: {e}")

    return ok


# ------------------------------------------------------------------
# 7. Module docstring conventions
# ------------------------------------------------------------------
def test_module_docstring() -> bool:
    print("\n--- module docstring ---")
    import volrender
    doc = volrender.__doc__ or ""
    ok = True
    for keyword in ["Entity", "sun", "density", "voxel_volume"]:
        if keyword.lower() not in doc.lower():
            ok = _fail(f"module docstring missing keyword '{keyword}'")
    if ok:
        _ok("module docstring contains entity/sun/density conventions")
    return ok


# ------------------------------------------------------------------
# runner
# ------------------------------------------------------------------
def main():
    tests = [
        test_imports,
        test_dataclass_defaults,
        test_dataclass_explicit,
        test_renderer_instantiation,
        test_method_signatures,
        test_stubs_raise,
        test_module_docstring,
    ]
    results = [(t.__name__, t()) for t in tests]
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
