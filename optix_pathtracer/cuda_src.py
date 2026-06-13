"""OptiX device code for path-traced sphere rendering.

Contains the CUDA C++ source compiled at runtime via NVRTC.
Single-bounce Lambert shading with HDR accumulation and progressive
sample refinement.  Step 2 of the path tracer implementation plan.

Entity layout (32 bytes, stride=8 floats):
    [0] px  [1] py  [2] pz    -- sphere center
    [3] vx  [4] vy  [5] vz    -- velocity (unused by renderer)
    [6] hue                    -- HSV hue for albedo coloring
    [7] size                   -- sphere radius
"""

PATHTRACER_CUDA_SRC = r"""
#include <optix.h>

extern "C" {
struct Params
{
    uchar4*            image;          // offset  0: mapped GL PBO (unused by OptiX programs, used by tonemap)
    float*             entities;       // offset  8: mapped GL entity buffer (raw floats)
    unsigned int       entity_stride;  // offset 16: floats per entity (8 for Fluoddity)
    // _pad0                           // offset 20: 4 bytes padding
    unsigned long long handle;         // offset 24: GAS traversable handle
    unsigned int       width;          // offset 32
    unsigned int       height;         // offset 36

    // Camera basis (pinhole)
    float3 eye;                        // offset 40
    float3 U;                          // offset 52
    float3 V;                          // offset 64
    float3 W;                          // offset 76

    // Lighting
    float3 light_dir;                  // offset 88: unit vector TOWARD the light
    float  ambient;                    // offset 100
    float  radius_scale;               // offset 104

    // Sky gradient
    float3 sky_color_top;              // offset 108
    float3 sky_color_bottom;           // offset 120

    // Accumulation (path tracer additions)
    // _pad1                           // offset 132: 4 bytes padding for pointer alignment
    float4*        accum_buffer;       // offset 136: CUDA-side HDR accumulation
    unsigned int   sample_index;       // offset 144: current sample (RNG seed)
    unsigned int   samples_accumulated;// offset 148: total samples so far
    float          exposure;           // offset 152: tonemap exposure multiplier
    // _pad2                           // offset 156: 4 bytes padding to 160 total
};
__constant__ Params params;
}

// --- float3 math (copied from optix_renderer/cuda_src.py) --------------------
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

// --- HSV to RGB (matches points_3d.frag) -------------------------------------
static __forceinline__ __device__ float fract_f(float x)
{ return x - floorf(x); }

static __forceinline__ __device__ float clamp_f(float x, float lo, float hi)
{ return fminf(fmaxf(x, lo), hi); }

static __forceinline__ __device__ float mix_f(float a, float b, float t)
{ return a + t * (b - a); }

static __forceinline__ __device__ float3 hsv2rgb(float h, float s, float v)
{
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

// --- PCG RNG (ported from volrender/shaders/common.glsl) ---------------------
// All functions take state by reference -- each thread keeps its own local copy.

static __forceinline__ __device__ void _pcg_advance(unsigned int& state, unsigned int delta)
{
    unsigned int acc_mult = 1u;
    unsigned int acc_plus = 0u;
    unsigned int cur_mult = 747796405u;   // PCG_MULT
    unsigned int cur_plus = 2891336453u;  // PCG_INC
    while (delta > 0u) {
        if ((delta & 1u) != 0u) {
            acc_mult *= cur_mult;
            acc_plus = acc_plus * cur_mult + cur_plus;
        }
        cur_plus = (cur_mult + 1u) * cur_plus;
        cur_mult *= cur_mult;
        delta >>= 1u;
    }
    state = acc_mult * state + acc_plus;
}

static __forceinline__ __device__ void rng_init(unsigned int& state,
                                                 unsigned int px,
                                                 unsigned int py,
                                                 unsigned int si)
{
    state = px * 1664525u + py * 1013904223u + si * 214013u + 2531011u;
    // Warm up: one full PCG step + output hash
    state = state * 747796405u + 2891336453u;
    state = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    state ^= state >> 22u;
    // Discard a seed-dependent count to break spatial correlation
    unsigned int discard_count = (state >> 16u) ^ (state & 0xFFFFu);
    _pcg_advance(state, discard_count);
}

static __forceinline__ __device__ float next_float(unsigned int& state)
{
    state = state * 747796405u + 2891336453u;
    unsigned int word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    word ^= word >> 22u;
    return (float)word / 4294967295.0f;
}

// --- ray generation ----------------------------------------------------------
extern "C" __global__ void __raygen__rg()
{
    const uint3 idx = optixGetLaunchIndex();

    // 1. Init RNG with pixel coordinates + sample index
    unsigned int rng;
    rng_init(rng, idx.x, idx.y, params.sample_index);

    // 2. Subpixel jitter for free AA across accumulated samples
    const float jx = next_float(rng);
    const float jy = next_float(rng);
    const float2 d = make_float2(
        2.0f * ((float)idx.x + jx) / (float)params.width  - 1.0f,
        2.0f * ((float)idx.y + jy) / (float)params.height - 1.0f);
    const float3 dir = normalize3(d.x * params.U + d.y * params.V + params.W);

    // 3. Trace primary ray (8 payloads)
    unsigned int p0 = 0, p1 = 0, p2 = 0, p3 = 0;
    unsigned int p4 = 0, p5 = 0, p6 = 0, p7 = 0;
    optixTrace(
        (OptixTraversableHandle)params.handle,
        params.eye, dir,
        0.0f, 1e16f, 0.0f,
        OptixVisibilityMask(255),
        OPTIX_RAY_FLAG_DISABLE_ANYHIT,
        0, 0,       // SBT offset, stride
        0,          // miss index: radiance
        p0, p1, p2, p3, p4, p5, p6, p7);

    // 4. Shade
    float3 color;
    float hit_t = __uint_as_float(p0);

    if (hit_t > 0.0f) {
        // Hit: reconstruct normal and albedo from payloads
        unsigned int prim = p1;
        float3 N = mk3(__uint_as_float(p2),
                        __uint_as_float(p3),
                        __uint_as_float(p4));

        // HSV->RGB albedo (S=0.8, V=1.0 matching points_3d.frag)
        float3 albedo = hsv2rgb(entity_hue(prim), 0.8f, 1.0f);

        // Single-bounce Lambert: albedo * (ambient + (1-ambient) * NdotL)
        float ndl = fmaxf(dot3(N, params.light_dir), 0.0f);
        float a = params.ambient;
        color = albedo * (mk3(a, a, a) + (1.0f - a) * ndl * mk3(1.0f, 1.0f, 1.0f));
    } else {
        // Miss: sky color from miss program
        color = mk3(__uint_as_float(p5),
                     __uint_as_float(p6),
                     __uint_as_float(p7));
    }

    // 5. Accumulate into float4 HDR buffer (additive)
    const unsigned int pixel_idx = idx.y * params.width + idx.x;
    float4 prev = params.accum_buffer[pixel_idx];
    params.accum_buffer[pixel_idx] = make_float4(
        prev.x + color.x,
        prev.y + color.y,
        prev.z + color.z,
        prev.w + 1.0f);
}

// --- miss programs -----------------------------------------------------------
extern "C" __global__ void __miss__radiance()
{
    const float3 dir = optixGetWorldRayDirection();
    const float t = 0.5f * (dir.y + 1.0f);
    const float3 c = (1.0f - t) * params.sky_color_bottom
                   + t * params.sky_color_top;

    // p0 stays 0 (initialized by caller) = miss signal
    // Write sky color to p5-p7
    optixSetPayload_5(__float_as_uint(c.x));
    optixSetPayload_6(__float_as_uint(c.y));
    optixSetPayload_7(__float_as_uint(c.z));
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

// --- closest hit: report hit data via payloads (shading in raygen) -----------
extern "C" __global__ void __closesthit__ch()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float3 center = entity_center(prim);

    const float  t = optixGetRayTmax();
    const float3 P = optixGetWorldRayOrigin() + t * optixGetWorldRayDirection();
    const float3 N = normalize3(P - center);

    // Report hit data via payloads
    optixSetPayload_0(__float_as_uint(t));    // hit distance (nonzero = hit)
    optixSetPayload_1(prim);                   // primitive index
    optixSetPayload_2(__float_as_uint(N.x));   // normal x
    optixSetPayload_3(__float_as_uint(N.y));   // normal y
    optixSetPayload_4(__float_as_uint(N.z));   // normal z
}
"""


TONEMAP_CUDA_SRC = r"""
extern "C" __global__ void tonemap(
    const float4* __restrict__ accum,
    uchar4*       __restrict__ image,
    unsigned int  width,
    unsigned int  height,
    unsigned int  samples_accumulated,
    float         exposure)
{
    const unsigned int x = blockIdx.x * blockDim.x + threadIdx.x;
    const unsigned int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    const unsigned int idx = y * width + x;
    float4 hdr = accum[idx];

    // Average over accumulated samples
    float inv_n = 1.0f / fmaxf((float)samples_accumulated, 1.0f);
    float r = hdr.x * inv_n * exposure;
    float g = hdr.y * inv_n * exposure;
    float b = hdr.z * inv_n * exposure;

    // Reinhard tonemap: c / (1 + c)
    r = r / (1.0f + r);
    g = g / (1.0f + g);
    b = b / (1.0f + b);

    // Approximate sRGB gamma (sqrt = gamma 2.0, matches existing to_srgb)
    r = sqrtf(fminf(fmaxf(r, 0.0f), 1.0f));
    g = sqrtf(fminf(fmaxf(g, 0.0f), 1.0f));
    b = sqrtf(fminf(fmaxf(b, 0.0f), 1.0f));

    // Y-flip for OpenGL convention
    const unsigned int out_y = height - 1u - y;
    image[out_y * width + x] = make_uchar4(
        (unsigned char)(r * 255.99f),
        (unsigned char)(g * 255.99f),
        (unsigned char)(b * 255.99f),
        255);
}
"""
