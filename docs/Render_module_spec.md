# Volumetric Point-Cloud Path Tracer — Implementation Spec

A standalone, offline volumetric path-tracing module. Ingests a moderngl buffer of
`Entity` structs, splats them into a dense voxel grid, and path-traces an isotropic
participating medium with colored extinction, single scattering albedo, ratio-tracked
direct sun lighting, and uniform sky illumination via multiple scattering.

This v1 is **isotropic only**. The anisotropic SGGX/microfacet phase function is
deliberately out of scope — but the orientation (outer-product) data is splatted now
so that the later SGGX work is a shading change, not a pipeline change.

---

## How to use this document

This spec is broken into **10 steps**. Each step is sized to fit comfortably in a
single Claude Code agent context window. Hand one step to a fresh agent at a time.

**Agent instructions (applies to every step):**

- Implement only the step you are given. Respect the interfaces, file layout, names,
  and conventions defined in "Global conventions" and in earlier steps — do not
  rename or redesign them.
- At the end of your step, **design the tests** described in that step's "Test design"
  section (write helper scripts, reference implementations, fixtures, etc.), but **do
  not run or verify them**. The human operator executes and verifies all tests between
  steps. Leave clear instructions for how the human runs each test and what a pass
  looks like.
- Where the spec calls for a `COMMENT FLAG`, leave a clearly marked, easy-to-find
  comment (e.g. `# COMMENT FLAG: rr_start_depth — change to cap...`) so the human can
  later tweak that knob without hunting.

---

## Global conventions

**Tech stack.** Python + moderngl. GUI/windowing via imgui_bundle (glfw backend) +
glfw. Compute shaders require an OpenGL **4.3+ core** context. Atomic float operations
require `#extension GL_NV_shader_atomic_float : require` (NVIDIA only; target is an
RTX 5060, so this is fine).

**Entity buffer contract.** The input is a moderngl Buffer of tightly packed structs,
32 bytes / 8 floats each, stride 8 floats:

```
struct Entity {            // offsets in floats
    float px, py, pz;      // 0,1,2  position (world space)
    float vx, vy, vz;      // 3,4,5  velocity (used as orientation for outer product)
    float hue;             // 6      IGNORED in v1 (later: albedo tint)
    float size;            // 7      IGNORED in v1 (later: splat kernel radius)
};
```

Bind this as an SSBO and index it as a **flat `float[]` array** with stride 8
(`base = id*8`) to avoid std430 struct-padding pitfalls. The active entity count is
passed explicitly (the buffer may be larger than the live set).

**Coordinate system & grid.** Right-handed world space (matches the existing camera).
The grid occupies an axis-aligned box `[bounds_min, bounds_max]` supplied as a required
parameter (the caller already maintains a bounded simulation region). Voxel size =
`(bounds_max - bounds_min) / resolution`. Provide GLSL helpers `world_to_grid` /
`grid_to_world` and a Python mirror for tests.

**Density normalization (single convention, used everywhere density is read).**
The splat accumulates raw trilinear weights. Physical density is always interpreted as:

```
physical_density(x) = raw_density(x) / voxel_volume
```

This makes apparent optical thickness resolution-independent (256³ and 512³ render the
same medium at a fixed `density_scale`). Apply it in transport AND in the majorant
build — nowhere else.

**Medium model.**
- `sigma_t_rgb(x) = extinction_rgb * density_scale * physical_density(x)`   (vec3)
- `albedo_rgb` = single-scatter albedo (vec3). Scattering is folded as a throughput
  multiply by `albedo_rgb` at each real collision; absorption is `(1 - albedo)`
  attenuation, handled implicitly by that multiply.
- Isotropic phase function `p = 1/(4π)`; scatter directions sampled uniformly on the
  sphere.

**Sun convention.** `sun.direction` is a **unit vector pointing FROM the scene TOWARD
the sun** (the direction a shadow ray marches). Light arrives along `-sun.direction`.
The sun is **NEE-only** — no visible disk. Sun radiance = `sun.color_rgb * sun.intensity`.

**Sky.** Uniform isotropic environment, `sky.color_rgb * sky.intensity`. **Not** NEE-sampled
(it's uniform); it contributes only through escaped/random-walk rays. A primary ray that
escapes the grid returns the sky as the visible background.

**Transport algorithms.**
- *Free flight:* **weighted (null-scattering) delta tracking** over a per-cell majorant
  via DDA through the coarse majorant grid. Carries an **RGB throughput weight** so
  colored extinction is unbiased. See Step 6 for the exact per-event math.
- *Sun NEE transmittance:* **ratio tracking** (unbiased, RGB) from the scatter vertex
  along `sun.direction` to grid exit. See Step 8.

**RNG.** Hash-based PCG. Seed each sample stream from `(pixel.x, pixel.y, global_sample_index)`;
advance state per draw; mix the bounce index into the stream so bounces decorrelate.
Provide a small GLSL `rng` include with `next_float()` and `next_float3()`.

**Output.** The renderer writes **linear HDR** into a caller-provided moderngl float
texture (assume RGBA16F or RGBA32F). Tonemapping/display is the caller's job. An
optional numpy readback is provided for offline saves.

**Suggested file layout.**

```
volrender/
  __init__.py          # public API re-exports
  params.py            # all dataclasses
  renderer.py          # VolumeRenderer orchestration + public API
  grid.py              # VoxelGrid: allocation, clear, world<->grid, splat dispatch
  majorant.py          # majorant grid build dispatch
  camera.py            # view_proj -> inverse, ray-gen helpers
  shaders/
    common.glsl        # rng, world<->grid, AABB slab, struct access
    splat.comp
    majorant.comp
    pathtrace.comp     # grows across steps 5-9
    resolve.comp       # accumulation -> target
  example/
    demo.py            # capstone harness (Step 10)
  tests/               # agent-authored test helpers & references
```

---

## Step 1 — Module scaffold, dataclasses, public API surface

**Objective.** Stand up the package, all parameter dataclasses, and the
`VolumeRenderer` skeleton with final method signatures (stubs raising
`NotImplementedError`). No GPU work yet. This freezes the public interface so later
steps have stable contracts.

**Deliverables.**

- `params.py` with dataclasses (fields and defaults shown):

```python
@dataclass
class GridParams:
    bounds_min: tuple[float, float, float]              # REQUIRED, world space
    bounds_max: tuple[float, float, float]              # REQUIRED, world space
    resolution: tuple[int, int, int] = (256, 256, 256)
    majorant_resolution: tuple[int, int, int] = (32, 32, 32)
    splat_outer_product: bool = True                    # splat d⊗d now (read later)

@dataclass
class MediumParams:
    extinction_rgb: tuple[float, float, float] = (1.0, 1.0, 1.0)  # per-unit-density, vec3
    albedo_rgb:     tuple[float, float, float] = (0.8, 0.8, 0.8)  # single-scatter albedo
    density_scale:  float = 1.0

@dataclass
class SunParams:
    direction: tuple[float, float, float]               # unit, scene -> sun
    color_rgb: tuple[float, float, float] = (1.0, 0.95, 0.9)
    intensity: float = 3.0

@dataclass
class SkyParams:
    color_rgb: tuple[float, float, float] = (0.5, 0.7, 1.0)
    intensity: float = 1.0

@dataclass
class RenderParams:
    num_samples: int = 64
    batch_spp:   int = 1        # COMMENT FLAG: dispatch granularity (TDR avoidance)
    max_bounces: int = 0        # COMMENT FLAG: 0 = unbounded (RR only)
    rr_start_depth: int = 4     # COMMENT FLAG: Russian roulette onset
    seed: int = 0
```

- `renderer.py` with the `VolumeRenderer` class skeleton:

```python
class VolumeRenderer:
    def __init__(self, ctx: moderngl.Context, grid_params: GridParams): ...
    def splat(self, entity_buffer: moderngl.Buffer, entity_count: int): ...
    def reset_accumulation(self): ...
    def accumulate(self, n_spp: int, view_proj, target,
                   medium: MediumParams, sun: SunParams, sky: SkyParams,
                   render: RenderParams): ...
    def render_to_completion(self, view_proj, target,
                             medium: MediumParams, sun: SunParams, sky: SkyParams,
                             render: RenderParams): ...
    def read_frame(self) -> "np.ndarray": ...   # optional HDR readback (H, W, 4) float32
```

- `__init__.py` re-exporting the dataclasses and `VolumeRenderer`.
- Module docstring restating the Global Conventions (entity layout, sun convention,
  normalization convention).

**Test design (human runs).** Import smoke test: construct each dataclass with defaults
and with explicit values; instantiate `VolumeRenderer` with a real moderngl standalone
context (`moderngl.create_standalone_context(require=430)`); assert all public methods
exist with the documented signatures (`inspect.signature`). Confirm the stubs raise
`NotImplementedError`. Pass = imports clean, context creates at 4.3, signatures match.

---

## Step 2 — Voxel grid allocation, clear, and world↔grid transform

**Objective.** Allocate the GPU grids and implement the coordinate transforms.

**Deliverables.**

- `grid.py` / `VoxelGrid`: allocate a **density** 3D texture (`r32f`) at
  `grid_params.resolution`, with **linear** filtering enabled (transport samples it as
  `sampler3D` for trilinear reconstruction) and clamp-to-edge wrapping.
- If `splat_outer_product`, allocate **6** additional `r32f` 3D textures for the
  symmetric outer-product components in fixed order `[xx, yy, zz, xy, xz, yz]`. (Six
  separate `r32f` images keeps `imageAtomicAdd` indexing uniform; packing into rgba32f
  is a later optimization, not now.)
- A scalar **majorant density** 3D texture (`r32f`) at `majorant_resolution`, nearest
  filtering (populated in Step 4; allocated here).
- `clear()` zeroing all grids (a tiny compute pass or `clear()`/PBO — agent's choice).
- GLSL helpers in `common.glsl`: `vec3 world_to_grid(vec3)`, `vec3 grid_to_world(vec3)`,
  plus the `voxel_volume` and resolution uniforms. Python mirrors for tests.
- VRAM accounting in a docstring: per `r32f` 3D texture = `4 * Nx*Ny*Nz` bytes.
  256³ density+6 OP+majorant ≈ **0.47 GB**; 512³ ≈ **3.75 GB** (fits 8 GB with room).

**Implementation notes.** A moderngl `Texture3D` can be both image-bound (for atomic
writes in the splat) and sampled (in transport). Make sure the density texture is
created so it can be bound as an image (`r32f`) and sampled with linear filtering.

**Test design (human runs).** Allocate at a tiny resolution (e.g. 16³) and at 256³;
log actual VRAM. `clear()` then read back a few slices and assert all zeros. Verify
`world_to_grid`/`grid_to_world` round-trip and that `bounds_min`→(0,0,0) and
`bounds_max`→`resolution` against the Python mirror for a handful of hand-picked points.

---

## Step 3 — Trilinear atomic splat compute shader

**Objective.** Deposit each entity into the grid with trilinear weights; splat the
outer product too (gated by the flag).

**Deliverables.**

- `shaders/splat.comp`: one invocation per entity, dispatch `ceil(count / local_size_x)`.
  - Read position via flat-float SSBO (`base = id*8`). Skip entities outside
    `[bounds_min, bounds_max]`.
  - Compute continuous grid coordinate, derive the 8 surrounding voxel indices and
    trilinear weights (weights sum to 1).
  - `imageAtomicAdd` the weight into **density** for each of the 8 voxels.
  - If `splat_outer_product`: `n = normalize(vec3(vx,vy,vz))`. **Guard zero-length
    velocity** (`length < eps`): contribute density only, skip OP. Otherwise
    `imageAtomicAdd` `weight * (n.x*n.x, n.y*n.y, n.z*n.z, n.x*n.y, n.x*n.z, n.y*n.z)`
    into the 6 OP textures `[xx,yy,zz,xy,xz,yz]`.
  - Header: `#version 430` + `#extension GL_NV_shader_atomic_float : require`.
- `VoxelGrid.splat(entity_buffer, count)` dispatching it (clear first, then splat).
- **Ignore `size` and `hue`.** All entities are point samples in v1.

**Implementation notes.** Trilinear splat is the dual of trilinear sampling — depositing
with the same weights you'll later reconstruct with keeps the medium consistent.
Worst-case atomics/particle = 8 (density) + 48 (OP) = 56; fine for an offline one-time
build over a few million particles.

**Test design (human runs).** Agent provides a CPU/numpy trilinear-splat reference.
Tests: (a) single particle at a voxel center → that voxel = 1, neighbors = 0;
(b) single particle on a voxel corner → 8-way split matches reference; (c) a small
random cloud → GPU density readback matches the CPU reference within float tolerance,
and total deposited weight ≈ entity count (minus any out-of-bounds). (d) Spot-check one
OP channel (e.g. all velocities = +x → `xx` channel mirrors density, others ≈ 0).

---

## Step 4 — Majorant grid build (dilated max-pool)

**Objective.** Populate the coarse scalar majorant density grid used to drive delta
tracking. Store **density only** (medium-independent) so medium edits don't force a
rebuild.

**Deliverables.**

- `shaders/majorant.comp`: one invocation per **coarse cell**. Loop over the fine
  voxels the cell covers in world space, **plus a one-fine-voxel guard band on every
  side**, taking the max of `physical_density` (i.e. `raw / voxel_volume`). Write that
  max into the majorant texture. (Gather-max via a loop avoids needing float atomic-max.)
- `majorant.py` dispatch + an optional global-max scalar (CPU readback once) for
  diagnostics.

**Implementation notes.** The guard band is mandatory for correctness: transport
reconstructs density with trilinear filtering, so a sample near a coarse-cell boundary
can read fine voxels from the neighboring cell. Without the ±1 dilation the stored max
can be a slight *under*-estimate and weighted delta tracking becomes biased. Handle
non-integer resolution ratios by computing the covered fine-voxel range from world-space
cell bounds (floor on the low side, ceil on the high side) before adding the guard band.
At render time, transport derives `mu_bar_cell = max_channel(extinction_rgb) *
density_scale * majorant_density_cell`.

**Test design (human runs).** Agent provides a CPU reference. On a known density field,
assert each coarse cell ≥ the max of every fine voxel it covers **including the guard
band**, and that it's a tight (not wildly inflated) bound. Critical regression check:
sample the trilinearly-filtered density at many random points inside each cell and
assert the sampled value never exceeds that cell's stored majorant.

---

## Step 5 — Primary ray generation, grid AABB, and a debug raymarch

**Objective.** Turn the camera into world rays, clip them to the grid, and validate the
whole front end with a non-stochastic visualization before any path tracing.

**Deliverables.**

- `camera.py`: accept the `view_proj` 4×4 (numpy, = `proj @ view` from
  `compute_fps_view_proj`), invert on the CPU, upload as `inv_view_proj`.
- In `pathtrace.comp` (first version): for pixel `gid.xy` and the target resolution,
  build NDC at the **pixel center** (`[-1,1]`, OpenGL z-range `[-1,1]`). Unproject NDC
  at z=−1 (near) and z=+1 (far) through `inv_view_proj`, perspective-divide → world
  near/far points. Ray origin = near point, dir = `normalize(far - near)`.
- Ray–AABB **slab** intersection against grid bounds → `(t_near, t_far)`; miss → write
  sky background.
- A **debug fixed-step raymarch** mode (toggle uniform): march `[t_near, t_far]` in N
  fixed steps accumulating optical depth `∫ sigma_t_rgb ds`, output either grayscale
  optical depth or `1 - exp(-tau_rgb)` as an alpha-over-sky composite. This is purely
  for validation; the real integrator replaces it in Step 6+.

**Test design (human runs).** Render a known cloud and confirm the silhouette/projection
matches the existing realtime glPoints preview from the **same** `view_proj` (overlay
them). Point the camera away from the box → pure sky. Verify increasing `density_scale`
darkens/thickens the debug image monotonically, and that colored `extinction_rgb`
produces the expected tint in `1 - exp(-tau)`.

---

## Step 6 — Delta-tracked free flight (weighted / null-scattering, RGB)

**Objective.** Implement unbiased free-flight distance sampling for **colored**
extinction, marching the per-cell majorant via DDA.

**Deliverables.** A `sample_free_flight(ray, rng, inout vec3 throughput)` routine that
returns either a real-collision position or "escaped grid", using:

- DDA traversal of the coarse majorant grid. Within a cell with majorant `mu_bar_cell`:
  sample `t = -ln(1 - rng()) / mu_bar_cell`. If `t` overshoots the cell's exit distance,
  advance to the cell boundary and continue in the next cell (no event). Otherwise an
  event occurs at `x`.
- At an event, evaluate `sigma_t_rgb(x)` (trilinear density sample × `extinction_rgb` ×
  `density_scale`). Choose a scalar real-collision probability
  `Pr = clamp(max_channel(sigma_t_rgb) / mu_bar_cell, 0, 1)`.
  - With prob `Pr` → **real collision**: `throughput *= sigma_t_rgb / (mu_bar_cell * Pr)`;
    return the hit.
  - Else → **null collision**: `throughput *= (mu_bar_cell - sigma_t_rgb) /
    (mu_bar_cell * (1 - Pr))`; continue marching.
- Escape when the ray exits the grid AABB with no real collision.

**Implementation notes.** This is the weighted null-scattering estimator; the RGB
throughput weight is what makes chromatic extinction unbiased under a single scalar
decision. Keep the math in one well-commented function — Steps 7–8 build the bounce loop
and NEE around it. Guard `mu_bar_cell == 0` (empty cell → skip to boundary).

**Test design (human runs).** Fill the grid with a **constant** density box (uniform
`sigma_t`). Cast many primary rays straight through and measure the fraction that
produce a real collision before exit; compare to the analytic `1 - exp(-sigma_t * L)`
**per channel** for a colored `extinction_rgb`. Also verify that with `extinction_rgb`
scaled up, mean collisions move correctly, and that the estimator mean is unbiased as
sample count grows. A quick visual mode (real collision → white, escape → sky) should
converge to the correct soft silhouette.

---

## Step 7 — Isotropic scattering + full path loop (multiple scattering, RR)

**Objective.** Assemble the bounce loop with throughput, albedo, Russian roulette, and
sky-lit multiple scattering. (Direct sun comes in Step 8.)

**Deliverables.** The integrator loop per sample:

1. Generate primary ray (Step 5), `throughput = vec3(1)`, `radiance = vec3(0)`,
   `depth = 0`.
2. `sample_free_flight` (Step 6).
   - **Escaped:** add `throughput * sky.color_rgb * sky.intensity` to `radiance`;
     terminate. (A primary escape shows the sky as background; a deeper escape is the
     uniform environment lighting the medium.)
   - **Real collision at x:** `throughput *= albedo_rgb` (absorption folded in). Sample
     a new **uniform-sphere** direction; continue the walk from `x`.
3. `depth += 1`. Apply termination:
   - `COMMENT FLAG: max_bounces` — if `> 0` and `depth >= max_bounces`, terminate.
   - `COMMENT FLAG: rr_start_depth` — past this depth, Russian roulette on
     `max_channel(throughput)`; survivors rescaled by `1/p`.
4. Accumulate `radiance` for this sample.

**Implementation notes.** This is the energy-correctness checkpoint. With no NEE yet,
the medium is lit purely by the environment via random walks — a legitimate image.

**Test design (human runs).** **Furnace test:** set `albedo_rgb = (1,1,1)` and a uniform
sky, no sun. A purely-scattering medium in a uniform environment must converge to the
environment radiance everywhere — the medium should become **invisible** (no darkening,
no brightening) against the sky. This is the single most diagnostic test for the loop.
Then set `albedo_rgb < 1` and confirm uniform darkening. Watch for NaNs and runaway
fireflies (a sign of a bad RR or weight bug).

---

## Step 8 — Ratio-tracked sun NEE + sky background

**Objective.** Add unbiased direct sun lighting with self-shadowing — the headline look.

**Deliverables.**

- A `transmittance_to_sun(x, rng) -> vec3` routine: **ratio tracking** from `x` along
  `sun.direction` to grid exit. Start `T = vec3(1)`; DDA-march by `mu_bar_cell`; at each
  tentative event `T *= (mu_bar_cell - sigma_t_rgb(x')) / mu_bar_cell`; continue to grid
  exit; return `T`. (Unbiased, RGB → naturally colored shadows.)
- At each real scatter vertex (in the Step 7 loop, before sampling the bounce direction),
  add the direct term:
  `radiance += throughput * (1.0/(4.0*PI)) * transmittance_to_sun(x, rng) *
   sun.color_rgb * sun.intensity;`
  (Directional/delta light: no solid-angle pdf, isotropic phase = `1/4π`. `throughput`
  already includes the `albedo_rgb` multiply from the collision.)
- Confirm the sun is **not** added on escaped rays (no visible disk); escapes add sky
  only.

**Implementation notes.** Self-shadowing emerges entirely from the ratio-tracked sun
transmittance. Reuse the DDA traversal from Step 6.

**Test design (human runs).** Visual: single sun on a cloud → bright lit side, soft
self-shadowed dark side; rotating `sun.direction` sweeps the shadow. Quantitative: a thin
homogeneous slab of known thickness `d` → mean `transmittance_to_sun` over many samples
matches `exp(-sigma_t_rgb * d)` **per channel**. Colored check: a reddish `extinction_rgb`
yields shadows tinted toward the complementary absorption (more blue/green removed),
matching `exp(-sigma_t)`.

---

## Step 9 — Progressive accumulation + public API wiring

**Objective.** Wrap the integrator in a progressive accumulator and finish the public
API.

**Deliverables.**

- An HDR **accumulation buffer** (rgba32f image, target resolution) + an integer sample
  counter.
- `reset_accumulation()` — zero the accumulator and counter.
- `accumulate(n_spp, ...)` — dispatch `n_spp` samples (in batches of `render.batch_spp`,
  ~1 spp/dispatch by default to dodge the Windows TDR watchdog on long renders), each
  with seed `hash(pixel, global_sample_index, bounce)`, **adding** into the accumulator;
  advance the counter.
- `render_to_completion(...)` — `reset_accumulation()` then `accumulate` until
  `num_samples`, then run `shaders/resolve.comp` to divide by the counter and write
  **linear HDR** into the caller's `target` texture.
- `read_frame()` — optional readback to `np.ndarray` (H, W, 4) float32.
- All `MediumParams` / `SunParams` / `SkyParams` / `RenderParams` passed as uniforms.
  Verify that changing medium or sun WITHOUT re-splatting works (majorant is density-only).
- `COMMENT FLAG`s preserved/exposed for `batch_spp`, `max_bounces`, `rr_start_depth`,
  `seed`.

**Test design (human runs).** Convergence: render at N and 4N; confirm variance drops
≈4× (noise halves) and the mean image is stable. Confirm `reset_accumulation` actually
resets (no ghosting between renders). Confirm a long render (e.g. 1024 spp at 256³) does
not TDR with default `batch_spp`. Confirm `read_frame` shape/range and absence of NaNs.
Confirm editing `MediumParams`/`SunParams` and re-rendering does **not** require a
re-splat.

---

## Step 10 — Example harness & integration (capstone)

**Objective.** A runnable demo that wires the module to the real camera and a sample
cloud — the acceptance test for the whole module.

**Deliverables.** `example/demo.py`:

- glfw window + moderngl 4.3 core context + imgui_bundle overlay.
- Generate a sample entity buffer in the exact 8-float `Entity` layout (e.g. a couple of
  procedural gaussian blobs / a noisy sphere with some coherent velocity field so the OP
  channels are non-trivial later). Fill `hue`/`size` with placeholder values (unused).
- Use the existing camera's `compute_fps_view_proj(pos, dir, up, fov, aspect)` to get
  `view_proj`.
- Instantiate `VolumeRenderer`, `splat`, `render_to_completion` into an rgba16f target,
  blit/tonemap (simple Reinhard or exposure) the HDR target to the screen.
- imgui controls: `extinction_rgb`, `albedo_rgb`, `density_scale`, sun direction/color/
  intensity, sky color/intensity, `num_samples`; a "re-render" button; a checkbox to
  overlay the realtime glPoints preview for camera/silhouette comparison.
- "Save PNG" (tonemap on export).

**Test design (human runs).** End-to-end acceptance: load the cloud, frame it, render →
expect a clean, self-shadowed isotropic medium with absorption and scattering. Tweak sun
direction → shadows track it. Set a reddish-orange `extinction_rgb` with low `albedo` →
the saturated smoke look. Toggle the glPoints overlay → the volume silhouette aligns with
the point preview under the same camera. No NaNs, converges with more samples, medium/sun
edits re-render without re-splatting.

---

## Out of scope for v1 (deliberately deferred)

- Anisotropic SGGX / microfacet phase function (OP data is splatted but unread).
- `size` (per-particle splat radius) and `hue` (per-particle albedo tint).
- Ground plane / surfaces and surface BRDFs.
- Denoiser.
- Sparse grid (NanoVDB) and LOD.
- RT-core / BVH discrete-glint path.
- Spectral rendering (RGB only).