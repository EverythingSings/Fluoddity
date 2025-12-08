#version 430

uniform int kernel_mode;
in vec2 uv;
in vec4 pos_vel;
in vec4 view_col;
layout(location = 0) out vec4 brush_out;
layout(location = 1) out vec4 view_brush_out;

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
    float kernel_func=gaussian(uv-.5,.163);//6*(.5-length(uv-.5));
    float particle_kernel=mix(kernel_func,1,kernel_mode);
    if (length(uv-.5)>.5||view_col.w==0){discard;}//particle_kernel=0;}
    vec2 vel=pos_vel.zw;
    brush_out = vec4(vel,1,1)*particle_kernel;
    vec3 hsv_viewcol=hsv2rgb(view_col.xyz);
    view_brush_out=vec4(hsv_viewcol, view_col.w*particle_kernel);
}