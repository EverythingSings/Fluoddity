#version 430

in vec2 in_vert;
out vec2 v_uv;

void main() {
    v_uv = in_vert * 0.5 + 0.5;
    gl_Position = vec4(in_vert, 0.0, 1.0);
}
