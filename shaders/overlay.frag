#version 330 core
// Overlay markup pass — runs AFTER the image pipeline over a finished frame.
// Adds the parameter-sweep reticle, the draw-trail radius ring, and the
// advanced-drawing field HSV overlay. Split out of frame_assembly.frag in
// Step 7 so markup is renderer-agnostic and never baked into recorded frames.
// (This is the proto-Viewer overlay pass; Step 8 folds it into the Viewer.)
uniform sampler2D input_frame;                       // the finished, tonemapped frame
uniform sampler2D field_texture;                     // Force/Strafe field (.xy=force, .zw=strafe)
uniform bool advanced_drawing_resources_initialized; // True when field_texture has valid data
uniform float draw_target_overlay_opacity;           // Opacity of field color overlay (0-1)

uniform bool PARAMETER_SWEEP_MODE;  // Whether parameter sweeps are active
uniform vec2 sweep_reticle_pos;     // Screen UV position of sweep reticle (0-1 range)
uniform bool sweep_reticle_visible; // Whether to show the reticle
uniform float screen_aspect;        // Screen width/height for aspect-correct circles
uniform bool WATERCOLOR_MODE;       // Whether watercolor mode (flips overlay sign)
uniform float EXPOSURE;             // Long-exposure amount (gates the draw ring)
uniform float TRAIL_DRAW_RADIUS;    // Draw size for trail drawing overlay (0 when not active)
uniform vec2 mouse_screen_coords;   // Mouse position in normalized screen coords (0-1)

// Camera state for screen-to-canvas UV conversion
uniform vec2 camera_position;       // Camera position in world space
uniform float camera_zoom;          // Camera zoom level
uniform vec2 canvas_resolution;     // Canvas pixel dimensions (width, height)

in vec2 uv;
out vec4 fragColor;

vec3 hsv2rgb(vec3 c)
{
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

// Convert screen UV coordinates to canvas texture coordinates
vec2 screen_to_canvas_uv(vec2 screen_uv) {
    vec2 ndc = screen_uv * 2.0 - 1.0;
    vec2 world_pos = ndc*camera_zoom + camera_position*vec2(1,-1);
    world_pos.y*=(canvas_resolution.x/canvas_resolution.y)/screen_aspect;
    return (world_pos/2.+.5);
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

void main() {
    fragColor = vec4(texture(input_frame, uv).rgb, 1.0);

    // Sweep reticle and mouse draw reticle
    vec2 overlay_uv = uv;
    if(PARAMETER_SWEEP_MODE){
        fragColor.xyz += sweep_overlay(overlay_uv)* (WATERCOLOR_MODE?-1:1);
    }
    if(TRAIL_DRAW_RADIUS > 0.0 && EXPOSURE<.25){
        fragColor.xyz += draw_overlay(overlay_uv)* (WATERCOLOR_MODE?-1:1);
    }

    // Field overlay (advanced drawing)
    if(advanced_drawing_resources_initialized && draw_target_overlay_opacity>0.0){
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
