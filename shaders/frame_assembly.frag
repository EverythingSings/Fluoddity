#version 330 core
uniform sampler2D input_frame;
uniform sampler2D accumulation_buffer;
uniform sampler2D field_texture;                    // Force/Strafe field (.xy=force, .zw=strafe)
uniform bool advanced_drawing_resources_initialized; // True when field_texture has valid data
uniform bool force_field_checked;   // Whether Force Field checkbox is active
uniform bool strafe_field_checked;  // Whether Strafe Field checkbox is active
uniform float draw_target_overlay_opacity; // Opacity of field color overlay (0-1)
uniform bool is_first_frame;
uniform bool final_sample;
uniform bool PARAMETER_SWEEP_MODE;  // Whether parameter sweeps are active
uniform vec2 sweep_reticle_pos;     // Screen UV position of sweep reticle (0-1 range)
uniform bool sweep_reticle_visible; // Whether to show the reticle
uniform float screen_aspect;        // Screen width/height for aspect-correct circles
uniform float BRIGHTNESS;           // Global brightness multiplier (applied before gamma)
uniform float EXPOSURE;//undo gamma from last frame and blend it with this frame, allows long exposure effect
uniform float TONEMAP_SOFTNESS;    // Asinh stretch parameter (higher = more highlight compression)
#define BRIGHTNESS_CONSTANT (3.*BRIGHTNESS)
uniform float INK_WEIGHT;           // Watercolor mode: controls optical density in exp()
uniform bool WATERCOLOR_MODE;       // Whether to use watercolor rendering
uniform float TRAIL_DRAW_RADIUS;    // Draw size for trail drawing overlay (0 when not active)
uniform vec2 mouse_screen_coords;   // Mouse position in normalized screen coords (0-1)

// Advanced drawing reticle uniforms
// brush_mode codes: 0=mouse_dir, 1=inverse, 2=fixed, 3=attract, 4=repel
uniform int brush_mode;
uniform float fixed_direction_heading;

// Camera state for screen-to-canvas UV conversion
uniform vec2 camera_position;       // Camera position in world space
uniform float camera_zoom;          // Camera zoom level
uniform vec2 canvas_resolution;     // Canvas pixel dimensions (width, height)

// SDF preview uniforms (3D mode only)
uniform bool u_sdf_enabled;        // "Enable SDF" toggle from Tracer controls
uniform mat4 u_inv_view_proj;      // Inverse view-projection for ray generation
uniform vec3 u_sdf_sun_dir;        // Normalized sun direction
uniform vec3 u_sdf_sun_color;      // Sun color * intensity
uniform vec3 u_sdf_sky_color;      // Sky color * intensity

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

// Convert screen UV coordinates to canvas texture coordinates
// Screen UV (0,0) to (1,1) -> world space -> canvas texture coords
vec2 screen_to_canvas_uv(vec2 screen_uv) {
    // Screen UV to normalized device coordinates (-1 to 1)
    vec2 ndc = screen_uv * 2.0 - 1.0;
    // Add camera position to get world space position
    vec2 world_pos = ndc*camera_zoom + camera_position*vec2(1,-1);
    // Apply aspect ratio correction
    world_pos.y*=(canvas_resolution.x/canvas_resolution.y)/screen_aspect;
    // World space to canvas texture coords: divide by 2 and add 0.5
    return (world_pos/2.+.5);
}

// Convert canvas texture coordinates to screen UV coordinates
// Inverse of screen_to_canvas_uv (canvas aspect ratio handled differently for reticle vs overlay)
vec2 canvas_uv_to_screen(vec2 canvas_uv) {
    // Canvas texture coords to world space: multiply by 2 and subtract 1
    vec2 world_pos = canvas_uv * 2.0 - 1.0;
    // Remove aspect ratio correction
    //world_pos.x /= screen_aspect;
    world_pos.y /= (canvas_resolution.x/canvas_resolution.y)/screen_aspect;
    // Subtract camera position to get NDC (with flipped y)
    vec2 ndc = (world_pos - camera_position*vec2(1,-1)) / camera_zoom;
    // NDC to screen UV coordinates (0 to 1)
    return ndc * 0.5 + 0.5;
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

vec3 draw_overlay(vec2 uv_coord) {

    // Draw a ring showing the trail drawing radius
    if (TRAIL_DRAW_RADIUS <= 0.0) {
        return vec3(0.0);
    }
    //uv_coord.x-=.5;
    uv_coord.x/=canvas_resolution.x/canvas_resolution.y;
    //uv_coord.x+=.5;
    // Calculate delta in screen space with aspect correction
    // Use mouse_screen_coords for the ring center
    vec2 mouse_pos = mouse_screen_coords;
    //mouse_pos.x/=canvas_resolution.x/canvas_resolution.y;
    vec2 delta = uv_coord - (vec2(0,1)+mouse_pos*vec2(canvas_resolution.y/canvas_resolution.x,-1));
    delta.x*= canvas_resolution.x/canvas_resolution.y;
    delta.x *= screen_aspect;

    float dist = length(delta);

    // Ring parameters - scale the radius to screen space
    // TRAIL_DRAW_RADIUS is in canvas space (0-1), need to convert to screen space
    float aspect_shrink = sqrt(min(canvas_resolution.x,canvas_resolution.y)/max(canvas_resolution.x,canvas_resolution.y));
    aspect_shrink *= canvas_resolution.x>canvas_resolution.y?4./3.:1;//I have no idea why this is necessary but it works to make the reticle match the actual draw size very closely but not perfectly. @Claude why do we need this?
    float radius = (aspect_shrink)*2*TRAIL_DRAW_RADIUS / camera_zoom;
    float line_thickness = 0.003;

    // Draw a thin ring at the draw radius
    float ring = smoothstep(radius - line_thickness, radius, dist)
               - smoothstep(radius, radius + line_thickness, dist);

    // Return white or black depending on watercolor mode (like sweep_overlay)
    return vec3(ring * 0.6);
}
vec2 safenorm(vec2 n){
    float l = length(n);
    return l>0?n/l:vec2(0);
}
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

        //Conditionally draw sweep reticle and mouse draw reticle
        vec2 overlay_uv = uv;
        if(PARAMETER_SWEEP_MODE){
            fragColor.xyz += sweep_overlay(overlay_uv)* (WATERCOLOR_MODE?-1:1);
        }
        if(TRAIL_DRAW_RADIUS > 0.0 && EXPOSURE<.25){
            fragColor.xyz += draw_overlay(overlay_uv)* (WATERCOLOR_MODE?-1:1);
        }

        //conditionally draw field overlay
        if(advanced_drawing_resources_initialized&& draw_target_overlay_opacity>0.0){
            vec2 field_uv = uv;
            field_uv=screen_to_canvas_uv(uv);
            if(canvas_resolution.y/canvas_resolution.x>=1.){
            field_uv-=.5;
            field_uv*=max(1,screen_aspect);//canvas_resolution.y/canvas_resolution.x;
            if(screen_aspect>1){field_uv *=canvas_resolution.y/canvas_resolution.x;}
            //field_uv/=1./screen_aspect*canvas_resolution.x/canvas_resolution.y;
            field_uv+=.5;
            }
            vec4 field = vec4(0);
            if(clamp(field_uv,vec2(0),vec2(1))==field_uv){
                field = texture(field_texture,field_uv);
            }
            vec3 force_col = 8*hsv2rgb(vec3(atan(field.y,field.x)/2./3.1415,.75,length(field.xy)));
            vec3 strafe_col = 8*hsv2rgb(vec3(atan(field.w,field.z)/2./3.1415,.75,length(field.zw)));
            fragColor.xyz +=draw_target_overlay_opacity*(force_col+strafe_col);
        }
    }
}
