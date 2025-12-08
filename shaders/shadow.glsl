#version 450

// Define local work group size - one thread per horizontal scanline
layout(local_size_x = 1, local_size_y = 1, local_size_z = 1) in;

// Input texture storing height and density data
layout(binding = 0) uniform sampler2D scape;

// Output buffer for accumulated density values
layout(binding = 1, r32f) uniform writeonly image2D out_buffer;

// Uniforms for light direction and other parameters
uniform vec3 light_direction;  // Normalized light direction

// Helper functions to extract data from scape texture
float get_scape_height(ivec2 texel) {
    //DEBUG!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    //return abs(sin(texel.x/5))*5;
    ivec2 tex_size = textureSize(scape, 0);
    if (texel.x < 0 || texel.x >= tex_size.x || texel.y < 0 || texel.y >= tex_size.y) {
        return 0.0;
    }

    return sqrt(texelFetch(scape, texel, 0).z);
}

float get_scape_density(ivec2 texel,float H, vec3 light_dir) {
    //DEBUG!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    //return .25;
    if(abs(light_dir.x)<.001){return H;}
    return .05*max(1,min(H,1/abs(light_dir.x)));
}

// Calculate the last pixel shadowed by a column at given position
int calculate_shadow_end(ivec2 column_pos, float column_height, vec3 light_dir, int scanline_width) {
    if (abs(light_dir.z) < 0.001) {
        // Nearly horizontal light - very long shadows
        return (light_dir.x > 0) ? scanline_width - 1 : 0;
    }
    
    // Calculate shadow length on ground
    float shadow_length = column_height * abs(light_dir.x / light_dir.z);
    
    // Determine shadow end position
    int shadow_end = column_pos.x;
    if (light_dir.x > 0) {
        shadow_end += int(shadow_length);
    } else {
        shadow_end -= int(shadow_length);
    }
    
    // Clamp to scanline bounds
    return clamp(shadow_end, 0, scanline_width - 1);
}

void main() {
    // Get the current scanline (y-coordinate)
    int scanline_y = int(gl_GlobalInvocationID.y);
    
    // Get texture dimensions
    ivec2 tex_size = textureSize(scape, 0);
    int scanline_width = tex_size.x;
    
    // Validate scanline bounds
    if (scanline_y >= tex_size.y) {
        return;
    }
    
    // Allocate shadow edge data array (dynamic size based on uniform)
    #define ARRAY_SIZE 1024
    float shadow_edge_data[ARRAY_SIZE]; // Max array size
    // Initialize shadow edge data
    for (int i = 0; i < ARRAY_SIZE; i++) {
        shadow_edge_data[i] = 0.0;
    }
    
    // Determine scanning direction based on light direction
    bool scan_left_to_right = (light_direction.x > 0);
    int start_x = scan_left_to_right ? 0 : (scanline_width - 1);
    int end_x = scan_left_to_right ? scanline_width : -1;
    int step = scan_left_to_right ? 1 : -1;
    
    // Track current ground shadow density
    float current_ground_shadow_density = 0.0;
    
    // Process each pixel in the scanline
    for (int x = start_x; x != end_x; x += step) {
        ivec2 current_pixel = ivec2(x, scanline_y);
        float column_height = get_scape_height(current_pixel);

        // Step 1: Add current pixel's density contribution
        float pixel_density = get_scape_density(current_pixel,column_height,light_direction);
        current_ground_shadow_density += pixel_density;
        
        // Step 2: Calculate shadow end for this column
        
        int shadow_end = calculate_shadow_end(current_pixel, column_height, light_direction, scanline_width);
        
        // Step 3: Add density to shadow edge data at shadow end
        if (shadow_end >= 0 && shadow_end < ARRAY_SIZE) {
            shadow_edge_data[shadow_end] += pixel_density;
        }
        
        // Step 4: Write current ground shadow density to output buffer
        imageStore(out_buffer, current_pixel,vec4(current_ground_shadow_density));
        
        // Step 5: Subtract shadow edge contribution at current position
        if (x >= 0 && x < ARRAY_SIZE) {
            current_ground_shadow_density -= shadow_edge_data[x];
        }
    }
}
