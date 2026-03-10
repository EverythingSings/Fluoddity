# Recursive SDF Domain Repetition via Camera-Space Self-Similarity

## Design Spec for GLSL Sphere Tracer Implementation

---

## 1. Overview

This system creates the illusion of infinite recursive self-similarity (a house containing a smaller copy of itself, containing a smaller copy, etc.) using only three SDF evaluations per `map()` call. The recursion is never evaluated in the SDF — it is handled entirely by camera-space transformations and teleportation.

The scene has a single canonical SDF (`sdf(p)`) defining geometry within a "fundamental region." Three instances are rendered simultaneously:

- **Macro**: a scaled-up copy surrounding the fundamental region (the "parent")
- **Base**: the fundamental region itself (the "current room")
- **Micro**: a scaled-down copy placed inside the fundamental region (the "child")

As the camera moves into Micro, it teleports to the corresponding position in Base and the world scale adjusts so the transition is seamless. Moving outward triggers teleportation from Base's edge into the corresponding position near Micro — the heart of the inward transition zone — eliminating the need for a separate outward transition.

---

## 2. Similarity Transform Definition

The relationship between Base and Micro is defined by three parameters:

```glsl
uniform vec3  u_offset;    // Translation: center of Micro within Base's coordinate frame
uniform float u_scale;     // Scale factor: size of Micro relative to Base (e.g. 0.2)
uniform mat3  u_rotation;  // Rotation: orientation of Micro relative to Base
```

### Transforms

**Base → Micro local frame (to evaluate canonical SDF at the micro level):**
```
p_micro = u_rotation * (p_base - u_offset) / u_scale
```

**Micro local frame → Base (retrieve base coords from a point in micro's local frame):**
```
p_base = u_scale * (inverse(u_rotation) * p_micro) + u_offset
```

**Base → Macro local frame (Base is Macro's Micro copy, so this is Micro→Base from Macro's POV):**
```
p_macro = u_scale * (inverse(u_rotation) * p_base) + u_offset
```
This is correct because from Macro's perspective, Base IS its Micro copy. To get Macro-space coords from Base-space coords, we apply the same Micro→Base transform (since Base plays the role of Micro within Macro).

**Macro local frame → Base:**
```
p_base = u_rotation * (p_macro - u_offset) / u_scale
```

---

## 3. The Fundamental Region and Micro Region

The fundamental region is an axis-aligned box centered at the origin:

```glsl
uniform vec3 u_region_half_extents;  // Half-size of the fundamental region AABB
```

The Micro region is a smaller box (in Base coordinates) centered at `u_offset`, with half-extents `u_region_half_extents * u_scale`, rotated by `u_rotation`.

For the transition zone, we need the signed distance from a point to the Micro box boundary, computed in Base (unscaled) space:

```glsl
// Signed box distance from point p to the Micro copy's bounding box,
// computed in Base (unscaled) space. Negative = inside Micro box.
float sdMicroBox(vec3 p) {
    // Transform p into Micro-box-local space (centered, axis-aligned)
    vec3 q = u_rotation * (p - u_offset);
    vec3 halfExt = u_region_half_extents * u_scale;
    vec3 d = abs(q) - halfExt;
    return length(max(d, 0.0)) + min(max(d.x, max(d.y, d.z)), 0.0);
}
```

---

## 4. The map() Function

`map()` evaluates the canonical SDF at three scales. No recursion, no branching on camera state — just three evaluations with scale correction.

```glsl
float sdf(vec3 p);  // User-defined canonical scene SDF

float map(vec3 p) {
    // --- Base: evaluate at current coordinates ---
    float dBase = sdf(p);

    // --- Micro: transform p into the scaled-down copy's local frame ---
    // Evaluate canonical SDF there, correct distance by multiplying by u_scale
    vec3 pMicro = u_rotation * (p - u_offset) / u_scale;
    float dMicro = sdf(pMicro) * u_scale;

    // --- Macro: transform p as if Base is the Micro copy of a larger parent ---
    // Base→Macro uses the Micro→Base transform (since Base IS Macro's Micro)
    vec3 pMacro = u_scale * (inverse(u_rotation) * p) + u_offset;
    float dMacro = sdf(pMacro) / u_scale;

    return min(dBase, min(dMicro, dMacro));
}
```

### Optional AABB Acceleration

Skip Micro/Macro SDF evaluation when the ray sample point is far from the respective region:

```glsl
float map(vec3 p) {
    float dBase = sdf(p);
    float d = dBase;

    // Only evaluate Micro if p is near the Micro bounding box
    float microBoxDist = sdMicroBox(p);
    if (microBoxDist < dBase) {
        vec3 pMicro = u_rotation * (p - u_offset) / u_scale;
        d = min(d, sdf(pMicro) * u_scale);
    }

    // Only evaluate Macro if p is near the edge of the fundamental region
    float regionBoxDist = sdBox(p, u_region_half_extents);  // negative = inside
    if (-regionBoxDist < dBase) {  // close to outer wall
        vec3 pMacro = u_scale * (inverse(u_rotation) * p) + u_offset;
        d = min(d, sdf(pMacro) / u_scale);
    }

    return d;
}
```

---

## 5. Camera System and Transition Zone

### 5.1 Core Invariant

**The camera position is always kept within the fundamental region.** It never enters Micro and never exits the fundamental region. This ensures numerical stability (SDF is always evaluated near unit-scale coordinates) and simplifies all rendering logic.

### 5.2 Transition Region

The transition region is a shell around the Micro bounding box. It is defined by the signed distance from the camera to the Micro box boundary (`sdMicroBox(cam)`), evaluated in Base (unscaled) space.

```glsl
uniform float u_transition_distance;  // Distance at which transition begins (positive)
```

The transition parameter `t` ramps from 0 (no scaling) to 1 (full scaling, ready for teleport):

```glsl
float microDist = sdMicroBox(cam);  // positive = outside micro, negative = inside
float t = smoothstep(u_transition_distance, 0.0, microDist);
// t = 0.0 when microDist >= u_transition_distance  (far from micro, no transition)
// t = 1.0 when microDist <= 0.0                     (at or inside micro boundary)
```

> **IMPORTANT — USER RESPONSIBILITY:**
> The transition region (the shell of thickness `u_transition_distance` around the Micro box)
> must not overlap with or extend beyond the fundamental region boundary.
> If it does, the inward and outward teleport triggers can conflict, causing visual pop-in.
>
> Ensure sufficient clearance:
>   distance_from_micro_box_to_region_boundary > u_transition_distance
>
> More precisely, for all points on the Micro OBB surface, sdBox(point, u_region_half_extents)
> must be more negative than -u_transition_distance.

### 5.3 World Scale

World scale interpolates based on `t`. At `t = 0`, `worldScale = 1.0`. At `t = 1`, `worldScale = u_scale`.

```glsl
float worldScale = mix(1.0, u_scale, t);
```

All distance-dependent rendering parameters scale with `worldScale`:

| Parameter          | Adjusted Value                    | Rationale                                      |
|--------------------|-----------------------------------|------------------------------------------------|
| Fog density        | `fogDensity / worldScale`         | Fog looks equally dense at every level          |
| Max march distance | `maxDist * worldScale`            | Proportional visible range                      |
| Hit epsilon        | `hitEpsilon * worldScale`         | Surface detection scales with geometry          |
| Shadow bias        | `shadowBias * worldScale`         | Self-shadowing threshold scales with geometry   |
| Camera move speed  | `moveSpeed * worldScale`          | Movement feels the same speed at every level    |
| Min step distance  | `minStep * worldScale`            | Ray march precision scales with geometry        |

### 5.4 Teleportation

Teleportation occurs on the CPU/JS side each frame, BEFORE uploading the camera uniform.

**Inward teleport** — camera enters Micro box (`sdMicroBox(cam) < 0`):

```
cam = u_rotation * (cam - u_offset) / u_scale
viewDir = u_rotation * viewDir
upDir = u_rotation * upDir
// worldScale was u_scale at this moment; after remap, recompute from new cam position
// sdMicroBox(new_cam) will place the camera inside the fundamental region,
// and the new t will reflect the new position's distance to Micro
```

**Outward teleport** — camera exits fundamental region (`sdBox(cam, u_region_half_extents) > 0`):

From Macro's frame of reference, Base IS its Micro copy. Exiting Base = entering Macro's Micro from inside. We teleport to the corresponding position in the fundamental region, which by construction will be near `u_offset` — the heart of the inward transition zone:

```
cam = u_scale * (inverse(u_rotation) * cam) + u_offset
viewDir = inverse(u_rotation) * viewDir
upDir = inverse(u_rotation) * upDir
// The new cam position is near u_offset, inside the transition zone
// sdMicroBox(new_cam) will be small and positive (or slightly negative)
// t will be close to 1.0, worldScale close to u_scale
// This is seamless: the view from just outside the region boundary
// matches the view from the teleported position near Micro
```

This eliminates the need for a separate outward transition zone.

---

## 6. Per-Frame Update (CPU/JS Side)

```
each frame:
    1. Apply camera movement:
         cam += moveDir * moveSpeed * worldScale * dt

    2. Check teleport conditions:
         microDist  = sdMicroBox(cam)
         regionDist = sdBox(cam, u_region_half_extents)

         if microDist < 0:                         // entered micro
             cam     = u_rotation * (cam - u_offset) / u_scale
             viewDir = u_rotation * viewDir
             upDir   = u_rotation * upDir

         else if regionDist > 0:                   // exited region
             cam     = u_scale * (inverse(u_rotation) * cam) + u_offset
             viewDir = inverse(u_rotation) * viewDir
             upDir   = inverse(u_rotation) * upDir

    3. Recompute transition parameter from (potentially teleported) camera:
         t = smoothstep(u_transition_distance, 0.0, sdMicroBox(cam))
         worldScale = mix(1.0, u_scale, t)

    4. Upload uniforms: cam, viewDir, upDir, worldScale
```

---

## 7. Shader Uniforms Summary

```glsl
// Similarity transform
uniform vec3  u_offset;               // Micro copy center in Base space
uniform float u_scale;                // Micro copy scale factor (0 < s < 1)
uniform mat3  u_rotation;             // Micro copy rotation relative to Base

// Fundamental region
uniform vec3  u_region_half_extents;  // Half-extents of the fundamental region AABB

// Camera (always in fundamental region)
uniform vec3  u_cam;                  // Camera position
uniform vec3  u_viewDir;              // Camera view direction
uniform vec3  u_upDir;                // Camera up vector

// Transition
uniform float u_worldScale;           // Current world scale (1.0 when far from micro)
uniform float u_transition_distance;  // Shell thickness for transition zone
```

---

## 8. Ray March Loop

```glsl
vec3 ro = u_cam;
vec3 rd = getRayDir(uv, u_cam, u_viewDir, u_upDir);

float t_march = 0.0;
float maxDist = BASE_MAX_DIST * u_worldScale;
float hitEps  = BASE_HIT_EPS  * u_worldScale;

for (int i = 0; i < MAX_STEPS; i++) {
    vec3 p = ro + rd * t_march;
    float d = map(p);
    if (d < hitEps) break;
    t_march += d;
    if (t_march > maxDist) break;
}

// Shading
vec3 hitPos = ro + rd * t_march;
vec3 nor = calcNormal(hitPos);  // Use map(), not sdf(), for normals
vec3 col = shade(hitPos, nor, rd);

// Fog (adjusted for current scale level)
col = mix(fogColor, col, exp(-t_march * FOG_DENSITY / u_worldScale));
```

---

## 9. The Canonical SDF Contract

The user provides `sdf(vec3 p)` which defines geometry within the fundamental region. Requirements:

1. **Must be a valid SDF** (Lipschitz ≤ 1) within the fundamental region.
2. **Should have an opening at the Micro copy location** — a doorway, portal, or gap at `u_offset` so the camera can visually enter the copy and so the interior of Micro is visible from Base.
3. **Should have a corresponding opening at the fundamental region boundary** — looking outward from Base toward the Macro level, there must be an opening so Macro geometry is visible. This opening corresponds to the door through which Macro "sees" Base (its Micro copy).
4. **Geometry should not extend beyond `u_region_half_extents`** — anything outside is not rendered by the Base evaluation and may cause discontinuities.

---

## 10. Rotation Handling Notes

When `u_rotation` is not identity:

- The Micro bounding box in Base space is an OBB. `sdMicroBox()` handles this by transforming into local frame before computing box distance.
- Camera direction and up vector must also be rotated on teleport (shown in Section 5.4).
- Accumulated rotation across many teleports may cause float drift. Periodically re-orthogonalize the view basis vectors (e.g., Gram-Schmidt every N teleports).

---

## 11. Animation and Time

If the scene has time-based animation:

```
// Animation time does NOT scale with worldScale by default.
// Objects at every level animate at the same visual rate.
//
// If you WANT physical consistency (smaller things move proportionally
// slower), pass worldScale into sdf() and scale animation frequencies.
// This is a creative decision, not a system requirement.
```

---

## 12. Implementation Checklist

| Component               | Where    | Description                                                |
|-------------------------|----------|------------------------------------------------------------|
| `sdf(vec3 p)`          | GLSL     | User-defined canonical scene geometry                      |
| `sdMicroBox(vec3 p)`   | GLSL+CPU | Signed distance to Micro OBB in Base space                 |
| `sdBox(vec3 p, vec3 h)`| GLSL+CPU | Standard signed box distance (for region boundary check)   |
| `map(vec3 p)`          | GLSL     | Three-cell evaluation: min(Macro, Base, Micro)             |
| `calcNormal(vec3 p)`   | GLSL     | Central differences using `map()`, NOT `sdf()`             |
| Camera update loop      | CPU/JS   | Movement, teleport detection, worldScale computation       |
| `worldScale` uniform    | CPU→GPU  | Drives fog, epsilon, maxDist, shadowBias, minStep          |
| Ray march loop          | GLSL     | Standard sphere trace with worldScale-adjusted constants   |
| Fog / post-processing   | GLSL     | worldScale-adjusted fog density                            |

---

## 13. Debugging Notes and Common Pitfalls

- **Scale correction direction in map()**: `dMicro` is multiplied by `u_scale` (micro-frame distances are `1/s` too large). `dMacro` is divided by `u_scale` (macro-frame distances are `s` too small). Getting these backwards is the #1 implementation bug.
- **Normals must use map()**: `calcNormal()` must call `map()`, not `sdf()`, to get correct normals at cell boundaries where Micro or Macro geometry is closest.
- **Shadow rays cross cells naturally**: Shadow rays from Base can hit Micro or Macro geometry. The three-cell `map()` handles this — no special shadow logic needed.
- **worldScale must NOT enter map()**: `worldScale` affects only rendering parameters (fog, epsilon, speed). The SDF geometry is always evaluated in canonical coordinates with proper scale correction. Leaking worldScale into map() causes geometric distortion.
- **Teleport must happen before worldScale computation**: If you compute worldScale first and then teleport, the worldScale will be stale for one frame.
- **Matrix inverse**: `inverse(u_rotation)` = `transpose(u_rotation)` since rotation matrices are orthogonal. Use transpose for efficiency.
