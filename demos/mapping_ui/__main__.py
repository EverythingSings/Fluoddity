"""Mapping UI Demo - standalone ImGui prototype for shader customization UI.

Run with:  python -m demos.mapping_ui
"""
import glfw
import moderngl
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend

from .params import PARAMS, PARAM_GROUPS, ParamDef
from .mapping_menu import (
    MappingType, MappingState, MappingMenuWindow, render_mapping_menu,
)


class MappingDemo:
    def __init__(self):
        # --- GLFW ---
        if not glfw.init():
            raise RuntimeError("GLFW init failed")
        self.window = glfw.create_window(900, 700, "Mapping UI Demo", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("Window creation failed")
        glfw.make_context_current(self.window)
        glfw.swap_interval(1)

        # --- ModernGL (needed by ImGui backend, no actual rendering) ---
        self.ctx = moderngl.create_context()

        # --- ImGui ---
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(self.window)
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable

        # --- App state ---
        self.values: dict[str, float] = {p.name: p.default_value for p in PARAMS}
        self.mappings: dict[str, MappingState] = {
            p.name: MappingState(param_name=p.name) for p in PARAMS
        }
        self.open_menus: dict[str, MappingMenuWindow] = {}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        while not glfw.window_should_close(self.window):
            glfw.poll_events()
            self.ctx.clear(0.15, 0.15, 0.18)

            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            self._render_physics_window()
            self._render_open_menus()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(self.window)

        self.imgui_renderer.shutdown()
        glfw.terminate()

    # ------------------------------------------------------------------
    # Physics sliders window
    # ------------------------------------------------------------------

    def _render_physics_window(self):
        imgui.begin("Physics Settings")

        group_labels = {
            'basics':   "Basics - Trail sensors and rule mutation",
            'forces':   "Forces",
            'advanced': "Advanced",
        }

        for group_key in ('basics', 'forces', 'advanced'):
            if imgui.collapsing_header(group_labels[group_key], imgui.TreeNodeFlags_.default_open):
                for pdef in PARAM_GROUPS[group_key]:
                    self._render_slider(pdef)

        imgui.end()

    def _render_slider(self, pdef: ParamDef):
        mapping = self.mappings[pdef.name]
        has_mapping = mapping.mapping_type != MappingType.NONE

        # Tint slider background when a mapping is active
        if has_mapping:
            imgui.push_style_color(imgui.Col_.frame_bg, imgui.ImVec4(0.35, 0.22, 0.10, 0.54))
            imgui.push_style_color(imgui.Col_.frame_bg_hovered, imgui.ImVec4(0.45, 0.28, 0.10, 0.70))
            imgui.push_style_color(imgui.Col_.frame_bg_active, imgui.ImVec4(0.55, 0.32, 0.12, 0.80))
            imgui.push_style_color(imgui.Col_.slider_grab, imgui.ImVec4(0.90, 0.60, 0.20, 1.0))
            imgui.push_style_color(imgui.Col_.slider_grab_active, imgui.ImVec4(1.0, 0.70, 0.30, 1.0))

        # Use mapping's range override if set, else param defaults
        s_min = mapping.slider_min if mapping.slider_min is not None else pdef.default_min
        s_max = mapping.slider_max if mapping.slider_max is not None else pdef.default_max
        changed, new_val = imgui.slider_float(
            pdef.label, self.values[pdef.name], s_min, s_max, "%.3f")
        if changed:
            self.values[pdef.name] = new_val

        if has_mapping:
            imgui.pop_style_color(5)

        # Right-click opens mapping menu
        if imgui.is_item_clicked(imgui.MouseButton_.right):
            mouse = imgui.get_mouse_pos()
            if pdef.name in self.open_menus:
                # Already open: reset position to bring to cursor and unpin
                menu = self.open_menus[pdef.name]
                menu.initial_pos = (mouse.x, mouse.y)
                menu.has_been_positioned = False
                menu.is_pinned = False
                menu._frames_since_open = 0
                imgui.set_window_focus(f"Mapping: {pdef.label}##{pdef.name}")
            else:
                self.open_menus[pdef.name] = MappingMenuWindow(
                    param_name=pdef.name,
                    initial_pos=(mouse.x, mouse.y),
                )

    # ------------------------------------------------------------------
    # Open mapping menus
    # ------------------------------------------------------------------

    def _render_open_menus(self):
        to_close = []
        for pname, menu in self.open_menus.items():
            mapping = self.mappings[pname]
            keep_open = render_mapping_menu(menu, mapping, self.mappings)
            if not keep_open:
                to_close.append(pname)
        for pname in to_close:
            del self.open_menus[pname]


if __name__ == "__main__":
    demo = MappingDemo()
    demo.run()
