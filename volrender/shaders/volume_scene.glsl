// volrender/shaders/volume_scene.glsl
//
// SDF scene definition and surface shading for the path tracer.
// Included (via string prepend) into pathtrace.comp after common.glsl.
//
// This file is standalone so it can also be included in the physics
// system for particle-surface interactions.
//
// EDIT THIS FILE to define your scene geometry and material properties.
// The scene() function and material lookups are hardcoded here —
// modify them directly for different scenes.
//
// NOTE: This file is NOT a standalone compilation unit. common.glsl
// must be prepended first (provides next_float(), sample_sphere()).

// ---- material ID constants ----
// scene(p).y encodes: floor = BRDF type, fract = sub-ID (for future use)
const float MAT_DIFFUSE = 0.0;
const float MAT_GLOSSY  = 1.0;
const float MAT_MIRROR  = 2.0;


// ====================================================================
// SDF primitives
// ====================================================================

float sd_sphere(vec3 p, vec3 center, float radius) {
    return length(p - center) - radius;
}

float sd_plane(vec3 p, vec3 normal, float offset) {
    return dot(p, normal) - offset;
}

float sd_box(vec3 p, vec3 center, vec3 half_extents) {
    vec3 q = abs(p - center) - half_extents;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}


// ====================================================================
// Boolean operations
// ====================================================================

vec2 sdf_union(vec2 a, vec2 b) {
    return (a.x < b.x) ? a : b;
}

vec2 sdf_subtract(vec2 a, vec2 b) {
    // a minus b
    return (-b.x > a.x) ? vec2(-b.x, b.y) : a;
}

vec2 sdf_intersect(vec2 a, vec2 b) {
    return (a.x > b.x) ? a : b;
}


// ====================================================================
// Scene definition — EDIT THIS
//
// Returns vec2(signed_distance, material_id)
// Material encoding: floor(y) = BRDF type, fract(y) = sub-ID
// ====================================================================

vec2 scene(vec3 p) {
    p*=2.;
    p.xz = abs(p.xz);
    float dts = sd_box(p,vec3(0),vec3(.5));
    p-=.5;
    dts = min(dts, (length(p)-.25));
    dts = min(dts, sd_box(p,vec3(0),vec3(.1,.6,.1)));
    return vec2(dts/2.,MAT_DIFFUSE);


    // Dark diffuse ground plane at y = -1
    //vec2 ground = vec2(sd_plane(p, vec3(0.0, 1.0, 0.0), -.80),
    //                   MAT_DIFFUSE + 0.0);
    //vec2 wall = vec2(p.x+.95,MAT_DIFFUSE+.2);
    //vec2 wall2 = vec2(p.z+.95,MAT_DIFFUSE+.4);
    //ground= sdf_union(ground,wall);
    //ground = sdf_union(ground, wall2);
    // Reflective sphere at origin
    //p-=vec3(.25,.25,.25);
    //vec2 sphere = vec2(length(p)-.25,
    //                   MAT_MIRROR + 0.0);

    //return ground;//sdf_union(ground, sphere);
}


// ====================================================================
// Material property lookups — EDIT THESE for your scene
//
// Use fract(mat.y) to distinguish objects sharing the same BRDF class.
// ====================================================================

vec3 sdf_get_albedo(vec2 mat) {
    float id = floor(mat.y);
    if (id == MAT_DIFFUSE) {
    float fm = fract(mat.y);
    if(fm == 0){
    return vec3(0.2);   // dark ground
    }
    else if(fm ==.2){
        return vec3(0.34,.02,.02);
    }
    else{
        return vec3(.14,.38,.14);
    }

    }
    return vec3(0.9);                            // bright reflector/glossy
}

float sdf_get_ior(vec2 mat) {
    // Index of refraction for glossy Fresnel. Unused by diffuse/mirror.
    return 1.5;   // glass-like
}


// ====================================================================
// SDF normal via tetrahedral 4-tap gradient (saves 2 evals vs central diff)
// ====================================================================

vec3 sdf_normal(vec3 p) {
    const float h = 1e-4;
    const vec2 k = vec2(1.0, -1.0);
    return normalize(
        k.xyy * scene(p + k.xyy * h).x +
        k.yyx * scene(p + k.yyx * h).x +
        k.yxy * scene(p + k.yxy * h).x +
        k.xxx * scene(p + k.xxx * h).x
    );
}


// ====================================================================
// Nearest surface point via SDF projection
//
// Assumes scene() is a true distance function.
// Returns p - f(p) * grad(f)(p), the closest point on the surface.
// ====================================================================

vec3 nearest_surf(vec3 p) {
    return p - scene(p).x * sdf_normal(p);
}


// ====================================================================
// Sphere tracing
//
// Returns true if SDF geometry is hit within [t_min, t_max].
// On hit: out_t = parametric distance, out_mat = scene(hit_pos).
// ====================================================================

const int   SDF_MAX_STEPS   = 356;
const float SDF_SURFACE_EPS = 2e-4;
const float SDF_MAX_DIST    = 60.0;

bool trace_sdf(vec3 origin, vec3 dir, float t_min, float t_max,
               out float out_t, out vec2 out_mat) {
    float t = t_min;
    for (int i = 0; i < SDF_MAX_STEPS; i++) {
        vec3 p = origin + t * dir;
        vec2 d = scene(p);
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

bool sdf_shadow_test(vec3 origin, vec3 dir, float t_min, float t_max) {
    float t = t_min;
    for (int i = 0; i < SDF_MAX_STEPS; i++) {
        vec3 p = origin + t * dir;
        float d = scene(p).x;
        if (d < SDF_SURFACE_EPS)
            return true;   // occluded
        t += d;
        if (t > t_max)
            return false;
    }
    return false;
}


// ====================================================================
// Cosine-weighted hemisphere sampling
//
// Uses the normal + random sphere point trick (Shirley):
// normalize(N + random_on_sphere) gives a cosine-distributed direction.
// ====================================================================

vec3 sample_cosine_hemisphere(vec3 n) {
    return normalize(n + sample_sphere());
}


// ====================================================================
// Fresnel utilities
// ====================================================================

float ior_to_r0(float ior) {
    float r = (ior - 1.0) / (ior + 1.0);
    return r * r;
}

float schlick_fresnel(float cos_theta, float R0) {
    float x = clamp(1.0 - cos_theta, 0.0, 1.0);
    return R0 + (1.0 - R0) * x * x * x * x * x;
}


// ====================================================================
// BRDF sampling
//
// Given incident direction (pointing TOWARD surface), normal, and
// material, samples an outgoing direction and returns throughput weight
// (= BRDF * cos(theta) / PDF).
//
// Diffuse:  cosine hemisphere, weight = albedo
// Mirror:   reflect, weight = albedo
// Glossy:   Schlick Fresnel decides mirror vs diffuse, weight = albedo
// ====================================================================

vec3 sample_brdf(vec3 incident, vec3 normal, vec2 mat, out vec3 out_dir) {
    float mat_id = floor(mat.y);
    vec3 albedo = sdf_get_albedo(mat);

    if (mat_id == MAT_MIRROR) {
        out_dir = reflect(incident, normal);
        return albedo;
    }

    if (mat_id == MAT_GLOSSY) {
        float cos_i = abs(dot(-incident, normal));
        float R0 = ior_to_r0(sdf_get_ior(mat));
        float R = schlick_fresnel(cos_i, R0);
        if (next_float() < R) {
            out_dir = reflect(incident, normal);
            return albedo;
        } else {
            out_dir = sample_cosine_hemisphere(normal);
            return albedo;
        }
    }

    // MAT_DIFFUSE: Lambertian
    out_dir = sample_cosine_hemisphere(normal);
    return albedo;
}


// ====================================================================
// BRDF * cos(theta) evaluation for NEE (direct light sampling)
//
// Returns the contribution for a given light direction. Delta lobes
// (mirror, glossy specular lobe) return 0 since a point light has
// zero probability of being hit by a delta BRDF.
// ====================================================================

vec3 eval_brdf_cos(vec3 incident, vec3 light_dir, vec3 normal, vec2 mat) {
    float mat_id = floor(mat.y);
    vec3 albedo = sdf_get_albedo(mat);
    float NdotL = max(dot(normal, light_dir), 0.0);

    if (mat_id == MAT_MIRROR) {
        return vec3(0.0);   // delta BRDF, no NEE contribution
    }

    if (mat_id == MAT_GLOSSY) {
        // Only the diffuse lobe contributes to NEE
        float cos_i = abs(dot(-incident, normal));
        float R0 = ior_to_r0(sdf_get_ior(mat));
        float R = schlick_fresnel(cos_i, R0);
        return (1.0 - R) * albedo * NdotL / 3.141592653589793;
    }

    // MAT_DIFFUSE: Lambertian BRDF = albedo/pi
    return albedo * NdotL / 3.141592653589793;
}
