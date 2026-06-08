# Spec: Emissive Participating Media via Collision-Sampled Emission

## Goal
Add emission to the volumetric path tracer. Emission is derived from the
existing density field — NO new splats, NO new grids, NO equiangular or
emission-importance sampling. Emission is collected on absorption events
using the existing delta-tracking collision sampler.

## What exists already (do not modify)
- Delta tracking for free-flight sampling.
- Ratio tracking for shadow/transmittance. **Leave entirely untouched** —
  emission does not affect transmittance.
- HG phase function. **Untouched** — emission is isotropic, no phase changes.
- A density field readable at any point along the ray.

## New helper (assume provided / declare as extern)
    vec3 calc_emission(float density);
Returns emitted radiance L_e (a color) as a nonlinear function of local
density. This is L_e ONLY — it is NOT premultiplied by sigma_a. Do not
multiply the result by sigma_a anywhere (see Correctness below). Takes
density only; no position param.

## The physics (one line)
On a REAL collision, delta tracking selects an event. The absorption event
is reached with probability sigma_a/sigma_t. Emission is tied to absorption
(Kirchhoff), so returning L_e on exactly that branch is already correctly
weighted by sigma_a/sigma_t — no explicit sigma_a factor needed.

## Required change

### 1. Locate the event-selection logic at a real collision
After a real (non-null) collision is accepted, the integrator decides
between scattering and absorption. THIS IS THE KEY INVESTIGATION TASK:
determine how absorption is currently modeled. Two cases:

  (a) There is an explicit absorption branch (e.g. terminate path with
      probability sigma_a/sigma_t, or 1 - albedo). 
      -> Modify that branch: before terminating, contribute emission.

  (b) Absorption is folded in implicitly (e.g. throughput multiplied by
      single-scattering albedo each bounce, path always scatters, never an
      explicit absorption event).
      -> You must introduce the absorption event explicitly, OR add emission
         in a way consistent with the implicit model (see note below).

Figure out which case this codebase is in before writing code. Report which
one you found.

### 2. Contribute emission (case a — explicit absorption branch)
On the absorption branch, at collision point with local `density`:

    radiance += throughput * calc_emission(density);

then terminate the path as it already does. `throughput` is the path
throughput accumulated up to (not including) this collision. Do NOT return
the emission raw — it must be scaled by throughput and added to the radiance
accumulator.

### 3. Contribute emission (case b — implicit/albedo absorption)
If the path never takes a discrete absorption event and instead attenuates
by albedo, the equivalent correct contribution at each real collision is:

    radiance += throughput * (sigma_a / sigma_t) * calc_emission(density);

then continue scattering as before. This reproduces the same expectation as
the explicit branch. Use whichever sigma_a / albedo / sigma_t quantities the
collision code already has in scope. Prefer matching the existing model
rather than restructuring it.

## Correctness checklist (verify before finishing)
- [ ] calc_emission result is never multiplied by an extra sigma_a in
      case (a). The sigma_a weighting comes from the branch probability.
- [ ] In case (b), sigma_a/sigma_t IS applied, because there is no branch
      probability doing it.
- [ ] Emission is multiplied by throughput and ADDED to radiance, never
      returned in place of it.
- [ ] Ratio tracking / transmittance code is unmodified.
- [ ] HG phase function code is unmodified.
- [ ] No new splat channels, grids, or buffers added.

## Validation
- A medium with calc_emission returning 0 everywhere must produce a
  pixel-identical image to before the change (regression check).
- A uniformly emissive medium with no external light and no scattering
  should converge to a flat glow whose brightness scales with sigma_a and
  path length, not blow up or depend on resolution.
- Increasing sample count should reduce noise but not shift the mean
  (unbiasedness sanity check).

## Out of scope (do not implement)
- Equiangular / emission-importance / next-event sampling for emission.
- New splatting passes or emission grids.
- Spectral / blackbody temperature mapping (calc_emission handles color).
- Spatially-varying emission beyond what density encodes.