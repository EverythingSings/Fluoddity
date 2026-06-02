// volrender/shaders/common.glsl
//
// Shared GLSL utilities for the volumetric path tracer.
// Included (via string prepend) into splat, majorant, and pathtrace shaders.
//
// NOTE: This file is NOT a standalone compilation unit.  The including
// shader must supply `#version 430` before this block is inserted.

// ---- grid uniforms (set by Python each dispatch) ----
uniform vec3  u_bounds_min;
uniform vec3  u_bounds_max;
uniform vec3  u_resolution;       // float cast of integer grid dims
uniform float u_voxel_volume;

// ---- world <-> grid coordinate transforms ----

// bounds_min -> (0,0,0),  bounds_max -> resolution
vec3 world_to_grid(vec3 world_pos) {
    return (world_pos - u_bounds_min) / (u_bounds_max - u_bounds_min) * u_resolution;
}

// (0,0,0) -> bounds_min,  resolution -> bounds_max
vec3 grid_to_world(vec3 grid_pos) {
    return grid_pos / u_resolution * (u_bounds_max - u_bounds_min) + u_bounds_min;
}

// ---- RNG (PCG hash) ----
// Seed from (pixel.x, pixel.y, global_sample_index); mix bounce index
// into the stream so bounces decorrelate.

uint rng_state;

void rng_init(uvec3 seed) {
    rng_state = seed.x * 1664525u + seed.y * 1013904223u
              + seed.z * 214013u + 2531011u;
    // Warm up — one full PCG step + output hash
    rng_state = rng_state * 747796405u + 2891336453u;
    rng_state = ((rng_state >> ((rng_state >> 28u) + 4u)) ^ rng_state) * 277803737u;
    rng_state ^= rng_state >> 22u;
}

float next_float() {
    rng_state = rng_state * 747796405u + 2891336453u;
    uint word = ((rng_state >> ((rng_state >> 28u) + 4u)) ^ rng_state) * 277803737u;
    word ^= word >> 22u;
    return float(word) / 4294967295.0;
}

vec3 next_float3() {
    return vec3(next_float(), next_float(), next_float());
}

// ---- uniform sphere sampling ----
// Analytic cos-theta / sin-theta method: branchless, exactly 2 random
// draws, no rejection waste.  Used for isotropic phase function and
// cosine-weighted hemisphere sampling (via the N + sphere trick).

vec3 sample_sphere() {
    float xi1 = next_float();
    float xi2 = next_float();
    float cos_theta = 1.0 - 2.0 * xi1;          // uniform in [-1, +1]
    float sin_theta = sqrt(max(0.0, 1.0 - cos_theta * cos_theta));
    float phi = 6.283185307 * xi2;               // 2*pi
    return vec3(sin_theta * cos(phi),
                sin_theta * sin(phi),
                cos_theta);
}

// ---- AABB slab intersection ----
// Returns true if the ray [origin, origin + dir*t] intersects the AABB.
// On hit, t_near/t_far give the parametric interval (t_near may be < 0
// if the origin is inside the box).  Uses IEEE inf arithmetic to handle
// axis-aligned rays (dir component == 0) without explicit guards.

bool intersect_aabb(vec3 origin, vec3 dir, vec3 box_min, vec3 box_max,
                    out float t_near, out float t_far) {
    vec3 inv_dir = 1.0 / dir;
    vec3 t0 = (box_min - origin) * inv_dir;
    vec3 t1 = (box_max - origin) * inv_dir;
    vec3 tmin = min(t0, t1);
    vec3 tmax = max(t0, t1);
    t_near = max(max(tmin.x, tmin.y), tmin.z);
    t_far  = min(min(tmax.x, tmax.y), tmax.z);
    return t_far >= max(t_near, 0.0);
}
