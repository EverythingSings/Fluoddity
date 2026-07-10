"""Physics Settings window: sliders, additional settings, appearance, notes."""
from imgui_bundle import imgui
from .physics_params import PARAM_GROUPS


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

        physics_any_menu_open_this_frame = self._render_physics_normal_menu_bar()

        # Display currently open project and rule seed
        pls = self.param_lock_service
        imgui.text(f"Project: {self.currently_open_project}")
        imgui.same_line()
        # Convert rule_seed (0.0-1.0 float) to short hex format
        seed_hex = format(int(self.state.sim.rule_seed * 0xFFFF), '04x')
        seed_locked = pls and pls.is_locked('rule_seed')
        if seed_locked:
            imgui.text_colored(imgui.ImVec4(1.0, 0.3, 0.3, 1.0), f"[L]Mutation Seed: #{seed_hex}")
        else:
            imgui.text_colored(imgui.ImVec4(0.5, 0.8, 1.0, 1.0), f"Mutation Seed: #{seed_hex}")
        if pls:
            pls.handle_alt_click('rule_seed')
        imgui.separator()

        # === Basics Group (Trail sensors and rule mutation) ===
        imgui.set_next_item_open(self.state.preferences.physics_group_basics)
        basics_open = imgui.collapsing_header("Basics - Trail sensors and rule mutation")
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_basics = basics_open
        if basics_open:
            for pdef in PARAM_GROUPS['basics']:
                self.render_physics_slider(pdef)

        # === Forces Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_forces)
        forces_open = imgui.collapsing_header("Forces")
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_forces = forces_open
        if forces_open:
            for pdef in PARAM_GROUPS['forces']:
                self.render_physics_slider(pdef)

        # === Advanced Group ===
        imgui.set_next_item_open(self.state.preferences.physics_group_advanced)
        advanced_open = imgui.collapsing_header("Advanced")
        if imgui.is_item_toggled_open():
            self.state.preferences.physics_group_advanced = advanced_open
        if advanced_open:
            for pdef in PARAM_GROUPS['advanced']:
                self.render_physics_slider(pdef)

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
            bc_lock_colors = pls.push_locked_style('boundary_conditions') if pls else 0
            bc_label = pls.get_display_label('boundary_conditions', "Boundary Conditions") if pls else "Boundary Conditions"
            imgui.set_next_item_width(100)
            if imgui.begin_combo(bc_label, boundary_options[self.state.sim.boundary_conditions]):
                if pls and pls.begin_combo_alt_click('boundary_conditions'):
                    pass  # alt-click intercepted; combo closed
                else:
                    for i, option in enumerate(boundary_options):
                        is_selected = (self.state.sim.boundary_conditions == i)
                        if imgui.selectable(option, is_selected)[0]:
                            self.state.sim.boundary_conditions = i
                        self._delayed_tooltip(boundary_tooltips[i])
                        if is_selected:
                            imgui.set_item_default_focus()
                    imgui.end_combo()
            elif pls:
                pls.handle_alt_click('boundary_conditions')
            if pls:
                pls.pop_locked_style(bc_lock_colors)

            # Initial Conditions (with per-option tooltips)
            initial_options = ["Grid", "Random", "Ring"]
            initial_tooltips = [
                "Particles start in a grid, organized by cohort",
                "Particles are spread uniformly across the canvas",
                "Particles start distributed around a circle, organized by cohort"
            ]
            ic_lock_colors = pls.push_locked_style('initial_conditions') if pls else 0
            ic_label = pls.get_display_label('initial_conditions', "Initial Conditions") if pls else "Initial Conditions"
            imgui.set_next_item_width(100)
            if imgui.begin_combo(ic_label, initial_options[self.state.sim.initial_conditions]):
                if pls and pls.begin_combo_alt_click('initial_conditions'):
                    pass  # alt-click intercepted; combo closed
                else:
                    for i, option in enumerate(initial_options):
                        is_selected = (self.state.sim.initial_conditions == i)
                        if imgui.selectable(option, is_selected)[0]:
                            self.state.sim.initial_conditions = i
                        self._delayed_tooltip(initial_tooltips[i])
                        if is_selected:
                            imgui.set_item_default_focus()
                    imgui.end_combo()
            elif pls:
                pls.handle_alt_click('initial_conditions')
            if pls:
                pls.pop_locked_style(ic_lock_colors)

            # Number of Cohorts
            nc_lock_colors = pls.push_locked_style('num_cohorts') if pls else 0
            nc_label = pls.get_display_label('num_cohorts', "Number of Cohorts") if pls else "Number of Cohorts"
            imgui.set_next_item_width(100)
            changed_nc, new_nc = imgui.slider_int(
                nc_label,
                self.state.sim.num_cohorts,
                1, 144
            )
            if pls and pls.handle_alt_click('num_cohorts'):
                pass  # alt-click intercepted; discard value change
            elif changed_nc:
                self.state.sim.num_cohorts = new_nc
            if pls:
                pls.pop_locked_style(nc_lock_colors)
            self._delayed_tooltip("Each particle is assigned to a cohort. Each cohort shares behavior:\neach cohort has a distinct mutation.")

            imgui.separator()

            # Disable Symmetry
            ds_lock_colors = pls.push_locked_style('DISABLE_SYMMETRY') if pls else 0
            ds_label = pls.get_display_label('DISABLE_SYMMETRY', "Disable Symmetry") if pls else "Disable Symmetry"
            changed_ds, new_ds = imgui.checkbox(
                ds_label,
                self.state.sim.DISABLE_SYMMETRY
            )
            if pls and pls.handle_alt_click('DISABLE_SYMMETRY'):
                pass  # alt-click intercepted; discard value change
            elif changed_ds:
                self.state.sim.DISABLE_SYMMETRY = new_ds
            if pls:
                pls.pop_locked_style(ds_lock_colors)
            self._delayed_tooltip("Allow particles to display \"right / left handed\" behavior,\nleading to clockwise/counterclockwise bias.\nTurn it on to see why we go through trouble\nof calculating \"mirror world\" behavior in entity_update.glsl")

            # Absolute Orientation (combo box with 3 modes)
            combo_items = ["Off", "Y axis", "Radial"]
            ao_lock_colors = pls.push_locked_style('ABSOLUTE_ORIENTATION') if pls else 0
            ao_label = pls.get_display_label('ABSOLUTE_ORIENTATION', "Absolute Orientation") if pls else "Absolute Orientation"
            clicked_ao, new_ao = imgui.combo(
                ao_label,
                self.state.sim.ABSOLUTE_ORIENTATION,
                combo_items
            )
            if pls and pls.handle_alt_click('ABSOLUTE_ORIENTATION'):
                pass  # alt-click intercepted; discard value change
            elif clicked_ao:
                self.state.sim.ABSOLUTE_ORIENTATION = new_ao
            if pls:
                pls.pop_locked_style(ao_lock_colors)
            self._delayed_tooltip("What direction are particles 'facing'? Which way is 'up'?\nOff: use particle velocity\nY axis: align to y axis\nRadial: align to center of canvas")

            # Orientation Mix (only visible if Absolute Orientation != Off)
            if self.state.sim.ABSOLUTE_ORIENTATION != 0:
                om_lock_colors = pls.push_locked_style('ORIENTATION_MIX') if pls else 0
                om_label = pls.get_display_label('ORIENTATION_MIX', "Orientation Mix") if pls else "Orientation Mix"
                imgui.set_next_item_width(100)
                changed_om, new_om = imgui.slider_float(
                    om_label,
                    self.state.sim.ORIENTATION_MIX,
                    0.0, 1.0,
                    "%.2f"
                )
                if pls and pls.handle_alt_click('ORIENTATION_MIX'):
                    pass  # alt-click intercepted; discard value change
                elif changed_om:
                    self.state.sim.ORIENTATION_MIX = new_om
                if pls:
                    pls.pop_locked_style(om_lock_colors)
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
        pls = self.param_lock_service
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
                cbc_lock_colors = pls.push_locked_style('color_by_cohort') if pls else 0
                cbc_label = pls.get_display_label('color_by_cohort', "Color by Cohort") if pls else "Color by Cohort"
                changed_cbc, new_cbc = imgui.checkbox(
                    cbc_label,
                    self.state.sim.color_by_cohort
                )
                if pls and pls.handle_alt_click('color_by_cohort'):
                    pass  # alt-click intercepted; discard value change
                elif changed_cbc:
                    self.state.sim.color_by_cohort = new_cbc
                if pls:
                    pls.pop_locked_style(cbc_lock_colors)
                self._delayed_tooltip("Colors particles based on their cohort assignment\nrather than their behavior.")

                # Hue Sensitivity (only if not color by cohort)
                if not self.state.sim.color_by_cohort:
                    hs_lock_colors = pls.push_locked_style('hue_sensitivity') if pls else 0
                    hs_label = pls.get_display_label('hue_sensitivity', "Hue Sensitivity") if pls else "Hue Sensitivity"
                    changed_hs, new_hs = imgui.slider_float(
                        hs_label, self.state.sim.hue_sensitivity, -1.0, 1.0
                    )
                    if pls and pls.handle_alt_click('hue_sensitivity'):
                        pass  # alt-click intercepted; discard value change
                    elif changed_hs:
                        self.state.sim.hue_sensitivity = new_hs
                    if pls:
                        pls.pop_locked_style(hs_lock_colors)
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
