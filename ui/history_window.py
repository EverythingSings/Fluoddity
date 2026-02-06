"""Rule history window with preview and tooltip shader rendering."""
import time
import random
import colorsys
import moderngl
from imgui_bundle import imgui


class HistoryWindowMixin:
    """Mixin for rule history window. Combined into UI via multiple inheritance."""

    def render_history_window(self):
        """Render rule history window with preview."""
        imgui.begin("Rule History")

        rule_history = self._display_info.get('rule_history', [])

        if not rule_history:
            imgui.text_colored(imgui.ImVec4(1.0, 0.5, 0.5, 1.0), "No rules in history")
            imgui.end()
            return

        # Sync metadata with rule history
        # When adding new rules, append new labels
        while len(self.history_window_labels) < len(rule_history):
            self.history_window_labels.append(self._generate_rule_label())
        # When removing old rules (from beginning), remove old labels (from beginning)
        while len(self.history_window_labels) > len(rule_history):
            self.history_window_labels.pop(0)

        # Determine how many rules to show (hide topmost if previewing)
        num_rules_to_show = len(rule_history)
        if self.currently_previewing_index is not None:
            # Previewing - hide the topmost element (it's the preview copy)
            num_rules_to_show -= 1

        # Render rules (newest first, but skip the preview if active)
        hovered_this_frame = None

        for i in range(num_rules_to_show - 1, -1, -1):
            # Get jersey number and colors
            jersey_number, color1_rgb, color2_rgb = self.history_window_labels[i]
            color1 = self._parse_rgb_color(color1_rgb)
            color2 = self._parse_rgb_color(color2_rgb)

            # Extract digits from jersey number
            digit1 = jersey_number // 10
            digit2 = jersey_number % 10

            # Render colored digits
            imgui.text_colored(imgui.ImVec4(*color1), str(digit1))
            imgui.same_line(spacing=0)
            imgui.text_colored(imgui.ImVec4(*color2), str(digit2))
            imgui.same_line(spacing=2)

            # Invisible selectable for click/hover detection
            clicked, _ = imgui.selectable(
                f"##{i}",
                False,
                imgui.SelectableFlags_.none,
                imgui.ImVec2(10, 0)  # Small width just for the hitbox
            )

            if imgui.is_item_hovered():
                hovered_this_frame = i

            # X button
            imgui.same_line()
            imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
            imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
            if imgui.small_button(f"X##history_{i}"):
                self._request_delete_history_rule = True
                self._history_preview_index = i
            imgui.pop_style_color(2)

            if imgui.is_item_hovered():
                hovered_this_frame = i

            if clicked:
                self._request_load_history_rule = True
                self._history_preview_index = i

        # Handle preview state changes
        if hovered_this_frame != self.currently_previewing_index:
            if self.currently_previewing_index is not None:
                self._request_clear_history_preview = True

            if hovered_this_frame is not None:
                self._request_preview_history_rule = True
                self._history_preview_index = hovered_this_frame
                self.currently_previewing_index = hovered_this_frame
            else:
                self.currently_previewing_index = None

        imgui.end()

    def update_tooltip_texture(self):
        """Render the tooltip graphic to texture using shader."""
        # Set time uniform for animations
        current_time = time.time() - self.tooltip_start_time
        self.tooltip_program['time'] = current_time * 3.0  # Speed up animation a bit

        # Set sensor angle (raw value, not normalized)
        self.tooltip_program['SENSOR_ANGLE'] = self.state.sim.SENSOR_ANGLE

        # Set MODE bools based on which slider is hovered
        self.tooltip_program['AXIAL_MODE'] = (self.last_hovered_slider == "Axial Force")
        self.tooltip_program['LATERAL_MODE'] = (self.last_hovered_slider == "Lateral Force")
        self.tooltip_program['SENSOR_MODE'] = (self.last_hovered_slider == "Sensor Gain")
        self.tooltip_program['DRAG_MODE'] = (self.last_hovered_slider == "Drag")
        self.tooltip_program['ANGLE_MODE'] = (self.last_hovered_slider == "Sensor Angle")
        self.tooltip_program['DISTANCE_MODE'] = (self.last_hovered_slider == "Sensor Distance")
        self.tooltip_program['TRAIL_MODE'] = (self.last_hovered_slider == "Trail Persistence")
        self.tooltip_program['DIFFUSION_MODE'] = (self.last_hovered_slider == "Trail Diffusion")
        self.tooltip_program['GLOBAL_MODE'] = (self.last_hovered_slider == "Global Force Mult")
        self.tooltip_program['STRAFE_MODE'] = (self.last_hovered_slider == "Strafe Power")
        self.tooltip_program['MUTATION_MODE'] = (self.last_hovered_slider == "Mutation Scale")

        # Render to framebuffer
        self.tooltip_fbo.use()
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        self.tooltip_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
        self.ctx.screen.use()  # Return to default framebuffer

    def render_custom_tooltip(self, label: str, description: str):
        """Render a custom tooltip anchored to the right edge of a window.

        Args:
            label: The label of the slider
            description: Description text to display in the tooltip
        """
        # Track which slider is currently hovered
        if imgui.is_item_hovered():
            self.last_hovered_slider = label
            self.last_hovered_description = description

        # Track if any item is being actively manipulated (dragged)
        if imgui.is_item_active():
            self.physics_window_interaction = True

    def render_physics_tooltip(self):
        """Render the tooltip if mouse is over the Physics Settings window."""
        # Early exit if tooltips are disabled
        if not self.state.preferences.physics_tooltips_enabled:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        # Check if physics settings window is hovered or if we're actively interacting with it
        physics_window_hovered = imgui.is_window_hovered()

        # First, check if we should show the tooltip at all
        # We need to render it at least once to check if IT is hovered
        should_show = (physics_window_hovered or
                      self.physics_window_interaction or
                      self.last_hovered_slider is not None)

        if not should_show:
            self.last_hovered_slider = None
            self.physics_window_interaction = False
            return

        if self.last_hovered_slider is None:
            self.physics_window_interaction = False
            return

        # Update the tooltip texture with current slider values
        self.update_tooltip_texture()

        # Get the position and size of the anchor window
        window_pos = imgui.get_window_pos()
        window_size = imgui.get_window_size()

        # Calculate tooltip position (right edge of the anchor window)
        tooltip_x = window_pos.x + window_size.x
        tooltip_y = window_pos.y

        # Set next window position
        imgui.set_next_window_pos(imgui.ImVec2(tooltip_x, tooltip_y))

        # Begin a borderless, no-move, no-focus tooltip window
        # Note: no_focus_on_appearing allows clicking to gain focus, just not automatic focus
        imgui.begin(
            "##SliderTooltip",
            flags=(
                imgui.WindowFlags_.no_title_bar |
                imgui.WindowFlags_.no_move |
                imgui.WindowFlags_.no_resize |
                imgui.WindowFlags_.always_auto_resize |
                imgui.WindowFlags_.no_focus_on_appearing |
                imgui.WindowFlags_.no_nav
            )
        )

        # Display the shader-rendered tooltip graphic
        imgui.image(
            self.tooltip_texture_id,
            imgui.ImVec2(self.tooltip_texture_size, self.tooltip_texture_size)
        )

        # Display slider name and description
        imgui.separator()
        imgui.text(f"Parameter: {self.last_hovered_slider}")
        imgui.separator()
        imgui.text_wrapped(self.last_hovered_description)

        # Check if tooltip itself is hovered (must be after content is rendered)
        tooltip_hovered = imgui.is_window_hovered()

        imgui.end()

        # Now decide if we should keep the tooltip visible next frame
        # Keep it if: physics window hovered, tooltip hovered, or actively dragging
        if not physics_window_hovered and not tooltip_hovered and not self.physics_window_interaction:
            self.last_hovered_slider = None

        # Reset interaction flag for next frame
        self.physics_window_interaction = False

    def _generate_rule_label(self) -> tuple[int, str, str]:
        """Generate random jersey number with colored digits.

        Returns:
            tuple: (jersey_number, digit1_rgb_string, digit2_rgb_string)
                   e.g., (42, "255,128,64", "64,255,128")
        """
        # Generate random jersey number (00-99)
        jersey_number = random.randint(0, 99)

        label_digits = []
        for _ in range(2):
            hue = random.randint(0, 255) / 255.0
            sat = random.randint(0, 150) / 255.0
            val = 1.0  # Brightness fixed at 255

            r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
            r_int, g_int, b_int = int(r * 255), int(g * 255), int(b * 255)
            label_digits.append(f"{r_int},{g_int},{b_int}")

        return (jersey_number, label_digits[0], label_digits[1])

    def _parse_rgb_color(self, rgb_string: str) -> tuple[float, float, float, float]:
        """Parse RGB string to ImVec4 color."""
        r, g, b = map(int, rgb_string.split(','))
        return (r / 255.0, g / 255.0, b / 255.0, 1.0)
