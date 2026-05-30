#version 450
layout(local_size_x = 16, local_size_y = 16) in;

// Extract a single z-slice from a 3D canvas texture into a 2D texture.
// Used for the canvas debug view instead of expensive CPU readback.

uniform sampler3D source_3d;
uniform int slice_z;
uniform ivec3 canvas_3d_size;

layout(r32f, binding = 0) uniform image2D dest_2d;

void main() {
    ivec2 pos = ivec2(gl_GlobalInvocationID.xy);
    if (pos.x >= canvas_3d_size.x || pos.y >= canvas_3d_size.y) return;

    int z = clamp(slice_z, 0, canvas_3d_size.z - 1);
    float val = texelFetch(source_3d, ivec3(pos, z), 0).r;
    imageStore(dest_2d, pos, vec4(val));
}
