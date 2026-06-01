#version 430

out vec4 frag_color;

void main() {
    // Circular falloff from gl_PointCoord
    vec2 coord = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(coord, coord);
    if (r2 > 1.0) discard;

    float alpha = 0.4 * (1.0 - r2);
    frag_color = vec4(1.0, 1.0, 0.6, alpha);
}
