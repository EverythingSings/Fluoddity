#version 430

uniform float BRIGHTNESS;
in vec2 uv;
in vec4 pos_vel;
in vec4 view_col;
out vec4 cam_brush_out;

vec3 hsv2rgb(vec3 c) {
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

float gaussian(vec2 pos, float sigma) {
    float sigma2 = sigma * sigma;
    float norm = 1.0 / (2.0 * 3.14159265359 * sigma2);
    float exponent = -(dot(pos, pos)) / (2.0 * sigma2);
    return norm * exp(exponent);
}

void main() {
    vec2 scaluv = uv - .5;
    float kernel_func = .5 * gaussian(scaluv, .163);

    // Discard fragments outside circular particle boundary or with zero alpha
    if (length(uv - 0.5) > 0.5 || view_col.w == 0.0) {
        discard;
    }

    // Output directly to viewport
    vec3 hsv_viewcol = hsv2rgb(view_col.xyz);
    cam_brush_out = vec4(hsv_viewcol, BRIGHTNESS * view_col.w * kernel_func);
}
