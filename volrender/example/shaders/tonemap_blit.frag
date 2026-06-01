#version 430

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_hdr_image;
uniform float u_exposure;  // default 1.0

void main() {
    vec3 hdr = texture(u_hdr_image, v_uv).rgb;

    // Exposure
    vec3 exposed = hdr * u_exposure;

    // Reinhard tonemap
    vec3 ldr = exposed / (1.0 + exposed);

    // Gamma correction (linear -> sRGB approx)
    ldr = pow(ldr, vec3(1.0 / 2.2));

    frag_color = vec4(ldr, 1.0);
}
