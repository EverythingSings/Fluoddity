# OptiX Python Module Symbol Reconnaissance

**Environment**: `Scratch.venv`, OptiX SDK 9.1, `pyoptix` v0.1.0, `optix.version() = (9, 1, 0)`

**Date**: Step 1 of PATHTRACER_PLAN.md

**Verdict**: All required symbols are exposed. The denoiser API is fully available. Proceed with implementation.

---

## 1. Denoiser API — Confirmed Present

### Creation

```python
denoiser = device_context.denoiserCreate(
    optix.DENOISER_MODEL_KIND_HDR,   # DenoiserModelKind enum
    denoiser_options                  # DenoiserOptions struct
)
```

`DeviceContext.denoiserCreate(model_kind, options) -> Denoiser`

### DenoiserModelKind (enum)

| Symbol | Value | Notes |
|--------|-------|-------|
| `optix.DENOISER_MODEL_KIND_HDR` | HDR | **Use this** — trained on linear HDR radiance |
| `optix.DENOISER_MODEL_KIND_LDR` | LDR | Trained on tonemapped LDR — not what we want |
| `optix.DENOISER_MODEL_KIND_AOV` | AOV | Multi-AOV denoiser |
| `optix.DENOISER_MODEL_KIND_TEMPORAL` | maps to AOV | Temporal mode (NOT USING — per spec §5.6) |
| `optix.DENOISER_MODEL_KIND_TEMPORAL_AOV` | maps to AOV | Temporal AOV (NOT USING) |

### DenoiserOptions

```python
opts = optix.DenoiserOptions()
opts.guideAlbedo = 1   # int: 0 = disabled, 1 = enabled
opts.guideNormal = 1   # int: 0 = disabled, 1 = enabled
# opts.denoiseAlpha    # EXISTS but has binding issue (OptixDenoiserAlphaMode not registered)
#                      # Leave at default (0 = disabled). We don't need alpha denoising.
```

### Denoiser.computeMemoryResources

```python
sizes = denoiser.computeMemoryResources(width, height)
# Returns DenoiserSizes with:
#   sizes.stateSizeInBytes               -- permanent state buffer
#   sizes.withOverlapScratchSizeInBytes   -- scratch with tiled overlap
#   sizes.withoutOverlapScratchSizeInBytes -- scratch without tiled overlap
#   sizes.overlapWindowSizeInPixels       -- overlap window for tiled
```

### Denoiser.setup

```python
denoiser.setup(
    stream,           # CUDA stream handle (int)
    width,            # output width
    height,           # output height
    state_buffer,     # device pointer to state buffer
    state_size,       # stateSizeInBytes
    scratch_buffer,   # device pointer to scratch buffer
    scratch_size      # withoutOverlapScratchSizeInBytes
)
```

7 arguments: `(stream, width, height, state_ptr, state_size, scratch_ptr, scratch_size)`

### Denoiser.invoke

```python
denoiser.invoke(
    stream,           # CUDA stream handle (int)
    params,           # DenoiserParams struct
    state_buffer,     # device pointer to state
    state_size,       # stateSizeInBytes
    guide_layer,      # DenoiserGuideLayer struct
    layer,            # DenoiserLayer struct
    num_layers,       # number of layers (1 for single-layer)
    scratch_buffer,   # device pointer to scratch
    scratch_size,     # withoutOverlapScratchSizeInBytes
    offset_x,         # tile offset X (0 for non-tiled)
    offset_y          # tile offset Y (0 for non-tiled)
)
```

11 arguments: `(stream, params, state_ptr, state_size, guide_layer, layer, num_layers, scratch_ptr, scratch_size, offset_x, offset_y)`

### Denoiser.computeIntensity

```python
denoiser.computeIntensity(
    stream,           # CUDA stream handle
    input_image,      # Image2D of the HDR input
    hdr_intensity,    # device pointer to output float
    scratch_buffer,   # device pointer to scratch
    scratch_size      # scratch size
)
```

### Denoiser.computeAverageColor

```python
denoiser.computeAverageColor(
    stream,           # CUDA stream handle
    input_image,      # Image2D of the HDR input
    avg_color,        # device pointer to output float3
    scratch_buffer,   # device pointer to scratch
    scratch_size      # scratch size
)
```

### DenoiserParams

```python
params = optix.DenoiserParams()
params.blendFactor = 0.0      # 0.0 = full denoise, 1.0 = full noisy
params.hdrIntensity = 0       # device pointer to float (from computeIntensity), or 0 to skip
params.hdrAverageColor = 0    # device pointer to float3 (from computeAverageColor), or 0 to skip
```

### DenoiserLayer

```python
layer = optix.DenoiserLayer()
layer.input = input_image2d            # Image2D: noisy HDR input
layer.output = output_image2d          # Image2D: denoised output
layer.previousOutput = prev_image2d    # Image2D: previous frame (temporal only, NOT USING)
```

### DenoiserGuideLayer

```python
guide = optix.DenoiserGuideLayer()
guide.albedo = albedo_image2d    # Image2D: primary-hit albedo
guide.normal = normal_image2d    # Image2D: primary-hit normal
guide.flow = flow_image2d        # Image2D: motion vectors (temporal only, NOT USING)
```

### Image2D

```python
img = optix.Image2D()
img.data = device_ptr              # int: CUDA device pointer
img.width = 512                    # int: image width in pixels
img.height = 512                   # int: image height in pixels
img.format = optix.PIXEL_FORMAT_FLOAT4   # PixelFormat enum
img.pixelStrideInBytes = 16        # int: bytes between adjacent pixels (0 = tight)
img.rowStrideInBytes = 512 * 16    # int: bytes between rows
```

### PixelFormat values (relevant)

| Symbol | Bytes/pixel | Notes |
|--------|-------------|-------|
| `PIXEL_FORMAT_FLOAT4` | 16 | **Use for accumulation, albedo, normal, denoised output** |
| `PIXEL_FORMAT_FLOAT3` | 12 | Alternative if padding is a concern |
| `PIXEL_FORMAT_HALF4` | 8 | Possible for guides if memory is tight |

---

## 2. Acceleration Structure API — Confirmed Matching Existing Renderer

All symbols used by `optix_renderer/renderer.py` are present and confirmed:

| Symbol | Type | Used for |
|--------|------|----------|
| `optix.BuildInputCustomPrimitiveArray` | class | AABB-based custom primitive input |
| `optix.AccelBuildOptions` | class | Build/refit options |
| `optix.BUILD_FLAG_PREFER_FAST_TRACE` | flag | Optimize for trace speed |
| `optix.BUILD_FLAG_ALLOW_UPDATE` | flag | Allow in-place refit |
| `optix.BUILD_OPERATION_BUILD` | enum | Full BVH build |
| `optix.BUILD_OPERATION_UPDATE` | enum | In-place refit |
| `optix.GEOMETRY_FLAG_DISABLE_ANYHIT` | flag | Skip anyhit programs |
| `DeviceContext.accelComputeMemoryUsage` | method | Compute buffer sizes |
| `DeviceContext.accelBuild` | method | Build/refit the GAS |

### AccelBuildOptions members
- `buildFlags` (int flags)
- `operation` (BuildOperation enum)
- `motionOptions` (MotionOptions)

### BuildInputCustomPrimitiveArray members
- `aabbBuffers` (list of device pointers)
- `numPrimitives` (int)
- `flags` (list of GeometryFlags)
- `numSbtRecords` (int)
- `primitiveIndexOffset`, `sbtIndexOffsetBuffer`, `sbtIndexOffsetSizeInBytes`, `sbtIndexOffsetStrideInBytes`, `strideInBytes`

### AccelBufferSizes members
- `outputSizeInBytes`
- `tempSizeInBytes`
- `tempUpdateSizeInBytes`

---

## 3. Pipeline API — Confirmed Higher Payload Values Supported

```python
pco = optix.PipelineCompileOptions(
    numPayloadValues=8,     # CONFIRMED: accepts values > 3
    numAttributeValues=2,
    # ... other fields same as existing renderer
)
assert pco.numPayloadValues == 8  # PASSED
```

The existing realtime renderer uses `numPayloadValues=3`. The path tracer will use `numPayloadValues=8` (for bounce loop: radiance RGB, hit distance, prim index, etc.). The OptiX SDK max is 32 payload values.

`maxTraceDepth` in `PipelineLinkOptions` also accepts higher values (we'll use 16 for multi-bounce).

---

## 4. Other Confirmed Symbols

| Symbol | Purpose |
|--------|---------|
| `optix.PipelineCompileOptions` | Pipeline configuration |
| `optix.PipelineLinkOptions` | Link options (maxTraceDepth) |
| `optix.ModuleCompileOptions` | Module compile options |
| `optix.ProgramGroupDesc` | Program group descriptor |
| `optix.ShaderBindingTable` | SBT construction |
| `optix.deviceContextCreate` | Create OptiX device context |
| `optix.launch` | Launch OptiX pipeline |
| `optix.sbtRecordPackHeader` | Pack SBT record headers |
| `optix.util.accumulateStackSizes` | Stack size computation |
| `optix.util.computeStackSizes` | Stack size computation |
| `optix.SBT_RECORD_HEADER_SIZE` | SBT alignment constant |
| `optix.SBT_RECORD_ALIGNMENT` | SBT alignment constant |
| `optix.TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_GAS` | GAS-only traversal |
| `optix.PRIMITIVE_TYPE_FLAGS_CUSTOM` | Custom primitive type |
| `optix.EXCEPTION_FLAG_NONE` | No exception checking |
| `optix.COMPILE_DEFAULT_MAX_REGISTER_COUNT` | Default register count |
| `optix.COMPILE_OPTIMIZATION_DEFAULT` | Default optimization |
| `optix.COMPILE_DEBUG_LEVEL_DEFAULT` | Default debug level |

---

## 5. Known Issues / Caveats

1. **`DenoiserOptions.denoiseAlpha`** has a pybind11 binding issue — the `OptixDenoiserAlphaMode` type is not registered. Workaround: leave at default (0 = disabled). We don't need alpha denoising for our use case.

2. **`DENOISER_MODEL_KIND_TEMPORAL` and `DENOISER_MODEL_KIND_TEMPORAL_AOV`** both map to the same enum value as `DENOISER_MODEL_KIND_AOV` in this build. This is fine — we're not using temporal denoising per spec §5.6.

3. **`Denoiser.invoke` signature** has 11 positional arguments. The exact mapping from C API:
   ```
   optixDenoiserInvoke(denoiser, stream, params, denoiserState, denoiserStateSizeInBytes,
                       guideLayer, layers, numLayers, inputOffsetX, inputOffsetY,
                       scratch, scratchSizeInBytes)
   ```
   In Python: `(stream, params, state_ptr, state_size, guide_layer, layer, num_layers, scratch_ptr, scratch_size, offset_x, offset_y)`

4. **`Denoiser.setup` signature** has 7 arguments:
   ```
   (stream, width, height, state_ptr, state_size, scratch_ptr, scratch_size)
   ```

---

## 6. Denoiser Usage Recipe (for Step 5)

```python
import optix
import cupy as cp

# 1. Create denoiser with guide options
opts = optix.DenoiserOptions()
opts.guideAlbedo = 1
opts.guideNormal = 1
denoiser = octx.denoiserCreate(optix.DENOISER_MODEL_KIND_HDR, opts)

# 2. Compute memory requirements
sizes = denoiser.computeMemoryResources(width, height)

# 3. Allocate state and scratch
d_state = cp.cuda.alloc(sizes.stateSizeInBytes)
d_scratch = cp.cuda.alloc(sizes.withoutOverlapScratchSizeInBytes)

# 4. Setup denoiser
denoiser.setup(stream, width, height,
               d_state.ptr, sizes.stateSizeInBytes,
               d_scratch.ptr, sizes.withoutOverlapScratchSizeInBytes)

# 5. Build Image2D descriptors
def make_image2d(ptr, w, h, fmt=optix.PIXEL_FORMAT_FLOAT4, channels=4):
    img = optix.Image2D()
    img.data = ptr
    img.width = w
    img.height = h
    img.format = fmt
    img.pixelStrideInBytes = channels * 4  # float4 = 16 bytes
    img.rowStrideInBytes = w * channels * 4
    return img

input_img = make_image2d(d_resolved.data.ptr, width, height)
output_img = make_image2d(d_denoised.data.ptr, width, height)
albedo_img = make_image2d(d_albedo.data.ptr, width, height)
normal_img = make_image2d(d_normal.data.ptr, width, height)

# 6. Build guide and layer structs
guide = optix.DenoiserGuideLayer()
guide.albedo = albedo_img
guide.normal = normal_img

layer = optix.DenoiserLayer()
layer.input = input_img
layer.output = output_img

# 7. Set params
params = optix.DenoiserParams()
params.blendFactor = 0.0  # full denoise
params.hdrIntensity = 0   # skip intensity computation (or provide d_intensity.ptr)

# 8. Invoke
denoiser.invoke(stream, params,
                d_state.ptr, sizes.stateSizeInBytes,
                guide, layer, 1,
                d_scratch.ptr, sizes.withoutOverlapScratchSizeInBytes,
                0, 0)

# 9. Sync
cudart.cudaStreamSynchronize(stream)
# d_denoised now contains the denoised image
```
