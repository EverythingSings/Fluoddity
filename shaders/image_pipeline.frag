#version 330 core
// Image-pipeline core: temporal accumulation + tonemap + watercolor.
// Split out of the old frame_assembly.frag in Step 7 — overlay markup (sweep
// reticle, draw-trail ring, advanced-drawing field overlay) now lives in a
// separate overlay pass (overlay.frag / OverlayCompositor) that runs AFTER this,
// so the accumulation texture this produces is markup-free (correct for video).
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
uniform float INK_WEIGHT;           // Watercolor mode: controls optical density in exp()
uniform bool WATERCOLOR_MODE;       // Whether to use watercolor rendering

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

    // In watercolor mode, convert from log-space optical density to linear transmission
    if (WATERCOLOR_MODE) {
        // INK_WEIGHT controls optical density - higher = darker/more opaque
        #define INK_CONSTANT 10
        current_color = exp(INK_WEIGHT*INK_CONSTANT * current_color);
    }
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
