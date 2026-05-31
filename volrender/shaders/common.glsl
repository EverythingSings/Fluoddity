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

// Step 5: RNG (PCG hash), AABB slab intersection, ray-gen helpers
