# Medium color from particle hue — volrender splat + path trace

## Context

The `volrender` module ingests a large buffer of `Entity` structs and splats them
into a traversal structure. We currently accumulate medium density but discard hue.
This task adds a medium *color* derived from particle hue, under the simplifying
assumption that all particles share a single saturation and brightness and differ
only in hue.

The `Entity` struct already carries a `float hue` value, so no RGB→hue extraction is
needed on the splat path.

## Core idea

Hue is periodic, so it cannot be averaged linearly. Instead, treat each particle's
hue as an angle `θ = 2π · hue` and accumulate it as a unit vector `(cos θ, sin θ)`
into two scalar buffers (the X and Y color buffers), using the *same per-particle
weight* the splat already applies to density. The accumulated 2D vector then encodes
both quantities we want: its **direction** is the weighted mean hue, and its
**magnitude relative to the total weight** is the degree of hue alignment.

A region of randomly-distributed hues cancels toward the zero vector (interpreted as
white/desaturated); a region of aligned hues produces a strong vector (high
saturation). This is the mean-resultant-length construction from directional
statistics, and the saturation interpretation is only valid because of it.

## Normalization — decision required during codebase exploration

The saturation reconstruction is `R = |C| / W`, where `C` is the accumulated color
vector and `W` is the sum of the *same weights* used to accumulate `C`. `R` only
lands in `[0, 1]` and only means "hue concentration" if `W` is exactly that matching
weight-sum. There are two valid ways to supply `W`, and the right one depends on the
existing density buffer's semantics:

- **(a) Reuse the density buffer as the denominator.** Valid only if density is
  accumulated as the same weighted sum of per-particle contributions, with the same
  footprint/weights and co-located voxels, as the color splat — i.e. it really is
  `Σ wᵢ`.
- **(b) Add a dedicated weight-sum buffer for color normalization.** Required if the
  density buffer is an optical/extinction quantity — scaled by cross-section,
  accumulated with a different footprint, or in different units — in which case the
  ratio against it is not a concentration and saturation will come out wrong
  (possibly `> 1`).

The implementing agent must inspect how the density buffer is actually built and
choose (a) or (b) accordingly. **Do not assume (a).** If choosing (a), verify and
note the weight/footprint/units equality in a comment; if (b), the new buffer must
share resolution and indexing with the color buffers.

## Accumulation buffers must be fp32

A sum of unit vectors grows toward magnitude N; fp16 loses integer-scale precision
past ~2k, so a busy voxel would accumulate garbage. Use fp32 atomics for the two
color buffers (and the weight buffer if (b)). Float atomics are fine on the target
NVIDIA hardware.

## Resolution and indexing

The two color buffers (and any (b) weight buffer) share resolution and voxel indexing
with the normalizing buffer. We are not using a coarser color grid in this pass.

## Hue convention, end to end

`Entity` stores hue as a `float`. Forward (splat): `θ = 2π · hue`. Inverse (resolve):
`hue = atan2(C_y, C_x) / (2π)`, wrapped to `[0, 1)`. The two ends must agree on
convention.

## Resolve — `get_albedo(location)`

Replaces the former `u_albedo_rgb` uniform. At a sampled location, read the color
vector `C = (C_x, C_y)` and the normalizer `W`, then:

1. `hue = atan2(C_y, C_x) / (2π)`, wrapped to `[0, 1)`  *(magnitude irrelevant here)*
2. `R = clamp(length(C) / max(W, eps), 0, 1)`
3. `S = u_albedo_saturation * R`  *(slider is the saturation ceiling; R pulls toward grey as hues disagree)*
4. `V = u_albedo_brightness`
5. `rgb = hsv2rgb(hue, S, V)`

## `W ≈ 0` fallback

Where there is effectively no medium (no scattering), albedo is irrelevant; the
`max(W, eps)` guard plus the resulting `R → 0` yields a neutral result. Define and
document the exact returned value rather than leaving it to floating-point chance.

## Known, correct edge case

A voxel with a single contributing particle yields `R = 1` — full saturation at that
particle's exact hue. This is correct, not a bug, though in sparse regions it can read
as hue noise. Note it so it isn't "fixed" later.

## Sliders are resolve-time, not splat-time

The two controls window albedo controls are replaced by **albedo saturation** and
**albedo brightness**. Neither touches the splat kernel: we accumulate *unit* hue
vectors, which are independent of saturation and brightness by construction. Both
sliders are consumed only inside `get_albedo()`, as `S`'s ceiling and `V` respectively
(steps 3–4 above).