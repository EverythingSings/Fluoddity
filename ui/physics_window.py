"""Physics Settings window: sliders, additional settings, appearance, notes (normal + multi-load modes)."""
from imgui_bundle import imgui


class PhysicsWindowMixin:
    """Mixin for physics settings window. Combined into UI via multiple inheritance."""

    def render_physics_settings_window(self):
        """Render the Physics Settings window with sliders."""
        # Apply bluish background when in sweep preview mode (waiting for click to restore sweeps)
        if self.state.sim.sweep_preview_pending_restore:
            imgui.push_style_color(imgui.Col_.window_bg, imgui.ImVec4(0.15, 0.20, 0.35, 0.94))
            imgui.push_style_color(imgui.Col_.title_bg_active, imgui.ImVec4(0.20, 0.30, 0.50, 1.0))

        # No p_open parameter - window is uncloseable
        imgui.begin('Physics Settings', flags=imgui.WindowFlags_.menu_bar)

        # Track if any physics menu is open
        physics_any_menu_open_this_frame = False

        # Multi-load mode: different rendering
        if self.state.multi_load.multi_load_enabled:
            self._render_physics_multi_load_mode(physics_any_menu_open_this_frame)
            return

        # Normal mode: render sliders and settings
        physics_any_menu_open_this_frame = self._render_physics_normal_menu_bar()

        # Display currently open project and rule seed
        imgui.text(f"Project: {self.currently_open_project}")
        imgui.same_line()
        # Convert rule_seed (0.0-1.0 float) to short hex format
        seed_hex = format(int(self.state.sim.rule_seed * 0xFFFF), '04x')
        imgui.text_colored(imgui.ImVec4( 0.5, 0.8, 1.0, 1.0),f"Mutation Seed: #{seed_hex}")
        imgui.separator()

        # === Basics Group (Trail sensors and rule mutation) ===
        imgui.set_next_item_open(self.state.preferences.physics_group_basics)
        basics_open = imgui.collapsing_header("Basics - Trail sensors and rule mutation")
        # Update state to match actual header state (handles user clicks)
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_basics = basics_open
        if basics_open:
            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("SENSOR_GAIN")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("SENSOR_GAIN", "Sensor Gain", self.state.sim.SENSOR_GAIN, 0.0, 5.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.SENSOR_GAIN = self.slider_float_with_range_menu(
                label="Sensor Gain",
                param_name="SENSOR_GAIN",
                value=self.state.sim.SENSOR_GAIN,
                default_min=0,
                default_max=5.0,
            )
            self.render_custom_tooltip("Sensor Gain",
                "Determines how strongly particles respond to sensor input. Higher values make particles more reactive to the trails they sense on the Canvas.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("SENSOR_ANGLE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("SENSOR_ANGLE", "Sensor Angle", self.state.sim.SENSOR_ANGLE, -1.0, 1.0, hard_min=-1.0, hard_max=1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.SENSOR_ANGLE = self.slider_float_with_range_menu(
                label="Sensor Angle",
                param_name="SENSOR_ANGLE",
                value=self.state.sim.SENSOR_ANGLE,
                default_min=-1.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Sensor Angle",
                "Sets the angular offset of particle sensors from their forward direction. Determines whether particles are 'looking ahead' or 'looking behind'.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("SENSOR_DISTANCE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("SENSOR_DISTANCE", "Sensor Distance", self.state.sim.SENSOR_DISTANCE, 0.0, 4.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.SENSOR_DISTANCE = self.slider_float_with_range_menu(
                label="Sensor Distance",
                param_name="SENSOR_DISTANCE",
                value=self.state.sim.SENSOR_DISTANCE,
                default_min=0.0,
                default_max=4.0,
            )
            self.render_custom_tooltip("Sensor Distance",
                "Determines distance between a particle's center and where it reads the trail information from Canvas. Longer distances tend to create larger scale patterns.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("MUTATION_SCALE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("MUTATION_SCALE", "Mutation Scale", self.state.sim.MUTATION_SCALE, -0.5, 0.5)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.MUTATION_SCALE = self.slider_float_with_range_menu(
                label="Mutation Scale",
                param_name="MUTATION_SCALE",
                value=self.state.sim.MUTATION_SCALE,
                default_min=-.5,
                default_max=.5,
            )
            self.render_custom_tooltip("Mutation Scale",
                "Controls the size of the random mutations applied to a rule when a new particle is clicked. At 0, every particle will behave exactly like the selected particle.")

        # === Forces Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_forces)
        forces_open = imgui.collapsing_header("Forces")
        # Update state to match actual header state (handles user clicks)
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_forces = forces_open
        if forces_open:
            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("GLOBAL_FORCE_MULT")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("GLOBAL_FORCE_MULT", "Global Force Mult", self.state.sim.GLOBAL_FORCE_MULT, 0.0, 2.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.GLOBAL_FORCE_MULT = self.slider_float_with_range_menu(
                label="Global Force Mult",
                param_name="GLOBAL_FORCE_MULT",
                value=self.state.sim.GLOBAL_FORCE_MULT,
                default_min=0.0,
                default_max=2.0,
            )
            self.render_custom_tooltip("Global Force Mult",
                "Scales axial and lateral forces applied to particles, and scales strafe power. Often tuned in the opposite direction to Sensor Gain and Drag to offset exploding/vanishing particle speed.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("DRAG")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("DRAG", "Drag", self.state.sim.DRAG, -1.0, 1.0, hard_min=-1.0, hard_max=1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.DRAG = self.slider_float_with_range_menu(
                label="Drag",
                param_name="DRAG",
                value=self.state.sim.DRAG,
                default_min=-1.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Drag",
                "Each physics update, particle velocity is multiplied by drag like so:   vel = vel*drag + forces; So drag less than 1 means particles are being slowed down. Powerful (<0.5) drag values can prevent energetic systems from 'blowing up'")

        # === Advanced Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_advanced)
        advanced_open = imgui.collapsing_header("Advanced")
        # Update state to match actual header state (handles user clicks)
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_advanced = advanced_open
        if advanced_open:
            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("AXIAL_FORCE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("AXIAL_FORCE", "Axial Force", self.state.sim.AXIAL_FORCE, -1.0, 1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.AXIAL_FORCE = self.slider_float_with_range_menu(
                label="Axial Force",
                param_name="AXIAL_FORCE",
                value=self.state.sim.AXIAL_FORCE,
                default_min=-1.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Axial Force",
                "Controls the strength of forces applied parallel to the direction of travel: acceleration and braking")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("LATERAL_FORCE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("LATERAL_FORCE", "Lateral Force", self.state.sim.LATERAL_FORCE, -1.0, 1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.LATERAL_FORCE = self.slider_float_with_range_menu(
                label="Lateral Force",
                param_name="LATERAL_FORCE",
                value=self.state.sim.LATERAL_FORCE,
                default_min=-1.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Lateral Force",
                "Controls the strength of forces applied perpendicular to the direction of travel: turning left and right.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("STRAFE_POWER")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("STRAFE_POWER", "Strafe Power", self.state.sim.STRAFE_POWER, 0.0, 0.5)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.STRAFE_POWER = self.slider_float_with_range_menu(
                label="Strafe Power",
                param_name="STRAFE_POWER",
                value=self.state.sim.STRAFE_POWER,
                default_min=0.0,
                default_max=0.5,
            )
            self.render_custom_tooltip("Strafe Power",
                "Controls particle movement without applying forces to velocity. 'Strafe' is a vector added directly to position each frame, like a little hop. Strafe power scales with Axial, Lateral, and Global force multipliers.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("TRAIL_PERSISTENCE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("TRAIL_PERSISTENCE", "Trail Persistence", self.state.sim.TRAIL_PERSISTENCE, 0.0, 1.0, hard_min=0.0, hard_max=1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.TRAIL_PERSISTENCE = self.slider_float_with_range_menu(
                label="Trail Persistence",
                param_name="TRAIL_PERSISTENCE",
                value=self.state.sim.TRAIL_PERSISTENCE,
                default_min=0.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Trail Persistence",
                "Controls how long particle trails remain visible. Higher values create longer-lasting trails, lower values make trails fade quickly. Values close to 1.0 tend to create 'sharper' more stable patterns. ")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("TRAIL_DIFFUSION")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("TRAIL_DIFFUSION", "Trail Diffusion", self.state.sim.TRAIL_DIFFUSION, 0.0, 1.0, hard_min=0.0, hard_max=1.0)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            _, self.state.sim.TRAIL_DIFFUSION = self.slider_float_with_range_menu(
                label="Trail Diffusion",
                param_name="TRAIL_DIFFUSION",
                value=self.state.sim.TRAIL_DIFFUSION,
                default_min=0.0,
                default_max=1.0,
            )
            self.render_custom_tooltip("Trail Diffusion",
                "Controls how quickly particle trails spread out and blend together.")

            if self.state.sim.parameter_sweeps_enabled:
                self.render_sweep_buttons("HAZARD_RATE")
                imgui.same_line(spacing=2)
                self.render_range_adjust_buttons("HAZARD_RATE", "Hazard Rate", self.state.sim.HAZARD_RATE, 0.0, 0.05, hard_min=0.0, hard_max=0.05)
                imgui.same_line(spacing=8)
                imgui.set_next_item_width(80)

            # Power-scaled slider for fine control at low values while reaching 0.0
            HAZARD_MAX = 0.05
            HAZARD_POWER = 3.0  # Higher = more resolution at low end
            # Convert actual value to slider position (0-1)
            slider_pos = (self.state.sim.HAZARD_RATE / HAZARD_MAX) ** (1.0 / HAZARD_POWER)
            _, new_pos = imgui.slider_float(
                "Hazard Rate",
                slider_pos,
                0.0,
                1.0,
                f"{self.state.sim.HAZARD_RATE:.5f}"
            )
            # Convert slider position back to actual value
            self.state.sim.HAZARD_RATE = HAZARD_MAX * (new_pos ** HAZARD_POWER)
            # Add context menu for min/max adjustment (no jitter for Hazard Rate)
            self.add_slider_context_menu("Hazard Rate", 0.0, 0.05)
            self.render_custom_tooltip("Hazard Rate",
                "Probability per frame that particles reset to initial conditions. Gives particles a probabalistic 'lifetime' after which they reset.")

        # === Additional Settings Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_additional)
        additional_open = imgui.collapsing_header("Additional Settings")
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_additional = additional_open
        if additional_open:
            # Boundary Conditions (with per-option tooltips)
            boundary_options = ["Bounce", "Reset", "Wrap"]
            boundary_tooltips = [
                "Particles bounce off the edges of the canvas",
                "Particles are reset to their initial conditions when leaving the canvas",
                "Particles wrap seamlessly to the other side of the canvas"
            ]
            imgui.set_next_item_width(100)
            if imgui.begin_combo("Boundary Conditions", boundary_options[self.state.sim.boundary_conditions]):
                for i, option in enumerate(boundary_options):
                    is_selected = (self.state.sim.boundary_conditions == i)
                    if imgui.selectable(option, is_selected)[0]:
                        self.state.sim.boundary_conditions = i
                    self._delayed_tooltip(boundary_tooltips[i])
                    if is_selected:
                        imgui.set_item_default_focus()
                imgui.end_combo()

            # Initial Conditions (with per-option tooltips)
            initial_options = ["Grid", "Random", "Ring"]
            initial_tooltips = [
                "Particles start in a grid, organized by cohort",
                "Particles are spread uniformly across the canvas",
                "Particles start distributed around a circle, organized by cohort"
            ]
            imgui.set_next_item_width(100)
            if imgui.begin_combo("Initial Conditions", initial_options[self.state.sim.initial_conditions]):
                for i, option in enumerate(initial_options):
                    is_selected = (self.state.sim.initial_conditions == i)
                    if imgui.selectable(option, is_selected)[0]:
                        self.state.sim.initial_conditions = i
                    self._delayed_tooltip(initial_tooltips[i])
                    if is_selected:
                        imgui.set_item_default_focus()
                imgui.end_combo()

            # Number of Cohorts
            imgui.set_next_item_width(100)
            _, self.state.sim.num_cohorts = imgui.slider_int(
                "Number of Cohorts",
                self.state.sim.num_cohorts,
                1, 144
            )
            self._delayed_tooltip("Each particle is assigned to a cohort. Each cohort shares behavior\nand there can be mutations between different cohorts.")

            imgui.separator()

            # Disable Symmetry
            _, self.state.sim.DISABLE_SYMMETRY = imgui.checkbox(
                "Disable Symmetry",
                self.state.sim.DISABLE_SYMMETRY
            )
            self._delayed_tooltip("Allow particles to display \"right / left handed\" behavior,\nleading to clockwise/counterclockwise bias.\nTurn it on to see why we go through trouble\nof calculating \"mirror world\" behavior in entity_update.glsl")

            # Absolute Orientation (combo box with 3 modes)
            combo_items = ["Off", "Y axis", "Radial"]
            clicked, current = imgui.combo(
                "Absolute Orientation",
                self.state.sim.ABSOLUTE_ORIENTATION,
                combo_items
            )
            if clicked:
                self.state.sim.ABSOLUTE_ORIENTATION = current
            self._delayed_tooltip("What direction are particles 'facing'? Which way is 'up'?\nOff: use particle velocity\nY axis: align to y axis\nRadial: align to center of canvas")

            # Orientation Mix (only visible if Absolute Orientation != Off)
            if self.state.sim.ABSOLUTE_ORIENTATION != 0:
                imgui.set_next_item_width(100)
                _, self.state.sim.ORIENTATION_MIX = imgui.slider_float(
                    "Orientation Mix",
                    self.state.sim.ORIENTATION_MIX,
                    0.0, 1.0,
                    "%.2f"
                )
                self._delayed_tooltip("Blend factor for orientation calculations (0.0 = velocity only, 1.0 = full absolute orientation)")

            imgui.separator()

            # Parameter Sweeps toggle
            _, self.state.sim.parameter_sweeps_enabled = imgui.checkbox(
                "Parameter Sweeps",
                self.state.sim.parameter_sweeps_enabled
            )
            sweep_key = self.keybindings.get_key_display_name('toggle_parameter_sweep')
            self._delayed_tooltip(f"Enable parameter sweeps to vary physics across the canvas.\nPress {sweep_key} to toggle. See Help -> Parameter Sweeps for details.")

        # === Notes Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_notes)
        notes_open = imgui.collapsing_header("Notes")
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_notes = notes_open
        if notes_open:
            imgui.set_next_item_width(-1)
            changed, new_notes = imgui.input_text_multiline(
                "##notes",
                self.state.sim.notes,
                imgui.ImVec2(0, 80),
                imgui.InputTextFlags_.word_wrap | imgui.InputTextFlags_.ctrl_enter_for_new_line
            )
            if changed:
                self.state.sim.notes = new_notes
            self._delayed_tooltip("Optional notes to save with this config.\nThese will be saved when you save the config.\nEnter to finish editing, Ctrl+Enter for newline.")

        imgui.separator()

        # Render the tooltip if window is hovered
        self.render_physics_tooltip()

        imgui.end()

        # Pop sweep preview style colors (pushed before imgui.begin)
        if self.state.sim.sweep_preview_pending_restore:
            imgui.pop_style_color(2)

    def _render_physics_normal_menu_bar(self) -> bool:
        """Render the normal mode menu bar for Physics Settings. Returns whether any menu is open."""
        physics_any_menu_open_this_frame = False

        if imgui.begin_menu_bar():
            # Track all open menu rectangles separately
            physics_menu_rectangles = []

            # Start with the menu bar itself
            physics_menu_bar_min = imgui.get_window_pos()
            physics_menu_bar_size = imgui.get_window_size()
            physics_menu_rectangles.append((physics_menu_bar_min.x, physics_menu_bar_min.y,
                                           physics_menu_bar_min.x + physics_menu_bar_size.x,
                                           physics_menu_bar_min.y + physics_menu_bar_size.y))

            # Appearance menu
            if imgui.begin_menu("Appearance", not self.force_close_physics_menus):
                physics_any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                appearance_settings_menu_min = imgui.get_window_pos()
                appearance_settings_menu_size = imgui.get_window_size()
                physics_menu_rectangles.append((appearance_settings_menu_min.x, appearance_settings_menu_min.y,
                                               appearance_settings_menu_min.x + appearance_settings_menu_size.x,
                                               appearance_settings_menu_min.y + appearance_settings_menu_size.y))

                # Color by cohort checkbox
                _, self.state.sim.color_by_cohort = imgui.checkbox(
                    "Color by Cohort",
                    self.state.sim.color_by_cohort
                )
                self._delayed_tooltip("Colors particles based on their cohort assignment\nrather than their behavior.")

                # Hue Sensitivity (only if not color by cohort)
                if not self.state.sim.color_by_cohort:
                    _, self.state.sim.hue_sensitivity = imgui.slider_float(
                        "Hue Sensitivity", self.state.sim.hue_sensitivity, -1.0, 1.0
                    )
                    self._delayed_tooltip("Controls color variation based on particle velocity.")

                imgui.separator()

                # Watercolor Mode checkbox
                _, self.state.sim.watercolor_mode = imgui.checkbox(
                    "Watercolor Mode (V)",
                    self.state.sim.watercolor_mode
                )

                # Ink Weight slider (only in watercolor mode, placed right after checkbox)
                if self.state.sim.watercolor_mode:
                    _, self.state.sim.ink_weight = imgui.slider_float(
                        "Ink Weight", self.state.sim.ink_weight, 0.0, 20.0
                    )
                    self._delayed_tooltip("Controls optical density in watercolor mode.\nHigher values = darker/more opaque.")
                self._delayed_tooltip("Enable watercolor rendering effect.")

                imgui.separator()

                # Emboss mode combo box
                emboss_options = ["Off", "Canvas (Trails)", "Brush (Particles)"]
                _, self.state.sim.emboss_mode = imgui.combo(
                    "Emboss", self.state.sim.emboss_mode, emboss_options
                )
                self._delayed_tooltip("Calculate some fake 3D lighting\nby treating (otherwise unused) particle\ndensity as a heightmap.")

                # Emboss sliders only visible when mode is not Off
                if self.state.sim.emboss_mode != 0:
                    # Emboss Intensity slider
                    _, self.state.sim.emboss_intensity = imgui.slider_float(
                        "Emboss Intensity", self.state.sim.emboss_intensity, 0.0, 1.0
                    )
                    self._delayed_tooltip("Intensity of emboss lighting effect. Negative values invert.")

                    # Emboss Smoothness slider
                    _, self.state.sim.emboss_smoothness = imgui.slider_float(
                        "Emboss Smoothness", self.state.sim.emboss_smoothness, 0.001, 1.0
                    )
                    self._delayed_tooltip("Controls the smoothness of emboss sampling.")

                imgui.end_menu()

            # After all menus: check mouse distance from all menu rectangles
            # Find the minimum distance to any rectangle
            if self.physics_menu_bar_has_open_menu and not self.save_popup_open:
                mouse_pos = imgui.get_mouse_pos()

                # Calculate minimum distance to any menu rectangle
                min_distance = float('inf')
                for min_x, min_y, max_x, max_y in physics_menu_rectangles:
                    dx = max(min_x - mouse_pos.x, 0, mouse_pos.x - max_x)
                    dy = max(min_y - mouse_pos.y, 0, mouse_pos.y - max_y)
                    distance = (dx * dx + dy * dy) ** 0.5
                    min_distance = min(min_distance, distance)

                # If mouse is too far away from all rectangles, signal to close menus
                if min_distance > self.state.preferences.menu_close_threshold:
                    self.force_close_physics_menus = True

            imgui.end_menu_bar()

        # Update physics menu tracking state
        self.physics_menu_bar_has_open_menu = physics_any_menu_open_this_frame
        # Reset force close flag after processing
        if self.force_close_physics_menus and not physics_any_menu_open_this_frame:
            self.force_close_physics_menus = False

        return physics_any_menu_open_this_frame

    def _render_physics_multi_load_mode(self, physics_any_menu_open_this_frame):
        """Render multi-load mode UI for Physics Settings window."""
        # Render multi-load specific UI
        if imgui.begin_menu_bar():
            # Track all open menu rectangles separately
            physics_menu_rectangles = []

            # Start with the menu bar itself
            physics_menu_bar_min = imgui.get_window_pos()
            physics_menu_bar_size = imgui.get_window_size()
            physics_menu_rectangles.append((physics_menu_bar_min.x, physics_menu_bar_min.y,
                                           physics_menu_bar_min.x + physics_menu_bar_size.x,
                                           physics_menu_bar_min.y + physics_menu_bar_size.y))

            if imgui.begin_menu("Multi-Load Settings", not self.force_close_physics_menus):
                physics_any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                multi_load_menu_min = imgui.get_window_pos()
                multi_load_menu_size = imgui.get_window_size()
                physics_menu_rectangles.append((multi_load_menu_min.x, multi_load_menu_min.y,
                                               multi_load_menu_min.x + multi_load_menu_size.x,
                                               multi_load_menu_min.y + multi_load_menu_size.y))

                # Particle Assignment combo
                assignment_options = ["Random", "Cohorts"]
                current_idx = 0 if self.state.multi_load.assignment_mode == "Random" else 1
                imgui.set_next_item_width(150)
                changed, new_idx = imgui.combo("Particle Assignment", current_idx, assignment_options)
                if changed:
                    self.state.multi_load.assignment_mode = assignment_options[new_idx]
                self._delayed_tooltip("Random: each particle randomly assigned\nCohorts: particles grouped by cohort")

                _, self.state.multi_load.per_config_initial_conditions = imgui.checkbox(
                    "Per-config Initial Conditions", self.state.multi_load.per_config_initial_conditions)
                self._delayed_tooltip("Each config uses its own initial conditions")

                _, self.state.multi_load.per_config_cohorts = imgui.checkbox(
                    "Per-config Cohorts", self.state.multi_load.per_config_cohorts)
                self._delayed_tooltip("Each config uses its own cohort count")

                _, self.state.multi_load.per_config_hazard_rate = imgui.checkbox(
                    "Per-config Hazard Rate", self.state.multi_load.per_config_hazard_rate)
                self._delayed_tooltip("Each config uses its own hazard rate setting")

                imgui.end_menu()

            # Simplified Additional Settings (some items greyed out)
            if imgui.begin_menu("Additional Settings", not self.force_close_physics_menus):
                physics_any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                additional_menu_min = imgui.get_window_pos()
                additional_menu_size = imgui.get_window_size()
                physics_menu_rectangles.append((additional_menu_min.x, additional_menu_min.y,
                                               additional_menu_min.x + additional_menu_size.x,
                                               additional_menu_min.y + additional_menu_size.y))

                # Boundary Conditions
                boundary_options = ["Bounce", "Reset", "Wrap"]
                imgui.set_next_item_width(100)
                if imgui.begin_combo("Boundary Conditions", boundary_options[self.state.sim.boundary_conditions]):
                    for i, option in enumerate(boundary_options):
                        if imgui.selectable(option, self.state.sim.boundary_conditions == i)[0]:
                            self.state.sim.boundary_conditions = i
                    imgui.end_combo()

                # Initial Conditions (greyed if per-config)
                if self.state.multi_load.per_config_initial_conditions:
                    imgui.begin_disabled()
                initial_options = ["Grid", "Random", "Ring"]
                imgui.set_next_item_width(100)
                if imgui.begin_combo("Initial Conditions", initial_options[self.state.sim.initial_conditions]):
                    for i, option in enumerate(initial_options):
                        if imgui.selectable(option, self.state.sim.initial_conditions == i)[0]:
                            self.state.sim.initial_conditions = i
                    imgui.end_combo()
                if self.state.multi_load.per_config_initial_conditions:
                    imgui.end_disabled()

                # Cohorts (greyed if per-config)
                if self.state.multi_load.per_config_cohorts:
                    imgui.begin_disabled()
                imgui.set_next_item_width(100)
                _, self.state.sim.num_cohorts = imgui.slider_int("Number of Cohorts", self.state.sim.num_cohorts, 1, 144)
                if self.state.multi_load.per_config_cohorts:
                    imgui.end_disabled()

                # Hazard Rate (conditional on per-config setting)
                if self.state.multi_load.per_config_hazard_rate:
                    imgui.begin_disabled()
                # Power-scaled slider for fine control at low values while reaching 0.0
                HAZARD_MAX = 0.05
                HAZARD_POWER = 3.0  # Higher = more resolution at low end
                # Convert actual value to slider position (0-1)
                slider_pos = (self.state.sim.HAZARD_RATE / HAZARD_MAX) ** (1.0 / HAZARD_POWER)
                _, new_pos = imgui.slider_float(
                    "Hazard Rate",
                    slider_pos,
                    0.0,
                    1.0,
                    f"{self.state.sim.HAZARD_RATE:.5f}"
                )
                # Convert slider position back to actual value
                self.state.sim.HAZARD_RATE = HAZARD_MAX * (new_pos ** HAZARD_POWER)
                if self.state.multi_load.per_config_hazard_rate:
                    imgui.end_disabled()
                self._delayed_tooltip("Probability per frame that particles reset to initial conditions")

                # Disable these options in multi-load (per-config settings)
                imgui.begin_disabled()
                imgui.checkbox("Disable Symmetry", False)
                imgui.checkbox("Absolute Orientation", False)
                imgui.end_disabled()
                self._delayed_tooltip("Per-config settings in Multi-Load mode")

                # Parameter Sweeps (disabled)
                imgui.begin_disabled()
                imgui.checkbox("Parameter Sweeps", False)
                imgui.end_disabled()
                self._delayed_tooltip("Disabled in Multi-Load mode")

                imgui.end_menu()

            # Appearance (unchanged, copy from normal mode)
            if imgui.begin_menu("Appearance", not self.force_close_physics_menus):
                physics_any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                appearance_menu_min = imgui.get_window_pos()
                appearance_menu_size = imgui.get_window_size()
                physics_menu_rectangles.append((appearance_menu_min.x, appearance_menu_min.y,
                                               appearance_menu_min.x + appearance_menu_size.x,
                                               appearance_menu_min.y + appearance_menu_size.y))

                _, self.state.sim.color_by_cohort = imgui.checkbox("Color by Cohort", self.state.sim.color_by_cohort)
                if not self.state.sim.color_by_cohort:
                    imgui.set_next_item_width(100)
                    _, self.state.sim.hue_sensitivity = imgui.slider_float("Hue Sensitivity", self.state.sim.hue_sensitivity, -1.0, 1.0)
                _, self.state.sim.watercolor_mode = imgui.checkbox("Watercolor Mode", self.state.sim.watercolor_mode)
                if self.state.sim.watercolor_mode:
                    imgui.set_next_item_width(100)
                    _, self.state.sim.ink_weight = imgui.slider_float("Ink Weight", self.state.sim.ink_weight, 0.0, 4.0)
                emboss_options = ["Off", "Canvas (Trails)", "Brush (Particles)"]
                imgui.set_next_item_width(150)
                if imgui.begin_combo("Emboss Mode", emboss_options[self.state.sim.emboss_mode]):
                    for i, option in enumerate(emboss_options):
                        if imgui.selectable(option, self.state.sim.emboss_mode == i)[0]:
                            self.state.sim.emboss_mode = i
                    imgui.end_combo()
                if self.state.sim.emboss_mode != 0:
                    imgui.set_next_item_width(100)
                    _, self.state.sim.emboss_intensity = imgui.slider_float("Emboss Intensity", self.state.sim.emboss_intensity, -1.0, 1.0)
                    imgui.set_next_item_width(100)
                    _, self.state.sim.emboss_smoothness = imgui.slider_float("Emboss Smoothness", self.state.sim.emboss_smoothness, 0.001, 1.0)
                imgui.end_menu()

            # After all menus: check mouse distance from all menu rectangles
            # Find the minimum distance to any rectangle
            if self.physics_menu_bar_has_open_menu and not self.save_popup_open:
                mouse_pos = imgui.get_mouse_pos()

                # Calculate minimum distance to any menu rectangle
                min_distance = float('inf')
                for min_x, min_y, max_x, max_y in physics_menu_rectangles:
                    dx = max(min_x - mouse_pos.x, 0, mouse_pos.x - max_x)
                    dy = max(min_y - mouse_pos.y, 0, mouse_pos.y - max_y)
                    distance = (dx * dx + dy * dy) ** 0.5
                    min_distance = min(min_distance, distance)

                # If mouse is too far away from all rectangles, signal to close menus
                if min_distance > self.state.preferences.menu_close_threshold:
                    self.force_close_physics_menus = True

            imgui.end_menu_bar()

        # Update physics menu tracking state
        self.physics_menu_bar_has_open_menu = physics_any_menu_open_this_frame
        # Reset force close flag after processing
        if self.force_close_physics_menus and not physics_any_menu_open_this_frame:
            self.force_close_physics_menus = False

        # Multi-load controls
        imgui.text("Multi-Load Controls")
        imgui.separator()

        # Get config count from service
        config_count = self.multi_load_service.get_config_count() if self.multi_load_service else 0

        _, self.state.multi_load.simultaneous_configs = imgui.slider_float(
            "Simultaneous Configs", self.state.multi_load.simultaneous_configs, 0.0, float(max(1, config_count-.001)))
        _, self.state.multi_load.progression_pace = imgui.slider_float(
            "Progression Pace", self.state.multi_load.progression_pace, 0.0, 1.0)

        # Sync current progress from service (for auto-advancement display)
        if self.multi_load_service:
            current_progress_value = self.multi_load_service.current_progress
        else:
            current_progress_value = self.state.multi_load.current_progress

        changed, new_progress = imgui.slider_float(
            "Current Progress", current_progress_value, 0.0, 1.0)
        if changed and self.multi_load_service:
            # User manually changed the slider - update service directly
            self.multi_load_service.set_progress(new_progress)
        # Always sync state from service for next frame
        if self.multi_load_service:
            self.state.multi_load.current_progress = self.multi_load_service.current_progress

        imgui.separator()
        imgui.text(f"Loaded Configurations ({config_count}/64)")
        imgui.separator()

        if config_count == 0:
            imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "No configs loaded")
            imgui.text_colored(imgui.ImVec4(0.6, 0.6, 0.6, 1.0), "Use File -> Load to add")
        else:
            # Render config list with remove buttons
            for i in range(config_count):
                filename = self.multi_load_service.get_filename(i)
                if filename:
                    # Config name
                    imgui.text(f"{i+1}. {filename}")
                    imgui.same_line()
                    # Remove button (aligned to right)
                    imgui.push_style_color(imgui.Col_.button, imgui.ImVec4(0.8, 0.2, 0.2, 1.0))
                    imgui.push_style_color(imgui.Col_.button_hovered, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
                    if imgui.small_button(f"Remove##{i}"):
                        self.multi_load_service.remove_config(i)
                    imgui.pop_style_color(2)

        imgui.end()
        if self.state.sim.sweep_preview_pending_restore:
            imgui.pop_style_color(2)
