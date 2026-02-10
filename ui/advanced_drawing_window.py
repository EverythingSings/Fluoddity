"""Advanced Drawing window: brush modes, force/strafe field controls."""
import math
from imgui_bundle import imgui


class AdvancedDrawingWindowMixin:
    """Mixin for advanced drawing controls. Combined into UI via multiple inheritance."""

    def render_advanced_drawing_window(self):
        """Render the Advanced Drawing Controls window."""
        expanded, opened = imgui.begin("Drawing Controls", True)

        if not opened:
            self.state.preferences.advanced_drawing_enabled = False
            imgui.end()
            return

        if expanded:
            prefs = self.state.preferences

            # === Draw Size + Draw Power sliders (coupled to same prefs as preferences_window) ===
            _, prefs.draw_size = imgui.slider_float(
                "Draw Size##adv", prefs.draw_size, 0.01, 0.5, format="%.3f"
            )
            _, prefs.draw_power = imgui.slider_float(
                "Draw Power##adv", prefs.draw_power, 0.1, 5.0, format="%.2f"
            )

            imgui.separator()

            # === Target Checkboxes ===
            imgui.text("Draw Targets")

            _, prefs.advanced_draw_canvas = imgui.checkbox(
                "Trails / Canvas (Default)", prefs.advanced_draw_canvas
            )
            self._delayed_tooltip("Draw on the particle trail canvas (existing behavior).")

            _, prefs.advanced_draw_force_field = imgui.checkbox(
                "Force Field", prefs.advanced_draw_force_field
            )
            self._delayed_tooltip(
                "Draw onto the force field texture.\n"
                "Particles will be pushed in the drawn direction."
            )

            _, prefs.advanced_draw_strafe_field = imgui.checkbox(
                "Strafe Field", prefs.advanced_draw_strafe_field
            )
            self._delayed_tooltip(
                "Draw onto the strafe field texture.\n"
                "Particles will strafe laterally based on drawn direction."
            )

            imgui.separator()

            # === Brush Mode Combo ===
            brush_modes = [
                "Mouse Direction",
                "Inverse Mouse Direction",
                "Fixed Direction",
                "In - Attract",
                "Out - Repel",
            ]
            _, prefs.brush_mode = imgui.combo("Brush Mode", prefs.brush_mode, brush_modes)

            # === Fixed Direction Heading slider ===
            _, prefs.fixed_direction_heading = imgui.slider_float(
                "Fixed Direction Heading",
                prefs.fixed_direction_heading,
                -math.pi,
                math.pi,
                format="%.3f",
            )
            self._delayed_tooltip(
                "Heading angle for Fixed Direction brush mode.\n"
                "0 = up (positive Y), PI/2 = right."
            )

            imgui.separator()

            # === Fill Popup (click to open) ===
            if imgui.button("Fill..."):
                imgui.open_popup("fill_popup")
            self._delayed_tooltip(
                "Apply the brush to the entire canvas/field for one frame.\n"
                "Uses full kernel coverage (weight=1.0 everywhere)."
            )
            if imgui.begin_popup("fill_popup"):
                if imgui.selectable("Fixed Direction",False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 0
                if imgui.selectable("Radial - In",False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 1
                if imgui.selectable("Radial - Out",False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 2
                imgui.end_popup()

            imgui.separator()

            # === Clear Button ===
            if imgui.button("Clear Force/Strafe Fields"):
                self._request_clear_fields = True
            self._delayed_tooltip("Reset the force and strafe field textures to zero.")

        imgui.end()
