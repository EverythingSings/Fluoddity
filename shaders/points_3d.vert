#version 450

//SYNC WITH ENTITY_UPDATE.GLSL
struct Entity {
    float px, py, pz;    // position (3D)
    float vx, vy, vz;    // velocity (3D)
    float hue;
    float size;
};  // Total: 32 bytes (8 floats)

layout(std430, binding = 0) buffer EntityBuffer {
    Entity entities[];
};

uniform mat4 view_proj;   // Combined view * projection matrix
uniform float point_scale; // Point size scaling factor

out float v_hue;
out float v_depth;

void main() {
    int id = gl_VertexID;
    float size = entities[id].size;

    // Skip zero-size entities by placing outside clip volume
    if (size <= 0.0) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 1.0;
        v_hue = 0.0;
        v_depth = 0.0;
        return;
    }

    vec3 pos = vec3(entities[id].px, entities[id].py, entities[id].pz);
    vec4 clip_pos = view_proj * vec4(pos, 1.0);
    gl_Position = clip_pos;

    // Scale point size by perspective divide, clamped to reasonable range
    float perspective_size = point_scale * size / max(clip_pos.w, 0.001);
    gl_PointSize = clamp(perspective_size, 1.0, 64.0);

    v_hue = entities[id].hue;
    v_depth = clip_pos.z / clip_pos.w; // Normalized depth for potential depth-based effects
}
