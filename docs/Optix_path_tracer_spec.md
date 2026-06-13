# Feature Spec: OptiX/CUDA Path Tracer with AI Denoiser

**Audience:** the Claude Code agent that will implement this.
**Status:** specification. Do not start coding until you have produced the staged plan described in §0.

---

## 0. Your first job: produce a staged plan (do this before any code)

This is a large feature. Before writing any implementation code, produce a **5–7 step plan** where:

- Each step is scoped to fit comfortably inside a single context window (you will likely be compacted or restarted between steps, so each step must leave the tree in a known, documented state).
- Each step ends with a **light testing affordance** — something runnable or visually inspectable that confirms the step worked before the next step builds on it. "Light" means a screenshot-able render, a printed buffer checksum, a `dir(optix)` dump, a single-pixel sanity trace — not a full test harness.
- Each step names the files it will touch and the symbols it expects to add.
- The plan explicitly defers the host/UI integration wiring (see §7) — that is out of scope for you beyond exposing a clean entry point.

Write the plan to `volrender/PATHTRACER_PLAN.md` and stop for review before proceeding. Suggested decomposition (adjust as you see fit):

1. Environment + binding reconnaissance (venv, OptiX symbol hunt, denoiser symbol confirmation). Pure investigation, no renderer code. Testing affordance: a committed notes file listing exact symbol names/signatures.
2. Minimal OptiX/CUDA path-tracer skeleton tracing the GAS with a single material (Lambert), primary ray + sky miss, accumulation buffer, no denoiser. Testing affordance: a static render of the particle field with flat Lambert shading.
3. Port the Monte Carlo framework + three materials from the existing GLSL (see §4). Testing affordance: side-by-side of the three materials on a test scene.
4. Sun NEE + shadow rays through the GAS. Testing affordance: render with visible shadows; toggle sun on/off.
5. Denoiser integration with albedo + normal guide buffers. Testing affordance: 1spp noisy vs. denoised toggle.
6. Motion-blur accumulation (mid-frame refits) + the realtime/offline mode split. Testing affordance: an offline high-spp motion-blurred frame and a realtime 1spp+denoise frame from the same code path.
7. Clean entry-point exposure for host/UI takeover (§7) + the separate cheap-AO addition to the *realtime* renderer (§8).

---

## 1. Context and motivation

The project is an SPH-style fluid simulation. **The general-purpose SMs are saturated by particle physics.** The entire architectural thrust of this feature is to push as much rendering work as possible onto the **RT cores** (BVH traversal) and the **tensor cores / AI denoiser**, leaving the SMs for physics.

There is an **existing realtime OptiX renderer** (the design it is based on is the `moderngl` + CUDA/GL interop + OptiX custom-AABB-sphere model: a GL buffer of particles is registered with CUDA, a GAS is built/refit over per-particle AABBs each frame, and OptiX traces directly into a GL PBO). This new path tracer **coexists** with that realtime renderer and **replaces `volrender`** in the UI.

The thing being replaced is a **GLSL compute-shader volumetric path tracer** (`volrender/shaders/pathtrace.comp`) that used a dense voxel grid + coarse majorant grid for delta/ratio tracking. **We are deleting that acceleration approach.** The medium is no longer voxelized; scene navigation is done by tracing the **OptiX GAS over the particles** with the RT cores. Keep the *Monte Carlo math and material framework* from the GLSL; discard the *volume/tracking machinery*.

### Division of labor (keep this in mind)

- **GL / SMs:** physics (SPH), owns the particle buffer, owns the final display and save-to-video path.
- **RT cores:** all scene navigation — GAS build/refit/traverse, primary rays, shadow rays, bounce rays.
- **Tensor cores:** the OptiX AI denoiser.
- **CUDA-GL bridge:** physics produces particle positions in a GL buffer → registered with CUDA → GAS built over it → path traced entirely CUDA-side → only the *final, completed, tonemapped frame* crosses back to GL for display/recording.

---

## 2. Environment (read this before running anything)

- **The project venv is `Scratch.venv`.** Every Python invocation — symbol inspection, test scripts, the renderer itself — must run inside it. Do not use system Python. Activate it for every command.
- OptiX SDK 9.x headers are required for NVRTC compilation of device code (the existing model resolves them via `OPTIX_PATH` → `include`). Reuse that include-resolution logic.
- Device code is compiled at runtime with NVRTC, same as the existing realtime renderer. You are writing CUDA `.cu` device code (raygen / miss / closesthit / intersection programs), not GLSL, for the new renderer.

### 2.1 Binding/symbol reconnaissance (Step 1 of your plan)

The `optix` Python module is **version-specific** and the binding surface is the one thing in this spec that must be empirically confirmed rather than assumed. Before designing against any OptiX host call:

- Run `Scratch.venv/bin/python -c "import optix; print('\n'.join(sorted(dir(optix))))"` and capture the full symbol list.
- **Confirm the denoiser is exposed.** The OptiX AI denoiser is part of the host API, so complete bindings should surface it, but confirm the exact casing/signatures. Grep the symbol dump for `enoiser` (case-insensitive partial to catch `Denoiser`/`denoiser`). You are looking for the analogues of: `optixDenoiserCreate`, `OptixDenoiserOptions`, `OptixDenoiserModelKind`, `denoiserComputeMemoryResources`, `denoiserSetup`, `denoiserInvoke`, `OptixDenoiserLayer`, `OptixDenoiserGuideLayer`, `OptixDenoiserParams`, and the `OptixImage2D` descriptor type. Record the **exact** Python names and constructor signatures you find — do not code against the C names from memory.
- Confirm the accel-structure calls you'll reuse from the realtime renderer (`accelComputeMemoryUsage`, `accelBuild`, the `BuildInputCustomPrimitiveArray` / `AccelBuildOptions` shapes, `BUILD_OPERATION_UPDATE` for refits) exist in this build's surface.
- If the denoiser is **not** exposed in this build's `optix` module, STOP and report. Do not attempt a workaround silently; the whole AI-denoise leg of the feature depends on it and the fallback (a hand-written À-Trous/SVGF spatial filter in CUDA) is a different, larger task that needs sign-off.

Write findings to the notes file from plan Step 1.

---

## 3. What to reuse vs. discard from the existing code

Two source files are your reference material. **Both are GLSL.** You are porting the reusable parts to CUDA device code, not calling them.

### 3.1 `volrender/shaders/pathtrace.comp`

**REUSE (port to CUDA device code, preserving the math):**

- The RNG: `rng_init(uvec3)`, `next_float()`, `next_float3()` and the per-sample seeding by `(pixel, sample_index)`. This is well-tested; replicate its behavior.
- Subpixel jitter for free AA (`uv = (pixel + (next_float(), next_float())) / size`).
- Depth-of-field block (lens sampling via `sample_disk()`, focal plane, camera right/up). Keep it; it's orthogonal to the volume removal.
- The **bounce-loop structure** for surfaces: the random walk, throughput accumulation, **Russian roulette** (`rr_start_depth`, `p_survive = max channel of throughput`, clamp `[0.05, 1.0]`, divide on survival), `max_bounces` termination, and `MAX_WALK_BOUNCES` safety cap.
- **Sun NEE structure** for surfaces: offset shadow origin along the normal, test occlusion toward `u_sun_direction`, accumulate `throughput * brdf_cos * T * sun_color * sun_intensity`. **Replace** the volumetric `transmittance_to_sun` (ratio tracking) with a **binary GAS shadow ray** — opaque particle occlusion, terminate-on-first-hit, exactly like the realtime renderer's shadow ray. No transmittance integration; particles are opaque surfaces now.
- **Per-sample firefly clamp** (`firefly_clamp`, `firefly_clamp_max`, clamp by luminance). Keep it; it matters more at low spp + denoise.
- Subpixel/sample accumulation semantics (`write_output` / `img_accum` / `u_accumulate`) — but the buffer moves CUDA-side (see §5).
- `get_sky_col` / procedural sky + photosphere skybox sampling + `SRGBToLinear`. Keep as the miss-program radiance.

**DISCARD (do not port — this is the volume machinery the GAS replaces):**

- `sample_free_flight` (delta tracking), `transmittance_to_sun` (ratio tracking), `sigma_t_at`, `get_albedo`/`get_hue_color` (voxel hue reconstruction), `calc_emission`/`blackbody`, the majorant grid, all `sampler3D` density/color/majorant lookups, `u_debug_raymarch`, `u_debug_delta_only`, the null-scattering throughput weights, and everything keyed off `u_voxel_volume`, `u_majorant_resolution`, `u_colored_extinction`.
- The entire media-scatter branch of the bounce loop. Every hit is now a **surface** hit on a particle (sphere) with a real position, normal, and material.

### 3.2 `volrender/shaders/volume_scene.glsl`

**REUSE (port the material system verbatim in spirit):** this file already implements exactly the three materials we want.

- `sample_cosine_hemisphere(n)` = `normalize(n + sample_sphere())` (Shirley trick) — cosine-weighted hemisphere sampling.
- Fresnel utilities: `ior_to_r0`, `schlick_fresnel`.
- `sample_brdf(incident, normal, mat, p, out out_dir)` returning throughput weight (BRDF·cos/pdf):
  - **MAT_DIFFUSE (Lambert):** cosine hemisphere, weight = albedo.
  - **MAT_MIRROR (tinted metal):** `reflect(incident, normal)`, weight = albedo. **This is the agreed convention** — a simple *tinted mirror* (reflection multiplied by a colored albedo). It is intentionally not physically-based complex-IOR metal; do not "improve" it. The architecture must make swapping in a better metal BRDF later a localized change.
  - **MAT_GLOSSY (plastic):** Schlick Fresnel chooses between perfect-mirror reflection and Lambert diffuse stochastically; weight = albedo either way.
- `eval_brdf_cos(...)` for NEE: mirror returns 0 (delta lobe, no NEE contribution), glossy returns only its diffuse-lobe contribution `(1-R)*albedo*NdotL/pi`, diffuse returns `albedo*NdotL/pi`.

**ADAPT:** `scene()`, `sdf_normal()`, `trace_sdf()`, `sdf_shadow_test()` are SDF sphere-tracing for a hardcoded test scene. The new renderer gets geometry from the **GAS**, not an SDF. You do **not** need SDF tracing for the particles. Keep a tiny SDF/analytic ground or test surface only if useful as a sanity backdrop during bring-up; it is not a shipping requirement. The **material lookups and BRDF functions are the valuable part** — those carry over unchanged.

> Net: the material math and the Monte Carlo plumbing are well-tested and battle-proven. Lift them. The acceleration structure and the volume integration are what change. Wherever you'd write new sampling/PDF/throughput code, check these two files first — it probably already exists and is correct.

---

## 4. The renderer core (CUDA/OptiX device code)

Mirror the existing realtime renderer's structure:

- **GAS over particle AABBs**, custom-primitive intersection program doing the analytic ray-sphere test (the realtime renderer's `__intersection__sphere` is the template). BVH build/traverse on RT cores; the analytic sphere test on SMs but that's cheap relative to traversal.
- **GAS lifecycle:** build once, **refit** per render frame, **rebuild** every ~10 frames (user-tunable cadence). Refit uses `BUILD_OPERATION_UPDATE` into the preallocated GAS/temp buffers (reuse the realtime renderer's `refit_gas`). The particle buffer is the **same GL buffer the physics writes**, registered with CUDA, mapped read-only for the AABB compute + trace, unmapped so GL/physics can write the next step. Honor that map/unmap discipline exactly — physics owns the buffer when it's unmapped.
- **Programs:** `__raygen__` (camera ray gen with jitter + DOF), `__miss__radiance` (sky), `__miss__occlusion` (shadow), `__intersection__sphere`, `__closesthit__` (material eval + NEE + set up next bounce). Two ray types: radiance and occlusion, as in the realtime renderer's SBT (miss index 0/1).
- **Per-particle material + albedo:** decide how a particle carries its material id and color. The GLSL derived hue from voxel accumulation — that's gone. Simplest: a parallel per-particle attribute buffer (material id + albedo) alongside the position/radius buffer, or a global material if per-particle isn't needed yet. Spec this as a clean seam; per-particle material is augmentable later. For bring-up a single global Lambert is fine (plan Step 2).

---

## 5. Accumulation, denoising, motion blur, and the CUDA-GL bridge

This is the subtle part. Read it carefully; it's new territory per your note that you've not denoised a path tracer before.

### 5.1 Where everything lives

**Everything from ray generation through denoise+tonemap stays CUDA-side.** GL only receives the final, completed, display-ready frame. Concretely, per displayed frame:

1. (physics has written particle positions to the GL buffer; map it read-only to CUDA)
2. refit (or periodically rebuild) the GAS over the current positions — **RT cores**
3. trace N samples-per-pixel, accumulating **linear HDR radiance** into a CUDA-side `float4` accumulation buffer — **RT cores + SMs**
4. (if denoising) run the denoiser on the accumulated HDR buffer using albedo + normal **guide buffers** — **tensor cores**
5. tonemap + quantize the (denoised) HDR result to the display format in a small CUDA kernel
6. write that into the **GL PBO** (the CUDA-registered pixel-unpack buffer), unmap, blit to texture, display / feed to the video encoder — **GL**

The HDR→RGB (tonemap/quantize) step happens **CUDA-side, after denoise, just before the PBO write.** Never tonemap before denoise — the denoiser wants linear HDR radiance, the same space it was trained on. Tonemapping first feeds it the wrong signal and produces smearing.

### 5.2 The accumulation buffer

The GLSL `img_accum` (rgba32f image2D) becomes a **CUDA-side float4 buffer**. `u_accumulate` semantics carry over: when accumulating, add each sample; the displayed/denoised value is the running mean (sum / sample_count). Keep the 1spp and progressive-accumulate controls exposed (they're the realtime knobs). GL never sees this buffer; it only sees the final PBO contents from step 6.

### 5.3 Guide buffers (why the GAS move makes this easy)

The denoiser quality at low spp depends on **albedo and normal guide layers**. Here is the good news: because we replaced the volume with **GAS surface geometry**, every hit now has a well-defined surface normal and surface albedo — so guide buffers are clean and natural, unlike a volumetric renderer where "the normal of a fog collision" is ill-defined.

- **Albedo guide:** write the *primary-hit* surface albedo (the material albedo at the first bounce) into a CUDA `float4` albedo buffer. For mirror/glossy, write the base albedo tint. For primary-ray sky misses, write the sky color.
- **Normal guide:** write the *primary-hit* world-space (or camera-space — match whatever the denoiser options expect; confirm during symbol recon) surface normal. For sky misses, a neutral normal is fine; the guide matters far less there.
- Enable the corresponding fields in the denoiser options struct to match the guide layers you provide. Mismatched options vs. provided layers is a common failure; confirm the exact option flags during §2.1 recon.

These are *primary-visibility* buffers — write them once per pixel from the first hit, not accumulated over bounces.

### 5.4 Motion blur and which side it belongs on (your specific question)

Your instinct was correct: **the denoiser wants ONE completed, converged, motion-blurred HDR frame — not N sharp sub-frames each denoised.** Denoising sub-frames and then averaging would denoise away the noise that *is* the motion blur, then blur the mush. So:

- **Motion blur OFF (realtime mode):** 1 spp into the HDR buffer, single GAS refit this frame, denoise once, tonemap, display. Refit every frame, rebuild every ~10 (user-tunable). This is the realtime target.
- **Motion blur ON (offline mode):** the frame is accumulated over **multiple physics sub-steps within a single displayed frame.** For each sub-step: advance physics (this happens on the GL/SM side and updates the particle buffer), **refit (or rebuild) the GAS at that sub-step's positions**, trace some samples, accumulate into the *same* HDR buffer. Repeat for all sub-steps and all spp. Only after the full accumulation is complete do you (optionally) denoise once, then tonemap, then hand the finished frame to GL for the video encoder.
  - This means **N GAS refits per displayed frame** in motion-blur mode (one per sub-step), where the realtime mode does one. Flag this cost to the user/config; it's inherent to motion blur with moving geometry. Refit is cheap relative to rebuild, but it is not free × N.
  - The accumulation buffer integrates across both the spp dimension and the sub-step (time) dimension into one radiance estimate — which is exactly a motion-blurred frame.

### 5.5 Denoising is optional and independent of mode

Expose denoise as an independent toggle, **not** coupled to realtime/offline:

- Realtime: typically 1spp **+ denoise** (the denoiser is what makes 1spp usable).
- Offline: high spp, motion blur, **denoise optional** — the user may turn it off and crank spp instead if denoising introduces smudging on a particular shot. Honor that: the pipeline must run cleanly with the denoiser bypassed (HDR accumulation → tonemap → PBO, skipping the denoise step entirely).

### 5.6 No temporal denoising

We are **not** using the denoiser's temporal mode. The particles move a lot frame-to-frame; motion vectors would be unreliable and the temporal model would ghost badly. Use the **non-temporal** model kind with strong albedo + normal guides plus the renderer's own per-frame accumulation. Do not wire up flow/motion-vector buffers or previous-frame inputs.

---

## 6. Controls to expose

Carry over all **non-volume** path-tracer controls; drop everything volume/tracking-specific.

**Keep / expose:**

- Mode-ish knobs: spp (1 for realtime, high for offline), `u_accumulate` (progressive accumulation), denoise on/off (independent toggle), motion-blur on/off + sub-step count, GAS rebuild cadence (refit-every-frame, rebuild-every-N).
- Camera: inverse-view-projection (or however the realtime renderer parameterizes its camera), DOF (`aperture`, `focal_plane_depth`, camera right/up).
- Sun / lighting: `sun_direction`, `sun_color`, `sun_intensity`, `sun_sampling` on/off (NEE toggle).
- Sky: `sky_color`, `sky_intensity`, photosphere mode + skybox texture, or procedural sky.
- Bounce control: `max_bounces` (0 = unbounded + RR only), `rr_start_depth`.
- Materials: per-particle (or global) material id + albedo; glossy IOR.
- Firefly clamp on/off + max luminance.

**Drop:** everything keyed off the voxel grid, majorant grid, extinction/density scale, colored-extinction, emission/blackbody, debug raymarch and debug-delta-only visual modes, HG phase function and asymmetry `g` (that was the volume phase function; surfaces use BRDFs now).

---

## 7. Host/UI integration (abstract — not your detailed concern)

You are the **CUDA/OptiX and CUDA-GL-bridge architect.** The ImGui/GL host wiring is "ImGui-and-GL-town's business" and will be hammered out separately by the human + a future session. Your responsibility is only to:

- Expose the new renderer behind a **clean entry point / interface** that the host can instantiate, drive per-frame (give it the mapped particle buffer + camera + controls, get back a completed frame in the GL PBO), and tear down — mirroring how the existing realtime OptiX renderer is driven.
- Ensure it **coexists** with the realtime renderer (no global-state collisions: separate OptiX pipeline/SBT/GAS ownership, or shared where genuinely safe and intentional).
- Note in your handoff (don't implement) that the host must **route the UI's `volrender` entry to this new renderer**, per the general principles in this spec: physics/display/record stay GL-side, the renderer takes the mapped particle buffer and returns finished frames. Leave the registration/dispatch-site discovery and rewiring to the host-side work.

Do not go hunting through ImGui code. Name the seam, expose it cleanly, stop.

---

## 8. Separate, smaller addition: cheap AO for the *realtime* (non-path-traced) OptiX renderer

This is a distinct, smaller task bundled into the same feature because it shares the GAS machinery. It applies to the **existing realtime OptiX renderer**, not the new path tracer. Its shadowed areas look flat; add cheap ray-traced ambient occlusion using the GAS already present.

- In the realtime renderer's closest-hit, after the existing shadow ray, fire a small number (1–4, tunable) of **short occlusion rays** over the cosine-weighted hemisphere around the surface normal.
- **Clamp `tmax` to a small world-space radius** — this is the whole trick. A short AO ray stays in-cache and only touches local BVH nodes, so it's cheap. Start around 20–50× the particle radius and expose it as a tunable AO radius.
- **Reuse the existing occlusion miss program and the terminate-on-first-hit / disable-anyhit / disable-closesthit shadow-ray setup** — no new SBT records needed. Average the miss fraction = AO term.
- Offset the AO ray origin along the normal (same epsilon discipline as the existing shadow ray; consider a slightly larger epsilon since neighboring particles are very close at this density).
- The realtime renderer's camera is effectively static frame-to-frame (particles animate, camera mostly doesn't), so **temporally accumulate** the AO term across frames with a small exponential blend and reset on large camera motion. This is what lets 1–2 AO rays look clean.
- Hash launch-index + frame for a rotated/jittered sample direction (low-discrepancy) to avoid banding.

This is the cheap win that fixes flat shadows without a full path tracer; keep it independent of the path-tracer code path.

---

## 9. Acceptance / done-ness

- The staged plan (`PATHTRACER_PLAN.md`) exists and was reviewed before implementation.
- New renderer traces the GAS (RT cores) with the three materials (tinted-mirror metal, Lambert, Fresnel glossy), sun NEE via binary GAS shadow rays, sky/photosphere miss, DOF, RR, firefly clamp — all ported from the existing tested GLSL math.
- HDR accumulation, optional denoise (non-temporal, albedo+normal guides), and tonemap all live CUDA-side; only the finished frame crosses to GL.
- Realtime mode (1spp + denoise + per-frame refit, periodic rebuild) and offline mode (high spp + motion blur via N mid-frame refits + optional denoise) both run from the same code path.
- Denoiser symbol names/signatures were empirically confirmed in `Scratch.venv`, not assumed.
- The realtime renderer gained cheap, `tmax`-clamped, temporally-accumulated AO.
- A clean entry point is exposed for host/UI takeover; the actual ImGui/GL rewiring is left documented but unimplemented.
- The volume/voxel/majorant/delta-tracking code is not carried into the new renderer.