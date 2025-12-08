import moderngl
import numpy as np
import struct
import math
from util import read_shader,tryset
import glfw
class GaussianBlurer:
    def __init__(self, ctx: moderngl.Context, texture_width: int = 512, texture_height: int = 512):
        self.ctx = ctx
        self.texture_width = texture_width
        self.texture_height = texture_height
        self.temp_buffer = ctx.texture(
            (texture_width, texture_height),
            components=4,  # RGBA format
            dtype='f4'
        )
        # Create framebuffer for temporary buffer
        self.temp_fbo = ctx.framebuffer([self.temp_buffer])
        
        # Create shader programs for horizontal and vertical blur passes
        self._create_blur_programs()
    
    def _create_blur_programs(self):
        """Create the shader programs for horizontal and vertical blur passes"""
        vertex_source = '''
        #version 150
        
        out VertexData
        {
            vec4 v_position;
            vec3 v_normal;
            vec2 v_texcoord;
        } outData;
        
        void main() {
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
            outData.v_position = gl_Position;
            outData.v_normal = vec3(0.0, 0.0, 1.0);
            outData.v_texcoord = texcoords[gl_VertexID];
        }
        '''
        
        # Horizontal blur fragment shader (blurs in X direction)
        horizontal_fragment_source = '''
        #version 150
        uniform int kernel_width;
        uniform sampler2D prevPass;
        uniform float sigma;
        in VertexData
        {
            vec4 v_position;
            vec3 v_normal;
            vec2 v_texcoord;
        } inData;
        out vec4 fragColor;
        
        // Separable Gaussian blur for noise reduction
        float gaussianWeight(float x, float sigma) {
            return exp(-(x * x) / (2.0 * sigma * sigma));
        }
        
        void main(void)
        {
            int KWID = kernel_width;
            vec3 color = vec3(0);
            float sum = 0;
            for(int i = -KWID; i <= KWID; i++){
                float offset = float(i) / textureSize(prevPass, 0).x;
                float wgt = gaussianWeight(offset, sigma/100);
                color += wgt * texture(prevPass, inData.v_texcoord + vec2(offset, 0)).xyz;
                sum += wgt;
            }
            fragColor = vec4(color/sum, 1);
        }
        '''
        
        # Vertical blur fragment shader (blurs in Y direction)
        vertical_fragment_source = '''
        #version 150
        uniform int kernel_width;
        uniform sampler2D prevPass;
        uniform float sigma;
        in VertexData
        {
            vec4 v_position;
            vec3 v_normal;
            vec2 v_texcoord;
        } inData;
        out vec4 fragColor;
        
        // Separable Gaussian blur for noise reduction
        float gaussianWeight(float x, float sigma) {
            return exp(-(x * x) / (2.0 * sigma * sigma));
        }
        
        void main(void)
        {
            int KWID = kernel_width;
            vec3 color = vec3(0);
            float sum = 0;
            for(int i = -KWID; i <= KWID; i++){
                float offset = float(i) / textureSize(prevPass, 0).y;
                float wgt = gaussianWeight(offset, sigma/100);
                color += wgt * texture(prevPass, inData.v_texcoord + vec2(0, offset)).xyz;
                sum += wgt;
            }
            fragColor = vec4(color/sum, 1);
        }
        '''
        
        # Create shader programs
        self.horizontal_program = self.ctx.program(
            vertex_shader=vertex_source,
            fragment_shader=horizontal_fragment_source
        )
        
        self.vertical_program = self.ctx.program(
            vertex_shader=vertex_source,
            fragment_shader=vertical_fragment_source
        )
        
        # Create vertex array objects
        self.horizontal_vao = self.ctx.vertex_array(self.horizontal_program, [])
        self.vertical_vao = self.ctx.vertex_array(self.vertical_program, [])
    
    def apply(self, fbo_to_blur, kernel_width=6, sigma=0.2):
        """
        Apply a two-pass separable Gaussian blur to the given framebuffer
        
        Args:
            fbo_to_blur: The framebuffer to blur (will be modified in-place)
            kernel_width: Half-width of the blur kernel
            sigma: Standard deviation of the Gaussian kernel
        """
        # First pass: horizontal blur from fbo_to_blur to temp_fbo
        self.temp_fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        
        # Set uniforms for horizontal pass
        self.horizontal_program['kernel_width'] = kernel_width
        self.horizontal_program['sigma'] = sigma
        self.horizontal_program['prevPass'] = 0
        
        # Bind the source texture and render
        fbo_to_blur.color_attachments[0].use(location=0) 
        self.horizontal_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
        
        # Second pass: vertical blur from temp_fbo back to fbo_to_blur
        fbo_to_blur.use()
        self.ctx.clear(0.0, 0.0, 0.0, 0.0)
        
        # Set uniforms for vertical pass
        self.vertical_program['kernel_width'] = kernel_width
        self.vertical_program['sigma'] = sigma
        self.vertical_program['prevPass'] = 0
        
        # Bind the temp buffer and render
        self.temp_buffer.use(location=0)
        self.vertical_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
    
    def cleanup(self):
        """Release GPU resources"""
        if hasattr(self, 'temp_buffer'):
            self.temp_buffer.release()
        if hasattr(self, 'temp_fbo'):
            self.temp_fbo.release()

class VolumetricRenderProgram:
    def __init__(self, ctx: moderngl.Context,hmap_tex,window_size):
        self.ctx = ctx
        self.hmap_fbo=ctx.framebuffer(hmap_tex)
        self.blurer = GaussianBlurer(ctx, hmap_tex.width, hmap_tex.height)
        screen_width, screen_height = window_size
        self.render_target = ctx.texture((screen_width, screen_height),4)
        self.render_fbo = ctx.framebuffer([self.render_target])
        self.create_march_program(ctx)

        self.sig = .2
        self.wid = 6
    def create_march_program(self,ctx):
        vertex_source = '''
        #version 430
        
        out vec2 texcoord;
        
        void main() {
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


        try:      
            # Create shader program
            frag_source = read_shader('shaders/march.frag')
            self.march_program = ctx.program(vertex_shader = vertex_source,fragment_shader = frag_source)
        except Exception as e:
            print('march shader failed')
            print(e)
        
        self.march_vao = ctx.vertex_array(self.march_program,[])
        #static uniforms
        tryset(self.march_program,'resolution', self.render_fbo.size)

    def render_frame(self,march_cam_pos,march_cam_ori,going):
        if(going and self.sig>0):
            self.blurer.apply(self.hmap_fbo,kernel_width=math.floor(self.wid),sigma = self.sig)
        self.hmap_fbo.color_attachments[0].use(0)
        tryset(self.march_program,'prevPass',0)
        tryset(self.march_program,'cam_pos',march_cam_pos)
        tryset(self.march_program,'cam_ori',march_cam_ori)
        self.render_fbo.use()
        self.march_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)