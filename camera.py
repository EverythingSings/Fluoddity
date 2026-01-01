import glfw
import numpy as np
from utilities.gl_helpers import read_shader, tryset
import moderngl
from state import CameraState
from utilities.frame_assembler import FrameAssembler

class Camera:
    def __init__(self, ctx, sim, window):
        self.ctx = ctx
        self.sim = sim
        self.window = window
        self.BRIGHTNESS = 1
        self.cam_brush_mode = True
        
        # Camera state
        self.position = np.array([0.0, 0.0])  # 2D position
        self.zoom = 1.0

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

        self.cam_brush_target = self.ctx.texture(glfw.get_framebuffer_size(self.window), 4, dtype='f4')
        self.cam_brush_fbo = self.ctx.framebuffer([self.cam_brush_target])

        # Frame assembler (temporal accumulation + gamma correction)
        self.frame_assembler = FrameAssembler(self.ctx, self.cam_brush_target)
        self.assembled_texture = None

    def generate_view_texture(self):
        """Generate raw view texture (PRE-gamma correction) based on current mode."""

        if self.cam_brush_mode:
            # Render particles to cam_brush_target
            self.cam_brush_fbo.use()
            width, height = glfw.get_framebuffer_size(self.window)
            self.ctx.viewport = (0, 0, width, height)
            self.ctx.clear(0, 0, 0, 1)

            self.cam_brush_program['cam_pos'].value = tuple(self.position)
            self.cam_brush_program['cam_zoom'].value = self.zoom
            self.cam_brush_program['canvas_resolution'].value = self.sim.view_tex.size
            self.cam_brush_program['window_size'].value = (width, height)

            # Particles need additive blending
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
            self.ctx.blend_equation = moderngl.FUNC_ADD

            self.cam_brush_vao.render(mode=moderngl.TRIANGLE_FAN, instances=self.sim.entity_count, vertices=4)

            self.ctx.disable(moderngl.BLEND)

            # Return raw texture (NO gamma correction - that happens in FrameAssembler)
            return self.cam_brush_target
        else:
            return self.sim.view_tex

    def apply_state(self, state: CameraState) -> None:
        """Apply camera state from Orchestrator."""
        self.position = state.position.copy()
        self.zoom = state.zoom
        self.BRIGHTNESS = state.BRIGHTNESS
        self.cam_brush_mode = state.cam_brush_mode

    def render(self, sim_going: bool = True, current_view_option: int = 2,
                sweep_mode: bool = False, sweep_reticle_pos: tuple = (0.5, 0.5),
                sweep_reticle_visible: bool = False, screen_aspect: float = 1.0):
        # ALWAYS use assembled texture when simulation is running
        # When paused, regenerate view to allow camera panning/zooming
        if sim_going and self.assembled_texture is not None:
            TEX_TO_VIEW = self.assembled_texture
        else:
            # When paused or no assembled texture yet, generate fresh frame and apply gamma
            raw_tex = self.generate_view_texture()
            # Apply gamma correction via frame assembler (single sample mode)
            TEX_TO_VIEW = self.frame_assembler.assemble_frame(
                raw_tex,
                total_samples=1,
                current_sample_index=0,
                view_mode=current_view_option,
                sweep_mode=sweep_mode,
                sweep_reticle_pos=sweep_reticle_pos,
                sweep_reticle_visible=sweep_reticle_visible,
                screen_aspect=screen_aspect,
                brightness=self.BRIGHTNESS
            )
            # assemble_frame returns the texture immediately when total_samples=1

        # Render to screen
        self.ctx.screen.use()
        width, height = glfw.get_framebuffer_size(self.window)
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        self.program['cam_pos'].value = tuple(self.position)
        self.program['cam_zoom'].value = self.zoom
        self.program['tex_size'].value = TEX_TO_VIEW.size
        self.program['window_size'].value = (width, height)

        if self.cam_brush_mode:
            tryset(self.program, 'cam_pos', (0, 0))
            tryset(self.program, 'cam_zoom', 1)

        TEX_TO_VIEW.use(location=0)
        self.program['view_tex'].value = 0
        self.vao.render()

    def reload(self):
        winx, winy =glfw.get_framebuffer_size(self.window)
        if winx > 0 and winy > 0:
            self.setup_rendering()

    def screen_to_tex(self, coord_tuple, tex_size: tuple = None):
        """
        Transform screen coordinates to texture coordinates.

        Args:
            coord_tuple: (x, y) screen coordinates where (0,0) is top-left
            tex_size: (width, height) of texture. If None, uses self.sim.view_tex.size

        Returns:
            (tex_x, tex_y) texture coordinates where (0,0) is top-left of texture
        """
        x_screen, y_screen = coord_tuple
        width, height = glfw.get_framebuffer_size(self.window)

        x_ndc = (x_screen / width) * 2 - 1
        y_ndc = (1 - y_screen / height) * 2 - 1

        if tex_size is None:
            tex_size = self.sim.view_tex.size
        tex_aspect = tex_size[0] / tex_size[1]
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

    def tex_to_screen(self, coord_tuple, tex_size: tuple = None):
        """
        Transform texture coordinates to screen coordinates.

        Args:
            coord_tuple: (tex_x, tex_y) texture coordinates where (0,0) is top-left
            tex_size: (width, height) of texture. If None, uses self.sim.view_tex.size

        Returns:
            (x, y) screen coordinates where (0,0) is top-left of screen
        """
        tex_x, tex_y = coord_tuple
        width, height = glfw.get_framebuffer_size(self.window)

        in_pos_x = tex_x * 2 - 1
        in_pos_y = tex_y * 2 - 1

        if tex_size is None:
            tex_size = self.sim.view_tex.size
        tex_aspect = tex_size[0] / tex_size[1]
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
