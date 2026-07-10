"""OptiX device code for path-traced sphere rendering.

Contains the CUDA C++ source compiled at runtime via NVRTC.
Multi-bounce path tracing with three materials (Lambert, Glossy, Mirror),
Russian roulette, depth of field, firefly clamping, HDR accumulation,
and sun NEE with binary GAS shadow rays. Supports optional SDF scene
geometry via sphere tracing within a BVH custom primitive.

Entity layout (32 bytes, stride=8 floats):
    [0] px  [1] py  [2] pz    -- sphere center
    [3] vx  [4] vy  [5] vz    -- velocity (unused by renderer)
    [6] hue                    -- HSV hue for albedo coloring
    [7] size                   -- sphere radius
"""

from .sdf_scene import SDF_SCENE_CUDA_SRC

_CUDA_HEADER = r"""
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

    // Albedo color controls
    float          albedo_saturation;  // offset 248: HSV saturation (0-1, default 0.8)
    float          albedo_brightness;  // offset 252: HSV value/brightness (0-1, default 1.0)
    // Sphere size jitter
    float          sphere_size_jitter; // offset 256: per-sphere radius jitter magnitude (0-1)
    // RNG decorrelation
    unsigned int   frame_seed;         // offset 260: monotonic counter (never resets)

    // SDF scene
    int            sdf_enabled;        // offset 264: bool: enable SDF geometry
    float          sdf_aabb_min_x;     // offset 268
    float          sdf_aabb_min_y;     // offset 272
    float          sdf_aabb_min_z;     // offset 276
    float          sdf_aabb_max_x;     // offset 280
    float          sdf_aabb_max_y;     // offset 284
    float          sdf_aabb_max_z;     // offset 288
    unsigned int   sdf_prim_index;     // offset 292: primitive index of SDF AABB (= entity_count)

    // Emissive particles
    float          emission_intensity; // offset 296: multiplier on emissive radiance

    // Curve primitives
    int            use_curves;        // offset 300: bool: curve mode active
    float          curve_length;      // offset 304: control point distance (multiplier on entity size)
    float          curve_r0;          // offset 308: radius at start (multiplier on entity size)
    float          curve_r1;          // offset 312: radius at end (multiplier on entity size)
    // Environment sky NEE
    int            env_sky_nee;       // offset 316: bool: use cosine-lobe env sky for NEE

    // Photosphere (equirectangular environment map)
    int            photosphere_enabled; // offset 320: bool: use photosphere sky
    // _pad_photo                       // offset 324: 4 bytes padding for pointer alignment
    unsigned long long photosphere_tex; // offset 328: cudaTextureObject_t handle
    float          photosphere_avg_r;  // offset 336: pre-computed average color R (for NEE)
    float          photosphere_avg_g;  // offset 340: pre-computed average color G
    float          photosphere_avg_b;  // offset 344: pre-computed average color B

    // Rasterize preset (merged sphere renderer): single-hit direct lighting +
    // AO-modulated fake ambient. Active when rasterize != 0.
    int            rasterize;          // offset 348: bool: rasterize (single-hit) mode
    int            ao_enabled;         // offset 352: bool: enable AO term
    int            ao_num_rays;        // offset 356: AO samples per hit
    float          ao_radius;          // offset 360: AO ray max length
    unsigned int   ao_frame_index;     // offset 364: AO jitter decorrelation counter
    float3         ambient_color;      // offset 368: rasterize ambient tint (scaled by `ambient`)
    // _pad_end                        // offset 380: pad to 384
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
    float r = params.entities[base + 7] * params.radius_scale;
    if (params.sphere_size_jitter > 0.0f) {
        unsigned int h = prim * 2654435761u;
        float jitter = ((float)(h & 0xFFFFu) / 32767.5f) - 1.0f;
        r *= (1.0f + params.sphere_size_jitter * jitter);
    }
    return r;
}

static __forceinline__ __device__ float entity_hue(unsigned int prim)
{
    unsigned int base = prim * params.entity_stride;
    return params.entities[base + 6];
}

static __forceinline__ __device__ float3 entity_velocity(unsigned int prim)
{
    unsigned int base = prim * params.entity_stride;
    return mk3(params.entities[base + 3],
               params.entities[base + 4],
               params.entities[base + 5]);
}

// --- emission helper (user-customizable) ---
// Returns emission radiance for an entity. Returns (0,0,0) for non-emissive.
// Default: negative hue -> emit at abs(hue), same saturation/brightness.
static __forceinline__ __device__ float3 get_emission(
    float hue, float saturation, float brightness)
{
    if (hue >= 0.0f)
        return mk3(0.0f, 0.0f, 0.0f);
    return hsv2rgb(-hue, saturation, brightness);
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
                                                 unsigned int si,
                                                 unsigned int frame_seed)
{
    state = px * 1664525u + py * 1013904223u + si * 214013u + frame_seed * 1103515245u + 2531011u;
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
    float3& out_dir, unsigned int& rng, int& out_delta)
{
    if (mat_id == MAT_MIRROR) {
        out_dir = reflect3(incident, normal);
        out_delta = 1;
        return albedo;
    }

    if (mat_id == MAT_GLOSSY) {
        float cos_i = fabsf(dot3(neg3(incident), normal));
        float R0 = ior_to_r0(ior);
        float R = schlick_fresnel(cos_i, R0);
        if (next_float(rng) < R) {
            out_dir = reflect3(incident, normal);
            out_delta = 1;
            return albedo;
        } else {
            out_dir = sample_cosine_hemisphere(normal, rng);
            out_delta = 0;
            return albedo;
        }
    }

    // MAT_DIFFUSE: Lambertian
    out_dir = sample_cosine_hemisphere(normal, rng);
    out_delta = 0;
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

// --- MIS helpers -------------------------------------------------------------

static __forceinline__ __device__ float power_heuristic(float pdf_a, float pdf_b)
{
    float a2 = pdf_a * pdf_a;
    return a2 / (a2 + pdf_b * pdf_b);
}

// Returns the continuous BRDF PDF for a given direction.
// Delta lobes (mirror, glossy specular) return 0.
static __forceinline__ __device__ float eval_brdf_pdf(
    float3 incident, float3 light_dir, float3 normal,
    int mat_id, float ior)
{
    float NdotL = fmaxf(dot3(normal, light_dir), 0.0f);
    float inv_pi = 0.31830988618f;

    if (mat_id == MAT_MIRROR)
        return 0.0f;

    if (mat_id == MAT_GLOSSY) {
        float cos_i = fabsf(dot3(neg3(incident), normal));
        float R0 = ior_to_r0(ior);
        float R = schlick_fresnel(cos_i, R0);
        return (1.0f - R) * NdotL * inv_pi;
    }

    return NdotL * inv_pi;
}

// --- environment sky helpers (cosine-power lobe model) -----------------------

static __forceinline__ __device__ void build_onb(
    float3 n, float3& t, float3& b)
{
    if (fabsf(n.y) < 0.999f) {
        t = normalize3(mk3(n.z, 0.0f, -n.x));
    } else {
        t = mk3(1.0f, 0.0f, 0.0f);
    }
    b = mk3(n.y * t.z - n.z * t.y,
             n.z * t.x - n.x * t.z,
             n.x * t.y - n.y * t.x);
}

static __forceinline__ __device__ float3 sample_cosine_power_lobe(
    float3 axis, float exponent, unsigned int& rng)
{
    float u1 = next_float(rng);
    float u2 = next_float(rng);
    float cos_theta = powf(u1, 1.0f / (exponent + 1.0f));
    float sin_theta = sqrtf(fmaxf(0.0f, 1.0f - cos_theta * cos_theta));
    float phi = 6.283185307f * u2;

    float3 t, b;
    build_onb(axis, t, b);

    return normalize3(
        sin_theta * cosf(phi) * t
      + sin_theta * sinf(phi) * b
      + cos_theta * axis);
}

static __forceinline__ __device__ float pdf_cosine_power_lobe(
    float3 dir, float3 axis, float exponent)
{
    float cos_theta = fmaxf(dot3(dir, axis), 0.0f);
    // pdf = (n+1) / (2*pi) * cos_theta^n
    return (exponent + 1.0f) * 0.15915494f * powf(cos_theta, exponent);
}

// Environment sky exponents (hardcoded)
#define ENV_SKY_EXP  1.0f
#define ENV_SUN_EXP  15.0f

// --- photosphere equirectangular texture lookup ------------------------------
static __forceinline__ __device__ float3 sample_photosphere(float3 dir)
{
    float theta = atan2f(dir.z, dir.x);          // [-pi, pi]
    float u = theta * 0.15915494f + 0.5f;        // theta/(2*pi) + 0.5 -> [0,1]
    float v = -dir.y * 0.5f + 0.5f;              // [-1,1] -> [1,0] (Y-inverted)
    float4 c = tex2D<float4>(params.photosphere_tex, u, v);
    return mk3(c.x, c.y, c.z);
}

static __forceinline__ __device__ float3 eval_env_sky(float3 dir)
{
    if (params.photosphere_enabled) {
        float3 photo = sample_photosphere(dir);
        if (params.env_sky_nee) {
            // Add sun lobe on top of photosphere
            float sun_cos = fmaxf(dot3(dir, params.sun_direction), 0.0f);
            float3 sun_contrib = powf(sun_cos, ENV_SUN_EXP)
                               * params.sun_color * params.sun_intensity;
            photo = photo + sun_contrib;
        }
        return photo;
    }

    // Original: Sky lobe + Sun lobe
    float sky_cos = fmaxf(dir.y, 0.0f);
    float3 sky_contrib = powf(sky_cos, ENV_SKY_EXP) * params.sky_color_top;

    float sun_cos = fmaxf(dot3(dir, params.sun_direction), 0.0f);
    float3 sun_contrib = powf(sun_cos, ENV_SUN_EXP)
                       * params.sun_color * params.sun_intensity;

    return sky_contrib + sun_contrib;
}

// Returns the mixture PDF of the environment sky for a given direction.
// Used by both sample_env_sky and MIS weighting at BRDF miss.
static __forceinline__ __device__ float eval_env_sky_pdf(float3 dir)
{
    if (params.photosphere_enabled) {
        // Cosine-hemisphere PDF for photosphere: cos(theta) / pi
        float cos_theta = fmaxf(dir.y, 0.0f);
        float photo_pdf = cos_theta * 0.31830988618f;  // cos/pi

        if (params.env_sky_nee) {
            // Mixture: photosphere (cosine hemisphere) + sun lobe
            float photo_bright = fmaxf(params.photosphere_avg_r,
                                  fmaxf(params.photosphere_avg_g,
                                        params.photosphere_avg_b));
            float w_photo = photo_bright;
            float w_sun   = params.sun_intensity / (ENV_SUN_EXP + 1.0f);
            float w_total = w_photo + w_sun;
            if (w_total < 1e-10f) return 0.079577f;  // 1/(4*pi) fallback
            float p_photo = w_photo / w_total;
            return p_photo * photo_pdf
                 + (1.0f - p_photo) * pdf_cosine_power_lobe(
                       dir, params.sun_direction, ENV_SUN_EXP);
        }
        // Photosphere only, no sun lobe in NEE
        return photo_pdf;
    }

    // Original: mixture of sky lobe + sun lobe
    float sky_bright = fmaxf(params.sky_color_top.x,
                       fmaxf(params.sky_color_top.y,
                             params.sky_color_top.z));
    float w_sky_raw = sky_bright / (ENV_SKY_EXP + 1.0f);
    float w_sun_raw = params.sun_intensity / (ENV_SUN_EXP + 1.0f);
    float w_total = w_sky_raw + w_sun_raw;
    if (w_total < 1e-10f) return 0.079577f;  // 1/(4*pi) fallback
    float p_sky = w_sky_raw / w_total;
    float3 up = mk3(0.0f, 1.0f, 0.0f);
    return p_sky * pdf_cosine_power_lobe(dir, up, ENV_SKY_EXP)
         + (1.0f - p_sky) * pdf_cosine_power_lobe(dir, params.sun_direction, ENV_SUN_EXP);
}

static __forceinline__ __device__ void sample_env_sky(
    unsigned int& rng, float3& out_dir, float& out_pdf)
{
    if (params.photosphere_enabled) {
        if (params.env_sky_nee) {
            // Mixture: cosine hemisphere (photosphere proxy) + sun lobe
            float photo_bright = fmaxf(params.photosphere_avg_r,
                                  fmaxf(params.photosphere_avg_g,
                                        params.photosphere_avg_b));
            float w_photo = photo_bright;
            float w_sun   = params.sun_intensity / (ENV_SUN_EXP + 1.0f);
            float w_total = w_photo + w_sun;

            if (w_total < 1e-10f) {
                out_dir = sample_sphere(rng);
                out_pdf = 0.079577f;  // 1/(4*pi)
                return;
            }

            float p_photo = w_photo / w_total;
            float3 up = mk3(0.0f, 1.0f, 0.0f);

            if (next_float(rng) < p_photo) {
                out_dir = sample_cosine_hemisphere(up, rng);
            } else {
                out_dir = sample_cosine_power_lobe(
                    params.sun_direction, ENV_SUN_EXP, rng);
            }
            out_pdf = eval_env_sky_pdf(out_dir);
        } else {
            // Photosphere only (no cos-lobe): cosine hemisphere
            float3 up = mk3(0.0f, 1.0f, 0.0f);
            out_dir = sample_cosine_hemisphere(up, rng);
            out_pdf = eval_env_sky_pdf(out_dir);
        }
        return;
    }

    // Original: Mixture weights proportional to integrated hemisphere power
    float sky_bright = fmaxf(params.sky_color_top.x,
                       fmaxf(params.sky_color_top.y,
                             params.sky_color_top.z));
    float w_sky_raw = sky_bright / (ENV_SKY_EXP + 1.0f);
    float w_sun_raw = params.sun_intensity / (ENV_SUN_EXP + 1.0f);
    float w_total = w_sky_raw + w_sun_raw;

    if (w_total < 1e-10f) {
        // Fallback: uniform sphere
        out_dir = sample_sphere(rng);
        out_pdf = 0.079577f;  // 1/(4*pi)
        return;
    }

    float p_sky = w_sky_raw / w_total;
    float3 up = mk3(0.0f, 1.0f, 0.0f);

    if (next_float(rng) < p_sky) {
        out_dir = sample_cosine_power_lobe(up, ENV_SKY_EXP, rng);
    } else {
        out_dir = sample_cosine_power_lobe(params.sun_direction, ENV_SUN_EXP, rng);
    }

    out_pdf = eval_env_sky_pdf(out_dir);
}
"""

# SDF scene code is inserted between header (math/BRDF) and programs (raygen etc.)
_CUDA_PROGRAMS = r"""
// --- ray generation (Step 3: full bounce loop) -------------------------------
extern "C" __global__ void __raygen__rg()
{
    const uint3 idx = optixGetLaunchIndex();

    // 1. Init RNG with pixel coordinates + sample index + frame seed
    unsigned int rng;
    rng_init(rng, idx.x, idx.y, params.sample_index, params.frame_seed);

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

    // MIS tracking: surface properties from previous hit for BRDF miss weighting
    int    is_delta_bounce = 0;
    float3 prev_N          = mk3(0.0f, 1.0f, 0.0f);
    int    prev_mat_id     = MAT_DIFFUSE;
    float  prev_ior        = 1.5f;
    float3 prev_incident   = mk3(0.0f, 0.0f, -1.0f);

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

            // MIS: when env sky NEE was performed at the previous hit,
            // weight this BRDF strategy sample against the light strategy
            if (params.sun_sampling && params.env_sky_nee
                && depth > 0 && !is_delta_bounce) {
                float brdf_pdf  = eval_brdf_pdf(
                    prev_incident, ray_dir, prev_N, prev_mat_id, prev_ior);
                float light_pdf = eval_env_sky_pdf(ray_dir);
                float mis_w     = power_heuristic(brdf_pdf, light_pdf);
                sky = sky * mis_w;
            }

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

        float3 albedo;
        int   mat_id;
        float ior;

        if (prim == 0xFFFFFFFFu) {
            // SDF hit: material from sdf_scene, albedo from sdf_get_albedo
            float2 sdf_mat = make_float2(__uint_as_float(p5), __uint_as_float(p6));
            mat_id = (int)floorf(sdf_mat.y);
            albedo = sdf_get_albedo(sdf_mat, P);
            ior    = sdf_get_ior(sdf_mat);
        } else {
            // Entity hit: check for emission (negative hue = emitter)
            float hue = entity_hue(prim);
            float3 emission = get_emission(hue, params.albedo_saturation, params.albedo_brightness);
            if (emission.x + emission.y + emission.z > 0.0f) {
                radiance = radiance + throughput * emission * params.emission_intensity;
                if (depth == 0 && params.albedo_buffer) {
                    const unsigned int pidx = idx.y * params.width + idx.x;
                    params.albedo_buffer[pidx] = make_float4(emission.x, emission.y, emission.z, 1.0f);
                    params.normal_buffer[pidx] = make_float4(N.x, N.y, N.z, 0.0f);
                }
                break;
            }
            albedo = hsv2rgb(hue, params.albedo_saturation, params.albedo_brightness);
            mat_id = params.global_material;
            ior    = params.glossy_ior;
        }

        // Guide buffers: primary hit -> surface albedo and normal
        if (depth == 0 && params.albedo_buffer) {
            const unsigned int pidx = idx.y * params.width + idx.x;
            params.albedo_buffer[pidx] = make_float4(albedo.x, albedo.y, albedo.z, 1.0f);
            params.normal_buffer[pidx] = make_float4(N.x, N.y, N.z, 0.0f);
        }

        // 4d. NEE: direct lighting via shadow ray
        if (params.sun_sampling) {
            float3 shadow_origin = P + 1e-4f * N;

            if (params.env_sky_nee) {
                // --- Environment sky NEE: importance-sample cosine-power lobes ---
                float3 light_dir;
                float  light_pdf;
                sample_env_sky(rng, light_dir, light_pdf);

                float NdotL = dot3(N, light_dir);
                if (NdotL > 0.0f && light_pdf > 1e-10f) {
                    unsigned int occluded = 1u;
                    optixTrace(
                        (OptixTraversableHandle)params.handle,
                        shadow_origin, light_dir,
                        0.0f, 1e16f, 0.0f,
                        OptixVisibilityMask(255),
                        OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
                        | OPTIX_RAY_FLAG_DISABLE_ANYHIT
                        | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
                        0, 0,
                        1,
                        occluded);

                    if (!occluded) {
                        float3 brdf_cos = eval_brdf_cos(
                            ray_dir, light_dir, N,
                            mat_id, albedo, ior);
                        float3 L_env = eval_env_sky(light_dir);
                        float brdf_pdf = eval_brdf_pdf(
                            ray_dir, light_dir, N, mat_id, ior);
                        float mis_w = power_heuristic(light_pdf, brdf_pdf);
                        radiance = radiance + throughput * brdf_cos
                                 * L_env * (mis_w / light_pdf);
                    }
                }
            } else {
                // --- Original directional sun NEE ---
                unsigned int occluded = 1u;
                optixTrace(
                    (OptixTraversableHandle)params.handle,
                    shadow_origin, params.sun_direction,
                    0.0f, 1e16f, 0.0f,
                    OptixVisibilityMask(255),
                    OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
                    | OPTIX_RAY_FLAG_DISABLE_ANYHIT
                    | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
                    0, 0,
                    1,
                    occluded);

                if (!occluded) {
                    float3 brdf_cos = eval_brdf_cos(
                        ray_dir, params.sun_direction, N,
                        mat_id, albedo, ior);
                    radiance = radiance + throughput * brdf_cos
                             * params.sun_color * params.sun_intensity;
                }
            }
        }

        // 4d'. Rasterize preset (merged sphere renderer): single-hit shading.
        // Add an AO-modulated fake-ambient term on top of the direct (NEE)
        // lighting above, then terminate — no secondary GI bounce. With NEE
        // off, only this ambient+AO term lights the hit.
        if (params.rasterize) {
            float ao_factor = 1.0f;
            if (params.ao_enabled && params.ao_num_rays > 0) {
                float3 ao_origin = P + 1e-4f * N;
                int ao_hits = 0;
                for (int ao_i = 0; ao_i < params.ao_num_rays; ao_i++) {
                    float3 ao_dir = sample_cosine_hemisphere(N, rng);
                    unsigned int ao_occluded = 1u;
                    optixTrace(
                        (OptixTraversableHandle)params.handle,
                        ao_origin, ao_dir,
                        0.0f, params.ao_radius, 0.0f,
                        OptixVisibilityMask(255),
                        OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
                        | OPTIX_RAY_FLAG_DISABLE_ANYHIT
                        | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
                        0, 0,
                        1,          // miss index: occlusion
                        ao_occluded);
                    ao_hits += ao_occluded ? 1 : 0;
                }
                ao_factor = 1.0f - (float)ao_hits / (float)params.ao_num_rays;
            }
            radiance = radiance
                     + throughput * albedo * params.ambient_color * ao_factor;
            break;
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
        int    is_delta_local;
        float3 weight = sample_brdf(ray_dir, N, mat_id, albedo, ior,
                                     bounce_dir, rng, is_delta_local);
        throughput = throughput * weight;

        // Track surface properties for MIS at potential next-bounce miss
        is_delta_bounce = is_delta_local;
        prev_N          = N;
        prev_mat_id     = mat_id;
        prev_ior        = ior;
        prev_incident   = ray_dir;

        // 4h. Self-intersection avoidance: offset origin along normal
        ray_origin = P + 1e-4f * N;
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
    float3 c;

    if (params.photosphere_enabled || params.env_sky_nee) {
        // Photosphere or cosine-lobe environment sky
        c = eval_env_sky(dir);
    } else {
        // Original gradient sky
        const float t = 0.5f * (dir.y + 1.0f);
        c = (1.0f - t) * params.sky_color_bottom
          + t * params.sky_color_top;
    }

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

// --- intersection (custom primitive: spheres + SDF) --------------------------
extern "C" __global__ void __intersection__sphere()
{
    const unsigned int prim = optixGetPrimitiveIndex();

    // SDF primitive: sphere trace instead of analytic sphere test
    if (params.sdf_enabled && prim == params.sdf_prim_index) {
        const float3 O = optixGetObjectRayOrigin();
        const float3 D = optixGetObjectRayDirection();
        const float tmin = optixGetRayTmin();
        const float tmax = optixGetRayTmax();

        float sdf_t;
        float2 sdf_mat;
        if (trace_sdf(O, D, fmaxf(tmin, SDF_SURFACE_EPS * 2.0f), tmax, sdf_t, sdf_mat))
            optixReportIntersection(sdf_t, 1);  // hit kind 1 = SDF
        return;
    }

    // Regular sphere intersection (hit kind 0)
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
    const float  t = optixGetRayTmax();
    const float3 P = optixGetWorldRayOrigin() + t * optixGetWorldRayDirection();

    if (optixGetHitKind() == 1) {
        // SDF hit: compute normal via gradient, pass material via payloads
        float3 N = sdf_normal(P);
        float2 mat = sdf_scene(P);

        optixSetPayload_0(__float_as_uint(t));     // hit distance (nonzero = hit)
        optixSetPayload_1(0xFFFFFFFFu);            // sentinel: SDF hit
        optixSetPayload_2(__float_as_uint(N.x));   // normal x
        optixSetPayload_3(__float_as_uint(N.y));   // normal y
        optixSetPayload_4(__float_as_uint(N.z));   // normal z
        optixSetPayload_5(__float_as_uint(mat.x)); // SDF distance (for scene re-eval)
        optixSetPayload_6(__float_as_uint(mat.y)); // SDF material ID
        return;
    }

    // Sphere hit: normal from center
    const float3 center = entity_center(prim);
    const float3 N = normalize3(P - center);

    // Report hit data via payloads
    optixSetPayload_0(__float_as_uint(t));    // hit distance (nonzero = hit)
    optixSetPayload_1(prim);                   // primitive index
    optixSetPayload_2(__float_as_uint(N.x));   // normal x
    optixSetPayload_3(__float_as_uint(N.y));   // normal y
    optixSetPayload_4(__float_as_uint(N.z));   // normal z
}

// --- closest hit for curve primitives (built-in IS, shading in raygen) --------
extern "C" __global__ void __closesthit__curve()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float  t = optixGetRayTmax();
    const float3 P = optixGetWorldRayOrigin() + t * optixGetWorldRayDirection();

    // Recompute control points from entity data (same formula as CPU-side)
    const float3 center = entity_center(prim);
    const float3 vel = entity_velocity(prim);
    const float  base_r = entity_radius(prim);

    float vel_len = sqrtf(dot3(vel, vel));
    float3 vel_norm;
    float has_vel;
    if (vel_len > 1e-6f) {
        vel_norm = (1.0f / vel_len) * vel;
        has_vel = 1.0f;
    } else {
        vel_norm = mk3(0.0f, 0.0f, 0.0f);
        has_vel = 0.0f;
    }

    float half_extent = has_vel * params.curve_length * base_r * 0.5f;
    float3 c0 = center - half_extent * vel_norm;
    float3 c1 = center + half_extent * vel_norm;

    // Normal: radial from the curve axis
    float3 axis = c1 - c0;
    float axis_len2 = dot3(axis, axis);
    float u_param = (axis_len2 > 1e-12f)
        ? clamp_f(dot3(P - c0, axis) / axis_len2, 0.0f, 1.0f)
        : 0.5f;
    float3 closest = c0 + u_param * axis;
    float3 N = normalize3(P - closest);

    optixSetPayload_0(__float_as_uint(t));
    optixSetPayload_1(prim);
    optixSetPayload_2(__float_as_uint(N.x));
    optixSetPayload_3(__float_as_uint(N.y));
    optixSetPayload_4(__float_as_uint(N.z));
}
"""


RESOLVE_TO_HALF_CUDA_SRC = r"""
// Resolve accumulation buffer to half-float (rgba16f) for OpenGL consumption.
// No tonemapping or gamma — that is handled by frame_assembly.frag on the GL side.

static __forceinline__ __device__ unsigned short f2h(float v) {
    unsigned short h;
    asm("cvt.rn.f16.f32 %0, %1;" : "=h"(h) : "f"(v));
    return h;
}

extern "C" __global__ void resolve_to_half(
    const float4* __restrict__ accum,
    unsigned short* __restrict__ image,
    unsigned int  width,
    unsigned int  height,
    unsigned int  samples_accumulated,
    unsigned int  flip_y)
{
    const unsigned int x = blockIdx.x * blockDim.x + threadIdx.x;
    const unsigned int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    const unsigned int idx = y * width + x;
    float4 hdr = accum[idx];

    // Average over accumulated samples (output linear HDR, no tonemap/gamma)
    float inv_n = 1.0f / fmaxf((float)samples_accumulated, 1.0f);
    float r = hdr.x * inv_n;
    float g = hdr.y * inv_n;
    float b = hdr.z * inv_n;

    // Conditional Y-flip for OpenGL convention
    const unsigned int out_y = flip_y ? (height - 1u - y) : y;
    const unsigned int out_idx = (out_y * width + x) * 4;
    image[out_idx + 0] = f2h(r);
    image[out_idx + 1] = f2h(g);
    image[out_idx + 2] = f2h(b);
    image[out_idx + 3] = f2h(1.0f);
}
"""


# Compose the full path tracer CUDA source: header + SDF scene + programs
PATHTRACER_CUDA_SRC = _CUDA_HEADER + "\n" + SDF_SCENE_CUDA_SRC + "\n" + _CUDA_PROGRAMS


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
