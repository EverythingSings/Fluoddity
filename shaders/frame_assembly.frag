#version 330 core
uniform sampler2D input_frame;
uniform sampler2D accumulation_buffer;
uniform bool is_first_frame;
uniform bool final_sample;
uniform int view_mode;  // 0=can, 1=brush_tex, 2=cam_brush

in vec2 uv;
out vec4 fragColor;

// TOTAL_SAMPLES placeholder - will be replaced by Python during shader creation
const int TOTAL_SAMPLES = {total_samples};

vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

void main() {
    // Sample the input frame
    vec3 current_color = texture(input_frame, uv).rgb;

    // Divide by number of samples (for averaging)
    current_color /= float(TOTAL_SAMPLES);

    // Add to or replace accumulation
    if (is_first_frame) {
        fragColor = vec4(current_color, 1.0);
    } else {
        vec3 previous_accumulation = texture(accumulation_buffer, uv).rgb;
        fragColor = vec4(previous_accumulation + current_color, 1.0);
    }

    // Apply gamma correction only on final sample (AFTER accumulation)
    if (final_sample) {
        //if we are in canvas or brush view, we must interpret raw texture before gamma correction and display:
        if(view_mode !=2){
            fragColor.xyz = 8*hsv2rgb(vec3(atan(fragColor.y,fragColor.x)/2./3.1415,.75,length(fragColor.xy)));
        }
        // SYNC WITH cam_brush_pp.frag line 42-43
        float len = length(fragColor.xyz);
        if (len > 0.0) {
            fragColor.xyz /= pow(len, 0.575);
        }
    }
}
