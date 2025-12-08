import moderngl
import struct
import numpy as np
from util import read_shader

class RBFNoiseTester:
    def __init__(self, ctx: moderngl.Context):
        self.vertex_source = '''
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
        
        self.fragment_source = read_shader('shaders/noise_test.frag')
        
        self.rbf_program = ctx.program(
            vertex_shader=self.vertex_source,
            fragment_shader=self.fragment_source
        )
        self.vao = ctx.vertex_array(self.rbf_program, [])
        
        # Create texture and framebuffer for rendering
        self.rbf_tex = ctx.texture((512, 512), 4, dtype='f4')
        self.framebuffer = ctx.framebuffer([self.rbf_tex])
    
    def render(self, ctx, index, frame_count, scale):
        self.framebuffer.use()
        
        # Set uniforms for the RBF noise visualization
        self.rbf_program['u_index'] = index
        self.rbf_program['u_frame_count'] = frame_count
        self.rbf_program['u_scale'] = scale
        
        # Render fullscreen quad
        # Note: RuleBuffer should be bound to binding point 2 before calling this
        self.vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
    def reload(self,ctx):
        self.fragment_source = read_shader('shaders/noise_test.frag')
        self.rbf_program = ctx.program(
            vertex_shader=self.vertex_source,
            fragment_shader=self.fragment_source
        )
        self.vao = ctx.vertex_array(self.rbf_program, [])
