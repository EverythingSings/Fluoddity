"""Volrender capstone demo — Step 10.

Interactive viewer for the volumetric path tracer. Generates a procedural
particle cloud, splats it into the voxel grid, and path-traces it with
adjustable medium/sun/sky parameters.

Run from project root:
    python -m volrender.example.demo
"""
from __future__ import annotations

import math
import os
import sys

import glfw
import moderngl
import numpy as np
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend

# Add project root to path so volrender is importable
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from volrender import (
    VolumeRenderer, GridParams, MediumParams, SunParams, SkyParams, RenderParams
)

_SHADER_DIR = os.path.join(os.path.dirname(__file__), "shaders")

# COMMENT FLAG: spp_per_frame — samples dispatched per frame tick to stay responsive
SPP_PER_FRAME = 2


# ------------------------------------------------------------------ camera math
def _look_at(eye, target, up):
    """Build a 4x4 view matrix (row-major storage, OpenGL convention)."""
    eye = np.array(eye, dtype=np.float64)
    target = np.array(target, dtype=np.float64)
    up = np.array(up, dtype=np.float64)
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float64)
    m[0, 0:3] = s
    m[1, 0:3] = u
    m[2, 0:3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m


def _perspective(fov_y_rad, aspect, near, far):
    """Build a 4x4 perspective projection matrix."""
    f = 1.0 / math.tan(fov_y_rad / 2.0)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def _compute_view_proj(eye, target, up, fov_deg, aspect):
    """Build view_proj = proj @ view (matching main camera convention)."""
    view = _look_at(eye, target, up)
    proj = _perspective(math.radians(fov_deg), aspect, 0.01, 100.0)
    return (proj @ view).astype(np.float32)


# ----------------------------------------------------------------- orbit camera
class OrbitCamera:
    """Simple orbit camera around a center point."""

    def __init__(self, center=(0, 0, 0), distance=4.0, azimuth=0.0,
                 elevation=0.3, fov_deg=50.0):
        self.center = np.array(center, dtype=np.float64)
        self.distance = distance
        self.azimuth = azimuth      # radians, horizontal
        self.elevation = elevation  # radians, vertical
        self.fov_deg = fov_deg

    def eye(self) -> np.ndarray:
        x = self.distance * math.cos(self.elevation) * math.sin(self.azimuth)
        y = self.distance * math.sin(self.elevation)
        z = self.distance * math.cos(self.elevation) * math.cos(self.azimuth)
        return self.center + np.array([x, y, z])

    def view_proj(self, aspect: float) -> np.ndarray:
        return _compute_view_proj(
            self.eye(), self.center, [0, 1, 0], self.fov_deg, aspect)


# ----------------------------------------------------------- entity generation
def generate_entities(n_entities: int = 50000, seed: int = 42) -> np.ndarray:
    """Generate procedural gaussian blobs with a vortex velocity field.

    Returns (N, 8) float32 array in Entity layout:
        px, py, pz, vx, vy, vz, hue, size
    """
    rng = np.random.default_rng(seed)
    entities = np.zeros((n_entities, 8), dtype=np.float32)

    half = n_entities // 2

    # Blob 1: centered at (-0.3, 0.0, 0.0), sigma=0.3
    pos1 = rng.normal(0, 0.3, (half, 3)).astype(np.float32)
    pos1 += np.array([-0.3, 0.0, 0.0], dtype=np.float32)

    # Blob 2: centered at (+0.3, 0.1, 0.0), sigma=0.25
    pos2 = rng.normal(0, 0.25, (n_entities - half, 3)).astype(np.float32)
    pos2 += np.array([0.3, 0.1, 0.0], dtype=np.float32)

    positions = np.concatenate([pos1, pos2], axis=0)
    entities[:, 0:3] = positions

    # Vortex velocity field: cross(Y_hat, r_xz) + noise
    r_xz = positions.copy()
    r_xz[:, 1] = 0.0  # project onto XZ plane
    y_hat = np.array([[0, 1, 0]], dtype=np.float32)
    velocity = np.cross(y_hat, r_xz)
    norms = np.linalg.norm(velocity, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-6)
    velocity = velocity / norms * 0.5
    velocity += rng.normal(0, 0.1, velocity.shape).astype(np.float32)
    entities[:, 3:6] = velocity

    # Placeholder hue and size (unused in v1)
    entities[:, 6] = rng.uniform(0, 1, n_entities).astype(np.float32)
    entities[:, 7] = 0.01

    return entities


# ----------------------------------------------------------- shader loading
def _read_shader(name: str) -> str:
    path = os.path.join(_SHADER_DIR, name)
    with open(path, 'r') as f:
        return f.read()


# ---------------------------------------------------------------- main demo
class VolrenderDemo:
    """Interactive volrender demo with imgui controls."""

    def __init__(self):
        # ---- GLFW ----
        if not glfw.init():
            raise RuntimeError("GLFW initialization failed")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)

        self.width, self.height = 1280, 720
        self.window = glfw.create_window(
            self.width, self.height, "Volrender Demo", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("GLFW window creation failed")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)

        # ---- ModernGL ----
        self.ctx = moderngl.create_context(require=430)

        # ---- ImGui ----
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(self.window)

        # ---- Generate entities ----
        print("Generating entities...")
        entities = generate_entities(n_entities=5000000)
        self.entity_count = len(entities)
        self.entity_buffer = self.ctx.buffer(entities.tobytes())

        # ---- Volume renderer ----
        print("Initializing volume renderer...")
        grid_params = GridParams(
            bounds_min=(-1.5, -1.5, -1.5),
            bounds_max=(1.5, 1.5, 1.5),
            resolution=(256, 256, 256),
            majorant_resolution=(16, 16, 16),
            splat_outer_product=False,
        )
        self.renderer = VolumeRenderer(self.ctx, grid_params)

        print("Splatting entities into voxel grid...")
        self.renderer.splat(self.entity_buffer, self.entity_count)

        # ---- Render target (rgba16f) ----
        self.target_tex = self.ctx.texture(
            (self.width, self.height), 4, dtype='f2')
        self.target_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        # ---- Tonemap blit program ----
        self._setup_tonemap_blit()

        # ---- Points overlay program ----
        self._setup_points_overlay()

        # ---- Camera ----
        self.camera = OrbitCamera(distance=4.0, elevation=0.3, azimuth=0.8)

        # ---- Render parameters ----
        self.extinction_rgb = [1.0, 1.0, 1.0]
        self.albedo_rgb = [0.8, 0.8, 0.8]
        self.density_scale = .0001
        self.sun_direction = [0.577, 0.577, 0.577]
        self.sun_color = [1.0, 0.95, 0.9]
        self.sun_intensity = 3.0
        self.sky_color = [0.5, 0.7, 1.0]
        self.sky_intensity = 1.0
        self.num_samples = 1
        self.exposure = 1.5
        self.show_points = False

        # ---- Progressive render state ----
        self._rendering = False        # currently accumulating?
        self._samples_done = 0         # samples accumulated so far
        self._render_view_proj = None  # view_proj locked at render start
        self._needs_restart = True     # start a fresh render on first frame

        # ---- Mouse state ----
        self._mouse_dragging = False
        self._last_mouse_x = 0.0
        self._last_mouse_y = 0.0

        # Register scroll callback
        glfw.set_scroll_callback(self.window, self._scroll_callback)

    def _setup_tonemap_blit(self):
        """Compile tonemap program and create fullscreen quad VAO."""
        vert_src = _read_shader("tonemap_blit.vert")
        frag_src = _read_shader("tonemap_blit.frag")
        self._tonemap_prog = self.ctx.program(
            vertex_shader=vert_src, fragment_shader=frag_src)

        # Fullscreen quad (two triangles, clip-space)
        vertices = np.array([
            -1.0, -1.0,
             1.0, -1.0,
             1.0,  1.0,
            -1.0, -1.0,
             1.0,  1.0,
            -1.0,  1.0,
        ], dtype=np.float32)
        vbo = self.ctx.buffer(vertices.tobytes())
        self._tonemap_vao = self.ctx.vertex_array(
            self._tonemap_prog, [(vbo, '2f', 'in_vert')])

    def _setup_points_overlay(self):
        """Compile points overlay program and create empty VAO."""
        vert_src = _read_shader("points_overlay.vert")
        frag_src = _read_shader("points_overlay.frag")
        self._points_prog = self.ctx.program(
            vertex_shader=vert_src, fragment_shader=frag_src)
        self._points_vao = self.ctx.vertex_array(self._points_prog, [])

    def _scroll_callback(self, window, xoffset, yoffset):
        """Zoom camera on scroll (only when imgui doesn't want mouse)."""
        if imgui.get_io().want_capture_mouse:
            return
        self.camera.distance *= 0.9 if yoffset > 0 else 1.1
        self.camera.distance = max(0.5, min(50.0, self.camera.distance))

    def _handle_mouse(self):
        """Handle orbit camera via left-mouse-button drag."""
        if imgui.get_io().want_capture_mouse:
            self._mouse_dragging = False
            return

        lmb = glfw.get_mouse_button(self.window, glfw.MOUSE_BUTTON_LEFT)
        mx, my = glfw.get_cursor_pos(self.window)

        if lmb == glfw.PRESS:
            if self._mouse_dragging:
                dx = mx - self._last_mouse_x
                dy = my - self._last_mouse_y
                self.camera.azimuth -= dx * 0.005
                self.camera.elevation += dy * 0.005
                self.camera.elevation = max(-math.pi / 2 + 0.01,
                                            min(math.pi / 2 - 0.01,
                                                self.camera.elevation))
            self._mouse_dragging = True
        else:
            self._mouse_dragging = False

        self._last_mouse_x = mx
        self._last_mouse_y = my

    def _build_params(self):
        """Build parameter dataclasses from current imgui state."""
        # Normalize sun direction
        sd = np.array(self.sun_direction, dtype=np.float64)
        norm = np.linalg.norm(sd)
        if norm > 1e-6:
            sd = sd / norm
        else:
            sd = np.array([0.0, 1.0, 0.0])

        medium = MediumParams(
            extinction_rgb=tuple(self.extinction_rgb),
            albedo_rgb=tuple(self.albedo_rgb),
            density_scale=self.density_scale,
        )
        sun = SunParams(
            direction=tuple(sd),
            color_rgb=tuple(self.sun_color),
            intensity=self.sun_intensity,
        )
        sky = SkyParams(
            color_top=tuple(self.sky_color),
            color_bottom=tuple(self.sky_color),
            intensity=self.sky_intensity,
        )
        render = RenderParams(
            num_samples=self.num_samples,
            batch_spp=1,
            max_bounces=0,
            rr_start_depth=4,
            seed=0,
        )
        return medium, sun, sky, render

    def _start_render(self):
        """Begin a new progressive render (reset accumulation)."""
        # Handle window resize
        fb_w, fb_h = glfw.get_framebuffer_size(self.window)
        if fb_w <= 0 or fb_h <= 0:
            return
        if (fb_w, fb_h) != (self.target_tex.width, self.target_tex.height):
            self.target_tex.release()
            self.target_tex = self.ctx.texture((fb_w, fb_h), 4, dtype='f2')
            self.target_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

        aspect = fb_w / fb_h
        self._render_view_proj = self.camera.view_proj(aspect)
        self.renderer.reset_accumulation()
        self._samples_done = 0
        self._rendering = True

    def _tick_render(self):
        """Accumulate a few samples this frame (non-blocking progressive)."""
        if not self._rendering:
            return

        remaining = self.num_samples - self._samples_done
        if remaining <= 0:
            self._rendering = False
            return

        batch = min(SPP_PER_FRAME, remaining)
        medium, sun, sky, render = self._build_params()

        self.renderer.accumulate(
            batch, self._render_view_proj, self.target_tex,
            medium, sun, sky, render)
        self._samples_done += batch

        if self._samples_done >= self.num_samples:
            self._rendering = False

        # Resolve current accumulation into target for display
        self._resolve_current()

    def _resolve_current(self):
        """Resolve the accumulation buffer into target_tex for display."""
        if self._samples_done == 0:
            return
        w, h = self.target_tex.width, self.target_tex.height
        prog = self.renderer._resolve_program
        from volrender.renderer import _tryset
        _tryset(prog, 'u_target_size', (w, h))
        _tryset(prog, 'u_sample_count', self._samples_done)

        self.renderer._accum_tex.bind_to_image(0, read=True, write=False)
        self.target_tex.bind_to_image(1, read=False, write=True)

        gx = math.ceil(w / 8)
        gy = math.ceil(h / 8)
        prog.run(gx, gy, 1)
        self.ctx.memory_barrier()

    def _blit_tonemap(self):
        """Blit the HDR target to screen with tonemapping."""
        self.ctx.screen.use()
        fb_w, fb_h = glfw.get_framebuffer_size(self.window)
        self.ctx.viewport = (0, 0, fb_w, fb_h)

        self.target_tex.use(location=0)
        if 'u_hdr_image' in self._tonemap_prog:
            self._tonemap_prog['u_hdr_image'] = 0
        if 'u_exposure' in self._tonemap_prog:
            self._tonemap_prog['u_exposure'] = self.exposure

        self._tonemap_vao.render()

    def _render_points_overlay(self):
        """Render GL_POINTS overlay of the entity buffer."""
        fb_w, fb_h = glfw.get_framebuffer_size(self.window)
        aspect = fb_w / fb_h
        view_proj = self.camera.view_proj(aspect)

        self.ctx.enable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)
        self.ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE)

        self.entity_buffer.bind_to_storage_buffer(0)
        if 'u_view_proj' in self._points_prog:
            self._points_prog['u_view_proj'].write(
                view_proj.T.astype(np.float32).tobytes())

        self._points_vao.render(mode=moderngl.POINTS,
                                vertices=self.entity_count)

        self.ctx.disable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)

    def _render_imgui(self):
        """Render imgui control panel."""
        self.imgui_renderer.process_inputs()
        imgui.new_frame()

        imgui.begin("Volume Renderer Controls")

        # ---- Medium ----
        if imgui.collapsing_header("Medium", imgui.TreeNodeFlags_.default_open.value):
            changed, self.extinction_rgb = imgui.color_edit3(
                "Extinction RGB", self.extinction_rgb)
            changed, self.albedo_rgb = imgui.color_edit3(
                "Albedo RGB", self.albedo_rgb)
            changed, self.density_scale = imgui.drag_float(
                "Density Scale", self.density_scale, 0.01, 0.01, 10.0)

        # ---- Sun ----
        if imgui.collapsing_header("Sun", imgui.TreeNodeFlags_.default_open.value):
            changed, self.sun_direction = imgui.drag_float3(
                "Direction", self.sun_direction, 0.01, -1.0, 1.0)
            changed, self.sun_color = imgui.color_edit3(
                "Sun Color", self.sun_color)
            changed, self.sun_intensity = imgui.slider_float(
                "Sun Intensity", self.sun_intensity, 0.0, 20.0)

        # ---- Sky ----
        if imgui.collapsing_header("Sky", imgui.TreeNodeFlags_.default_open.value):
            changed, self.sky_color = imgui.color_edit3(
                "Sky Color", self.sky_color)
            changed, self.sky_intensity = imgui.slider_float(
                "Sky Intensity", self.sky_intensity, 0.0, 5.0)

        # ---- Render ----
        if imgui.collapsing_header("Render", imgui.TreeNodeFlags_.default_open.value):
            changed, self.num_samples = imgui.slider_int(
                "Samples (SPP)", self.num_samples, 1, 512)
            changed, self.exposure = imgui.slider_float(
                "Exposure", self.exposure, 0.1, 10.0)

            if imgui.button("Re-render"):
                self._needs_restart = True

            imgui.same_line()
            changed, self.show_points = imgui.checkbox(
                "Show Points Overlay", self.show_points)

            # Progress indicator
            if self._rendering:
                imgui.same_line()
                imgui.text(f"  [{self._samples_done}/{self.num_samples} spp]")
            elif self._samples_done > 0:
                imgui.same_line()
                imgui.text(f"  [done: {self._samples_done} spp]")

        # ---- Export ----
        imgui.separator()
        if imgui.button("Save PNG"):
            self._save_png()

        imgui.end()

        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())

    def _save_png(self):
        """Tonemap HDR frame on CPU and save as PNG."""
        if self._samples_done == 0:
            print("Nothing to save — no samples rendered yet.")
            return

        # Read back the target texture directly
        tex = self.target_tex
        raw = tex.read()
        expected_f16 = tex.height * tex.width * 4 * 2
        expected_f32 = tex.height * tex.width * 4 * 4
        if len(raw) == expected_f32:
            hdr = np.frombuffer(raw, dtype=np.float32).reshape(
                tex.height, tex.width, 4)
        elif len(raw) == expected_f16:
            hdr = np.frombuffer(raw, dtype=np.float16).astype(
                np.float32).reshape(tex.height, tex.width, 4)
        else:
            print(f"Unexpected texture size: {len(raw)}")
            return

        rgb = hdr[:, :, :3].copy()

        # Exposure + Reinhard (matches shader)
        exposed = rgb * self.exposure
        ldr = exposed / (1.0 + exposed)

        # Gamma
        ldr = np.power(np.clip(ldr, 0.0, None), 1.0 / 2.2)

        # Convert to uint8
        img_u8 = (np.clip(ldr, 0.0, 1.0) * 255).astype(np.uint8)

        # Flip vertically (OpenGL bottom-up -> top-down for image files)
        img_u8 = img_u8[::-1]

        try:
            from PIL import Image
            img = Image.fromarray(img_u8, 'RGB')
            out_path = "volrender_output.png"
            img.save(out_path)
            print(f"Saved: {out_path}")
        except ImportError:
            # Fallback: save raw numpy
            out_path = "volrender_output.npy"
            np.save(out_path, img_u8)
            print(f"Pillow not found. Saved raw numpy: {out_path}")

    def run(self):
        """Main loop."""
        while not glfw.window_should_close(self.window):
            glfw.poll_events()

            # ESC to quit
            if glfw.get_key(self.window, glfw.KEY_ESCAPE) == glfw.PRESS:
                glfw.set_window_should_close(self.window, True)
                continue

            # Handle orbit camera
            self._handle_mouse()

            # Start a new render if requested
            if self._needs_restart:
                self._start_render()
                self._needs_restart = False

            # Accumulate a few samples this frame (progressive)
            self._tick_render()

            # Blit tonemapped result to screen
            self.ctx.screen.use()
            self.ctx.clear(0.1, 0.1, 0.1)
            self._blit_tonemap()

            # Points overlay
            if self.show_points:
                self._render_points_overlay()

            # ImGui on top
            self._render_imgui()

            glfw.swap_buffers(self.window)

    def cleanup(self):
        """Release resources."""
        self.imgui_renderer.shutdown()
        glfw.terminate()


# -------------------------------------------------------------------- entry
def main():
    demo = VolrenderDemo()
    try:
        demo.run()
    finally:
        demo.cleanup()


if __name__ == "__main__":
    main()
