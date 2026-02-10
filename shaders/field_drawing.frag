#version 430

// Force/Strafe field drawing shader.
// Runs once per render frame (60fps), NOT per physics frame.
// Output .xy = force field contribution, .zw = strafe field contribution.
// Uses additive blending (ONE, ONE) for drawing; no blending for erasing.

in vec2 texcoord;
out vec4 fragColor;

// Draw mode uniforms (mirror canvas.frag)
uniform bool draw_mode;
uniform bool erase_mode;
uniform vec2 mouse;
uniform vec2 previous_mouse;
uniform float draw_size;
uniform float draw_power;
uniform bool tiling_mode;

// Advanced drawing uniforms
// brush_mode codes: 0=mouse_dir, 1=inverse, 2=fixed, 3=attract, 4=repel
uniform int brush_mode;
uniform float fixed_direction_heading;
uniform bool force_field_active;
uniform bool strafe_field_active;

// Fill operation
uniform bool fill_mode;
uniform int fill_direction_type;  // 0=fixed, 1=radial_in, 2=radial_out

// Gaussian kernel (same as canvas.frag)
float draw_kernel(float distance, float size) {
    float sigma = size;
    return exp(-distance * distance / (2.0 * sigma * sigma));
}

// Calculate draw vector based on brush mode
vec2 calculate_draw_vector(int mode, vec2 mouse_vel, float heading,
                           vec2 pixel_pos, vec2 mouse_p) {
    if (mode == 0) {
        return mouse_vel;                       // Mouse Direction
    } else if (mode == 1) {
        return -mouse_vel;                      // Inverse Mouse Direction
    } else if (mode == 2) {
        return vec2(sin(heading), cos(heading)); // Fixed Direction (0 = up)
    } else if (mode == 3) {
        // In - Attract (toward mouse)
        vec2 to_mouse = mouse_p - pixel_pos;
        float len = length(to_mouse);
        return len > 0.0 ? to_mouse / len : vec2(0.0);
    } else if (mode == 4) {
        // Out - Repel (away from mouse)
        vec2 from_mouse = pixel_pos - mouse_p;
        float len = length(from_mouse);
        return len > 0.0 ? from_mouse / len : vec2(0.0);
    }
    return vec2(0.0);
}

// Tiling-corrected distance to mouse (returns distance and best mouse velocity)
void tiling_distance(vec2 frag_pos, vec2 mouse_p, vec2 prev_mouse_p, bool tiling,
                     out float dist, out vec2 best_velocity) {
    if (tiling) {
        float min_distance = 999.0;
        vec2 min_velocity = vec2(999.0);
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
                vec2 wrapped_mouse = mouse_p + vec2(dx, dy);
                float d = length(frag_pos - wrapped_mouse);
                min_distance = min(min_distance, d);
                vec2 vel = wrapped_mouse - prev_mouse_p;
                min_velocity = length(vel) < length(min_velocity) ? vel : min_velocity;
            }
        }
        dist = min_distance;
        best_velocity = min_velocity;
    } else {
        dist = length(frag_pos - mouse_p);
        best_velocity = mouse_p - prev_mouse_p;
    }
}

void main() {
    // === ERASE MODE ===
    if (erase_mode) {
        float distance_to_mouse;
        vec2 unused_vel;
        tiling_distance(texcoord, mouse, previous_mouse, tiling_mode,
                        distance_to_mouse, unused_vel);

        // Hard circle erase within draw_size radius
        if (distance_to_mouse < draw_size) {
            // Zero out channels corresponding to active fields
            fragColor = vec4(0.0);
        } else {
            discard;
        }
        return;
    }

    // === FILL MODE ===
    if (fill_mode) {
        vec2 fill_vector;
        if (fill_direction_type == 0) {
            // Fixed direction
            fill_vector = vec2(sin(fixed_direction_heading), cos(fixed_direction_heading));
        } else if (fill_direction_type == 1) {
            // Radial In (toward center 0.5, 0.5)
            vec2 to_center = vec2(0.5) - texcoord;
            float len = length(to_center);
            fill_vector = len > 0.0 ? to_center / len : vec2(0.0);
        } else {
            // Radial Out (away from center)
            vec2 from_center = texcoord - vec2(0.5);
            float len = length(from_center);
            fill_vector = len > 0.0 ? from_center / len : vec2(0.0);
        }

        // No persistence factor for fill (instantaneous)
        fill_vector *= draw_power / 5.0;

        fragColor = vec4(0.0);
        if (force_field_active)  fragColor.xy = fill_vector;
        if (strafe_field_active) fragColor.zw = fill_vector;
        return;
    }

    // === DRAW MODE ===
    if (!draw_mode || draw_power <= 0.0) {
        discard;
        return;
    }

    float distance_to_mouse;
    vec2 mouse_velocity;
    tiling_distance(texcoord, mouse, previous_mouse, tiling_mode,
                    distance_to_mouse, mouse_velocity);

    // Calculate draw vector based on brush mode
    vec2 draw_vector = calculate_draw_vector(
        brush_mode, mouse_velocity, fixed_direction_heading,
        texcoord, mouse
    );
    draw_vector *= draw_power / 5.0;

    // Gaussian kernel
    float kernel_weight = draw_kernel(distance_to_mouse, draw_size);

    // Output delta (will be additively blended)
    vec2 contribution = draw_vector * kernel_weight / draw_size;

    fragColor = vec4(0.0);
    if (force_field_active)  fragColor.xy = contribution;
    if (strafe_field_active) fragColor.zw = contribution;
}
