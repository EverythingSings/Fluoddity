# `instanced_volrender` — Design Specification

**Status:** draft for handoff
**Target:** moderngl, RTX 5060 (compute shaders, float atomics, SSBOs, MRT all assumed available)
**Relationship to existing system:** modify `volrender` in place; keep the public interface broadly identical so the two can later be factored apart by someone else. Extracting common code and building the swap mechanism is explicitly **out of scope** for this task.

---

## 1. Goal

Produce an alternate volume renderer that reuses `volrender`'s voxel splatting + DDA + delta/ratio-tracking path-tracing machinery for **shading**, but replaces primary-ray volume integration with **instanced rasterized billboards** — one soft round "bead" per particle. Each bead is shaded **exactly once per sample** by a path trace through the voxel medium, then all beads are blended into the frame.

The look we want: *a big mass of semi-transparent, isotropically scattering beads, each correctly self-shadowed by the surrounding mass.* A "beady" (discrete) appearance is acceptable and arguably desirable; we are not trying to reproduce a continuous volume.

### Why we expect this to be a win

The current fully-volumetric path tracer is correct and beautiful, but at 512³ it still shows **voxel aliasing along wisps and sharp borders**, because primary visibility is reconstructed by sampling the grid along each eye ray — a hard, high-frequency signal sampled on a coarse lattice.

In `instanced_volrender`, **primary visibility comes from rasterized per-particle geometry at full screen resolution**, not from the grid. The grid is queried only for *shading* — in-scattering and transmittance toward lights — which is low-frequency and diffuse. Undersampling a low-frequency signal produces soft lighting error, not sharp geometric aliasing.

**Consequence (the real coup):** we expect to drop voxel resolution substantially (e.g. 512³ → 128³ or lower) with little perceptible degradation, because the grid no longer carries the sharp edges. The main thing that softens as resolution drops is self-shadow contact detail — treat grid resolution as a quality/perf knob and tune it down aggressively.

---

## 2. What is reused vs. what changes

**Reused unchanged:**
- Voxel grid construction (splatting particles into the grid). Existing rebuild/invalidation rules apply — the grid is reused across frames exactly as today.
- DDA traversal of the grid.
- Delta-tracking / ratio-tracking estimators, phase function (isotropic), light sampling, transmittance estimation.
- HDR accumulation discipline and final tonemap.

**Changed / new:**
- Primary rays from the camera are **gone**. We no longer integrate the medium along the eye ray.
- A new **compute shade-prepass** runs the path trace once per particle and writes a per-particle radiance into a buffer (with progressive accumulation).
- A new **instanced billboard draw** turns each particle into a soft round quad, reads its precomputed color, applies a deterministic kernel alpha, and blends.
- Blending is **order-independent (weighted-blended OIT)** — no per-frame sort.
- SDF occlusion is handled by a **depth prepass + hardware depth test**, gated by the existing *Enable SDF* checkbox.

---

## 3. Pipeline overview

Per displayed frame, in order:

```
(0) Voxel grid           — reuse existing; rebuild only per existing rules
(1) Shade prepass        — COMPUTE: 1 path-trace sample per particle, accumulate
                           running mean radiance into per-particle buffer
(2) SDF depth prepass    — only if Enable SDF: raymarch SDF fullscreen, write gl_FragDepth
(3) Bead composite       — instanced quads, OIT MRT (accum + revealage),
                           depth-test vs (2), depth-write OFF
(4) OIT resolve + tonemap— combine accum/revealage over background, tonemap, present
```

Notes:
- Passes (1) and (3) are decoupled. Shading cost is independent of rasterization. This is what guarantees **once-per-particle** shading and gives us the accumulator for free.
- We do **not** use a geometry shader and do **not** shade in the vertex stage. The expensive work lives in the compute prepass; the vertex shader only does cheap billboard math + a buffer read (the fact that it runs 4× per quad is irrelevant because it isn't doing the path trace).

---

## 4. Pass detail

### 4.1 Shade prepass (compute) — once per particle, with accumulator

One thread per particle. For particle `i`:

1. Seed RNG from `hash(particle_id, sample_index)` so noise is decorrelated across particles and advances cleanly across samples.
2. Run **one** delta/ratio-tracking sample to estimate outgoing radiance `C_i` at the particle (in-scattering + direct lighting + transmittance toward lights through the grid). This is the same estimator as `volrender`, just originated at the particle rather than along an eye ray.
3. Accumulate into a running mean in the per-particle buffer:
   ```
   n        = sampleCount[i] + 1
   mean[i] += (C_i - mean[i]) / n
   sampleCount[i] = n
   ```

`C_i` is **HDR radiance** (may exceed 1). The composite reads `mean[i]`.

**Reset / reproject:** zero `sampleCount` (and optionally `mean`) on camera move, light change, or voxel rebuild — same triggers `volrender` already uses to restart accumulation. Static camera ⇒ samples keep accumulating ⇒ noise falls with no flicker.

> **Why this and not "Monte-Carlo whole frames":** with deterministic alpha and order-independent blending, averaging composited frames and compositing once from per-particle means converge to the same image. The accumulator is strictly cheaper (composite once per *displayed* frame, not once per sample), is robust to output nonlinearity (we average radiance in float *before* tonemap, never after), and we need a per-particle buffer for progressive rendering anyway. So the two "architectures" collapse into one: the accumulator *is* the prepass.

### 4.2 Particle alpha (deterministic, from kernel)

Alpha is **not** Monte-Carlo'd. It is an analytic function of the bead's density kernel and screen-space footprint, computed per-fragment in pass (3). Keeping alpha deterministic is what makes frame-averaging unbiased and keeps compositing linear. Only **radiance** is stochastic.

### 4.3 SDF depth prepass

Only runs if **Enable SDF** is checked.

- Raymarch the SDF scene in a fullscreen pass; on hit, convert hit distance to clip-space depth and write `gl_FragDepth`. (Colour output of this pass is whatever the existing system wants for the opaque scene; at minimum it populates the depth buffer.)
- Then pass (3) draws beads with **depth-test ON, depth-write OFF**, so fragments behind the SDF surface are discarded by the hardware. Occlusion is therefore **per-fragment**, while shading stays **per-particle** — independent concerns, both correct.

When **Enable SDF is unchecked:** skip this pass entirely and run pass (3) with depth-test disabled (or depth cleared to far). We pay nothing for occlusion we didn't ask for — as required.

> **Decision needed:** the depth a bead writes for the *test*. Cheapest and recommended: use the **particle-center** depth for the whole quad (constant per instance, computed in VS). This gives a slightly "carded" intersection with geometry. A truer alternative is a per-fragment imposter depth (treat the disc as a sphere), at extra cost. Start with center depth; revisit only if surface intersections look too flat.

### 4.4 Bead composite (instanced billboards + OIT)

**Geometry:** one base quad (a unit quad, 4 verts as a triangle strip or 6 as two tris), instanced once per particle.

**Vertex shader (cheap, no shading):**
- Read particle position and radius.
- Read `mean[i]` (the shaded HDR color) via `gl_InstanceID` → SSBO/texture-buffer lookup; pass it as a `flat` varying so it is **not** interpolated and is fetched once-per-instance conceptually.
- Build a **camera-facing billboard** (view-space, screen-aligned) sized by the projected radius. Emit the quad corner.
- Also compute the constant center depth for the depth test (see 4.3).

**Kernel / footprint (go cheap):** render each bead as a **flat round soft disc** — a screen-facing quad with a **radial alpha falloff** (Gaussian or `smoothstep`) on `r = length(local_uv)`, `r∈[0,1]`, `alpha=0` outside the unit disc. This is the cheapest option that gives the soft beady look with self-shadowing handled by the grid. We deliberately avoid a full spherical imposter (per-fragment normal + depth) since beads are isotropic scatterers and we accept the approximation. Overdraw scales with on-screen bead area — keep radii modest.

**Fragment shader:**
1. Compute kernel `a = falloff(r)`; `discard` if `a` ~ 0.
2. (Depth test against SDF already applied by hardware if enabled.)
3. Premultiply: `premul = mean_rgb * a`.
4. Write to the two OIT targets (see §5).

### 4.5 OIT resolve + tonemap

Single fullscreen pass that combines the accum + revealage targets over the background, then applies the **existing tonemap** as the very last step (tonemap once, after all averaging/compositing, in float).

---

## 5. Weighted-Blended OIT (the blending math, spelled out)

We use McGuire & Bavoil weighted-blended OIT: order-independent, no sort, approximate. Good fit for fuzzy semi-transparent beads, and it's the deliberate accuracy-for-speed trade we're making.

**Two render targets (MRT), HDR:**
- `accumTex`  : `RGBA16F`, **cleared to (0,0,0,0)**
- `revealTex` : `R16F` (or `R8`), **cleared to 1.0**

**Per-fragment outputs in pass (3)** — with premultiplied color `premul = rgb*a`, alpha `a`, and a depth-based weight `w`:

```glsl
// MRT target 0 (accum):    blend = (GL_ONE, GL_ONE)            → additive
out0 = vec4(premul, a) * w;

// MRT target 1 (revealage): blend = (GL_ZERO, GL_ONE_MINUS_SRC_COLOR)
out1 = a;                    // accumulates product of (1 - a)
```

A workable weight (tune for our depth range / radiance scale):

```glsl
float w = a * clamp(0.03 / (1e-5 + pow(z_view / 200.0, 4.0)), 1e-2, 3e3);
```

Because beads tend to cluster at similar depths, a gentler weight (or near-constant `w = a`) may look better — treat `w` as a tuning knob. Our colors are HDR; the resolve normalizes by accumulated weight so radiance scale is preserved.

**Resolve pass:**

```glsl
vec4  accum     = texture(accumTex, uv);
float revealage = texture(revealTex, uv).r;     // = Π(1 - a_i)
vec3  avgColor  = accum.rgb / max(accum.a, 1e-5);
vec3  outRGB    = mix(background, avgColor, 1.0 - revealage);
// then existing tonemap(outRGB)
```

> Degenerate fallback if beads are treated as purely emissive (no occlusion between beads): plain **additive** blending (`GL_ONE, GL_ONE`) with no revealage target. Mention only; default is weighted-blended.

**Required raster state for pass (3):** blending enabled with the two funcs above, **depth-write OFF**, depth-test ON iff SDF enabled, premultiplied alpha throughout.

---

## 6. Buffers / data layout

- `particle_color_buf` (SSBO): per-particle `vec4` = running-mean radiance (`.a` spare or store sampleCount separately). Read by VS in pass (3), written by compute in pass (1).
- `particle_samplecount_buf` (SSBO or packed): per-particle accumulation counter.
- `accumTex` (RGBA16F), `revealTex` (R16F) for OIT.
- Scene depth buffer (written by SDF prepass when enabled).
- Voxel grid: existing structure, untouched.

(Particle positions/radii presumably already live in a buffer the current system uses for the GL-points renderer — reuse it.)

---

## 7. Interface / form factor

Keep the public surface of `volrender` so the future swap is mechanical:

- **Inputs:** same particle buffer, lights, camera, voxel grid (+ existing rebuild rules), and the same control toggles. In particular **Enable SDF** behaves exactly as described in §4.3.
- **Outputs:** an HDR frame that goes through the same tonemap/present path.
- **Accumulation control:** reuse the existing "restart accumulation on camera/scene change" hooks to reset the per-particle accumulator.

Anything that doesn't map cleanly (e.g. primary-ray sample counts) should keep the same name/role where it makes sense (now driving the per-particle prepass instead).

---

## 8. Tuning knobs (call these out in the implementation)

- **Voxel resolution** — expected to drop hard vs. the volumetric renderer; main visible cost is softened self-shadow contact.
- **Bead radius / screen footprint** — look vs. overdraw.
- **Kernel falloff** (Gaussian vs smoothstep, sharpness) — beadiness.
- **OIT weight function `w(z,a)`** — ordering fidelity for clustered depths.
- **Samples-per-frame in the prepass** — convergence speed vs. frame time.
- **Center-depth vs imposter-depth** for SDF intersection.

---

## 9. Honest caveats

1. **Not pixel-identical to the volumetric path tracer, by design.** Shading (in-scattering, self-shadowing, lighting) is physically grounded and reuses the full rig. But primary visibility is now **discrete alpha-composited splats**, and ordering is the **OIT approximation** — a different, more approximate eye-ray integral than the original transmittance march. This is the intended trade. Don't expect a reference match; expect the aliasing to go away.
2. **OIT is approximate ordering.** For near-emissive / low-opacity beads it's invisible; for high-opacity overlapping beads with strong depth separation it can mis-weight. If it ever looks wrong, the escalation path is a real per-frame depth sort (à la 3D Gaussian splatting) — explicitly *not* in this task.
3. **Low grid resolution softens self-shadowing**, since shadow/contact detail is the one sharp thing still read from the grid. Tune to taste.

---

## 10. Out of scope (for the next Claude)

- Factoring the shared splat/DDA/tracking code out of `volrender`.
- The runtime swap mechanism between `volrender` and `instanced_volrender`.
- Per-frame depth sorting / sorted OIT, unless weighted-blended proves inadequate.