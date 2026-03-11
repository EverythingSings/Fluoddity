"""
Minimal shader harness: GLFW + ModernGL + optional ImGui.

Self-similar SDF explorer.  The scene is defined around the origin;
a contraction map (scale + rotation) tiles it into nested spherical
cells.  Camera teleportation at cell boundaries creates the illusion
of infinite recursion.

Controls:
    Left-drag    Look around
    WASD         Move horizontally
    Space        Move up
    Left Shift   Move down
    V            Hot-reload march.frag
    Esc          Quit
"""

import math, sys, time
from pathlib import Path

import numpy as np
import glfw
import moderngl


def rot_mat(x, y, z):
    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)

    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

    return Rz @ Ry @ Rx

# ---------------------------------------------------------------------------
# Contraction-map defaults (fixed point at origin)
# ---------------------------------------------------------------------------

DEFAULT_SCALE       = 0.019
DEFAULT_EULER       = [0.0, 0.0, 0.0]   # (x, y, z) radians
DEFAULT_CELL_RADIUS = 5.0

# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

def _norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _rodrigues(v, axis, angle):
    """Rotate *v* around *axis* by *angle* radians (Rodrigues' formula)."""
    a = _norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(a, v) * s + a * np.dot(a, v) * (1.0 - c)

# ---------------------------------------------------------------------------
# Camera – stores orientation as explicit vectors so that arbitrary rotation
# matrices (e.g. cell-transition teleports) can be applied directly.
# ---------------------------------------------------------------------------

class Camera:
    def __init__(self, pos=(0, 2, 0), fwd=(0, 0, -1), up=(0, 1, 0)):
        self.pos = np.array(pos, dtype=np.float64)
        self.fwd = _norm(np.array(fwd, dtype=np.float64))
        self.up  = _norm(np.array(up,  dtype=np.float64))
        self.speed       = 5.0
        self.sensitivity = 0.003

    @property
    def right(self):
        return _norm(np.cross(self.fwd, self.up))

    def rotate(self, yaw, pitch):
        """Apply yaw (around camera-up) and pitch (around camera-right)."""
        if abs(yaw) > 1e-9:
            self.fwd = _rodrigues(self.fwd, self.up, yaw)
        if abs(pitch) > 1e-9:
            r = self.right
            new_fwd = _rodrigues(self.fwd, r, pitch)
            if abs(np.dot(new_fwd, self.up)) < 0.99:
                self.fwd = new_fwd
                self.up  = _rodrigues(self.up, r, pitch)
        self._ortho()

    def _ortho(self):
        """Gram-Schmidt re-orthogonalisation to prevent float drift."""
        self.fwd = _norm(self.fwd)
        self.up  = self.up - np.dot(self.up, self.fwd) * self.fwd
        self.up  = _norm(self.up)

    def move(self, window, dt, world_scale=1.0):
        s = self.speed * world_scale * dt
        f, r, u = self.fwd, self.right, self.up
        pressed = lambda k: glfw.get_key(window, k) == glfw.PRESS
        if pressed(glfw.KEY_W):          self.pos += f * s
        if pressed(glfw.KEY_S):          self.pos -= f * s
        if pressed(glfw.KEY_D):          self.pos += r * s
        if pressed(glfw.KEY_A):          self.pos -= r * s
        if pressed(glfw.KEY_SPACE):      self.pos += u * s
        if pressed(glfw.KEY_LEFT_SHIFT): self.pos -= u * s
        self.pos *= .99

    def teleport_inward(self, scale, rotation):
        """Camera crossed inner sphere → zoom into nested cell."""
        self.pos = rotation @ self.pos / scale
        self.fwd = rotation @ self.fwd
        self.up  = rotation @ self.up
        self._ortho()

    def teleport_outward(self, scale, rotation):
        """Camera crossed outer sphere → zoom out to parent cell."""
        rot_inv = rotation.T
        self.pos = scale * (rot_inv @ self.pos)
        self.fwd = rot_inv @ self.fwd
        self.up  = rot_inv @ self.up
        self._ortho()

# ---------------------------------------------------------------------------
# Embedded vertex shader (fullscreen quad)
# ---------------------------------------------------------------------------

_VERT = """\
#version 330
in vec2 in_position;
out vec2 v_texcoord;
void main() {
    gl_Position = vec4(in_position, 0.0, 1.0);
    v_texcoord  = in_position * 0.5 + 0.5;
}
"""

# ---------------------------------------------------------------------------
# Shader loader + hot-reload helper
# ---------------------------------------------------------------------------

_STUB_MARKER = "//STUB VERSION: GETS REPLACED BY SCENE.GLSL"


def _load_program(ctx, frag_path, scene_path=None):
    """Compile a new program from the vertex source and *frag_path* on disk.

    If *scene_path* is given, the block between the two STUB markers in the
    fragment source is replaced with the contents of that file.
    """
    frag_src = frag_path.read_text()
    if scene_path is not None:
        first = frag_src.index(_STUB_MARKER)
        second = frag_src.index(_STUB_MARKER, first + len(_STUB_MARKER))
        end = second + len(_STUB_MARKER)
        scene_src = scene_path.read_text()
        frag_src = frag_src[:first] + scene_src + frag_src[end:]
    return ctx.program(vertex_shader=_VERT, fragment_shader=frag_src)


def _try_reload(ctx, frag_path, old_prog, vbo, scene_path=None):
    """Attempt hot-reload.  Returns (prog, vao, ok)."""
    try:
        prog = _load_program(ctx, frag_path, scene_path)
        vao  = ctx.vertex_array(prog, [(vbo, "2f", "in_position")])
        old_prog.release()
        label = "full scene" if scene_path else "stub"
        print(f"[reload] shader reloaded OK ({label})")
        return prog, vao, True
    except Exception as exc:
        print(f"[reload] FAILED – {exc}")
        return None, None, False

# ---------------------------------------------------------------------------
# Uniform helpers
# ---------------------------------------------------------------------------

def _u(prog, name, value):
    """Set a uniform, tolerating optimised-away names."""
    if name in prog:
        prog[name].value = value


def _u_mat3(prog, name, mat):
    """Upload a 3×3 matrix uniform (column-major)."""
    if name in prog:
        prog[name].write(mat.astype("f4").T.tobytes())

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # ---- GLFW init -----------------------------------------------------------
    if not glfw.init():
        sys.exit("Failed to initialise GLFW")

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)

    window = glfw.create_window(700, 700, "Recursive SDF", None, None)
    if not window:
        glfw.terminate()
        sys.exit("Failed to create GLFW window")

    glfw.make_context_current(window)
    glfw.swap_interval(1)  # vsync

    # ---- ModernGL context ----------------------------------------------------
    ctx = moderngl.create_context()

    # ---- Shader program ------------------------------------------------------
    frag_path  = Path(__file__).parent / "march.frag"
    scene_path = Path(__file__).parent / "scene.glsl"
    full_scene = False
    prog = _load_program(ctx, frag_path)

    # ---- Fullscreen quad (triangle-strip) ------------------------------------
    vbo = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4"))
    vao = ctx.vertex_array(prog, [(vbo, "2f", "in_position")])

    # ---- Camera (start inside the fundamental cell) --------------------------
    cam = Camera(pos=[0.0, 2.0, 0.0])

    # ---- Contraction-map state (driven by ImGui) -----------------------------
    sim_scale   = DEFAULT_SCALE
    sim_euler   = list(DEFAULT_EULER)
    cell_radius = DEFAULT_CELL_RADIUS

    # ---- Recursive SDF state -------------------------------------------------
    world_scale = 1.0
    world_orientation = np.eye(3, dtype=np.float64)

    # ---- Optional ImGui overlay ----------------------------------------------
    imgui_ok = False
    imgui_mod = None
    imgui_renderer = None
    try:
        from imgui_bundle import imgui as _imgui
        from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

        _imgui.create_context()
        imgui_renderer = GlfwRenderer(window)
        imgui_mod = _imgui
        imgui_ok = True
    except Exception as exc:
        print(f"[info] ImGui unavailable ({exc}) – running without overlay")

    # ---- Input state ---------------------------------------------------------
    dragging = False
    last_mx = last_my = 0.0
    want_reload = False

    # Save ImGui's callbacks so we can chain through them
    _prev_mouse_button_cb = glfw.set_mouse_button_callback(window, None)
    _prev_key_cb = glfw.set_key_callback(window, None)

    def _on_mouse_button(win, button, action, mods):
        if _prev_mouse_button_cb:
            _prev_mouse_button_cb(win, button, action, mods)
        nonlocal dragging, last_mx, last_my
        if imgui_ok and imgui_mod.get_io().want_capture_mouse:
            return
        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                dragging = True
                last_mx, last_my = glfw.get_cursor_pos(win)
                glfw.set_input_mode(win, glfw.CURSOR, glfw.CURSOR_DISABLED)
            else:
                dragging = False
                glfw.set_input_mode(win, glfw.CURSOR, glfw.CURSOR_NORMAL)

    def _on_key(win, key, scancode, action, mods):
        if _prev_key_cb:
            _prev_key_cb(win, key, scancode, action, mods)
        nonlocal want_reload
        if imgui_ok and imgui_mod.get_io().want_capture_keyboard:
            return
        if action == glfw.PRESS:
            if key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(win, True)
            elif key == glfw.KEY_V:
                want_reload = True

    glfw.set_mouse_button_callback(window, _on_mouse_button)
    glfw.set_key_callback(window, _on_key)

    # ---- Timing --------------------------------------------------------------
    frame_count = 0
    t0 = last_t = time.perf_counter()
    log_scale = math.log(DEFAULT_SCALE)  # cached, updated when scale changes

    # ---- Main loop -----------------------------------------------------------
    while not glfw.window_should_close(window):
        glfw.poll_events()

        now = time.perf_counter()
        dt  = now - last_t
        last_t = now

        # Hot-reload
        if want_reload:
            want_reload = False
            sp = scene_path if full_scene else None
            new_prog, new_vao, ok = _try_reload(ctx, frag_path, prog, vbo, sp)
            if ok:
                vao.release()
                prog, vao = new_prog, new_vao

        # Mouse look
        if dragging:
            mx, my = glfw.get_cursor_pos(window)
            cam.rotate(
                -(mx - last_mx) * cam.sensitivity,
                -(my - last_my) * cam.sensitivity,
            )
            last_mx, last_my = mx, my

        # ---- Per-frame update ------------------------------------------------

        sim_rotation = rot_mat(*sim_euler)

        # 1. Move camera (speed scaled by world_scale from previous frame)
        cam.move(window, dt, world_scale)

        # 2. Teleport checks — spherical cells centered on the origin
        d = float(np.linalg.norm(cam.pos))
        r_inner = cell_radius * sim_scale

        if d < r_inner:
            cam.teleport_inward(sim_scale, sim_rotation)
            world_orientation = sim_rotation @ world_orientation
            d = float(np.linalg.norm(cam.pos))
        elif d > cell_radius:
            cam.teleport_outward(sim_scale, sim_rotation)
            world_orientation = sim_rotation.T @ world_orientation
            d = float(np.linalg.norm(cam.pos))

        # 3. world_scale: logarithmic interpolation from cell_radius (=1.0)
        #    down to r_inner (=sim_scale).
        #    t = log(cell_radius / d) / log(cell_radius / r_inner)
        #      = log(cell_radius / d) / log(1 / sim_scale)
        #      = log(cell_radius / d) / -log(sim_scale)
        d_clamped = max(r_inner, min(cell_radius, d))
        t = math.log(cell_radius / d_clamped) / -log_scale
        world_scale = sim_scale ** t

        # ---- Render ----------------------------------------------------------
        w, h = glfw.get_framebuffer_size(window)
        if w == 0 or h == 0:
            continue
        ctx.viewport = (0, 0, w, h)
        ctx.clear()

        # Upload uniforms
        _u(prog, "resolution",         (float(w), float(h)))
        _u(prog, "time",               now - t0)
        _u(prog, "frame_count",        frame_count)
        _u(prog, "u_cam",              tuple(cam.pos.astype("f4")))
        _u(prog, "u_view_dir",         tuple(cam.fwd.astype("f4")))
        _u(prog, "u_up_dir",           tuple(cam.up.astype("f4")))
        _u(prog, "u_scale",            float(sim_scale))
        _u_mat3(prog, "u_rotation",    sim_rotation)
        _u(prog, "u_cell_radius",      float(cell_radius))
        _u(prog, "u_worldScale",       float(world_scale))
        _u_mat3(prog, "u_world_orientation", world_orientation)

        vao.render(moderngl.TRIANGLE_STRIP)

        # ---- ImGui overlay ---------------------------------------------------
        if imgui_ok:
            imgui_renderer.process_inputs()
            imgui_mod.new_frame()

            imgui_mod.set_next_window_pos((10, 10), imgui_mod.Cond_.once)
            imgui_mod.begin(
                "Info", flags=imgui_mod.WindowFlags_.always_auto_resize
            )
            imgui_mod.text(f"FPS: {1.0 / max(dt, 1e-6):.0f}")
            p = cam.pos
            imgui_mod.text(f"Pos:  ({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})")
            f = cam.fwd
            imgui_mod.text(f"Fwd:  ({f[0]:.2f}, {f[1]:.2f}, {f[2]:.2f})")
            imgui_mod.text(f"Scale: {world_scale:.6f}")
            imgui_mod.separator()

            # -- Contraction map controls --
            imgui_mod.text("Contraction Map")

            ch, v = imgui_mod.drag_float("Scale", sim_scale, 0.001, 0.001, 1.0)
            if ch:
                sim_scale = v
                log_scale = math.log(sim_scale)

            ch, v = imgui_mod.drag_float3("Rotation (rad)", list(sim_euler), 0.01)
            if ch:
                sim_euler[:] = v

            ch, v = imgui_mod.drag_float("Cell Radius", cell_radius, 0.1, 0.5, 50.0)
            if ch:
                cell_radius = v

            imgui_mod.separator()

            ch, v = imgui_mod.checkbox("Full Scene", full_scene)
            if ch:
                full_scene = v
                want_reload = True

            imgui_mod.separator()
            imgui_mod.text_colored(
                (0.5, 0.5, 0.5, 1.0),
                "LMB-drag:look  WASD:move  V:reload  Esc:quit",
            )
            imgui_mod.end()

            imgui_mod.render()
            imgui_renderer.render(imgui_mod.get_draw_data())

        glfw.swap_buffers(window)
        frame_count += 1

    # ---- Cleanup -------------------------------------------------------------
    if imgui_ok:
        imgui_renderer.shutdown()
    vao.release()
    vbo.release()
    prog.release()
    ctx.release()
    glfw.terminate()


if __name__ == "__main__":
    main()
