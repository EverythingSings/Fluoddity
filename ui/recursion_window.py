"""Recursion Settings window: contraction map parameters and SDF recursion controls."""
from imgui_bundle import imgui


class RecursionWindowMixin:
    """Mixin for the Recursion Settings window. Combined into UI via multiple inheritance."""

    def render_recursion_window(self):
        """Render the Recursion Settings window (visible when shader_driven_field is checked)."""
        visible, opened = imgui.begin("Recursion Settings", True)
        if not opened:
            self.state.preferences.show_recursion_window = False
            imgui.end()
            return
        if visible:
            prefs = self.state.preferences

            # --- Read-only displays ---
            rec_info = self._display_info.get('recursion_info', {})
            pos = rec_info.get('pos', (0, 0, 0))
            fwd = rec_info.get('fwd', (0, 0, 0))
            ws  = rec_info.get('world_scale', 1.0)
            imgui.text(f"Pos:  ({pos[0]:.2f}, {pos[1]:.2f}, {pos[2]:.2f})")
            imgui.text(f"Fwd:  ({fwd[0]:.2f}, {fwd[1]:.2f}, {fwd[2]:.2f})")
            imgui.text(f"Scale: {ws:.6f}")
            imgui.separator()

            # --- Contraction Map Controls ---
            imgui.text("Contraction Map")

            _, prefs.sim_scale = imgui.drag_float(
                "Scale##rec", prefs.sim_scale, 0.001, 0.001, 1.0
            )
            self._delayed_tooltip("Contraction ratio. Smaller = more nesting levels visible.")

            euler = [prefs.sim_euler_x, prefs.sim_euler_y, prefs.sim_euler_z]
            changed, new_euler = imgui.drag_float3("Rotation (rad)", euler, 0.01)
            if changed:
                prefs.sim_euler_x, prefs.sim_euler_y, prefs.sim_euler_z = new_euler
            self._delayed_tooltip("Per-level rotation in radians (X, Y, Z Euler angles).")

            _, prefs.cell_radius = imgui.drag_float(
                "Cell Radius", prefs.cell_radius, 0.1, 0.5, 50.0
            )
            self._delayed_tooltip("Radius of the fundamental spherical cell.")

            offset = [prefs.sim_offset_x, prefs.sim_offset_y, prefs.sim_offset_z]
            changed, new_offset = imgui.drag_float3("Sim Offset", offset, 0.01)
            if changed:
                prefs.sim_offset_x, prefs.sim_offset_y, prefs.sim_offset_z = new_offset
            self._delayed_tooltip("Manual offset for the recurrence origin.")

            _, prefs.zoom_rate = imgui.slider_float(
                "Zoom Rate", prefs.zoom_rate, 0.95, 1.05
            )
            self._delayed_tooltip("Continuous zoom speed. 1.0 = off. <1 = zoom in, >1 = zoom out.")

            imgui.separator()

            # --- Disable Recursion checkbox ---
            changed, prefs.disable_recursion = imgui.checkbox(
                "Disable Recursion", prefs.disable_recursion
            )
            if changed:
                self._request_recursion_recompile = True
            self._delayed_tooltip(
                "Disables micro/macro SDF chains.\n"
                "Only the base SDF is rendered. Teleportation is also disabled."
            )

        imgui.end()
