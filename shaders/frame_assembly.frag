#version 330 core
uniform sampler2D input_frame;
uniform sampler2D accumulation_buffer;
uniform bool is_first_frame;
uniform bool final_sample;
uniform int view_mode;  // 0=can, 1=brush_tex, 2=cam_brush
uniform bool PARAMETER_SWEEP_MODE;  // Whether parameter sweeps are active
uniform vec2 sweep_reticle_pos;     // Screen UV position of sweep reticle (0-1 range)
uniform bool sweep_reticle_visible; // Whether to show the reticle
uniform float screen_aspect;        // Screen width/height for aspect-correct circles

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

vec3 sweep_overlay(vec2 uv_coord) {
    uv_coord.y=1-uv_coord.y;//flip y axis
    // Draw a crosshair/reticle at the sweep target position
    if (!sweep_reticle_visible) {
        return vec3(0.0);
    }

    // Calculate delta with aspect ratio correction for proper circles
    vec2 delta = uv_coord - sweep_reticle_pos;
    delta.x *= screen_aspect;  // Correct for aspect ratio

    float dist = length(delta);

    // Reticle parameters (in corrected space)
    float inner_radius = 0.02;
    float outer_radius = 0.03;
    float line_thickness = 0.004;
    float crosshair_length = 0.05;

    // Circular ring
    float ring = smoothstep(inner_radius - line_thickness, inner_radius, dist)
               - smoothstep(outer_radius, outer_radius + line_thickness, dist);

    // Crosshair lines extending from the ring (also aspect-corrected)
    float cross_x = step(abs(delta.y), line_thickness)
                  * step(outer_radius, abs(delta.x))
                  * step(abs(delta.x), crosshair_length);
    float cross_y = step(abs(delta.x), line_thickness)
                  * step(outer_radius, abs(delta.y))
                  * step(abs(delta.y), crosshair_length);

    float reticle = max(ring, max(cross_x, cross_y));

    // White reticle with slight transparency effect
    return vec3(reticle * 0.8);
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
        float len = length(fragColor.xyz);
        if (len > 0.0) {
            fragColor.xyz /= pow(len, 0.575);
        }

    }
        if(PARAMETER_SWEEP_MODE){
            fragColor.xyz += sweep_overlay(uv);
        }
}
