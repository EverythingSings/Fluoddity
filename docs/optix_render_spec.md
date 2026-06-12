# OptiX Raytraced Sphere Renderer -- Implementation Spec

## Overview

Replace the simple GL_POINTS 3D renderer with an OptiX-based raytracer that renders each entity as a solid sphere using NVIDIA RT cores. Lambert shading with shadow rays gives the particles a physical, solid appearance. The OptiX renderer coexists with GL_POINTS as a selectable option in the 3D Controls window.

**Reference implementation:** `demos/optix_demo.py` demonstrates the full ModernGL <-> OptiX bridge.

### Dependencies

- `pyoptix` (OptiX 9.1 Python bindings)
- `cuda-bindings` (`cuda.bindings.runtime`, `cuda.bindings.nvrtc`)
- `cupy-cuda12x` (GPU array operations for AABB computation)
- OptiX SDK 9.1+ headers (for NVRTC compilation; `OPTIX_PATH` env var or default Windows location)

### Entity Buffer Layout

```
Offset  Field   Used by OptiX
0       px      center.x
1       py      center.y
2       pz      center.z
3       vx      --
4       vy      --
5       vz      --
6       hue     albedo (HSV->RGB)
7       size    sphere radius
```

Stride = 8 floats (32 bytes). SSBO binding 0. Count: ~4M entities.

---

## Step 1 -- Standalone OptiX Sphere Renderer Module

**Goal:** Create `optix_renderer/`, a self-contained module that can render spheres from any GL buffer via OptiX. Testable independently from the main app.

### Files Created

| File | Purpose |
|------|---------|
| `optix_renderer/__init__.py` | Re-exports `OptiXSphereRenderer` |
| `optix_renderer/renderer.py` | Core renderer class |
| `optix_renderer/interop.py` | GL-CUDA interop helpers |
| `optix_renderer/cuda_src.py` | OptiX device code (CUDA C++ string) |

### `OptiXSphereRenderer` API

```python
class OptiXSphereRenderer:
    def __init__(self, ctx, entity_buffer, entity_count, entity_stride=8)
    def build_accel(self)           # Full GAS build
    def refit_accel(self)           # In-place GAS refit
    def render(self, width, height, eye, U, V, W, light_dir) -> moderngl.Texture
    def update_entity_buffer(self, entity_buffer, entity_count)
    def resize(self, width, height) # Recreate PBO/texture for new resolution
    def cleanup(self)
    @staticmethod
    def is_available() -> bool
```

### Key adaptations from demo

- Params struct uses `float* entities` + `uint entity_stride` instead of `float4* spheres`
- Intersection/closest-hit read at `prim * stride + offset` for position, hue, size
- CuPy AABB computation reshapes to `(N, stride)` and indexes columns 0:3, 7
- HSV->RGB albedo from entity hue field (matching `points_3d.frag`)
- Zero-size entity culling (AABB = degenerate, intersection returns immediately)

### Verification

- Create a synthetic 8-float-stride buffer, render, verify spheres appear with correct coloring
- Verify `is_available()` returns False without OptiX packages (no crash)
- Verify GAS build and refit cycle over 100+ frames without crashes

---

## Step 2 -- OptiX Interface Bridge

**Goal:** Create `optix_interface.py` bridging the standalone renderer to Fluoddity's camera system and frame lifecycle.

### Files Created/Modified

| File | Action |
|------|--------|
| `optix_interface.py` | Create -- `OptiXInterface` class (like `tracer_interface.py`) |

### What It Does

- Manages `OptiXSphereRenderer` lifecycle (lazy creation, cleanup)
- Converts ControllerCam (pos, dir, up, fov) to OptiX pinhole basis (eye, U, V, W)
- Implements GAS rebuild/refit scheduling (frame counter + user-controlled interval)
- Handles entity buffer re-registration after world_size changes
- Provides `display_texture` property for the camera rendering path
- GL fence synchronization (`ctx.finish()`) before mapping buffers to CUDA

### Camera Basis Conversion

```python
eye = cam.pos
W = cam.dir  # unit look direction
U = normalize(cross(W, cam.up)) * vlen * aspect
V = normalize(cross(U, W)) * vlen
# where vlen = tan(fov/2)
```

### Verification

- Test harness with mock entity buffer + ControllerCam, render frame, save PNG
- Verify perspective matches GL_POINTS from same viewpoint
- Test GAS rebuild/refit scheduling over 200+ frames

---

## Step 3 -- Integration into Camera + UI Toggle

**Goal:** Wire OptiX into the 3D rendering path as a selectable alternative, with UI controls.

### Files Modified

| File | Changes |
|------|---------|
| `state/camera_state.py` | Add `optix_enabled: bool = False` |
| `state/preferences_state.py` | Add `three_d_optix_enabled`, `three_d_optix_gas_rebuild_interval`, `three_d_optix_sphere_radius_scale` |
| `camera.py` | Add OptiX path in `_generate_3d_view_texture()`, fallback to GL_POINTS |
| `ui/three_d_window.py` | Add OptiX toggle checkbox, GAS rebuild interval slider, sphere scale slider |
| `main.py` | Wire OptiXInterface lifecycle (init, cleanup, preference sync) |

### Rendering Integration

`camera._generate_3d_view_texture()` checks `optix_enabled`:
- If True and OptiX available: call `optix_interface.render_frame()`, blit result into `cam_brush_fbo`
- If False or unavailable: existing GL_POINTS path (unchanged)

Output flows through the existing FrameAssembler for temporal accumulation + gamma.

### UI Controls

- "OptiX Spheres (RTX)" checkbox (greyed out with tooltip if unavailable)
- "GAS Rebuild" slider (1-120 frames)
- "Sphere Scale" slider (0.1-10.0x)

### Verification

- Toggle between GL_POINTS and OptiX, verify both work
- Verify greyed-out checkbox on machines without OptiX
- Verify preferences persist across sessions

---

## Step 4 -- Lighting, Shading, and Visual Quality

**Goal:** Production-quality shading with configurable lighting controls.

### Files Modified

| File | Changes |
|------|---------|
| `optix_renderer/cuda_src.py` | Enhanced shading (configurable ambient, shadow toggle, sky gradient) |
| `optix_interface.py` | Additional lighting parameters |
| `ui/three_d_window.py` | Lighting controls (collapsing header: light direction, shadows, ambient) |
| `state/preferences_state.py` | Lighting preference fields |

### Shading Features

- HSV->RGB coloring matching `points_3d.frag` (hue, S=0.8, V=1.0)
- Configurable directional light (direction, color, intensity)
- Shadow ray toggle (disable for performance)
- Adjustable ambient term
- Sky gradient background
- Zero-size entity culling

### Verification

- Hue coloring matches GL_POINTS rainbow when switching renderers
- Shadow direction responds to light direction slider
- Shadows toggle on/off cleanly

---

## Step 5 -- Build, Performance, and Polish

**Goal:** PyInstaller distribution, error recovery, performance optimization.

### Files Modified

| File | Changes |
|------|---------|
| `Fluoddity.spec` | Hidden imports for cupy, cuda.bindings, optix |
| `build.ps1` | PTX pre-compilation step |
| `requirements.txt` | Add pyoptix, cuda-bindings (version pinned) |
| `optix_renderer/renderer.py` | Pre-compiled PTX loading, CUDA stream, async PBO |
| `optix_interface.py` | Error recovery (auto-disable on crash), timing display |
| `main.py` | Guard OptiX init behind try/except |

### Build Strategy

Pre-compile PTX during build (`compile_ptx.py` script). Renderer loads pre-compiled PTX if available, falls back to runtime NVRTC compilation for development.

### Error Recovery

- Catch OptiX exceptions per-frame, auto-disable `optix_enabled`, fall back to GL_POINTS
- Log reason for OptiX unavailability at startup

### Performance

- Dedicated CUDA stream for OptiX launches
- Timing display in 3D Controls: "GAS refit 1.2ms, render 8.3ms"
- Adaptive GAS rebuild interval suggestion based on entity count

### VRAM Budget (additional)

| Resource | Size |
|----------|------|
| AABB buffer | 96 MB (4M * 24B) |
| GAS (BVH) | ~200-400 MB |
| GAS temp | ~100-200 MB (build only) |
| PBO + texture | ~14 MB (1080p) |
| **Total** | **~430-730 MB** |

### Verification

- PyInstaller build works with OptiX
- Graceful degradation without OptiX (checkbox greyed out, no crash)
- Auto-recovery after OptiX crash
- Memory cleanup on exit
