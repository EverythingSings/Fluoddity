import glfw
import numpy as np
from util import read_shader, tryset
import moderngl

class Camera:
    def __init__(self, ctx, sim, window):
        self.ctx = ctx
        self.sim = sim
        self.window = window
        self.amplitude = 1
        self.cam_brush_mode = False
        # Camera state
        self.position = np.array([0.0, 0.0])  # 2D position
        self.zoom = 1.0  # zoom factor

        self.setup_rendering()

    def setup_rendering(self):
        # Fullscreen quad vertices (position + texcoord)
        quad_vertices = np.array([
            -1.0, -1.0,  0.0, 0.0,  # bottom-left
             1.0, -1.0,  1.0, 0.0,  # bottom-right
             1.0,  1.0,  1.0, 1.0,  # top-right
            -1.0,  1.0,  0.0, 1.0   # top-left
        ], dtype=np.float32)

        quad_indices = np.array([0, 1, 2, 2, 3, 0], dtype=np.uint32)

        # Vertex shader
        self.vertex_shader = read_shader('shaders/camera.vert')

        # Fragment shader
        self.fragment_shader = read_shader('shaders/camera.frag')

        try:
            # Create shader program
            self.program = self.ctx.program(
                vertex_shader=self.vertex_shader,
                fragment_shader=self.fragment_shader
            )
        except Exception as e:
            print('Camera shader failed')
            print(e)

        # Create cam brush program
        self.cam_brush_vertex_shader = read_shader('shaders/cam_brush.vert')
        self.cam_brush_fragment_shader = read_shader('shaders/cam_brush.frag')

        try:
            self.cam_brush_program = self.ctx.program(
                vertex_shader=self.cam_brush_vertex_shader,
                fragment_shader=self.cam_brush_fragment_shader
            )
        except Exception as e:
            print('Cambrush shader failed')
            print(e)

        self.cam_brush_pp_vertex_shader = read_shader('shaders/cam_brush_pp.vert')
        self.cam_brush_pp_fragment_shader = read_shader('shaders/cam_brush_pp.frag')

        try:
            self.cam_brush_postprocess_program = self.ctx.program(
                vertex_shader=self.cam_brush_pp_vertex_shader,
                fragment_shader=self.cam_brush_pp_fragment_shader
            )
        except Exception as e:
            print('Cambrush postprocess shader failed')
            print(e)

        # Create vertex array
        vbo = self.ctx.buffer(quad_vertices.tobytes())
        ibo = self.ctx.buffer(quad_indices.tobytes())
        self.vao = self.ctx.vertex_array(
            self.program,
            [(vbo, '2f 2f', 'in_position', 'in_texcoord')],
            ibo
        )
        self.cam_brush_vao = self.ctx.vertex_array(
            self.cam_brush_program,
            []
        )
        self.cam_brush_postprocess_vao = self.ctx.vertex_array(
            self.cam_brush_postprocess_program,
            []
        )

        self.cam_brush_target = self.ctx.texture(glfw.get_framebuffer_size(self.window), 4, dtype='f4')
        self.cam_brush_fbo = self.ctx.framebuffer([self.cam_brush_target])

        self.cam_brush_pp_target = self.ctx.texture(glfw.get_framebuffer_size(self.window), 4, dtype='f4')
        self.cam_brush_pp_fbo = self.ctx.framebuffer([self.cam_brush_pp_target])

        # Temporal accumulation
        self.use_accumulated_view = False
        self.accumulated_view_texture = None

    def generate_view_texture(self):
        """Generate the appropriate view texture based on current mode without rendering to screen."""
        TEX_TO_VIEW = self.sim.view_tex

        if self.cam_brush_mode:
            self.cam_brush_fbo.use()
            width, height = glfw.get_framebuffer_size(self.window)
            self.ctx.viewport = (0, 0, width, height)
            self.ctx.clear(0, 0, 0, 1)

            self.cam_brush_program['cam_pos'].value = tuple(self.position)
            self.cam_brush_program['cam_zoom'].value = self.zoom
            self.cam_brush_program['canvas_resolution'].value = self.sim.view_tex.size
            self.cam_brush_program['window_size'].value = (width, height)
            self.cam_brush_program['amp'].value = self.amplitude

            # Always use additive blending
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
            self.ctx.blend_equation = moderngl.FUNC_ADD

            self.cam_brush_vao.render(mode=moderngl.TRIANGLE_FAN, instances=self.sim.entity_count, vertices=4)

            self.cam_brush_pp_fbo.use()
            self.ctx.disable(moderngl.BLEND)
            width, height = glfw.get_framebuffer_size(self.window)
            self.ctx.viewport = (0, 0, width, height)

            self.cam_brush_target.use(location=0)
            self.cam_brush_postprocess_program['brush'] = 0
            self.sim.can.use(location=1)
            tryset(self.cam_brush_postprocess_program, 'can', 1)
            tryset(self.cam_brush_postprocess_program, 'cam_pos', tuple(self.position))
            tryset(self.cam_brush_postprocess_program, 'cam_zoom', self.zoom)
            tryset(self.cam_brush_postprocess_program, 'tex_size', TEX_TO_VIEW.size)
            tryset(self.cam_brush_postprocess_program, 'window_size', glfw.get_framebuffer_size(self.window))

            self.cam_brush_postprocess_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)

            TEX_TO_VIEW = self.cam_brush_pp_target

        return TEX_TO_VIEW

    def render(self):
        # Use accumulated texture if temporal accumulation is active
        if self.use_accumulated_view and self.accumulated_view_texture is not None:
            TEX_TO_VIEW = self.accumulated_view_texture
        else:
            TEX_TO_VIEW = self.generate_view_texture()

        # Render to screen
        self.ctx.screen.use()
        width, height = glfw.get_framebuffer_size(self.window)
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        self.program['cam_pos'].value = tuple(self.position)
        self.program['cam_zoom'].value = self.zoom
        self.program['tex_size'].value = TEX_TO_VIEW.size
        self.program['window_size'].value = (width, height)
        self.program['amp'].value = self.amplitude

        if self.cam_brush_mode:
            tryset(self.program, 'cam_pos', (0, 0))
            tryset(self.program, 'cam_zoom', 1)

        TEX_TO_VIEW.use(location=0)
        self.program['view_tex'].value = 0
        self.vao.render()

    def reload(self):
        self.setup_rendering()

    def screen_to_tex(self, coord_tuple):
        """
        Transform screen coordinates to texture coordinates.

        Args:
            coord_tuple: (x, y) screen coordinates where (0,0) is top-left

        Returns:
            (tex_x, tex_y) texture coordinates where (0,0) is top-left of texture
        """
        x_screen, y_screen = coord_tuple
        width, height = glfw.get_framebuffer_size(self.window)

        x_ndc = (x_screen / width) * 2 - 1
        y_ndc = (1 - y_screen / height) * 2 - 1

        tex_aspect = self.sim.view_tex.size[0] / self.sim.view_tex.size[1]
        window_aspect = width / height

        if tex_aspect > window_aspect:
            scale_x = 1.0
            scale_y = window_aspect / tex_aspect
        else:
            scale_x = tex_aspect / window_aspect
            scale_y = 1.0

        scale_x /= self.zoom
        scale_y /= self.zoom

        x_ndc += self.position[0] / self.zoom
        y_ndc -= self.position[1] / self.zoom

        in_pos_x = x_ndc / scale_x
        in_pos_y = y_ndc / scale_y

        tex_x = (in_pos_x + 1) / 2
        tex_y = (in_pos_y + 1) / 2

        return (tex_x, tex_y)

    def tex_to_screen(self, coord_tuple):
        """
        Transform texture coordinates to screen coordinates.

        Args:
            coord_tuple: (tex_x, tex_y) texture coordinates where (0,0) is top-left

        Returns:
            (x, y) screen coordinates where (0,0) is top-left of screen
        """
        tex_x, tex_y = coord_tuple
        width, height = glfw.get_framebuffer_size(self.window)

        in_pos_x = tex_x * 2 - 1
        in_pos_y = tex_y * 2 - 1

        tex_aspect = self.sim.view_tex.size[0] / self.sim.view_tex.size[1]
        window_aspect = width / height

        if tex_aspect > window_aspect:
            scale_x = 1.0
            scale_y = window_aspect / tex_aspect
        else:
            scale_x = tex_aspect / window_aspect
            scale_y = 1.0

        scale_x /= self.zoom
        scale_y /= self.zoom

        pos_x = in_pos_x * scale_x
        pos_y = in_pos_y * scale_y

        pos_x -= self.position[0] / self.zoom
        pos_y += self.position[1] / self.zoom

        x_screen = (pos_x + 1) / 2 * width
        y_screen = (1 - (pos_y + 1) / 2) * height

        return (x_screen, y_screen)
