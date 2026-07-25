"""SDF scene definition for the OptiX renderers (path tracer + rasterizer).

CUDA device code ported from volrender/shaders/volume_scene.glsl.

This file is the user-editable scene definition. Modify sdf_scene() to define
your SDF geometry and sdf_get_albedo() to define material colors. The code is
compiled into both the path tracer and rasterize renderer at runtime.

IMPORTANT: This source relies on float3 math helpers (mk3, dot3, normalize3)
already defined in the main CUDA source. It must be inserted AFTER those
helpers.
"""

# Default SDF bounding box (used by renderers when SDF is enabled)
SDF_AABB_MIN = (-2.0, -2.0, -2.0)
SDF_AABB_MAX = (2.0, 2.0, 2.0)


SDF_SCENE_CUDA_SRC = r"""
// ====================================================================
// SDF scene definition — ported from volrender/shaders/volume_scene.glsl
//
// EDIT sdf_scene() and sdf_get_albedo() to define your scene.
// ====================================================================

// ---- SDF primitives ----

static __forceinline__ __device__ float sd_sphere(float3 p, float3 center, float radius)
{
    float3 d = p - center;
    return sqrtf(dot3(d, d)) - radius;
}

static __forceinline__ __device__ float sd_plane(float3 p, float3 normal, float offset)
{
    return dot3(p, normal) - offset;
}

static __forceinline__ __device__ float sd_box(float3 p, float3 center, float3 half_extents)
{
    float3 q = mk3(fabsf(p.x - center.x) - half_extents.x,
                    fabsf(p.y - center.y) - half_extents.y,
                    fabsf(p.z - center.z) - half_extents.z);
    float3 q_pos = mk3(fmaxf(q.x, 0.0f), fmaxf(q.y, 0.0f), fmaxf(q.z, 0.0f));
    float outside = sqrtf(dot3(q_pos, q_pos));
    float inside = fminf(fmaxf(q.x, fmaxf(q.y, q.z)), 0.0f);
    return outside + inside;
}

static __forceinline__ __device__ float sd_cut_hollow_sphere(float3 p, float r, float h, float t)
{
    float w = sqrtf(r * r - h * h);
    float2 q = make_float2(sqrtf(p.x * p.x + p.z * p.z), p.y);
    return ((h * q.x < w * q.y)
        ? sqrtf((q.x - w) * (q.x - w) + (q.y - h) * (q.y - h))
        : fabsf(sqrtf(q.x * q.x + q.y * q.y) - r)) - t;
}

// ---- Collider SDF ----

static __forceinline__ __device__ float collider_scene_sdf(float3 p)
{
    return sd_cut_hollow_sphere(p-mk3(0.0f,0.5f,0.0f), 01.5f, -01.25f, 0.031f);
}

// ---- Boolean operations (vec2 = float2(distance, material_id)) ----

static __forceinline__ __device__ float2 sdf_union(float2 a, float2 b)
{
    return (a.x < b.x) ? a : b;
}

static __forceinline__ __device__ float2 sdf_subtract(float2 a, float2 b)
{
    return (-b.x > a.x) ? make_float2(-b.x, b.y) : a;
}

static __forceinline__ __device__ float2 sdf_intersect(float2 a, float2 b)
{
    return (a.x > b.x) ? a : b;
}

// ====================================================================
// Scene definition — EDIT THIS
//
// Returns float2(signed_distance, material_id)
// Material encoding: floor(y) = BRDF type (0=diffuse, 1=glossy, 2=mirror)
//                    fract(y) = sub-ID for per-object variation
// ====================================================================

static __forceinline__ __device__ float2 sdf_scene(float3 p)
{
    float dts = sd_box(p, mk3(0.0f, 0.0f, 0.0f), mk3(1.0f, 1.0f, 1.0f));
    dts = fmaxf(p.y + 0.725f, -dts);
    dts = fmaxf(dts, sd_box(p, mk3(0.0f, 0.0f, 0.0f), mk3(2.0f, 2.0f, 2.0f)));
    float2 platform = make_float2(dts, (float)MAT_DIFFUSE);

    // The collider is the presentation bowl. Keep it diffuse so its concave
    // interior remains readable against a dark environment instead of acting
    // like a black mirror with only a bright specular rim.
    float2 collider = make_float2(collider_scene_sdf(p), (float)MAT_DIFFUSE);

    return collider;//sdf_union(platform, collider);
}


// ====================================================================
// SDF normal via tetrahedral 4-tap gradient (saves 2 evals vs central diff)
// ====================================================================

static __forceinline__ __device__ float3 sdf_normal(float3 p)
{
    const float h = 1e-4f;
    return normalize3(mk3(
        sdf_scene(mk3(p.x + h, p.y - h, p.z - h)).x
      - sdf_scene(mk3(p.x - h, p.y + h, p.z - h)).x
      + sdf_scene(mk3(p.x + h, p.y + h, p.z + h)).x
      - sdf_scene(mk3(p.x - h, p.y - h, p.z + h)).x,

        sdf_scene(mk3(p.x - h, p.y + h, p.z - h)).x
      - sdf_scene(mk3(p.x + h, p.y - h, p.z - h)).x
      + sdf_scene(mk3(p.x + h, p.y + h, p.z + h)).x
      - sdf_scene(mk3(p.x - h, p.y - h, p.z + h)).x,

        sdf_scene(mk3(p.x - h, p.y - h, p.z + h)).x
      - sdf_scene(mk3(p.x + h, p.y - h, p.z - h)).x
      + sdf_scene(mk3(p.x + h, p.y + h, p.z + h)).x
      - sdf_scene(mk3(p.x - h, p.y + h, p.z - h)).x
    ));
}


// ====================================================================
// Material property lookups — EDIT THESE for your scene
//
// Use fract(mat.y) to distinguish objects sharing the same BRDF class.
// ====================================================================

static __forceinline__ __device__ float3 sdf_get_albedo(float2 mat, float3 p)
{
    int id = (int)floorf(mat.y);
    if (id == MAT_DIFFUSE) {
        // Warm ceramic white: bright enough to describe the full bowl surface
        // while preserving shading and contact with the simulated material.
        return mk3(0.88f, 0.84f, 0.78f);
    }
    return mk3(0.9f, 0.9f, 0.9f);  // bright reflector/glossy
}

static __forceinline__ __device__ float sdf_get_ior(float2 mat)
{
    return 1.5f;  // glass-like
}


// ====================================================================
// Sphere tracing
// ====================================================================

#define SDF_MAX_STEPS   356
#define SDF_SURFACE_EPS 1e-4f
#define SDF_MAX_DIST    60.0f

static __forceinline__ __device__ bool trace_sdf(
    float3 origin, float3 dir, float t_min, float t_max,
    float& out_t, float2& out_mat)
{
    float t = t_min;
    for (int i = 0; i < SDF_MAX_STEPS; i++) {
        float3 p = origin + t * dir;
        float2 d = sdf_scene(p);
        if (d.x < SDF_SURFACE_EPS) {
            out_t = t;
            out_mat = d;
            return true;
        }
        t += d.x;
        if (t > t_max)
            return false;
    }
    return false;
}


// ====================================================================
// SDF shadow test — binary occlusion for shadow rays
// ====================================================================

static __forceinline__ __device__ bool sdf_shadow_test(
    float3 origin, float3 dir, float t_min, float t_max)
{
    float t = t_min;
    for (int i = 0; i < SDF_MAX_STEPS; i++) {
        float3 p = origin + t * dir;
        float d = sdf_scene(p).x;
        if (d < SDF_SURFACE_EPS)
            return true;   // occluded
        t += d;
        if (t > t_max)
            return false;
    }
    return false;
}
"""
