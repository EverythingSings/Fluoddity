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

            # === 1. Draw Size + Draw Power sliders ===
            _, prefs.draw_size = imgui.slider_float(
                "Draw Size##adv", prefs.draw_size, 0.01, 0.5, format="%.3f"
            )
            _, prefs.draw_power = imgui.slider_float(
                "Draw Power##adv", prefs.draw_power, 0.1, 5.0, format="%.2f"
            )

            # === 2. Brush Mode Combo ===
            brush_modes = [
                "Mouse Direction",
                "Inverse Mouse Direction",
                "Fixed Direction",
                "In - Attract",
                "Out - Repel",
            ]
            _, prefs.brush_mode = imgui.combo("Brush Mode", prefs.brush_mode, brush_modes)

            # === 3. Fill Popup ===
            if imgui.button("Fill..."):
                imgui.open_popup("fill_popup")
            self._delayed_tooltip(
                "Apply the brush to the entire canvas/field for one frame.\n"
                "Uses full kernel coverage (weight=1.0 everywhere)."
            )
            if imgui.begin_popup("fill_popup"):
                if imgui.selectable("Fixed Direction", False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 0
                if imgui.selectable("Radial - In", False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 1
                if imgui.selectable("Radial - Out", False)[0]:
                    self._request_fill_operation = True
                    self._fill_direction_type = 2
                imgui.end_popup()

            # === 4. Fixed Direction Heading slider ===
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

            # === 5. Active Draw Target (mutually exclusive radio buttons) ===
            imgui.text("Active Draw Target")

            # Determine current selection: 0=canvas, 1=force, 2=strafe
            if prefs.advanced_draw_force_field:
                target = 1
            elif prefs.advanced_draw_strafe_field:
                target = 2
            else:
                target = 0

            if imgui.radio_button("Trails / Canvas", target == 0):
                target = 0
            self._delayed_tooltip("Draw on the particle trail canvas (existing behavior).")

            if imgui.radio_button("Force Field", target == 1):
                target = 1
            self._delayed_tooltip(
                "Draw onto the force field texture.\n"
                "Particles will be pushed in the drawn direction."
            )

            if imgui.radio_button("Strafe Field", target == 2):
                target = 2
            self._delayed_tooltip(
                "Draw onto the strafe field texture.\n"
                "Particles will strafe laterally based on drawn direction."
            )

            # Apply mutually exclusive selection back to prefs
            prefs.advanced_draw_canvas = (target == 0)
            prefs.advanced_draw_force_field = (target == 1)
            prefs.advanced_draw_strafe_field = (target == 2)

            # === 6. Dynamic Clear button ===
            clear_labels = ["Trails/Canvas", "Force Field", "Strafe Field"]
            clear_label = clear_labels[target]
            if imgui.button(f"Clear {clear_label}"):
                if target == 0:
                    self._request_clear_canvas = True
                elif target == 1:
                    self._request_clear_force_field = True
                elif target == 2:
                    self._request_clear_strafe_field = True
            self._delayed_tooltip(f"Clear the {clear_label.lower()} to zero.")

            imgui.separator()

            # === 7. Force Field Strength (logarithmic: 0.0001 to 10.0) ===
            FIELD_MIN_EXP = -4.0  # 10^-4 = 0.0001
            FIELD_MAX_EXP = 1.0   # 10^1 = 10.0
            FIELD_EXP_RANGE = FIELD_MAX_EXP - FIELD_MIN_EXP  # 5.0

            if prefs.force_field_strength > 0:
                fslider = (math.log10(prefs.force_field_strength) - FIELD_MIN_EXP) / FIELD_EXP_RANGE
            else:
                fslider = 0.0
            fslider = max(0.0, min(1.0, fslider))
            _, new_fpos = imgui.slider_float(
                "Force Field Strength",
                fslider,
                0.0,
                1.0,
                f"{prefs.force_field_strength:.4f}",
            )
            prefs.force_field_strength = 10.0 ** (FIELD_MIN_EXP + FIELD_EXP_RANGE * new_fpos)
            self._delayed_tooltip(
                "Multiplier for force field effects.\n"
                "Logarithmic scale: 0.0001 to 10.0, default 1.0."
            )

            # === 8. Strafe Field Strength (logarithmic: 0.0001 to 10.0) ===
            if prefs.strafe_field_strength > 0:
                sslider = (math.log10(prefs.strafe_field_strength) - FIELD_MIN_EXP) / FIELD_EXP_RANGE
            else:
                sslider = 0.0
            sslider = max(0.0, min(1.0, sslider))
            _, new_spos = imgui.slider_float(
                "Strafe Field Strength",
                sslider,
                0.0,
                1.0,
                f"{prefs.strafe_field_strength:.4f}",
            )
            prefs.strafe_field_strength = 10.0 ** (FIELD_MIN_EXP + FIELD_EXP_RANGE * new_spos)
            self._delayed_tooltip(
                "Multiplier for strafe field effects.\n"
                "Logarithmic scale: 0.0001 to 10.0, default 1.0."
            )

        imgui.end()
