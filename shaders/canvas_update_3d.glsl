#version 450
layout(local_size_x = 4, local_size_y = 4, local_size_z = 4) in;

// 3D canvas texture for reading (packed RGBA16F: R=vx, G=vy, B=vz)
uniform sampler3D can_tex;

// 3D canvas image for writing (packed RGBA16F)
layout(rgba16f, binding = 0) uniform image3D can_out;

uniform ivec3 canvas_3d_size;  // (W, H, D) — supports non-cube shapes
// TESTING_MODE (2D XY-only path) removed in the 3D-only cleanup; always 3D now.
const bool TESTING_MODE = false;
uniform int BOUNDARY_CONDITIONS_MODE; // 0=Bounce, 1=Reset, 2=Wrap
uniform int frame_count;

// SYNCHRONIZED: This struct must match entity_update.glsl and canvas.frag
struct PhysicsSetting {
    float slider_value;
    float min_value;
    float max_value;
    float x_sweep;
    float y_sweep;
    float cohort_sweep;
    float jitter;
};

uniform PhysicsSetting TRAIL_PERSISTENCE_SETTING;
uniform PhysicsSetting TRAIL_DIFFUSION_SETTING;

// Simplified calculate_setting for canvas (no cohort, uses position-based sweeps)
float calculate_setting(PhysicsSetting setting, vec2 pos) {
    if (setting.y_sweep == 0.0 && setting.x_sweep == 0.0 && setting.jitter == 0.0)
        return setting.slider_value;

    pos = (pos + 1.0) / 2.0;
    float result = 0.0;
    int active_sweeps = 0;

    if (setting.x_sweep != 0.0) {
        if (setting.x_sweep > 0.0)
            result += mix(setting.min_value, setting.max_value, pos.x);
        else
            result += mix(setting.max_value, setting.min_value, pos.x);
        active_sweeps++;
    }
    if (setting.y_sweep != 0.0) {
        if (setting.y_sweep > 0.0)
            result += mix(setting.min_value, setting.max_value, pos.y);
        else
            result += mix(setting.max_value, setting.min_value, pos.y);
        active_sweeps++;
    }

    result = active_sweeps > 0 ? result / float(active_sweeps) : setting.slider_value;

    if (setting.jitter != 0.0) {
        float random = fract(sin(dot(pos + float(frame_count) * 0.01, vec2(12.9898, 78.233))) * 43758.5453) * 2.0 - 1.0;
        result += setting.jitter * result * random;
    }

    return result;
}

// Read a voxel with boundary handling
ivec3 wrap_coord(ivec3 coord) {
    if (BOUNDARY_CONDITIONS_MODE == 2) {
        // Wrap mode
        coord = ((coord % canvas_3d_size) + canvas_3d_size) % canvas_3d_size;
    } else {
        // Clamp for bounce/reset modes
        coord = clamp(coord, ivec3(0), canvas_3d_size - 1);
    }
    return coord;
}

vec3 fetch3(ivec3 coord) {
    coord = wrap_coord(coord);
    return texelFetch(can_tex, coord, 0).rgb;
}

// Diffusion blur: 4-neighbor (XY only) in TESTING_MODE, 6-neighbor (3D) otherwise
vec3 getBlur3D(ivec3 pos, float K) {
    vec3 center = fetch3(pos);
    vec3 sum = vec3(0.0);
    int neighbor_count;

    // Always include XY neighbors
    sum += fetch3(pos + ivec3(1, 0, 0));
    sum += fetch3(pos + ivec3(-1, 0, 0));
    sum += fetch3(pos + ivec3(0, 1, 0));
    sum += fetch3(pos + ivec3(0, -1, 0));

    if (TESTING_MODE || canvas_3d_size.z <= 1) {
        // 4-neighbor blur in XY only (matches 2D behavior)
        neighbor_count = 4;
    } else {
        // 6-neighbor 3D blur
        sum += fetch3(pos + ivec3(0, 0, 1));
        sum += fetch3(pos + ivec3(0, 0, -1));
        neighbor_count = 6;
    }

    return (center * K + sum) / (float(neighbor_count) + K);
}

void main() {
    ivec3 pos = ivec3(gl_GlobalInvocationID);
    if (any(greaterThanEqual(pos, canvas_3d_size))) return;

    // Clear on frame 0
    if (frame_count == 0) {
        imageStore(can_out, pos, vec4(0.0));
        return;
    }

    // Map voxel position to entity space for parameter sweeps (XY only)
    vec2 entity_space_pos = (vec2(pos.xy) / vec2(canvas_3d_size.xy) * 2.0 - 1.0);
    // Scale by aspect ratio like canvas.frag does
    float _ca = float(canvas_3d_size.x) / float(canvas_3d_size.y);
    entity_space_pos *= vec2(sqrt(_ca), 1.0 / sqrt(_ca));

    float TRAIL_DIFFUSION = calculate_setting(TRAIL_DIFFUSION_SETTING, entity_space_pos);
    TRAIL_DIFFUSION = clamp(TRAIL_DIFFUSION, 0.001, 1.0);

    vec3 can_color;
    if (TRAIL_DIFFUSION > 0.0) {
        TRAIL_DIFFUSION = TRAIL_DIFFUSION * TRAIL_DIFFUSION;
        TRAIL_DIFFUSION = 4.0 / (pow(5.0, TRAIL_DIFFUSION) - 1.0);
        can_color = getBlur3D(pos, TRAIL_DIFFUSION);
    } else {
        can_color = fetch3(pos);
    }

    float trail_persistence = calculate_setting(TRAIL_PERSISTENCE_SETTING, entity_space_pos);
    trail_persistence = clamp(trail_persistence, 0.0, 0.999);

    vec3 result = can_color * trail_persistence;

    imageStore(can_out, pos, vec4(result, 0.0));
}
