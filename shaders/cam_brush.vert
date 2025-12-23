#version 430 

uniform vec2 canvas_resolution;
uniform vec2 cam_pos;
uniform float cam_zoom;
uniform vec2 window_size;

//SYNC WITH ENTITY_UPDATE.GLSL AND BRUSH.VERT
struct Entity {
    vec2 pos;
    vec2 vel;
    float size;
    float padding[3];  // Align to 16-byte boundary for vec4
    vec4 color;
};  // Total: 48 bytes (12 floats)
layout(std430, binding = 0) buffer EntityBuffer {
    Entity entities[];
};

out vec2 uv;
out vec4 pos_vel;
out vec4 view_col;
vec2 w2a(vec2 v,vec2 axis){
    axis=normalize(axis);
    float dav = dot(axis,v);
    return vec2(dav,dot(axis.yx*vec2(1,-1),v-dav*axis));
}
vec2 a2w(vec2 v,vec2 axis){
    axis=normalize(axis);
    return (v.x*axis)+(v.y*axis.yx*vec2(1,-1));
}
void main() {
    int instance_id = gl_InstanceID;
    int vertex_id = gl_VertexID;
    // Read entity data
    vec2 entity_pos = entities[instance_id].pos;
    vec2 entity_vel = entities[instance_id].vel;
    float size = entities[instance_id].size;
    // Calculate particle center in viewport coordinates for culling
    vec2 canvas_ndc_center = entity_pos * vec2(1, canvas_resolution.x/canvas_resolution.y);
    
    // Apply camera transformation to center
    float tex_aspect = canvas_resolution.x / canvas_resolution.y;
    float window_aspect = window_size.x / window_size.y;
    
    vec2 scale;
    if (tex_aspect > window_aspect) {
        scale.x = 1.0;
        scale.y = window_aspect / tex_aspect;
    } else {
        scale.x = tex_aspect / window_aspect;
        scale.y = 1.0;
    }
    scale /= cam_zoom;
    
    vec2 center_pos = canvas_ndc_center * scale;
    center_pos -= cam_pos * vec2(1.0, -1.0) / cam_zoom;
    
    // Calculate particle size in viewport coordinates
    vec2 particle_size_in_viewport = size * vec2(1, canvas_resolution.x/canvas_resolution.y) * scale;
    float max_size = max(particle_size_in_viewport.x, particle_size_in_viewport.y);
    
    // Check if particle bounding box overlaps viewport
    bool is_visible = (center_pos.x + max_size >= -1.0 && center_pos.x - max_size <= 1.0 &&
                       center_pos.y + max_size >= -1.0 && center_pos.y - max_size <= 1.0);
    
    // Generate quad vertices - collapse to center if not visible
    vec2 offsets[4] = vec2[](
        vec2(-size, -size),  // bottom-left
        vec2( size, -size),  // bottom-right
        vec2( size,  size),  // top-right
        vec2(-size,  size)   // top-left
    );
    vec2 uv_coords[4] = vec2[](
        vec2(0,0),
        vec2(1,0),
        vec2(1,1),
        vec2(0,1)
    );
    //////////////PARTICLE SHAPING
    #define NARROWED_EDGE 0 //1 to turn on
    #define STRETCH 1 //2 to turn on 
    #define sprite_size 1.5
    for(int i=0;i<4;i++){
        if(i==1 || i == 2){
            float mixamt = NARROWED_EDGE;
            offsets[i].y=mix(offsets[i].y,0,mixamt);
            vec2 meanpos=vec2(1,.5);
            uv_coords[i]=mix(uv_coords[i],meanpos,mixamt);
        }
        else{
            offsets[i].x*=1+NARROWED_EDGE;
        }
        offsets[i]*=sprite_size;
        offsets[i]=a2w(offsets[i],entity_vel);

    }

    // If not visible, render degenerate primitive (all vertices at same position)
    vec2 offset = is_visible ? offsets[vertex_id] : vec2(0.0);
    vec2 vertex_pos = entity_pos + offset;
    
    // Apply combined transformation: entity space -> canvas space -> viewport space
    vec2 canvas_ndc = vertex_pos * vec2(1, canvas_resolution.x/canvas_resolution.y);



    vec2 pos = canvas_ndc * scale;
    pos -= cam_pos * vec2(1.0, -1.0) / cam_zoom;
    
    gl_Position = vec4(pos, 0.0, 1.0);
    // Pass through vertex data
    uv = uv_coords[vertex_id];
    pos_vel = vec4(entity_pos, entity_vel);
    view_col = entities[instance_id].color;
}