"""OptiX device code for path-traced sphere rendering.

Contains the CUDA C++ source compiled at runtime via NVRTC.
Multi-bounce path tracing with three materials (Lambert, Glossy, Mirror),
Russian roulette, depth of field, firefly clamping, HDR accumulation,
and sun NEE with binary GAS shadow rays.
Step 4 of the path tracer implementation plan.

Entity layout (32 bytes, stride=8 floats):
    [0] px  [1] py  [2] pz    -- sphere center
    [3] vx  [4] vy  [5] vz    -- velocity (unused by renderer)
    [6] hue                    -- HSV hue for albedo coloring
    [7] size                   -- sphere radius
"""

PATHTRACER_CUDA_SRC = r"""
#include <optix.h>

// Material ID constants
#define MAT_DIFFUSE  0
#define MAT_GLOSSY   1
#define MAT_MIRROR   2

extern "C" {
struct Params
{
    uchar4*            image;          // offset  0: mapped GL PBO (used by tonemap)
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

    // Sun lighting (Step 4: NEE + shadow rays)
    float3 sun_direction;              // offset 88: unit vector TOWARD the sun
    float  sun_intensity;              // offset 100: sun radiance multiplier
    float  radius_scale;               // offset 104

    // Sky gradient
    float3 sky_color_top;              // offset 108
    float3 sky_color_bottom;           // offset 120

    // Accumulation
    // _pad1                           // offset 132: 4 bytes padding for pointer alignment
    float4*        accum_buffer;       // offset 136: CUDA-side HDR accumulation
    unsigned int   sample_index;       // offset 144: current sample (RNG seed)
    unsigned int   samples_accumulated;// offset 148: total samples so far
    float          exposure;           // offset 152: tonemap exposure multiplier

    // DOF (Step 3)
    float          aperture;           // offset 156: lens radius (0 = pinhole)
    float          focal_plane_depth;  // offset 160: focal distance
    float3         cam_right;          // offset 164: normalized camera right (DOF)
    float3         cam_up;             // offset 176: normalized camera up (DOF)

    // Bounce control (Step 3)
    int            max_bounces;        // offset 188: 0 = unlimited (RR only)
    int            rr_start_depth;     // offset 192: depth where RR begins

    // Firefly clamp (Step 3)
    int            firefly_clamp;      // offset 196: bool: enable clamping
    float          firefly_clamp_max;  // offset 200: max luminance per sample

    // Material (Step 3)
    int            global_material;    // offset 204: 0=Lambert, 1=Glossy, 2=Mirror
    float          glossy_ior;         // offset 208: IOR for Fresnel (default 1.5)

    // Sun NEE (Step 4)
    float3         sun_color;          // offset 212: sun color RGB
    int            sun_sampling;       // offset 224: bool: enable NEE shadow rays
    // _pad4                           // offset 228: 4 bytes padding for pointer alignment

    // Denoiser guide buffers (Step 5)
    float4*        albedo_buffer;      // offset 232: primary-hit albedo guide (null if disabled)
    float4*        normal_buffer;      // offset 240: primary-hit normal guide (null if disabled)
    // Total: 248 bytes
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

static __forceinline__ __device__ float3 neg3(float3 a)
{ return mk3(-a.x, -a.y, -a.z); }

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

// --- sampling utilities (ported from volrender/shaders/common.glsl) -----------

static __forceinline__ __device__ float3 sample_sphere(unsigned int& rng)
{
    float xi1 = next_float(rng);
    float xi2 = next_float(rng);
    float cos_theta = 1.0f - 2.0f * xi1;           // uniform in [-1, +1]
    float sin_theta = sqrtf(fmaxf(0.0f, 1.0f - cos_theta * cos_theta));
    float phi = 6.283185307f * xi2;                 // 2*pi
    return mk3(sin_theta * cosf(phi),
               sin_theta * sinf(phi),
               cos_theta);
}

static __forceinline__ __device__ float2 sample_disk(unsigned int& rng)
{
    float r = sqrtf(next_float(rng));
    float theta = 6.283185307f * next_float(rng);
    return make_float2(r * cosf(theta), r * sinf(theta));
}

// --- cosine-weighted hemisphere sampling (Shirley trick) ---------------------
// Ported from volrender/shaders/volume_scene.glsl

static __forceinline__ __device__ float3 sample_cosine_hemisphere(float3 n, unsigned int& rng)
{
    return normalize3(n + sample_sphere(rng));
}

// --- reflection and Fresnel utilities ----------------------------------------

static __forceinline__ __device__ float3 reflect3(float3 incident, float3 normal)
{
    return incident - 2.0f * dot3(incident, normal) * normal;
}

static __forceinline__ __device__ float ior_to_r0(float ior)
{
    float r = (ior - 1.0f) / (ior + 1.0f);
    return r * r;
}

static __forceinline__ __device__ float schlick_fresnel(float cos_theta, float R0)
{
    float x = clamp_f(1.0f - cos_theta, 0.0f, 1.0f);
    float x2 = x * x;
    return R0 + (1.0f - R0) * x2 * x2 * x;   // x^5
}

// --- BRDF sampling (ported from volrender/shaders/volume_scene.glsl) ---------
// Returns throughput weight = BRDF * cos(theta) / PDF.
// out_dir receives the sampled bounce direction.

static __forceinline__ __device__ float3 sample_brdf(
    float3 incident, float3 normal,
    int mat_id, float3 albedo, float ior,
    float3& out_dir, unsigned int& rng)
{
    if (mat_id == MAT_MIRROR) {
        out_dir = reflect3(incident, normal);
        return albedo;
    }

    if (mat_id == MAT_GLOSSY) {
        float cos_i = fabsf(dot3(neg3(incident), normal));
        float R0 = ior_to_r0(ior);
        float R = schlick_fresnel(cos_i, R0);
        if (next_float(rng) < R) {
            out_dir = reflect3(incident, normal);
            return albedo;
        } else {
            out_dir = sample_cosine_hemisphere(normal, rng);
            return albedo;
        }
    }

    // MAT_DIFFUSE: Lambertian
    out_dir = sample_cosine_hemisphere(normal, rng);
    return albedo;
}

// --- BRDF evaluation for NEE (used in Step 4) --------------------------------
// Returns BRDF * cos(theta) for a given light direction.
// Delta lobes (mirror, glossy specular) return 0.

static __forceinline__ __device__ float3 eval_brdf_cos(
    float3 incident, float3 light_dir, float3 normal,
    int mat_id, float3 albedo, float ior)
{
    float NdotL = fmaxf(dot3(normal, light_dir), 0.0f);

    if (mat_id == MAT_MIRROR) {
        return mk3(0.0f, 0.0f, 0.0f);   // delta BRDF, no NEE contribution
    }

    if (mat_id == MAT_GLOSSY) {
        float cos_i = fabsf(dot3(neg3(incident), normal));
        float R0 = ior_to_r0(ior);
        float R = schlick_fresnel(cos_i, R0);
        float inv_pi = 0.31830988618f;
        return (1.0f - R) * albedo * NdotL * inv_pi;
    }

    // MAT_DIFFUSE
    float inv_pi = 0.31830988618f;
    return albedo * NdotL * inv_pi;
}

// --- ray generation (Step 3: full bounce loop) -------------------------------
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

    float3 ray_origin = params.eye;
    float3 ray_dir = normalize3(d.x * params.U + d.y * params.V + params.W);

    // 3. Depth of field: thin lens model
    if (params.aperture > 0.0f) {
        float3 focal_point = ray_origin + ray_dir * params.focal_plane_depth;
        float2 lens = sample_disk(rng);
        lens.x *= params.aperture;
        lens.y *= params.aperture;
        ray_origin = ray_origin
                   + lens.x * params.cam_right
                   + lens.y * params.cam_up;
        ray_dir = normalize3(focal_point - ray_origin);
    }

    // 4. Bounce loop
    float3 throughput = mk3(1.0f, 1.0f, 1.0f);
    float3 radiance   = mk3(0.0f, 0.0f, 0.0f);
    int    depth      = 0;

    const int MAX_WALK_BOUNCES = 512;

    for (int bounce = 0; bounce < MAX_WALK_BOUNCES; bounce++) {

        // 4a. Trace ray (8 payloads)
        unsigned int p0 = 0, p1 = 0, p2 = 0, p3 = 0;
        unsigned int p4 = 0, p5 = 0, p6 = 0, p7 = 0;
        optixTrace(
            (OptixTraversableHandle)params.handle,
            ray_origin, ray_dir,
            0.0f, 1e16f, 0.0f,
            OptixVisibilityMask(255),
            OPTIX_RAY_FLAG_DISABLE_ANYHIT,
            0, 0,       // SBT offset, stride
            0,          // miss index: radiance
            p0, p1, p2, p3, p4, p5, p6, p7);

        float hit_t = __uint_as_float(p0);

        // 4b. Miss: accumulate sky and exit
        if (hit_t <= 0.0f) {
            float3 sky = mk3(__uint_as_float(p5),
                             __uint_as_float(p6),
                             __uint_as_float(p7));
            radiance = radiance + throughput * sky;

            // Guide buffers: primary miss -> sky albedo, neutral normal
            if (depth == 0 && params.albedo_buffer) {
                const unsigned int pidx = idx.y * params.width + idx.x;
                params.albedo_buffer[pidx] = make_float4(sky.x, sky.y, sky.z, 1.0f);
                params.normal_buffer[pidx] = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
            }

            break;
        }

        // 4c. Hit: reconstruct P, N, albedo
        unsigned int prim = p1;
        float3 N = mk3(__uint_as_float(p2),
                        __uint_as_float(p3),
                        __uint_as_float(p4));
        float3 P = ray_origin + hit_t * ray_dir;

        // Flip normal to face incoming ray
        if (dot3(N, ray_dir) > 0.0f)
            N = neg3(N);

        // HSV->RGB albedo (S=0.8, V=1.0 matching points_3d.frag)
        float3 albedo = hsv2rgb(entity_hue(prim), 0.8f, 1.0f);

        // Guide buffers: primary hit -> surface albedo and normal
        if (depth == 0 && params.albedo_buffer) {
            const unsigned int pidx = idx.y * params.width + idx.x;
            params.albedo_buffer[pidx] = make_float4(albedo.x, albedo.y, albedo.z, 1.0f);
            params.normal_buffer[pidx] = make_float4(N.x, N.y, N.z, 0.0f);
        }

        // Material (global for now; per-particle in future)
        int   mat_id = params.global_material;
        float ior    = params.glossy_ior;

        // 4d. Sun NEE: direct sun lighting via binary GAS shadow ray
        if (params.sun_sampling) {
            float3 shadow_origin = P + 1e-3f * N;

            unsigned int occluded = 1u;
            optixTrace(
                (OptixTraversableHandle)params.handle,
                shadow_origin, params.sun_direction,
                0.0f, 1e16f, 0.0f,
                OptixVisibilityMask(255),
                OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
                | OPTIX_RAY_FLAG_DISABLE_ANYHIT
                | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
                0, 0,       // SBT offset, stride
                1,          // miss index: occlusion (miss -> p0 = 0 = not occluded)
                occluded);

            if (!occluded) {
                float3 brdf_cos = eval_brdf_cos(
                    ray_dir, params.sun_direction, N,
                    mat_id, albedo, ior);
                radiance = radiance + throughput * brdf_cos
                         * params.sun_color * params.sun_intensity;
            }
        }

        // 4e. Depth and max_bounces check
        depth++;
        if (params.max_bounces > 0 && depth >= params.max_bounces)
            break;

        // 4f. Russian roulette
        if (depth > params.rr_start_depth) {
            float p_survive = fmaxf(throughput.x,
                               fmaxf(throughput.y, throughput.z));
            p_survive = clamp_f(p_survive, 0.05f, 1.0f);
            if (next_float(rng) >= p_survive)
                break;
            throughput = throughput * (1.0f / p_survive);
        }

        // 4g. Sample BRDF for next bounce
        float3 bounce_dir;
        float3 weight = sample_brdf(ray_dir, N, mat_id, albedo, ior,
                                     bounce_dir, rng);
        throughput = throughput * weight;

        // 4h. Self-intersection avoidance: offset origin along normal
        ray_origin = P + 1e-3f * N;
        ray_dir = bounce_dir;
    }

    // 5. Firefly clamp: cap per-sample radiance to reduce outliers
    if (params.firefly_clamp) {
        float lum = fmaxf(radiance.x, fmaxf(radiance.y, radiance.z));
        if (lum > params.firefly_clamp_max) {
            radiance = radiance * (params.firefly_clamp_max / lum);
        }
    }

    // 6. Accumulate into float4 HDR buffer (additive)
    const unsigned int pixel_idx = idx.y * params.width + idx.x;
    float4 prev = params.accum_buffer[pixel_idx];
    params.accum_buffer[pixel_idx] = make_float4(
        prev.x + radiance.x,
        prev.y + radiance.y,
        prev.z + radiance.z,
        prev.w + 1.0f);
}

// --- miss programs -----------------------------------------------------------
extern "C" __global__ void __miss__radiance()
{
    const float3 dir = optixGetWorldRayDirection();

    // Base gradient sky
    const float t = 0.5f * (dir.y + 1.0f);
    float3 c = (1.0f - t) * params.sky_color_bottom
             + t * params.sky_color_top;

    // Sun glow: bright spot in the sun direction
    // (ported from volrender/shaders/pathtrace.comp get_sky_col)
    float sun_dot = dot3(dir, params.sun_direction);
    float sun_glow = powf(clamp_f(sun_dot * 0.5f + 0.5f, 0.0f, 1.0f), 900.0f);
    c = c + sun_glow * 200.0f * params.sun_color * params.sun_intensity;

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


RESOLVE_CUDA_SRC = r"""
extern "C" __global__ void resolve(
    const float4* __restrict__ accum,
    float4*       __restrict__ resolved,
    unsigned int  width,
    unsigned int  height,
    unsigned int  samples)
{
    const unsigned int x = blockIdx.x * blockDim.x + threadIdx.x;
    const unsigned int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    const unsigned int idx = y * width + x;
    float4 hdr = accum[idx];

    float inv_n = 1.0f / fmaxf((float)samples, 1.0f);
    resolved[idx] = make_float4(
        hdr.x * inv_n,
        hdr.y * inv_n,
        hdr.z * inv_n,
        1.0f);
}
"""
