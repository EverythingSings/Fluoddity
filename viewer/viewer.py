"""Viewer window + overlay pass.

The Viewer displays the active renderer's *finished, markup-free* frame in an
always-present ImGui window that fills the docking central node. It owns an
`OverlayCompositor` and runs a small overlay pass so UI markup (sweep reticle,
draw-trail ring, advanced-drawing field overlay) is composited over the finished
frame **for display only** — recorded video and screenshots keep the clean frame.

Two-phase per frame:

1. `prepare(finished_tex, overlay_params, ...)` runs during the GL phase of the
   frame (called from the orchestrator right after the renderer produces its
   finished frame). It composites overlays into a display texture and stashes it.
2. `render_window(hidden)` runs inside the ImGui frame (called from `UI.render()`
   render dispatch). It draws the stashed display texture as an ImGui image
   filling the central dock node. It is **immune to the show/hide-windows button**
   (the `hidden` flag is accepted for symmetry but never hides the Viewer).

Keeping the overlay GL pass out of the ImGui draw (phase 1) mirrors the
video-recorder-as-file / viewer-as-display symmetry and keeps FBO work off the
ImGui render path.
"""
from __future__ import annotations

import moderngl
import numpy as np
from imgui_bundle import imgui

from rendering import OverlayCompositor


class Viewer:
    """Always-displayed window that shows the renderer's finished frame + markup."""

    WINDOW_NAME = "Viewer"

    def __init__(self, ctx, window):
        self.ctx = ctx
        self.window = window
        self.overlay_compositor = OverlayCompositor(ctx)
        # The texture actually shown on screen this frame (finished frame with
        # display-only overlays composited). None until the first prepare().
        self._display_tex = None
        self._tex_ref = None
        self._tex_glo = None  # cache: only rebuild the ImTextureRef when glo changes
        # Whether the central-node docking has been set up once.
        self._dock_initialized = False
        # True when the pointer is over the Viewer window (and nothing floats
        # above it there). Updated each frame in render_window(); read by the UI
        # mouse gating so clicks/scroll on the Viewer pass through to the sim,
        # but clicks on floating panels don't. Reflects last-built-frame state
        # (GLFW callbacks fire before this frame's UI is built) — same one-frame
        # latency the old `want_capture_mouse` gate had.
        self.hovered = False
        # Owned target for display-only debug overlays (arrow debug) so they
        # never touch the recorded frame. Lazily allocated.
        self._debug_tex = None
        self._debug_fbo = None
        self._debug_shader = None
        self._debug_vao = None
        self._debug_size = (0, 0)

    def prepare(self, finished_tex, *, overlay_params=None, watercolor_mode=False,
                screen_aspect=1.0, exposure=0.0, mouse_screen_coords=(0.5, 0.5),
                camera_position=(0.0, 0.0), camera_zoom=1.0,
                canvas_resolution=(1024, 1024)):
        """Composite display-only overlays over ``finished_tex`` and stash it.

        Call during the GL phase (after the renderer produces its finished
        frame). ``finished_tex`` must be a window-sized, 1:1 display texture.
        Passing ``None`` clears the Viewer (nothing to show this frame).
        """
        if finished_tex is None:
            self._display_tex = None
            return

        self._display_tex = self._composite_overlays(
            finished_tex, overlay_params, watercolor_mode, screen_aspect,
            exposure, mouse_screen_coords, camera_position, camera_zoom,
            canvas_resolution)

    def _composite_overlays(self, finished_tex, overlay_params, watercolor_mode,
                            screen_aspect, exposure, mouse_screen_coords,
                            camera_position, camera_zoom, canvas_resolution):
        """Composite UI markup over a finished frame for display only.

        Returns the composited display texture, or ``finished_tex`` unchanged
        when there is no markup to draw. Never mutates the recorded frame.
        """
        if not overlay_params:
            return finished_tex
        comp = self.overlay_compositor
        if not comp.has_markup(
                sweep_mode=overlay_params.get('sweep_mode', False),
                sweep_reticle_visible=overlay_params.get('sweep_reticle_visible', False)):
            return finished_tex
        return comp.composite(
            finished_tex,
            sweep_mode=overlay_params.get('sweep_mode', False),
            sweep_reticle_pos=overlay_params.get('sweep_reticle_pos', (0.5, 0.5)),
            sweep_reticle_visible=overlay_params.get('sweep_reticle_visible', False),
            screen_aspect=screen_aspect,
            watercolor_mode=watercolor_mode,
            exposure=exposure,
        )

    def draw_debug_overlay(self, render_fn):
        """Render a display-only debug overlay (e.g. arrow debug) over the frame.

        ``render_fn()`` should draw a blended fullscreen pass into the currently
        bound framebuffer. To keep the recorded frame clean, this always renders
        into a Viewer-owned copy of the current display texture — never into the
        finished frame the video recorder captures. No-ops when there is no
        display texture yet.
        """
        if self._display_tex is None:
            return
        src = self._display_tex
        width, height = src.size
        self._ensure_debug_target(width, height)
        # Copy the current display texture into the owned debug target, then let
        # render_fn() blend its overlay on top.
        self._debug_fbo.use()
        self.ctx.viewport = (0, 0, width, height)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self._blit(src, self._debug_shader, self._debug_vao)
        render_fn()
        self._display_tex = self._debug_tex

    def _ensure_debug_target(self, width, height):
        if self._debug_shader is None:
            self._debug_shader = self.ctx.program(
                vertex_shader=(
                    "#version 330 core\nin vec2 position;\nout vec2 uv;\n"
                    "void main(){uv=position*0.5+0.5;"
                    "gl_Position=vec4(position,0.0,1.0);}"),
                fragment_shader=(
                    "#version 330 core\nin vec2 uv;\nout vec4 fragColor;\n"
                    "uniform sampler2D src;\n"
                    "void main(){fragColor=vec4(texture(src,uv).rgb,1.0);}"))
            verts = np.array([-1.0, -1.0, 1.0, -1.0, 1.0, 1.0, -1.0, 1.0],
                             dtype=np.float32)
            idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
            vbo = self.ctx.buffer(verts.tobytes())
            ibo = self.ctx.buffer(idx.tobytes())
            self._debug_vao = self.ctx.vertex_array(
                self._debug_shader, [(vbo, '2f', 'position')], ibo)
        if self._debug_size != (width, height):
            if self._debug_tex is not None:
                self._debug_fbo.release()
                self._debug_tex.release()
            self._debug_tex = self.ctx.texture((width, height), 4, dtype='f4')
            self._debug_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self._debug_fbo = self.ctx.framebuffer(color_attachments=[self._debug_tex])
            self._debug_size = (width, height)

    def _blit(self, src_tex, shader, vao):
        src_tex.use(location=0)
        shader['src'] = 0
        vao.render()

    def _texture_ref(self):
        """ImTextureRef for the current display texture, rebuilt only on change."""
        glo = self._display_tex.glo
        if self._tex_ref is None or self._tex_glo != glo:
            self._tex_ref = imgui.ImTextureRef(glo)
            self._tex_glo = glo
        return self._tex_ref

    def render_window(self, dockspace_id):
        """Draw the Viewer window filling the central dock node.

        Called from the UI render dispatch, inside the ImGui frame. Immune to
        the show/hide-windows button — always drawn. Docks into the passthru
        central node the first time so it fills the render area behind panels.
        """
        # Dock the Viewer into the central node once, so it fills the render
        # area (behind/around the floating panels) instead of appearing as a
        # free-floating window on first launch.
        if not self._dock_initialized:
            imgui.set_next_window_dock_id(dockspace_id, imgui.Cond_.once)
            self._dock_initialized = True

        window_flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_scroll_with_mouse
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_nav_focus
        )

        imgui.push_style_var(imgui.StyleVar_.window_padding, imgui.ImVec2(0.0, 0.0))
        # p_open=None -> no close button; the Viewer can never be closed.
        imgui.begin(self.WINDOW_NAME, None, window_flags)
        # Pointer over the Viewer content (and nothing floating above it here)?
        # Drives the UI mouse gating so Viewer clicks reach the sim while panel
        # clicks don't.
        self.hovered = imgui.is_window_hovered()
        avail = imgui.get_content_region_avail()
        if self._display_tex is not None and avail.x > 0 and avail.y > 0:
            # The display texture is APP-WINDOW-sized and lives in app-window
            # screen space. The Viewer is a *window onto* that texture: it must
            # show the sub-rectangle of the texture that sits under its own
            # screen rect (CROP), not stretch the whole texture into its content
            # region (which would squish). Cropping keeps all mouse<->texture
            # math in full-window screen space, and lets the recorder capture the
            # full app-window frame while the Viewer shows a possibly-cropped
            # view of it.
            vp = imgui.get_main_viewport()
            vp_pos = vp.pos
            vp_size = vp.size  # full viewport — matches the framebuffer-sized texture
            origin = imgui.get_cursor_screen_pos()
            inv_w = 1.0 / max(vp_size.x, 1.0)
            inv_h = 1.0 / max(vp_size.y, 1.0)
            # uv sub-rectangle of the texture under this window's content rect.
            # No vertical flip: screen-top maps to texture v=0 (reproduces the
            # old camera.frag orientation), and screen y increases downward with
            # v, so the mapping is a direct proportion.
            u0 = (origin.x - vp_pos.x) * inv_w
            v0 = (origin.y - vp_pos.y) * inv_h
            u1 = (origin.x - vp_pos.x + avail.x) * inv_w
            v1 = (origin.y - vp_pos.y + avail.y) * inv_h
            imgui.image(self._texture_ref(), imgui.ImVec2(avail.x, avail.y),
                        uv0=imgui.ImVec2(u0, v0), uv1=imgui.ImVec2(u1, v1))
        imgui.end()
        imgui.pop_style_var()

    def cleanup(self):
        self.overlay_compositor.cleanup()
        for attr in ('_debug_fbo', '_debug_tex', '_debug_vao', '_debug_shader'):
            obj = getattr(self, attr, None)
            if obj is not None:
                obj.release()
                setattr(self, attr, None)
        self._debug_size = (0, 0)
        self._display_tex = None
        self._tex_ref = None
