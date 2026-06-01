#version 430

layout(std430, binding = 0) buffer EntityBuffer {
    float data[];  // stride 8 floats per entity: px,py,pz,vx,vy,vz,hue,size
};

uniform mat4 u_view_proj;

void main() {
    int base = gl_VertexID * 8;
    vec3 pos = vec3(data[base], data[base + 1], data[base + 2]);
    gl_Position = u_view_proj * vec4(pos, 1.0);
    gl_PointSize = 2.0;
}
