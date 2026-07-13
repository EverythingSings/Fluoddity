#version 330 core
// Overlay markup pass — runs AFTER the image pipeline over a finished frame.
// Adds the parameter-sweep reticle. Split out of frame_assembly.frag in Step 7
// so markup is renderer-agnostic and never baked into recorded frames.
// (The draw-trail ring and advanced-drawing field overlay were removed in the
// 3D-only cleanup along with the drawing mode.)
uniform sampler2D input_frame;      // the finished, tonemapped frame

uniform bool PARAMETER_SWEEP_MODE;  // Whether parameter sweeps are active
uniform vec2 sweep_reticle_pos;     // Screen UV position of sweep reticle (0-1 range)
uniform bool sweep_reticle_visible; // Whether to show the reticle
uniform float screen_aspect;        // Screen width/height for aspect-correct circles
uniform bool WATERCOLOR_MODE;       // Whether watercolor mode (flips overlay sign)
uniform float EXPOSURE;             // Long-exposure amount (unused; kept for compat)

in vec2 uv;
out vec4 fragColor;

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
    fragColor = vec4(texture(input_frame, uv).rgb, 1.0);

    // Sweep reticle
    if(PARAMETER_SWEEP_MODE){
        fragColor.xyz += sweep_overlay(uv)* (WATERCOLOR_MODE?-1:1);
    }
}
