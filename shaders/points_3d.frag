#version 450

in float v_hue;
in float v_depth;
out vec4 frag_color;

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    // Circular point shape from gl_PointCoord
    vec2 coord = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(coord, coord);
    if (r2 > 1.0) discard;

    vec3 color = hsv2rgb(vec3(v_hue, 0.8, 1.0));
    float alpha = 0.15 * (1.0 - r2); // Soft falloff
    frag_color = vec4(color, alpha);
}
