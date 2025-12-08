import moderngl
import struct
import numpy as np

class StackFreeListTester:
    def __init__(self, ctx: moderngl.Context):
        test_vertex_source = '''
                #version 430
                
                out vec2 texcoord;
                
                void main() {
                    // Generate fullscreen quad vertices
                    vec2 positions[4] = vec2[](
                        vec2(-1.0, -1.0),  // bottom-left
                        vec2( 1.0, -1.0),  // bottom-right
                        vec2( 1.0,  1.0),  // top-right
                        vec2(-1.0,  1.0)   // top-left
                    );
                    
                    vec2 texcoords[4] = vec2[](
                        vec2(0.0, 0.0),
                        vec2(1.0, 0.0),
                        vec2(1.0, 1.0),
                        vec2(0.0, 1.0)
                    );
                    
                    gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
                    texcoord = texcoords[gl_VertexID];
                }
                '''
                
        test_fragment_source = '''
                
                #version 450
                
                in vec2 texcoord;
                out vec4 fragColor;

                // Updated buffer layout for stack-based free list
                layout(std430, binding = 1) restrict readonly buffer FreeListBuffer {
                    uint head;              // Number of items currently in stack
                    uint buffer_data[];     // Stack storage for available IDs
                };

                const uint BUFFER_SIZE = 1024*1024+64;  // Total buffer capacity
                const float BUFFER_HEIGHT = 0.3;       // Height of the buffer visualization
                const float BUFFER_Y_CENTER = 0.5;     // Vertical center of buffer
                const float BUFFER_MARGIN = 0.05;      // Horizontal margins
                const float ARROW_HEIGHT = 0.1;        // Height of the head indicator
                const float ARROW_WIDTH = 0.015;       // Half-width of arrow base

                // Convert HSV to RGB
                vec3 hsv2rgb(vec3 c) {
                    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
                    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
                    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
                }

                // Check if point is inside a triangle
                bool pointInTriangle(vec2 p, vec2 a, vec2 b, vec2 c) {
                    vec2 v0 = c - a;
                    vec2 v1 = b - a;
                    vec2 v2 = p - a;
                    
                    float dot00 = dot(v0, v0);
                    float dot01 = dot(v0, v1);
                    float dot02 = dot(v0, v2);
                    float dot11 = dot(v1, v1);
                    float dot12 = dot(v1, v2);
                    
                    float invDenom = 1.0 / (dot00 * dot11 - dot01 * dot01);
                    float u = (dot11 * dot02 - dot01 * dot12) * invDenom;
                    float v = (dot00 * dot12 - dot01 * dot02) * invDenom;
                    
                    return (u >= 0.0) && (v >= 0.0) && (u + v <= 1.0);
                }

                void main() {
                    vec2 pos = texcoord;
                    vec3 color = vec3(0.1, 0.1, 0.15); // Dark background
                    
                    // Buffer visualization area
                    float buffer_left = BUFFER_MARGIN;
                    float buffer_right = 1.0 - BUFFER_MARGIN;
                    float buffer_top = BUFFER_Y_CENTER + BUFFER_HEIGHT * 0.5;
                    float buffer_bottom = BUFFER_Y_CENTER - BUFFER_HEIGHT * 0.5;
                    
                    // Get current head position
                    uint current_head = head;
                    
                    // Draw buffer contents
                    if (pos.y >= buffer_bottom && pos.y <= buffer_top && 
                        pos.x >= buffer_left && pos.x <= buffer_right) {
                        
                        // Which buffer index does this pixel correspond to?
                        float norm_x = (pos.x - buffer_left) / (buffer_right - buffer_left);
                        uint buffer_index = uint(norm_x * float(BUFFER_SIZE));
                        
                        if (buffer_index < BUFFER_SIZE) {
                            if (buffer_index < current_head) {
                                // Active stack area - show the stored ID
                                uint stored_id = buffer_data[buffer_index];
                                
                                // Convert ID to hue and then to RGB
                                float hue = float(stored_id) / float(BUFFER_SIZE);
                                vec3 hsv = vec3(hue, 0.8, 0.9);
                                color = hsv2rgb(hsv);
                            } else {
                                // Inactive stack area - show as empty
                                color = vec3(0.2, 0.2, 0.25); // Slightly lighter gray
                            }
                            
                            // Add grid lines between slices
                            float slice_width = (buffer_right - buffer_left) / float(BUFFER_SIZE);
                            float local_x = mod(pos.x - buffer_left, slice_width);
                            if (local_x < slice_width * 0.02) {
                                color *= 0.7; // Darken grid lines
                            }
                            
                            // Highlight the boundary between active and inactive
                            if (buffer_index == current_head || buffer_index == current_head - 1) {
                                if (local_x > slice_width * 0.9) {
                                    color = mix(color, vec3(1.0, 1.0, 0.2), 0.6); // Yellow boundary
                                }
                            }
                        }
                    }
                    
                    // Draw head indicator arrow (pointing down to show where next push goes)
                    if (current_head < BUFFER_SIZE) {
                        float head_x = buffer_left + (float(current_head) + 0.5) / float(BUFFER_SIZE) * (buffer_right - buffer_left);
                        float arrow_top = buffer_top + ARROW_HEIGHT * 0.3;
                        float arrow_bottom = buffer_top + ARROW_HEIGHT;
                        
                        vec2 head_tip = vec2(head_x, buffer_top);
                        vec2 head_left = vec2(head_x - ARROW_WIDTH, arrow_bottom);
                        vec2 head_right = vec2(head_x + ARROW_WIDTH, arrow_bottom);
                        
                        if (pointInTriangle(pos, head_tip, head_left, head_right)) {
                            color = vec3(0.2, 0.8, 1.0); // Cyan arrow for head
                        }
                    }
                    
                    // Draw buffer border
                    if ((pos.y >= buffer_bottom - 0.002 && pos.y <= buffer_bottom + 0.002) ||
                        (pos.y >= buffer_top - 0.002 && pos.y <= buffer_top + 0.002) ||
                        (pos.x >= buffer_left - 0.002 && pos.x <= buffer_left + 0.002 && 
                         pos.y >= buffer_bottom && pos.y <= buffer_top) ||
                        (pos.x >= buffer_right - 0.002 && pos.x <= buffer_right + 0.002 && 
                         pos.y >= buffer_bottom && pos.y <= buffer_top)) {
                        color = vec3(0.6, 0.6, 0.6); // Gray border
                    }
                    
                    // Add text-like indicators for stack state
                    // Draw a simple "STACK" label and fill indicator
                    float label_y = buffer_bottom - 0.1;
                    if (pos.y >= label_y - 0.02 && pos.y <= label_y + 0.02) {
                        // Stack fill percentage bar
                        float fill_left = buffer_left;
                        float fill_right = buffer_left + (float(current_head) / float(BUFFER_SIZE)) * (buffer_right - buffer_left);
                        
                        if (pos.x >= fill_left && pos.x <= fill_right) {
                            float fill_ratio = float(current_head) / float(BUFFER_SIZE);
                            if (fill_ratio < 0.3) {
                                color = vec3(0.2, 0.8, 0.2); // Green - plenty of space
                            } else if (fill_ratio < 0.7) {
                                color = vec3(0.8, 0.8, 0.2); // Yellow - getting full
                            } else {
                                color = vec3(0.8, 0.2, 0.2); // Red - nearly full
                            }
                        } else if (pos.x >= buffer_left && pos.x <= buffer_right) {
                            color = vec3(0.3, 0.3, 0.3); // Empty portion
                        }
                    }
                    
                    fragColor = vec4(color, 1.0);
                }
                '''
                
        self.stack_test_program = ctx.program(
            vertex_shader=test_vertex_source,
            fragment_shader=test_fragment_source
        )
        self.vao = ctx.vertex_array(self.stack_test_program, [])
        
        # Create texture and framebuffer
        self.stack_test_tex = ctx.texture((1024, 512), 4, dtype='f4')
        self.framebuffer = ctx.framebuffer([self.stack_test_tex])
    
    def render(self, ctx, buffer_object):
        self.framebuffer.use()
        # buffer_object.bind_to_storage_buffer(1) should be handled in the calling code
        
        self.vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)