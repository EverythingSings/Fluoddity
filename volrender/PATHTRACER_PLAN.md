# OptiX/CUDA Path Tracer with AI Denoiser — Staged Implementation Plan

## Context

The project is Fluoddity, a GPU-accelerated 2D particle simulation. The **general-purpose SMs are saturated by particle physics**, so this feature pushes rendering onto **RT cores** (BVH traversal) and **tensor cores** (AI denoiser), leaving SMs for physics.

There is an **existing realtime OptiX renderer** (`optix_renderer/`) that traces a GAS over particle AABBs with single-bounce Lambert shading + shadow rays. There is also an **existing GLSL compute-shader volumetric path tracer** (`volrender/`) that uses dense voxel grids for delta/ratio tracking.

This feature **replaces `volrender`** with a new OptiX/CUDA path tracer that traces the **GAS over particles** (no voxels). The Monte Carlo math and material framework are ported from the GLSL; all volume/voxel machinery is discarded. An OptiX AI denoiser is added for low-spp realtime quality.

**Spec**: `docs/Optix_path_tracer_spec.md`

---

## Architecture

```
optix_pathtracer/                    NEW MODULE
├── __init__.py                      exports PathTracerRenderer
├── renderer.py                      PathTracerRenderer class
├── cuda_src.py                      CUDA C++ device code (Python string, NVRTC-compiled)
└── OPTIX_SYMBOLS.md                 Step 1 investigation results

pathtracer_interface.py              NEW — bridge for host/UI takeover
```

Reuses `optix_renderer/interop.py` for GL-CUDA interop helpers (`register_gl_buffer`, `map_resource`, `unmap_resource`, `compile_ptx`, `aligned_dtype`, `to_device`, `check_cuda`).

---

## Critical Reference Files

| File | Role |
|------|------|
| `optix_renderer/renderer.py` | Template for PathTracerRenderer — GAS build/refit, pipeline/SBT, PBO, render loop |
| `optix_renderer/cuda_src.py` | Template for CUDA device code — intersection, miss, closesthit, float3 math, entity access |
| `optix_renderer/interop.py` | GL-CUDA interop helpers — import directly, no changes |
| `volrender/shaders/pathtrace.comp` | Source for Monte Carlo framework to port — bounce loop, RNG, DOF, RR, NEE, firefly clamp, sky |
| `volrender/shaders/volume_scene.glsl` | Source for BRDF system to port — Lambert, Mirror, Glossy, `sample_brdf`, `eval_brdf_cos` |
| `optix_interface.py` | Template for PathTracerInterface — lazy init, GAS scheduling, error recovery, param sync |
| `tracer_interface.py` | Template for progressive/video/realtime modes |

---

## Step 1: Environment + Binding Reconnaissance

**Goal**: Empirically confirm the `optix` Python module's symbol surface — especially the denoiser API. No code is written.

**Files touched**:
- CREATE `optix_pathtracer/OPTIX_SYMBOLS.md`

**What to do**:
1. Activate `Scratch.venv` and dump `sorted(dir(optix))`.
2. Grep for denoiser symbols (case-insensitive `enoiser`). Record exact Python names for:
   - Denoiser creation (`optixDenoiserCreate` analogue)
   - `DenoiserOptions`, `DenoiserModelKind` enum (look for `DENOISER_MODEL_KIND_HDR`)
   - `denoiserComputeMemoryResources` / `denoiserComputeSizes`
   - `denoiserSetup`, `denoiserInvoke`
   - `DenoiserLayer`, `DenoiserGuideLayer`, `DenoiserParams`
   - `Image2D` descriptor type
   - Guide layer option flags (albedo, normals, flow)
3. Confirm accel-structure calls match the existing realtime renderer (`accelComputeMemoryUsage`, `accelBuild`, `BuildInputCustomPrimitiveArray`, `AccelBuildOptions`, `BUILD_OPERATION_UPDATE`).
4. Confirm `PipelineCompileOptions` supports higher `numPayloadValues` (path tracer needs more than the realtime renderer's 3).
5. **If the denoiser is NOT exposed, STOP and report.** Do not attempt a workaround.

**Testing affordance**: The committed `OPTIX_SYMBOLS.md` file with exact symbol names/signatures.

**State on completion**: Symbol surface is known. No code changes to existing files.

---

## Step 2: Minimal Path Tracer Skeleton

**Goal**: Create `optix_pathtracer/` module with single-bounce Lambert path tracer. Primary rays + sky miss + HDR accumulation buffer + tonemap + PBO output. No denoiser, no bounce loop.

**Files touched**:
- CREATE `optix_pathtracer/__init__.py`
- CREATE `optix_pathtracer/renderer.py`
- CREATE `optix_pathtracer/cuda_src.py`

**Key symbols**:

`PathTracerRenderer` class in `renderer.py`:
- `__init__(ctx, entity_buffer, entity_count, entity_stride=8)` — OptiX context, PTX, pipeline/SBT, stream
- `build_accel(radius_scale)` / `refit_accel(radius_scale)` — GAS build/refit (same logic as `optix_renderer/renderer.py` lines 404-510)
- `render(width, height, eye, U, V, W, ...)` — trace, accumulate, tonemap, PBO→texture
- `render_from_camera(width, height, cam_pos, cam_dir, cam_up, fov_deg, ...)` — convenience wrapper
- `reset_accumulation()` — zero HDR buffer + sample counter
- `_ensure_accum_buffers(width, height)` — CUDA-side `float4` accumulation buffer (+ preallocate albedo/normal guide buffers for Step 5)
- `_ensure_display(width, height)` — PBO + rgba8 texture (same pattern as existing)
- `cleanup()`, `update_entity_buffer()`, `is_available()` — same patterns as existing

`PATHTRACER_CUDA_SRC` string in `cuda_src.py`:
- Extended `Params` struct (accumulation buffer ptr, sample_index, samples_accumulated, exposure, etc.)
- **RNG** — port from `volrender/shaders/common.glsl`: `rng_init(uvec3)`, `next_float()`, `next_float3()`, PCG with `_pcg_advance()`
- **`__raygen__rg()`** — subpixel jitter (port from `pathtrace.comp` lines 582-583), primary ray, single-bounce Lambert, accumulate into `float4` buffer
- **`__miss__radiance()`** — sky gradient (copy from `optix_renderer/cuda_src.py` lines 142-151)
- **`__miss__occlusion()`** — shadow miss (copy from `optix_renderer/cuda_src.py` lines 153-156)
- **`__intersection__sphere()`** — verbatim copy from `optix_renderer/cuda_src.py` lines 159-184
- **`__closesthit__ch()`** — report `primitiveIndex` + `rayTmax` via payloads. Raygen reconstructs P, N, albedo.
- **Tonemap kernel** — separate `__global__`: read accum buffer, divide by sample count, Reinhard + gamma, write uchar4 to PBO with Y-flip
- Float3 math, `hsv2rgb`, entity accessors — copy from existing `optix_renderer/cuda_src.py`

**Pipeline config**: `numPayloadValues=8`, `maxTraceDepth=16`, same `TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_GAS` and `PRIMITIVE_TYPE_FLAGS_CUSTOM`.

**Testing affordance**: Render frozen particle field at 1-16 spp. Expected: Lambert-shaded spheres against sky gradient.

---

## Step 3: Port Monte Carlo Framework + Three Materials

**Goal**: Full bounce loop, Russian roulette, DOF, firefly clamp, and three materials (Lambert, Mirror, Glossy).

**Files touched**:
- MODIFY `optix_pathtracer/cuda_src.py` — major expansion
- MODIFY `optix_pathtracer/renderer.py` — add DOF/material/bounce params

**Port from `volrender/shaders/volume_scene.glsl`**:
- `sample_cosine_hemisphere(n)` = `normalize(n + sample_sphere())` (line 210-212)
- `sample_sphere()` from `volrender/shaders/common.glsl`
- `sample_disk()` from `common.glsl`
- `ior_to_r0(ior)`, `schlick_fresnel(cos_theta, R0)` (lines 219-227)
- `sample_brdf(incident, normal, mat_id, albedo, ior, out_dir)` — adapted from lines 242-267 (explicit mat_id/albedo instead of SDF lookup)
- `eval_brdf_cos(incident, light_dir, normal, mat_id, albedo, ior)` — adapted from lines 278-297

**Port from `volrender/shaders/pathtrace.comp`**:
- Bounce loop (lines 689-850): throughput accumulation, surface interaction branch only (discard media branch)
- Russian roulette (lines 802-807): `p_survive = max(throughput channels)`, clamp `[0.05, 1.0]`
- DOF (lines 596-601): focal point, lens sampling, reoriented ray
- Firefly clamp (lines 853-858): per-sample luminance cap
- `MAX_WALK_BOUNCES = 512` safety cap

**Raygen bounce loop structure**:
```
throughput = (1,1,1), radiance = (0,0,0)
for bounce in 0..512:
    trace primary/bounce ray
    if miss: radiance += throughput * sky; break
    if hit: reconstruct P, N, albedo, mat from prim index
    // (NEE deferred to Step 4)
    depth++; max_bounces check; Russian roulette
    out_dir, weight = sample_brdf(...)
    throughput *= weight
    origin = P + eps*N; dir = out_dir
firefly_clamp(radiance)
accumulate(radiance)
```

**Params additions**: `aperture`, `focal_plane_depth`, `cam_right`, `cam_up`, `max_bounces`, `rr_start_depth`, `firefly_clamp`, `firefly_clamp_max`, `global_material`, `glossy_ior`

**Testing affordance**: Render with each material globally:
1. Lambert (MAT_DIFFUSE=0): soft diffuse spheres
2. Mirror (MAT_MIRROR=2): reflective spheres showing inter-reflections
3. Glossy (MAT_GLOSSY=1): plastic-look with Fresnel
4. Test DOF with non-zero aperture. Verify RR convergence at high spp.

---

## Step 4: Sun NEE + Shadow Rays

**Goal**: Next Event Estimation with binary GAS shadow rays. Adds direct sun lighting.

**Files touched**:
- MODIFY `optix_pathtracer/cuda_src.py` — NEE block in raygen + enhanced sky
- MODIFY `optix_pathtracer/renderer.py` — sun params

**NEE in raygen bounce loop** (port from `pathtrace.comp` lines 820-828, replacing volumetric `transmittance_to_sun` with binary GAS shadow ray):
```c
if (sun_sampling) {
    float3 shadow_origin = P + N * 1e-3f;
    unsigned int occluded = 1u;
    optixTrace(handle, shadow_origin, sun_dir,
        0.0f, 1e16f, 0.0f, mask(255),
        TERMINATE_ON_FIRST_HIT | DISABLE_ANYHIT | DISABLE_CLOSESTHIT,
        0, 0, 1, occluded);  // miss index 1 = occlusion
    if (!occluded) {
        radiance += throughput * eval_brdf_cos(...) * sun_color * sun_intensity;
    }
}
```
Shadow ray pattern: verbatim from `optix_renderer/cuda_src.py` lines 203-218.

**Enhanced sky** — port `get_sky_col()` from `pathtrace.comp` lines 140-151: procedural sky with soft sun glow + photosphere/skybox if CUDA texture is available.

**Params additions**: `sun_direction`, `sun_color`, `sun_intensity`, `sun_sampling`

**Testing affordance**: Render with sun on → visible directional shadows. Toggle sun off → sky-only illumination.

---

## Step 5: Denoiser Integration

**Goal**: OptiX AI denoiser with albedo + normal guide buffers. Non-temporal. Makes 1spp usable.

**Files touched**:
- MODIFY `optix_pathtracer/cuda_src.py` — write guide buffers from first bounce
- MODIFY `optix_pathtracer/renderer.py` — denoiser setup/invoke

**Guide buffers** (written once per pixel, not accumulated):
- `albedo_buffer[pixel]` = primary-hit surface albedo (sky color on miss)
- `normal_buffer[pixel]` = primary-hit world-space normal (neutral on miss)

**Renderer additions**:
- `_setup_denoiser(width, height)` — create denoiser with `DENOISER_MODEL_KIND_HDR` (from Step 1 symbols), guide options (albedo=True, normals=True, flow=False), compute memory, allocate state/scratch, call `denoiserSetup`
- `_run_denoiser(width, height)` — build `Image2D` descriptors for input/albedo/normal/output, `DenoiserGuideLayer`, `DenoiserLayer`, `DenoiserParams`, call `denoiserInvoke`
- Updated render pipeline: trace → accumulate → resolve (divide by N) → **if denoise:** denoise → tonemap from denoised output, **else:** tonemap from resolved HDR

**Params additions**: `denoise_enabled`, `albedo_buffer`, `normal_buffer` pointers

**Testing affordance**:
1. 1spp WITHOUT denoiser: very noisy
2. 1spp WITH denoiser: dramatically cleaner
3. Toggle on/off to see difference
4. Dump guide buffers as images: albedo should show clean primary-hit colors, normals should show smooth sphere normals

---

## Step 6: Motion Blur + Realtime/Offline Split

**Goal**: Two modes from the same code path. Realtime = 1spp + denoise + per-frame refit. Offline = high spp + N mid-frame GAS refits (motion blur) + optional denoise.

**Files touched**:
- MODIFY `optix_pathtracer/renderer.py` — realtime/offline mode API

**New renderer methods**:
- `render_realtime(...)` — reset accum, refit GAS, trace 1spp, denoise (if on), tonemap, PBO
- `render_offline_begin(...)` — reset accum, store target spp/sub-step count
- `render_offline_substep(...)` — refit GAS with new entity positions, trace `spp_per_substep` samples into same HDR buffer (accumulation integrates across time + spp)
- `render_offline_finish(...)` — optional denoise on fully motion-blurred frame, tonemap, PBO

**Motion blur semantics** (from spec §5.4):
- Each sub-step: physics advances → entity buffer updates → GAS refit → trace N samples → accumulate
- All samples go into the same buffer → final resolve divides by total samples across all sub-steps
- Denoise runs **once** at the end on the completed frame, never per-sub-step

**GAS scheduling**: refit every sub-step, periodic rebuild every N frames (user-tunable). N refits per frame in offline mode.

**Testing affordance**:
1. Realtime mode with sim running: clean-ish interactive frames
2. Offline mode: produce motion-blurred frame (streaked particles) vs sharp static frame at same total spp

---

## Step 7: Clean Entry Point + Cheap AO

**Goal**: `PathTracerInterface` for host/UI takeover. Cheap RT-AO for the existing realtime renderer.

**Files touched**:
- CREATE `pathtracer_interface.py`
- MODIFY `optix_renderer/cuda_src.py` — AO rays in closesthit
- MODIFY `optix_renderer/renderer.py` — AO params

### PathTracerInterface

Modeled on `optix_interface.py` and `tracer_interface.py`:
- Lazy initialization, auto-disable on failure
- `render_frame(entity_buffer, entity_count, cam_pos, cam_dir, cam_up, fov, width, height) -> Texture | None` — realtime mode
- `start_offline_render(...)` / `offline_substep(...)` / `finish_offline_render()` — offline mode
- Property-based parameter exposure (spp, denoise, sun, sky, materials, DOF, firefly, GAS scheduling, etc.)
- Entity buffer change detection, GAS scheduling (refit/rebuild cadence)
- Timing properties (`gas_time_ms`, `render_time_ms`, `denoise_time_ms`)

**Note for host/UI work** (documented, not implemented): the host must route the UI's `volrender` entry to this new renderer. The registration/dispatch-site discovery is left to the host-side session.

### Cheap AO for Realtime Renderer

In `optix_renderer/cuda_src.py` `__closesthit__ch()`, after the shadow ray block:
- Fire 1-4 short cosine-hemisphere AO rays with `tmax` clamped to a small world-space radius (20-50x particle radius, tunable)
- Reuse the existing occlusion miss program and terminate-on-first-hit shadow ray setup
- Offset origin along normal (slightly larger epsilon for dense particles)
- Average miss fraction = AO term, multiply into final color
- Hash `launch_index + frame_index + ray_index` for jittered sample direction
- Temporal accumulation: exponential blend on host side, reset on large camera motion

**Params additions**: `ao_enabled`, `ao_num_rays`, `ao_radius`, `ao_frame_index`

**Testing affordance**:
1. AO on: crevices between close particles darken
2. AO off: flat lighting (existing behavior)
3. Adjust `ao_radius`: small = local only, large = more global
4. PathTracerInterface: verify `render_frame()` returns texture, GAS scheduling works, offline mode produces motion blur

---

## Dependency Graph

```
Step 1 (recon) --> Step 2 (skeleton) --> Step 3 (materials) --> Step 4 (sun NEE)
       |                                                               |
       +-- denoiser symbols --> Step 5 (denoiser) --> Step 6 (modes) --> Step 7 (interface + AO)
```

All steps are strictly sequential. The AO portion of Step 7 is conceptually independent of Steps 2-6 but is bundled at the end for convenience.

---

## Verification (End-to-End)

After all steps:
- [ ] Path tracer traces the GAS with three materials (Lambert, tinted-mirror, Fresnel glossy)
- [ ] Sun NEE via binary GAS shadow rays
- [ ] Sky/photosphere miss, DOF, RR, firefly clamp — all ported from tested GLSL math
- [ ] HDR accumulation, optional denoise (non-temporal, albedo+normal guides), tonemap — all CUDA-side
- [ ] Only the finished frame crosses to GL via PBO
- [ ] Realtime mode (1spp + denoise + per-frame refit, periodic rebuild)
- [ ] Offline mode (high spp + motion blur via N mid-frame refits + optional denoise)
- [ ] Denoiser symbol names empirically confirmed in Scratch.venv
- [ ] Realtime OptiX renderer gained cheap tmax-clamped temporally-accumulated AO
- [ ] Clean PathTracerInterface entry point exposed for host/UI takeover
- [ ] No volume/voxel/majorant/delta-tracking code carried into new renderer
