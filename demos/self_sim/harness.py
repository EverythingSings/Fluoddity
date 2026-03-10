"""
Minimal shader harness: GLFW + ModernGL + optional ImGui.

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
# Similarity transform constants (Base ↔ Micro relationship)
# ---------------------------------------------------------------------------

SIM_OFFSET      = np.array([1.0, 0.0, 0.0])     # Micro copy center in Base space
SIM_SCALE       = 0.06                            # Micro scale factor
SIM_ROTATION    = rot_mat(0,.21,0)#np.eye(3, dtype=np.float64)     # Micro rotation (identity = no rotation)
REGION_HALF_EXT = np.array([5.0, 5.0, 5.0])      # Fundamental region AABB half-size
TRANSITION_DIST = 1.0                             # Transition shell thickness

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
# SDF helpers (Python mirrors of GLSL functions for CPU-side teleport checks)
# ---------------------------------------------------------------------------

def sd_box(p, half_extents):
    """Signed box distance. Negative = inside."""
    q = np.abs(p) - half_extents
    return float(np.linalg.norm(np.maximum(q, 0.0)) + min(max(q[0], max(q[1], q[2])), 0.0))


def sd_micro_box(p, offset, scale, rotation, region_half_ext):
    """Signed distance to the Micro OBB in Base space. Negative = inside."""
    q = rotation @ (p - offset)
    half_ext = region_half_ext * scale
    d = np.abs(q) - half_ext
    return float(np.linalg.norm(np.maximum(d, 0.0)) + min(max(d[0], max(d[1], d[2])), 0.0))


def smoothstep(edge0, edge1, x):
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)

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

    # -- derived basis vector ---------------------------------------------------
    @property
    def right(self):
        return _norm(np.cross(self.fwd, self.up))

    # -- mouse look -------------------------------------------------------------
    def rotate(self, yaw, pitch):
        """Apply yaw (around camera-up) and pitch (around camera-right)."""
        if abs(yaw) > 1e-9:
            self.fwd = _rodrigues(self.fwd, self.up, yaw)
            # self.up is the rotation axis, so it's invariant under yaw
        if abs(pitch) > 1e-9:
            r = self.right
            new_fwd = _rodrigues(self.fwd, r, pitch)
            if abs(np.dot(new_fwd, self.up)) < 0.99:   # clamp to avoid flip
                self.fwd = new_fwd
                self.up  = _rodrigues(self.up, r, pitch)
        self._ortho()

    def _ortho(self):
        """Gram-Schmidt re-orthogonalisation to prevent float drift."""
        self.fwd = _norm(self.fwd)
        self.up  = self.up - np.dot(self.up, self.fwd) * self.fwd
        self.up  = _norm(self.up)

    # -- keyboard movement ------------------------------------------------------
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

    # -- teleportation ---------------------------------------------------------
    def teleport_inward(self, offset, scale, rotation):
        """Camera entered Micro box → remap to Base coordinates."""
        self.pos = rotation @ (self.pos - offset) / scale
        self.fwd = rotation @ self.fwd
        self.up  = rotation @ self.up
        self._ortho()

    def teleport_outward(self, offset, scale, rotation):
        """Camera exited fundamental region → remap toward Micro in Base."""
        rot_inv = rotation.T  # transpose = inverse for orthogonal matrices
        self.pos = scale * (rot_inv @ self.pos) + offset
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

def _load_program(ctx, frag_path):
    """Compile a new program from the vertex source and *frag_path* on disk."""
    return ctx.program(
        vertex_shader=_VERT,
        fragment_shader=frag_path.read_text(),
    )


def _try_reload(ctx, frag_path, old_prog, vbo):
    """Attempt hot-reload.  Returns (prog, vao, ok)."""
    try:
        prog = _load_program(ctx, frag_path)
        vao  = ctx.vertex_array(prog, [(vbo, "2f", "in_position")])
        old_prog.release()
        print("[reload] shader reloaded OK")
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
    frag_path = Path(__file__).parent / "march.frag"
    prog = _load_program(ctx, frag_path)

    # ---- Fullscreen quad (triangle-strip) ------------------------------------
    vbo = ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4"))
    vao = ctx.vertex_array(prog, [(vbo, "2f", "in_position")])

    # ---- Camera (start inside the fundamental region) ------------------------
    cam = Camera(pos=[0.0, 2.0, 0.0])

    # ---- Recursive SDF state -------------------------------------------------
    world_scale = 1.0
    world_orientation = np.eye(3, dtype=np.float64)  # accumulated rotation across teleports

    # ---- Input state ---------------------------------------------------------
    dragging = False
    last_mx = last_my = 0.0
    want_reload = False

    def _on_mouse_button(win, button, action, _mods):
        nonlocal dragging, last_mx, last_my
        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                dragging = True
                last_mx, last_my = glfw.get_cursor_pos(win)
                glfw.set_input_mode(win, glfw.CURSOR, glfw.CURSOR_DISABLED)
            else:
                dragging = False
                glfw.set_input_mode(win, glfw.CURSOR, glfw.CURSOR_NORMAL)

    def _on_key(win, key, _scancode, action, _mods):
        nonlocal want_reload
        if action == glfw.PRESS:
            if key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(win, True)
            elif key == glfw.KEY_V:
                want_reload = True

    glfw.set_mouse_button_callback(window, _on_mouse_button)
    glfw.set_key_callback(window, _on_key)

    # ---- Optional ImGui overlay ----------------------------------------------
    imgui_ok = False
    imgui_mod = None
    imgui_renderer = None
    try:
        from imgui_bundle import imgui as _imgui
        from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

        _imgui.create_context()
        imgui_renderer = GlfwRenderer(window, attach_callbacks=False)
        imgui_mod = _imgui
        imgui_ok = True
    except Exception as exc:
        print(f"[info] ImGui unavailable ({exc}) – running without overlay")

    # ---- Timing --------------------------------------------------------------
    frame_count = 0
    t0 = last_t = time.perf_counter()

    # ---- Main loop -----------------------------------------------------------
    while not glfw.window_should_close(window):
        glfw.poll_events()

        now = time.perf_counter()
        dt  = now - last_t
        last_t = now

        # Hot-reload
        if want_reload:
            want_reload = False
            new_prog, new_vao, ok = _try_reload(ctx, frag_path, prog, vbo)
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

        # ---- Per-frame update (spec §6) --------------------------------------

        # 1. Move camera (speed scaled by previous frame's worldScale)
        cam.move(window, dt, world_scale)

        # 2. Teleport checks
        micro_dist  = sd_micro_box(cam.pos, SIM_OFFSET, SIM_SCALE,
                                   SIM_ROTATION, REGION_HALF_EXT)
        region_dist = sd_box(cam.pos, REGION_HALF_EXT)

        if micro_dist < 0.0:
            # Entered Micro → remap to Base
            cam.teleport_inward(SIM_OFFSET, SIM_SCALE, SIM_ROTATION)
            # Inward teleport applies rotation to camera, so world dirs
            # need the inverse rotation to stay consistent
            #THIS WAS BACKWARDS it needs forward orientation here.
            world_orientation = SIM_ROTATION @ world_orientation
        elif region_dist > 0.0:
            # Exited fundamental region → remap toward Micro
            cam.teleport_outward(SIM_OFFSET, SIM_SCALE, SIM_ROTATION)
            world_orientation = SIM_ROTATION.T @ world_orientation

        # 3. Recompute transition parameter from (potentially teleported) camera
        micro_dist = sd_micro_box(cam.pos, SIM_OFFSET, SIM_SCALE,
                                  SIM_ROTATION, REGION_HALF_EXT)
        t = smoothstep(TRANSITION_DIST, 0.0, micro_dist)
        world_scale = 1.0 + (SIM_SCALE - 1.0) * t  # lerp(1.0, SIM_SCALE, t)

        # ---- Render ----------------------------------------------------------
        w, h = glfw.get_framebuffer_size(window)
        if w == 0 or h == 0:
            continue
        ctx.viewport = (0, 0, w, h)
        ctx.clear()

        # Upload uniforms
        _u(prog, "resolution",           (float(w), float(h)))
        _u(prog, "time",                 now - t0)
        _u(prog, "frame_count",          frame_count)
        _u(prog, "u_cam",               tuple(cam.pos.astype("f4")))
        _u(prog, "u_view_dir",          tuple(cam.fwd.astype("f4")))
        _u(prog, "u_up_dir",            tuple(cam.up.astype("f4")))
        _u(prog, "u_offset",            tuple(SIM_OFFSET.astype("f4")))
        _u(prog, "u_scale",             float(SIM_SCALE))
        _u_mat3(prog, "u_rotation",     SIM_ROTATION)
        _u(prog, "u_region_half_extents", tuple(REGION_HALF_EXT.astype("f4")))
        _u(prog, "u_worldScale",        float(world_scale))
        _u(prog, "u_transition_distance", float(TRANSITION_DIST))
        _u_mat3(prog, "u_world_orientation", world_orientation)

        # Draw
        vao.render(moderngl.TRIANGLE_STRIP)

        # ImGui overlay
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
            imgui_mod.text(f"Scale: {world_scale:.4f}")
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
