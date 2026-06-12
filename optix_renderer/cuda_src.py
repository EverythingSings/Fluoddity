"""OptiX device code for sphere rendering.

Contains the CUDA C++ source compiled at runtime via NVRTC.
Adapted from demos/optix_demo.py for Fluoddity's 8-float entity stride.

Entity layout (32 bytes, stride=8 floats):
    [0] px  [1] py  [2] pz    -- sphere center
    [3] vx  [4] vy  [5] vz    -- velocity (unused by renderer)
    [6] hue                    -- HSV hue for albedo coloring
    [7] size                   -- sphere radius
"""

SPHERE_CUDA_SRC = r"""
#include <optix.h>

extern "C" {
struct Params
{
    uchar4*            image;          // mapped GL PBO
    float*             entities;       // mapped GL entity buffer (raw floats)
    unsigned int       entity_stride;  // floats per entity (8 for Fluoddity)
    unsigned long long handle;         // GAS traversable handle
    unsigned int       width;
    unsigned int       height;
    float3 eye; float3 U; float3 V; float3 W;  // pinhole camera basis
    float3 light_dir;                           // unit vector TOWARD the light
    float  ambient;                             // ambient light intensity
    float  radius_scale;                        // multiplier on entity size
    int    shadows_enabled;                     // 0 or 1
};
__constant__ Params params;
}

// --- float3 math -------------------------------------------------------------
static __forceinline__ __device__ float3 mk3(float x, float y, float z)
{ return make_float3(x, y, z); }

static __forceinline__ __device__ float3 operator+(float3 a, float3 b)
{ return mk3(a.x+b.x, a.y+b.y, a.z+b.z); }

static __forceinline__ __device__ float3 operator-(float3 a, float3 b)
{ return mk3(a.x-b.x, a.y-b.y, a.z-b.z); }

static __forceinline__ __device__ float3 operator*(float s, float3 a)
{ return mk3(s*a.x, s*a.y, s*a.z); }

static __forceinline__ __device__ float3 operator*(float3 a, float s)
{ return mk3(a.x*s, a.y*s, a.z*s); }

static __forceinline__ __device__ float3 operator*(float3 a, float3 b)
{ return mk3(a.x*b.x, a.y*b.y, a.z*b.z); }

static __forceinline__ __device__ float dot3(float3 a, float3 b)
{ return a.x*b.x + a.y*b.y + a.z*b.z; }

static __forceinline__ __device__ float3 normalize3(float3 a)
{ float s = rsqrtf(fmaxf(dot3(a, a), 1e-20f)); return s * a; }

// --- sRGB gamma --------------------------------------------------------------
static __forceinline__ __device__ unsigned char to_srgb(float x)
{
    x = sqrtf(fminf(fmaxf(x, 0.0f), 1.0f));   // approximate gamma 2.2 -> 2.0
    return (unsigned char)(x * 255.99f);
}

// --- HSV to RGB (matches points_3d.frag) -------------------------------------
static __forceinline__ __device__ float fract_f(float x)
{ return x - floorf(x); }

static __forceinline__ __device__ float clamp_f(float x, float lo, float hi)
{ return fminf(fmaxf(x, lo), hi); }

static __forceinline__ __device__ float mix_f(float a, float b, float t)
{ return a + t * (b - a); }

static __forceinline__ __device__ float3 hsv2rgb(float h, float s, float v)
{
    // Same algorithm as points_3d.frag: hsv2rgb(vec3(hue, 0.8, 1.0))
    float px = fabsf(fract_f(h + 1.0f)       * 6.0f - 3.0f);
    float py = fabsf(fract_f(h + 2.0f/3.0f)  * 6.0f - 3.0f);
    float pz = fabsf(fract_f(h + 1.0f/3.0f)  * 6.0f - 3.0f);
    return mk3(
        v * mix_f(1.0f, clamp_f(px - 1.0f, 0.0f, 1.0f), s),
        v * mix_f(1.0f, clamp_f(py - 1.0f, 0.0f, 1.0f), s),
        v * mix_f(1.0f, clamp_f(pz - 1.0f, 0.0f, 1.0f), s));
}

// --- entity data access (stride-aware) ---------------------------------------
static __forceinline__ __device__ float3 entity_center(unsigned int prim)
{
    unsigned int base = prim * params.entity_stride;
    return mk3(params.entities[base + 0],
               params.entities[base + 1],
               params.entities[base + 2]);
}

static __forceinline__ __device__ float entity_radius(unsigned int prim)
{
    unsigned int base = prim * params.entity_stride;
    return params.entities[base + 7] * params.radius_scale;
}

static __forceinline__ __device__ float entity_hue(unsigned int prim)
{
    unsigned int base = prim * params.entity_stride;
    return params.entities[base + 6];
}

// --- ray generation ----------------------------------------------------------
extern "C" __global__ void __raygen__rg()
{
    const uint3 idx = optixGetLaunchIndex();
    const float2 d = make_float2(
        2.0f * ((float)idx.x + 0.5f) / (float)params.width  - 1.0f,
        2.0f * ((float)idx.y + 0.5f) / (float)params.height - 1.0f);
    const float3 dir = normalize3(d.x * params.U + d.y * params.V + params.W);

    unsigned int p0, p1, p2;  // RGB payload
    optixTrace(
        (OptixTraversableHandle)params.handle,
        params.eye, dir,
        0.0f, 1e16f, 0.0f,
        OptixVisibilityMask(255),
        OPTIX_RAY_FLAG_DISABLE_ANYHIT,
        0, 0,       // SBT offset, stride
        0,          // miss index: radiance
        p0, p1, p2);

    params.image[idx.y * params.width + idx.x] = make_uchar4(
        to_srgb(__uint_as_float(p0)),
        to_srgb(__uint_as_float(p1)),
        to_srgb(__uint_as_float(p2)),
        255);
}

// --- miss programs -----------------------------------------------------------
extern "C" __global__ void __miss__radiance()
{
    const float3 dir = optixGetWorldRayDirection();
    const float t = 0.5f * (dir.y + 1.0f);
    const float3 c = (1.0f - t) * mk3(0.08f, 0.08f, 0.10f)
                   + t * mk3(0.45f, 0.62f, 0.85f);
    optixSetPayload_0(__float_as_uint(c.x));
    optixSetPayload_1(__float_as_uint(c.y));
    optixSetPayload_2(__float_as_uint(c.z));
}

extern "C" __global__ void __miss__occlusion()
{
    optixSetPayload_0(0u);  // reached the light: not occluded
}

// --- sphere intersection (custom primitive, stride-aware) --------------------
extern "C" __global__ void __intersection__sphere()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float3 center = entity_center(prim);
    const float  radius = entity_radius(prim);

    // Skip degenerate (zero-size) entities
    if (radius <= 0.0f) return;

    const float3 O = optixGetObjectRayOrigin() - center;
    const float3 D = optixGetObjectRayDirection();

    const float a = dot3(D, D);
    const float b = dot3(O, D);
    const float c = dot3(O, O) - radius * radius;
    const float disc = b * b - a * c;
    if (disc < 0.0f) return;

    const float sq = sqrtf(disc);
    const float t0 = (-b - sq) / a;
    const float t1 = (-b + sq) / a;
    const float tmin = optixGetRayTmin();
    const float tmax = optixGetRayTmax();
    if (t0 > tmin && t0 < tmax)       optixReportIntersection(t0, 0);
    else if (t1 > tmin && t1 < tmax)  optixReportIntersection(t1, 0);
}

// --- closest hit: Lambert + shadow ray + hue-based albedo --------------------
extern "C" __global__ void __closesthit__ch()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float3 center = entity_center(prim);
    const float  hue    = entity_hue(prim);

    const float  t = optixGetRayTmax();
    const float3 P = optixGetWorldRayOrigin() + t * optixGetWorldRayDirection();
    const float3 N = normalize3(P - center);
    const float3 L = params.light_dir;

    // HSV->RGB albedo (S=0.8, V=1.0 matching points_3d.frag)
    const float3 albedo = hsv2rgb(hue, 0.8f, 1.0f);

    // Shadow ray (optional)
    float vis = 1.0f;
    if (params.shadows_enabled)
    {
        unsigned int occluded = 1u;
        optixTrace(
            (OptixTraversableHandle)params.handle,
            P + 1e-4f * N, L,
            0.0f, 1e16f, 0.0f,
            OptixVisibilityMask(255),
            OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
            | OPTIX_RAY_FLAG_DISABLE_ANYHIT
            | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
            0, 0,
            1,  // miss index: occlusion
            occluded);
        vis = occluded ? 0.0f : 1.0f;
    }

    const float ndl = fmaxf(dot3(N, L), 0.0f);
    const float3 c = albedo * (params.ambient + (1.0f - params.ambient) * ndl * vis);

    optixSetPayload_0(__float_as_uint(c.x));
    optixSetPayload_1(__float_as_uint(c.y));
    optixSetPayload_2(__float_as_uint(c.z));
}
"""
