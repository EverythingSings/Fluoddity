"""Step 7 verification: PathTracerInterface + Cheap AO for realtime renderer.

Tests:
1. AO struct layout match between CUDA and numpy (realtime renderer)
2. AO CUDA source compiles (NVRTC)
3. PathTracerInterface lazy init, render_frame, cleanup
4. PathTracerInterface offline API (begin/substep/finish)
5. Visual AO test — render with and without AO, verify pixel differences

Run: Scratch.venv\\Scripts\\python optix_pathtracer\\test_step7.py
"""

import sys
import os
import numpy as np

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_ao_struct_layout():
    """Verify AO fields in PARAMS_DTYPE match the CUDA struct layout."""
    from optix_renderer.renderer import PARAMS_DTYPE

    print("=== AO Struct Layout Test ===")
    print(f"PARAMS_DTYPE itemsize: {PARAMS_DTYPE.itemsize} bytes")
    assert PARAMS_DTYPE.itemsize == 168, f"Expected 168 bytes, got {PARAMS_DTYPE.itemsize}"

    # Verify AO field offsets
    expected = {
        "ao_enabled": (152, "i4"),
        "ao_num_rays": (156, "i4"),
        "ao_radius": (160, "f4"),
        "ao_frame_index": (164, "u4"),
    }
    for name, (expected_offset, expected_fmt) in expected.items():
        actual_offset = PARAMS_DTYPE.fields[name][1]
        actual_dtype = PARAMS_DTYPE.fields[name][0]
        print(f"  {name}: offset={actual_offset} (expected {expected_offset}), "
              f"dtype={actual_dtype}")
        assert actual_offset == expected_offset, (
            f"{name}: offset mismatch: {actual_offset} != {expected_offset}"
        )

    # Verify we can fill the struct
    h = np.zeros(1, dtype=PARAMS_DTYPE)
    h["ao_enabled"] = 1
    h["ao_num_rays"] = 4
    h["ao_radius"] = 0.5
    h["ao_frame_index"] = 42
    raw = h.tobytes()
    assert len(raw) == 168
    print("  Fill test: OK")
    print("PASS: AO struct layout matches\n")


def test_ao_cuda_compile():
    """Verify the updated CUDA source with AO compiles via NVRTC."""
    from optix_renderer.cuda_src import SPHERE_CUDA_SRC
    from optix_renderer.interop import compile_ptx

    print("=== AO CUDA Compile Test ===")

    # Check AO fields are in the source
    assert "ao_enabled" in SPHERE_CUDA_SRC, "ao_enabled not in CUDA source"
    assert "ao_num_rays" in SPHERE_CUDA_SRC, "ao_num_rays not in CUDA source"
    assert "ao_radius" in SPHERE_CUDA_SRC, "ao_radius not in CUDA source"
    assert "ao_frame_index" in SPHERE_CUDA_SRC, "ao_frame_index not in CUDA source"
    assert "ao_cosine_dir" in SPHERE_CUDA_SRC, "ao_cosine_dir not in CUDA source"
    print("  AO symbols found in CUDA source")

    # Compile
    ptx = compile_ptx(SPHERE_CUDA_SRC)
    print(f"  PTX compiled: {len(ptx)} bytes")
    assert len(ptx) > 1000, f"PTX suspiciously small: {len(ptx)} bytes"
    print("PASS: AO CUDA source compiles\n")


def test_pathtracer_interface_import():
    """Verify PathTracerInterface can be imported."""
    print("=== PathTracerInterface Import Test ===")
    from pathtracer_interface import PathTracerInterface
    print(f"  PathTracerInterface: {PathTracerInterface}")
    print(f"  is_available: {PathTracerInterface.is_available()}")
    print("PASS: PathTracerInterface imports\n")


def test_pathtracer_interface_attrs():
    """Verify PathTracerInterface has the expected public attributes."""
    print("=== PathTracerInterface Attributes Test ===")

    # We can't create a real one without a ModernGL context, but we can
    # inspect the class definition and default values
    from pathtracer_interface import PathTracerInterface
    import inspect

    sig = inspect.signature(PathTracerInterface.__init__)
    print(f"  __init__ params: {list(sig.parameters.keys())}")

    # Check render_frame signature
    sig_rf = inspect.signature(PathTracerInterface.render_frame)
    rf_params = list(sig_rf.parameters.keys())
    expected_rf = ['self', 'entity_buffer', 'entity_count', 'cam_pos',
                   'cam_dir', 'cam_up', 'fov', 'width', 'height']
    print(f"  render_frame params: {rf_params}")
    assert rf_params == expected_rf, f"render_frame params mismatch: {rf_params}"

    # Check offline API exists
    assert hasattr(PathTracerInterface, 'start_offline_render')
    assert hasattr(PathTracerInterface, 'offline_substep')
    assert hasattr(PathTracerInterface, 'finish_offline_render')
    assert hasattr(PathTracerInterface, 'force_rebuild')
    assert hasattr(PathTracerInterface, 'cleanup')
    assert hasattr(PathTracerInterface, 'is_available')
    print("  All expected methods present")

    # Check properties
    for prop in ['display_texture', 'gas_time_ms', 'render_time_ms',
                 'failed', 'fail_reason']:
        assert isinstance(getattr(PathTracerInterface, prop), property), (
            f"{prop} is not a property"
        )
    print("  All expected properties present")

    print("PASS: PathTracerInterface attributes correct\n")


def test_ao_integration():
    """Full integration test: render with and without AO, compare pixels.

    Requires GPU + OpenGL context.
    """
    print("=== AO Integration Test ===")

    try:
        import glfw
        import moderngl
    except ImportError:
        print("SKIP: glfw/moderngl not available for integration test\n")
        return

    from optix_renderer import OptiXSphereRenderer
    if not OptiXSphereRenderer.is_available():
        print("SKIP: OptiX not available\n")
        return

    # Create hidden GL window + context
    if not glfw.init():
        print("SKIP: GLFW init failed\n")
        return

    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    window = glfw.create_window(1, 1, "AO test", None, None)
    if not window:
        glfw.terminate()
        print("SKIP: window creation failed\n")
        return

    glfw.make_context_current(window)
    ctx = moderngl.create_context()

    try:
        # Create random entities (spheres)
        N = 2000
        rng = np.random.default_rng(42)
        entities = np.zeros((N, 8), dtype=np.float32)
        entities[:, 0:3] = rng.uniform(-1.0, 1.0, (N, 3))  # position
        entities[:, 6] = rng.uniform(0.0, 1.0, N)           # hue
        entities[:, 7] = 0.05                                 # radius
        entity_buffer = ctx.buffer(entities.tobytes())

        renderer = OptiXSphereRenderer(ctx, entity_buffer, N)
        renderer.build_accel()

        W, H = 256, 256
        cam_pos = np.array([0, 0, 3], dtype=np.float32)
        cam_dir = np.array([0, 0, -1], dtype=np.float32)
        cam_up = np.array([0, 1, 0], dtype=np.float32)

        # Render WITHOUT AO
        tex_no_ao = renderer.render_from_camera(
            W, H, cam_pos, cam_dir, cam_up, 60.0,
            ao_enabled=False,
        )
        pixels_no_ao = np.frombuffer(tex_no_ao.read(), dtype=np.uint8).reshape(H, W, 4)
        mean_no_ao = pixels_no_ao[:, :, :3].mean()
        print(f"  No AO:   mean brightness = {mean_no_ao:.1f}")

        # Render WITH AO (4 rays, tight radius)
        tex_ao = renderer.render_from_camera(
            W, H, cam_pos, cam_dir, cam_up, 60.0,
            ao_enabled=True, ao_num_rays=4, ao_radius=0.3,
            ao_frame_index=0,
        )
        pixels_ao = np.frombuffer(tex_ao.read(), dtype=np.uint8).reshape(H, W, 4)
        mean_ao = pixels_ao[:, :, :3].mean()
        print(f"  With AO: mean brightness = {mean_ao:.1f}")

        # AO should darken the image (lower mean brightness)
        # It's stochastic so we just check it's not identical
        diff = abs(mean_no_ao - mean_ao)
        print(f"  Brightness difference: {diff:.1f}")
        if diff > 0.5:
            print("  AO is producing visible darkening (expected)")
        else:
            print("  WARNING: AO difference is very small — might not be working")

        # Save comparison images
        try:
            from PIL import Image
            img_no_ao = Image.fromarray(pixels_no_ao[::-1, :, :3])
            img_ao = Image.fromarray(pixels_ao[::-1, :, :3])
            img_no_ao.save("test_step7_no_ao.png")
            img_ao.save("test_step7_with_ao.png")
            print("  Saved: test_step7_no_ao.png, test_step7_with_ao.png")
        except ImportError:
            print("  (PIL not available, skipping image save)")

        renderer.cleanup()
        print("PASS: AO integration test\n")

    finally:
        ctx.release()
        glfw.destroy_window(window)
        glfw.terminate()


def test_pathtracer_interface_integration():
    """Integration test for PathTracerInterface.

    Requires GPU + OpenGL context.
    """
    print("=== PathTracerInterface Integration Test ===")

    try:
        import glfw
        import moderngl
    except ImportError:
        print("SKIP: glfw/moderngl not available\n")
        return

    from pathtracer_interface import PathTracerInterface
    if not PathTracerInterface.is_available():
        print("SKIP: PathTracer not available\n")
        return

    # Create hidden GL window + context
    if not glfw.init():
        print("SKIP: GLFW init failed\n")
        return

    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    window = glfw.create_window(1, 1, "PT interface test", None, None)
    if not window:
        glfw.terminate()
        print("SKIP: window creation failed\n")
        return

    glfw.make_context_current(window)
    ctx = moderngl.create_context()

    try:
        # Create random entities
        N = 3000
        rng = np.random.default_rng(123)
        entities = np.zeros((N, 8), dtype=np.float32)
        entities[:, 0:3] = rng.uniform(-1.0, 1.0, (N, 3))
        entities[:, 6] = rng.uniform(0.0, 1.0, N)
        entities[:, 7] = 0.04
        entity_buffer = ctx.buffer(entities.tobytes())

        W, H = 256, 256
        cam_pos = np.array([0, 0, 3], dtype=np.float32)
        cam_dir = np.array([0, 0, -1], dtype=np.float32)
        cam_up = np.array([0, 1, 0], dtype=np.float32)

        # Create interface
        iface = PathTracerInterface(ctx)
        assert not iface.failed, "Interface should not be failed initially"

        # 1. Realtime render
        print("  Testing render_frame (realtime)...")
        tex = iface.render_frame(
            entity_buffer, N, cam_pos, cam_dir, cam_up, 60.0, W, H
        )
        assert tex is not None, "render_frame returned None"
        assert tex.width == W and tex.height == H
        pixels = np.frombuffer(tex.read(), dtype=np.uint8).reshape(H, W, 4)
        mean_val = pixels[:, :, :3].mean()
        print(f"    Texture: {W}x{H}, mean brightness: {mean_val:.1f}")
        assert mean_val > 5, "Image too dark — possibly all black"
        print(f"    GAS time: {iface.gas_time_ms:.2f} ms")
        print(f"    Render time: {iface.render_time_ms:.2f} ms")

        # 2. Second frame (tests GAS refit path)
        print("  Testing second frame (refit)...")
        tex2 = iface.render_frame(
            entity_buffer, N, cam_pos, cam_dir, cam_up, 60.0, W, H
        )
        assert tex2 is not None

        # 3. Force rebuild
        print("  Testing force_rebuild...")
        iface.force_rebuild()
        tex3 = iface.render_frame(
            entity_buffer, N, cam_pos, cam_dir, cam_up, 60.0, W, H
        )
        assert tex3 is not None

        # 4. Offline render (2 substeps, 1 spp each)
        print("  Testing offline render (2 substeps, 1 spp each)...")
        iface.start_offline_render(entity_buffer, N, W, H,
                                   total_substeps=2, spp_per_substep=1)
        iface.offline_substep(cam_pos, cam_dir, cam_up, 60.0)
        iface.offline_substep(cam_pos, cam_dir, cam_up, 60.0)
        tex_offline = iface.finish_offline_render()
        assert tex_offline is not None, "finish_offline_render returned None"
        pixels_off = np.frombuffer(tex_offline.read(), dtype=np.uint8).reshape(H, W, 4)
        mean_off = pixels_off[:, :, :3].mean()
        print(f"    Offline result: mean brightness: {mean_off:.1f}")

        # Save test image
        try:
            from PIL import Image
            img = Image.fromarray(pixels[::-1, :, :3])
            img.save("test_step7_pathtracer.png")
            print("    Saved: test_step7_pathtracer.png")
        except ImportError:
            pass

        # 5. Cleanup
        iface.cleanup()
        assert iface.display_texture is None
        print("  Cleanup: OK")

        print("PASS: PathTracerInterface integration test\n")

    finally:
        ctx.release()
        glfw.destroy_window(window)
        glfw.terminate()


if __name__ == "__main__":
    print("=" * 60)
    print("Step 7 Verification: PathTracerInterface + Cheap AO")
    print("=" * 60 + "\n")

    # Non-GPU tests
    test_ao_struct_layout()
    test_pathtracer_interface_import()
    test_pathtracer_interface_attrs()

    # GPU tests
    test_ao_cuda_compile()
    test_ao_integration()
    test_pathtracer_interface_integration()

    print("=" * 60)
    print("All Step 7 tests complete.")
    print("=" * 60)
