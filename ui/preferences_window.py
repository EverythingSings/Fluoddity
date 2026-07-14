"""Preferences window: particle count, canvas resolution, physics frequency, mouse mode, view, appearance."""
from imgui_bundle import imgui


class PreferencesWindowMixin:
    """Mixin for preferences window. Combined into UI via multiple inheritance."""

    def render_preferences_window(self):
        """Render the Preferences window (closeable)."""
        recording_active = self._display_info.get('recording_active', False)
        video_pending = self._display_info.get('video_pending', False)

        # Apply red tint to window background when recording or pending
        if recording_active or video_pending:
            imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.3, 0.1, 0.1, 1.0))

        # Use p_open to allow closing with X button
        expanded, self.state.preferences.ui_windows.show_preferences_window = imgui.begin("Preferences", True)

        if expanded:
            # === World Size section ===
            imgui.text("World Size")

            # Particle Count — commit on Enter
            changed, new_count = imgui.input_int(
                "Particle Count",
                self.state.preferences.rendering.entity_count,
                step=0,
                step_fast=0,
            )
            new_count = max(1000, min(new_count, 100_000_000))
            self.state.preferences.rendering.entity_count = new_count
            if imgui.is_item_deactivated_after_edit():
                if self.state.preferences.rendering.entity_count != self._last_applied_entity_count:
                    self._request_world_size_change = True
            self._delayed_tooltip("Number of active particles. Takes effect on Enter.\nMore particles = more VRAM (32 bytes each).")

            # Canvas Resolution — commit on Enter
            changed, new_res = imgui.input_int(
                "Canvas Resolution",
                self.state.preferences.rendering.canvas_resolution,
                step=0,
                step_fast=0,
            )
            new_res = max(64, min(new_res, 1024))
            self.state.preferences.rendering.canvas_resolution = new_res
            if imgui.is_item_deactivated_after_edit():
                if self.state.preferences.rendering.canvas_resolution != self._last_applied_canvas_resolution:
                    self._request_world_size_change = True
            self._delayed_tooltip("Cubic canvas dimension (W=H=D) for 3D trail textures.\nTakes effect on Enter. 6 textures at dim^3 * 4 bytes each.")

            # VRAM estimate
            ent_mb = self.state.preferences.rendering.entity_count * 32 / (1024 * 1024)
            rule_mb = 16384 * 480 / (1024 * 1024)  # fixed 2^14 entries * 480 bytes
            dim = self.state.preferences.rendering.canvas_resolution
            canvas_mb = 6 * dim * dim * dim * 4 / (1024 * 1024)
            total_mb = ent_mb + rule_mb + canvas_mb
            if total_mb >= 1024:
                imgui.text_colored(imgui.ImVec4(1.0, 0.7, 0.3, 1.0),
                                   f"Est. VRAM: {total_mb / 1024:.2f} GB")
            else:
                imgui.text(f"Est. VRAM: {total_mb:.0f} MB")

            imgui.separator()

            # === Physics Update Frequency section ===
            imgui.text("Physics Update Frequency")

            # Lock speedmult to motion_blur_samples when recording video
            if recording_active:
                locked_value = self.state.preferences.recording.motion_blur_samples
                imgui.begin_disabled()
                imgui.slider_int(
                    label="Rate",
                    v=locked_value,
                    v_min=1,
                    v_max=6,
                    format=f"x{locked_value} ({locked_value * 60}hz) [locked]"
                )
                imgui.end_disabled()
            else:
                # Slider with custom format showing multiplier and hz
                current_hz = self.state.preferences.rendering.speedmult * 60
                _, self.state.preferences.rendering.speedmult = imgui.slider_int(
                    label="Rate",
                    v=self.state.preferences.rendering.speedmult,
                    v_min=1,
                    v_max=30,
                    format=f"x%d ({current_hz}hz)"
                )
            self._delayed_tooltip("EXPENSIVE- Multiple physics steps can be calculated each\nrender frame and blended together for faster physics.\nMotion blur can be costly for high frequencies,\ntry turning it off if things feel sluggish.")

            # Motion blur checkbox (lock during recording)
            if recording_active:
                imgui.begin_disabled()

            _, self.state.preferences.rendering.motion_blur = imgui.checkbox(
                "Motion Blur",
                self.state.preferences.rendering.motion_blur
            )
            self._delayed_tooltip("EXPENSIVE- Multiple physics steps can be calculated each\nrender frame and blended together for faster physics.\nMotion blur can be costly for high frequencies,\ntry turning it off if things feel sluggish.")

            if recording_active:
                imgui.end_disabled()

            # Blur Quality slider (only shown when motion blur is enabled)
            if self.state.preferences.rendering.motion_blur:
                imgui.indent(20)
                # Custom format for blur quality
                blur_val = self.state.preferences.rendering.blur_quality
                if blur_val == 1:
                    blur_format = "1 : Every Frame"
                else:
                    blur_format = f"{blur_val} : Every {blur_val} Frames"

                _, self.state.preferences.rendering.blur_quality = imgui.slider_int(
                    "Blur Quality",
                    self.state.preferences.rendering.blur_quality,
                    1, 20,
                    format=blur_format
                )
                self._delayed_tooltip("Motion Blur can be expensive at high frequencies,\nskip some frames to improve performance")
                imgui.unindent(20)

            # Renderer selection (OpenGL vs Optix). Drives the whole app: display,
            # recording, and screenshots all use whichever renderer is active.
            from pathtracer_interface import PathTracerInterface
            renderer_labels = ["OpenGL", "Optix"]
            optix_available = PathTracerInterface.is_available()
            cur = self.state.preferences.rendering.renderer
            if cur < 0 or cur >= len(renderer_labels):
                cur = 0
            clicked, new_renderer = imgui.combo("Renderer", cur, renderer_labels)
            if clicked:
                if new_renderer == 1 and not optix_available:
                    pass  # OptiX unavailable — ignore the selection
                else:
                    self.state.preferences.rendering.renderer = new_renderer
            self._delayed_tooltip(
                "OpenGL: GL points (RT Off) or the volumetric path tracer (RT on).\n"
                "Optix: the RTX path tracer (rasterize / path-trace modes).\n"
                "Requires an NVIDIA RTX GPU with OptiX/CUDA installed for Optix."
            )

            imgui.separator()

            # === Mouse Interaction section ===
            imgui.text("Mouse Interaction")

            # Mouse mode combo box (kept for future interaction modes)
            mouse_modes = ["Select Particle"]
            current_mode_idx = mouse_modes.index(self.state.preferences.ui_windows.mouse_mode) if self.state.preferences.ui_windows.mouse_mode in mouse_modes else 0
            clicked, new_mode_idx = imgui.combo("Mouse Mode", current_mode_idx, mouse_modes)
            if clicked:
                self.state.preferences.ui_windows.mouse_mode = mouse_modes[new_mode_idx]
            self._delayed_tooltip("In Select Particle mode, clicking selects a particle rule to focus on.\nSee Help->Controls for more")

            imgui.separator()

            # Physics tooltips checkbox
            _, self.state.preferences.ui_windows.physics_tooltips_enabled = imgui.checkbox(
                "Physics Tooltips",
                self.state.preferences.ui_windows.physics_tooltips_enabled
            )
            self._delayed_tooltip("Enable verbose tooltip and vector diagram for physics sliders.")

            # Arrow debug checkbox — visualizes the trail canvas velocity field
            _, self.state.preferences.ui_windows.debug_arrows = imgui.checkbox(
                "View Trail Arrows",
                self.state.preferences.ui_windows.debug_arrows
            )
            self._delayed_tooltip("Render a grid of arrows to help visualize the trail canvas velocity field.")

            # Arrow sensitivity slider (only show when debug arrows enabled)
            if self.state.preferences.ui_windows.debug_arrows:
                imgui.indent(20)
                _, self.state.preferences.ui_windows.arrow_sensitivity = imgui.slider_float(
                    "Arrow Sensitivity",
                    self.state.preferences.ui_windows.arrow_sensitivity,
                    1.0, 20.0,
                    format="%.1f"
                )
                imgui.unindent(20)

            imgui.separator()

            # === Appearance section ===
            imgui.text("Appearance")

            # Brightness slider
            _, self.state.preferences.rendering.brightness = imgui.slider_float(
                "Brightness",
                self.state.preferences.rendering.brightness,
                0.01, 10.0,
                format="%.2f"
            )
            self._delayed_tooltip("Global brightness multiplier for the output.")

            # Tonemap Softness slider
            _, self.state.preferences.rendering.tonemap_softness = imgui.slider_float(
                "Tonemap Softness",
                self.state.preferences.rendering.tonemap_softness,
                0.1, 5.0,
                format="%.2f"
            )
            self._delayed_tooltip("Controls highlight compression (asinh stretch).\nLow values = more linear (brighter highlights).\nHigh values = more logarithmic (reveals faint detail).")

            # Exposure / Cheap Blur slider
            _, self.state.preferences.rendering.exposure = imgui.slider_float(
                "Exposure / Cheap Blur",
                self.state.preferences.rendering.exposure,
                0.0, 1.0,
                format="%.2f"
            )
            self._delayed_tooltip("Blend frames together for a cheap motion blur or set near 1 for a long exposure effect.")

            # Bloom checkbox + sliders (disabled in watercolor mode)
            watercolor_active = self.state.sim.watercolor_mode
            if watercolor_active:
                imgui.begin_disabled()
            _, self.state.preferences.bloom.enabled = imgui.checkbox(
                "Bloom",
                self.state.preferences.bloom.enabled
            )
            if watercolor_active:
                self._delayed_tooltip("Bloom is disabled in Watercolor mode.")
            else:
                self._delayed_tooltip("Add a glow effect around bright areas.")

            if self.state.preferences.bloom.enabled and not watercolor_active:
                imgui.indent(20)
                _, self.state.preferences.bloom.threshold = imgui.slider_float(
                    "Threshold",
                    self.state.preferences.bloom.threshold,
                    0.0, 2.0,
                    format="%.2f"
                )
                self._delayed_tooltip("Brightness cutoff for bloom extraction.\nLower = more glow everywhere.")

                _, self.state.preferences.bloom.intensity = imgui.slider_float(
                    "Intensity",
                    self.state.preferences.bloom.intensity,
                    0.0, 3.0,
                    format="%.2f"
                )
                self._delayed_tooltip("Strength of the bloom glow.")

                _, self.state.preferences.bloom.radius = imgui.slider_float(
                    "Radius",
                    self.state.preferences.bloom.radius,
                    0.1, 3.0,
                    format="%.2f"
                )
                self._delayed_tooltip("Spread of the bloom blur kernel.")
                imgui.unindent(20)
            if watercolor_active:
                imgui.end_disabled()

        imgui.end()

        # Restore normal window background color if it was changed
        if recording_active or video_pending:
            imgui.pop_style_color()

    def _get_key_combo(self, action: str, modifier: str = "") -> str:
        """
        Get a formatted key combination string for display.

        Args:
            action: The action name from keyboard_controls.json
            modifier: Optional modifier like "Ctrl+" or "Shift+"

        Returns:
            Formatted string like "Ctrl+C" or "WASD"
        """
        key = self.keybindings.get_key_display_name(action)
        if modifier:
            return f"{modifier}{key}"
        return key
