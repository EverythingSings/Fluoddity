#version 330 core
// Image-pipeline core: temporal accumulation + tonemap.
// Split out of the old frame_assembly.frag in Step 7. Produces a markup-free
// accumulation texture (correct for video); there is no overlay pass anymore.
uniform sampler2D input_frame;
uniform sampler2D accumulation_buffer;
uniform bool is_first_frame;
uniform bool final_sample;
uniform float BRIGHTNESS;           // Global brightness multiplier (applied before gamma)
// EXPOSURE (frame-blend long-exposure knob) was removed in the 3D-only cleanup
// — it was always 0. Kept as a compile-time const so the accumulation math is
// unchanged (EXPOSURE=0 = plain motion-blur accumulation).
const float EXPOSURE = 0.0;
uniform float TONEMAP_SOFTNESS;    // Asinh stretch parameter (higher = more highlight compression)
#define BRIGHTNESS_CONSTANT (3.*BRIGHTNESS)

in vec2 uv;
out vec4 fragColor;

// TOTAL_SAMPLES placeholder - will be replaced by Python during shader creation
const int TOTAL_SAMPLES = {total_samples};

vec3 safenorm(vec3 n){
    float l = length(n);
    return l>0?n/l:vec3(0);
}

void main() {
    // Sample the input frame
    vec3 current_color = texture(input_frame, uv).rgb;

    // Divide by number of samples (for averaging)
    current_color /= float(TOTAL_SAMPLES);

    // Add to or replace accumulation
    if (is_first_frame) {
        vec3 previous_frame = texture(accumulation_buffer, uv).rgb;
        float previous_len = length(previous_frame);
        previous_frame=safenorm(previous_frame)*sinh(previous_len*TONEMAP_SOFTNESS)/TONEMAP_SOFTNESS;
        previous_frame/=BRIGHTNESS_CONSTANT;
        fragColor = vec4(mix(current_color,previous_frame,EXPOSURE-.0001), 1.0);
    } else {
        vec3 previous_accumulation = texture(accumulation_buffer, uv).rgb;
        fragColor = vec4(previous_accumulation + (1.0001-EXPOSURE)*current_color, 1.0);
    }

    // Apply gamma correction only on final sample (AFTER accumulation)
    if (final_sample) {
        // Apply brightness multiplier before gamma correction
        fragColor.xyz *= BRIGHTNESS_CONSTANT;
        float len = length(fragColor.xyz);
        if (len > 0.0) {
            fragColor.xyz *= asinh(len * TONEMAP_SOFTNESS) / (len * TONEMAP_SOFTNESS);
        }
    }
}
