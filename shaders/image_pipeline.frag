#version 330 core
// Image-pipeline core: temporal accumulation + tonemap + watercolor + SDF preview.
// Split out of the old frame_assembly.frag in Step 7 — overlay markup (sweep
// reticle, draw-trail ring, advanced-drawing field overlay) now lives in a
// separate overlay pass (overlay.frag / OverlayCompositor) that runs AFTER this,
// so the accumulation texture this produces is markup-free (correct for video).
uniform sampler2D input_frame;
uniform sampler2D accumulation_buffer;
uniform bool is_first_frame;
uniform bool final_sample;
uniform float BRIGHTNESS;           // Global brightness multiplier (applied before gamma)
uniform float EXPOSURE;//undo gamma from last frame and blend it with this frame, allows long exposure effect
uniform float TONEMAP_SOFTNESS;    // Asinh stretch parameter (higher = more highlight compression)
#define BRIGHTNESS_CONSTANT (3.*BRIGHTNESS)
uniform float INK_WEIGHT;           // Watercolor mode: controls optical density in exp()
uniform bool WATERCOLOR_MODE;       // Whether to use watercolor rendering

// SDF preview uniforms (3D GL-points mode only)
uniform bool u_sdf_enabled;        // "Enable SDF" toggle from Tracer controls
uniform mat4 u_inv_view_proj;      // Inverse view-projection for ray generation
uniform vec3 u_sdf_sun_dir;        // Normalized sun direction
uniform vec3 u_sdf_sun_color;      // Sun color * intensity
uniform vec3 u_sdf_sky_color;      // Sky color * intensity

in vec2 uv;
out vec4 fragColor;

// TOTAL_SAMPLES placeholder - will be replaced by Python during shader creation
const int TOTAL_SAMPLES = {total_samples};

vec3 safenorm(vec3 n){
    float l = length(n);
    return l>0?n/l:vec3(0);
}

// ====================================================================
// SDF preview rendering (primary ray + shadow + AO)
// Uses scene(), sdf_normal(), trace_sdf(), sdf_shadow_test(),
// sdf_get_albedo() from volume_scene.glsl (prepended at compile time).
// ====================================================================

float calc_sdf_ao(vec3 pos, vec3 nor) {
    float occ = 0.0;
    float sca = 1.0;
    for (int i = 0; i < 5; i++) {
        float h = 0.01 + 0.12 * float(i) / 4.0;
        float d = scene(pos + h * nor).x;
        occ += (h - d) * sca;
        sca *= 0.95;
    }
    return clamp(1.0 - 3.0 * occ, 0.0, 1.0);
}

vec3 sdf_preview_shade(vec3 ro, vec3 rd) {
    float hit_t;
    vec2 hit_mat;
    if (!trace_sdf(ro, rd, 0.001, SDF_MAX_DIST, hit_t, hit_mat)) {
        // Sky gradient
        float sky_t = max(rd.y, 0.0);
        vec3 sky_base = u_sdf_sky_color * 0.15;
        return mix(sky_base, u_sdf_sky_color * 0.5, sky_t);
    }

    vec3 pos = ro + hit_t * rd;
    vec3 nor = sdf_normal(pos);
    vec3 albedo = sdf_get_albedo(hit_mat,pos);

    // Direct sun lighting
    float NdotL = max(dot(nor, u_sdf_sun_dir), 0.0);
    float shadow = 1.0;
    if (NdotL > 0.0) {
        shadow = sdf_shadow_test(pos + nor * 0.01, u_sdf_sun_dir,
                                  0.01, SDF_MAX_DIST) ? 0.0 : 1.0;
    }

    // AO
    float ao = calc_sdf_ao(pos, nor);

    // Ambient from sky
    vec3 ambient = u_sdf_sky_color * 0.15 * ao;

    return albedo * (u_sdf_sun_color * NdotL * shadow + ambient);
}

void main() {
    // Sample the input frame
    vec3 current_color = texture(input_frame, uv).rgb;

    // SDF background: composite particles over raymarched scene
    if (u_sdf_enabled) {
        vec2 ndc_xy = uv * 2.0 - 1.0;
        vec4 near_h = u_inv_view_proj * vec4(ndc_xy, -1.0, 1.0);
        vec4 far_h  = u_inv_view_proj * vec4(ndc_xy,  1.0, 1.0);
        vec3 near_w = near_h.xyz / near_h.w;
        vec3 far_w  = far_h.xyz / far_h.w;
        vec3 ray_origin = near_w;
        vec3 ray_dir = normalize(far_w - near_w);

        vec3 bg = sdf_preview_shade(ray_origin, ray_dir);
        // Particles are additive on black — overlay on top of raymarched scene
        current_color = bg + current_color;
    }

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
