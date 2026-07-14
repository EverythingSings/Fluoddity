import glfw
import math
import numpy as np
from utilities.gl_helpers import read_shader, tryset, tryset_mat4
import moderngl
from state import CameraState
from rendering import ImagePipeline

class Camera:
    def __init__(self, ctx, sim, window, controller_cam=None):
        self.ctx = ctx
        self.sim = sim
        self.window = window
        self.BRIGHTNESS = 1
        self.ink_weight = 1
        self.watercolor_mode = False

        # Camera state (2D pan/zoom retained only for sweep-reticle screen mapping)
        self.position = np.array([0.0, 0.0])
        self.zoom = 1.0

        # 3D camera state (the app is 3D-only)
        self.fov_3d = 50.0
        self.controller_cam = controller_cam  # 3D FPS camera (injected by App)
        self.optix_interface = None  # Set by orchestrator: the OptiX path tracer (or None)
        self.optix_enabled = False   # Transient per-frame flag: OptiX active (renderer==Optix)
        self.optix_resolution_scale = 1.0  # Render resolution multiplier for OptiX

        self.setup_rendering()

    def setup_rendering(self):
        # Fullscreen quad vertices (position + texcoord)
        quad_vertices = np.array([
            -1.0, -1.0,  0.0, 1.0,  # bottom-left
             1.0, -1.0,  1.0, 1.0,  # bottom-right
             1.0,  1.0,  1.0, 0.0,  # top-right
            -1.0,  1.0,  0.0, 0.0   # top-left
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

        # Create vertex array
        vbo = self.ctx.buffer(quad_vertices.tobytes())
        ibo = self.ctx.buffer(quad_indices.tobytes())
        self.vao = self.ctx.vertex_array(
            self.program,
            [(vbo, '2f 2f', 'in_position', 'in_texcoord')],
            ibo
        )

        # Shared render-output FBO: both the OptiX path tracer and the GL_POINTS
        # path blit their result into this texture, which the ImagePipeline reads.
        self.cam_brush_target = self.ctx.texture(glfw.get_framebuffer_size(self.window), 4, dtype='f4')
        self.cam_brush_fbo = self.ctx.framebuffer([self.cam_brush_target])

        # 3D point renderer
        try:
            points_vert = read_shader('shaders/points_3d.vert')
            points_frag = read_shader('shaders/points_3d.frag')
            self.points_3d_program = self.ctx.program(
                vertex_shader=points_vert,
                fragment_shader=points_frag
            )
        except Exception as e:
            print('Points 3D shader failed')
            print(e)
            self.points_3d_program = None

        # Empty VAO for GL_POINTS rendering (reads from SSBO via gl_VertexID)
        self.points_3d_vao = self.ctx.vertex_array(self.points_3d_program, []) if self.points_3d_program else None

        # Image pipeline (temporal accumulation + tonemap + watercolor + SDF +
        # bloom). Produces a markup-free finished frame. Overlay markup (sweep /
        # draw / field) is composited afterwards by the Viewer for display only,
        # so recorded frames stay clean.
        self.image_pipeline = ImagePipeline(self.ctx)
        self.assembled_texture = None

    @staticmethod
    def _look_at(eye, target, up):
        """Build a 4x4 view matrix (column-major, OpenGL convention)."""
        f = target - eye
        f = f / np.linalg.norm(f)
        s = np.cross(f, up)
        s = s / np.linalg.norm(s)
        u = np.cross(s, f)

        m = np.eye(4, dtype=np.float32)
        m[0, 0:3] = s
        m[1, 0:3] = u
        m[2, 0:3] = -f
        m[0, 3] = -np.dot(s, eye)
        m[1, 3] = -np.dot(u, eye)
        m[2, 3] = np.dot(f, eye)
        return m

    @staticmethod
    def _perspective(fov_y, aspect, near, far):
        """Build a 4x4 perspective projection matrix."""
        f = 1.0 / math.tan(fov_y / 2.0)
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = f / max(.0001,aspect)
        m[1, 1] = f
        m[2, 2] = (far + near) / (near - far)
        m[2, 3] = (2.0 * far * near) / (near - far)
        m[3, 2] = -1.0
        return m

    def compute_fps_view_proj(self, pos, dir_vec, up, fov, aspect):
        """Compute combined view*projection from FPS camera vectors."""
        eye = np.array(pos, dtype=np.float32)
        target = eye + np.array(dir_vec, dtype=np.float32)
        up_vec = np.array(up, dtype=np.float32)
        view = self._look_at(eye, target, up_vec)
        proj = self._perspective(math.radians(fov), aspect, 0.01, 100.0)
        return proj @ view

    @staticmethod
    def compute_fps_camera_basis(dir_vec, up):
        """Return (right, up) unit vectors for the camera.

        Used for depth-of-field lens offset in the path tracer.
        """
        f = np.array(dir_vec, dtype=np.float32)
        f = f / np.linalg.norm(f)
        u = np.array(up, dtype=np.float32)
        right = np.cross(f, u)
        right = right / np.linalg.norm(right)
        true_up = np.cross(right, f)
        return right, true_up

    def generate_view_texture(self):
        """Generate raw view texture (PRE-gamma correction). Always 3D."""
        return self._generate_3d_view_texture()

    def _generate_3d_view_texture(self):
        """Render particles in 3D using OptiX (if enabled) or GL_POINTS."""
        width, height = glfw.get_framebuffer_size(self.window)

        # OptiX path: raytrace spheres via RT cores
        if (self.optix_enabled
                and self.optix_interface is not None
                and self.controller_cam is not None):
            cam = self.controller_cam
            scale = max(0.1, self.optix_resolution_scale)
            render_w = max(1, int(width * scale))
            render_h = max(1, int(height * scale))
            tex = self.optix_interface.render_frame(
                entity_buffer=self.sim.get_entity_buffer(),
                entity_count=self.sim.entity_count,
                cam_pos=cam.pos,
                cam_dir=cam.dir,
                cam_up=cam.up,
                fov=self.fov_3d,
                width=render_w,
                height=render_h,
            )
            if tex is not None:
                # Blit OptiX result into cam_brush_target via FBO
                self.cam_brush_fbo.use()
                self.ctx.viewport = (0, 0, width, height)
                self.ctx.clear(0, 0, 0, 1)
                tex.use(location=0)
                self.program['cam_pos'].value = (0, 0)
                self.program['cam_zoom'].value = 1.0
                self.program['tex_size'].value = (float(width), float(height))
                self.program['window_size'].value = (width, height)
                self.program['view_tex'].value = 0
                self.vao.render()
                return self.cam_brush_target

        # GL_POINTS fallback path
        self.cam_brush_fbo.use()
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0, 0, 0, 1)

        aspect = width / max(height, 1)
        cam = self.controller_cam
        view_proj = self.compute_fps_view_proj(
            cam.pos, cam.dir, cam.up, self.fov_3d, aspect
        )
        tryset_mat4(self.points_3d_program, 'view_proj', view_proj)
        tryset(self.points_3d_program, 'point_scale', 800.0)

        # Enable point size from vertex shader, depth test, and additive blending
        self.ctx.enable_only(moderngl.PROGRAM_POINT_SIZE | moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        self.ctx.blend_equation = moderngl.FUNC_ADD

        self.points_3d_vao.render(mode=moderngl.POINTS, vertices=self.sim.entity_count)

        self.ctx.disable(moderngl.BLEND)
        self.ctx.enable_only(0)  # Reset to defaults

        return self.cam_brush_target

    def apply_state(self, state: CameraState) -> None:
        """Apply camera state from Orchestrator."""
        self.position = state.position.copy()
        self.zoom = state.zoom
        self.BRIGHTNESS = state.BRIGHTNESS

        # 3D camera state
        self.fov_3d = state.fov
        self.optix_enabled = state.optix_enabled

    def render(self, sim_going: bool = True,
                screen_aspect: float = 1.0,
                watercolor_mode: bool = False, ink_weight: float = 1.0,
                tonemap_softness: float = 1.0,
                bloom_enabled: bool = False, bloom_threshold: float = 0.8,
                bloom_intensity: float = 0.5, bloom_radius: float = 1.0,
                sdf_enabled: bool = False, inv_view_proj=None,
                sdf_sun_dir: tuple = (0.577, 0.577, 0.577),
                sdf_sun_color: tuple = (3.0, 3.0, 3.0),
                sdf_sky_color: tuple = (0.5, 0.7, 1.0)):
        """Produce the finished, markup-free display texture and return it.

        No longer draws to the screen or composites overlays — that is the
        Viewer's job (display) and the video recorder's (file). Returns a
        window-sized, 1:1 finished texture (or None if none is available yet).
        """
        self.watercolor_mode = watercolor_mode
        self.ink_weight = ink_weight

        # ALWAYS use the (markup-free) finished texture when the sim is running.
        # When paused, regenerate the view so camera panning/zooming still works.
        if sim_going and self.assembled_texture is not None:
            return self.assembled_texture

        # Paused / no finished texture yet: generate a fresh finished frame.
        raw_tex = self.generate_view_texture()
        return self.image_pipeline.assemble_frame(
            raw_tex,
            total_samples=1,
            current_sample_index=0,
            brightness=self.BRIGHTNESS,
            ink_weight=self.ink_weight,
            watercolor_mode=watercolor_mode,
            tonemap_softness=tonemap_softness,
            sdf_enabled=sdf_enabled,
            inv_view_proj=inv_view_proj,
            sdf_sun_dir=sdf_sun_dir,
            sdf_sun_color=sdf_sun_color,
            sdf_sky_color=sdf_sky_color,
            bloom_enabled=bloom_enabled,
            bloom_threshold=bloom_threshold,
            bloom_intensity=bloom_intensity,
            bloom_radius=bloom_radius,
        )

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
        width = max(1,width)
        height = max(1,height)
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

    def screen_to_ray_3d(self, screen_pos: tuple) -> tuple[np.ndarray, np.ndarray]:
        """Convert screen coordinates to a 3D ray for entity picking.

        Uses the same camera parameters as _generate_3d_view_texture() so the
        ray matches the rendered perspective view exactly.

        Args:
            screen_pos: (x, y) screen coordinates where (0,0) is top-left

        Returns:
            (ray_origin, ray_direction) where both are (3,) numpy arrays
            and ray_direction is unit length.
        """
        cam = self.controller_cam
        width, height = glfw.get_framebuffer_size(self.window)
        width = max(1, width)
        height = max(1, height)

        # Screen coords to NDC
        x_ndc = (screen_pos[0] / width) * 2.0 - 1.0
        y_ndc = (screen_pos[1] / height) * 2.0 - 1.0  # Flipped to match Y-flipped render

        aspect = width / height
        tan_half_fov = math.tan(math.radians(self.fov_3d) / 2.0)

        # Ray direction in world space (unnormalized)
        direction = (cam.dir
                     + cam.right * (x_ndc * tan_half_fov * aspect)
                     + cam.up * (y_ndc * tan_half_fov))
        direction = direction / np.linalg.norm(direction)

        return (cam.pos.copy(), direction)

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
