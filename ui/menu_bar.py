"""Main menu bar: File, Reset, Help, Extras menus with auto-close logic."""
from imgui_bundle import imgui


class MenuBarMixin:
    """Mixin for main menu bar. Combined into UI via multiple inheritance."""

    def render_main_menu_bar(self):
        """Render the main application menu bar at the top of the window."""
        load_submenu_open = False
        any_menu_open_this_frame = False

        if imgui.begin_main_menu_bar():
            # Track all open menu rectangles separately (not combined into one giant box)
            # We'll calculate distance as the minimum distance to any of these rectangles
            menu_rectangles = []

            # Start with the menu bar itself
            menu_bar_min = imgui.get_window_pos()
            menu_bar_size = imgui.get_window_size()
            menu_rectangles.append((menu_bar_min.x, menu_bar_min.y,
                                   menu_bar_min.x + menu_bar_size.x,
                                   menu_bar_min.y + menu_bar_size.y))
            if imgui.begin_menu("File", not self.force_close_main_menus):
                any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                file_menu_min = imgui.get_window_pos()
                file_menu_size = imgui.get_window_size()
                menu_rectangles.append((file_menu_min.x, file_menu_min.y,
                                       file_menu_min.x + file_menu_size.x,
                                       file_menu_min.y + file_menu_size.y))

                if imgui.menu_item("New", "", False)[0]:
                    self._load_filename = "_Default"
                    self._load_category = "Core"
                    self._request_load_file = True
                    self._load_watercolor_override = None
                self._delayed_tooltip("Start a fresh config. Loads from _Default")

                imgui.separator()

                if imgui.menu_item("Save...", "", False)[0]:
                    self.save_popup_open = True
                    # Default to last loaded filename
                    self.save_filename_buffer = self.currently_open_project
                self._delayed_tooltip("Save the current physics settings including particle rules.")

                # Load submenu with preview - locks to current watercolor mode
                # Right-click toggles watercolor mode
                if imgui.begin_menu("Load", not self.force_close_main_menus):
                    any_menu_open_this_frame = True
                    load_submenu_open = True
                    # Add this submenu's bounding box to the list
                    load_menu_min = imgui.get_window_pos()
                    load_menu_size = imgui.get_window_size()
                    menu_rectangles.append((load_menu_min.x, load_menu_min.y,
                                           load_menu_min.x + load_menu_size.x,
                                           load_menu_min.y + load_menu_size.y))

                    # First frame submenu opens: cache current state and scan config files
                    if not self.load_submenu_was_open:
                        self._cache_all_configs()
                        # Cache current config as JSON string for restoration
                        self.cached_config = self.config_saver.save_to_string(
                            self.state.sim, self._display_info.get('current_rule'))
                        self.preview_rule_pushed = False
                        self.currently_previewing = None
                        self.currently_previewing_category = None
                        # Lock to current watercolor mode when menu opens
                        self.load_menu_watercolor_mode = self.state.sim.watercolor_mode

                    # Use locked watercolor mode
                    current_menu_watercolor = self.load_menu_watercolor_mode

                    # Header showing right-click hint (compact two-line format)
                    mode_text = "Watercolor ON" if current_menu_watercolor else "Watercolor OFF"
                    imgui.text_disabled("Right-click toggles:")
                    imgui.text_disabled(f"({mode_text})")
                    imgui.separator()

                    # Check for right-click anywhere in the menu to toggle watercolor
                    if imgui.is_window_hovered() and imgui.is_mouse_clicked(imgui.MouseButton_.right):
                        self.load_menu_watercolor_mode = not self.load_menu_watercolor_mode
                        current_menu_watercolor = self.load_menu_watercolor_mode
                        # Update any current preview with new watercolor mode
                        if self.currently_previewing and self.currently_previewing_category:
                            cache_key = f"{self.currently_previewing_category}/{self.currently_previewing}"
                            if cache_key in self.cached_configs:
                                config = self.cached_configs[cache_key]
                                self.config_saver.apply_config(config, self.state.sim,
                                                              watercolor_override=current_menu_watercolor)
                        elif self.cached_config:
                            # Restore from cache with watercolor override
                            self.config_saver.load_from_string(
                                self.cached_config, self.state.sim,
                                watercolor_override=current_menu_watercolor)

                    # Lock watercolor mode to menu's mode
                    self.state.sim.watercolor_mode = current_menu_watercolor

                    hovered_this_frame = self._render_load_submenu_content(current_menu_watercolor)

                    # Handle preview on hover (works in both normal and multi-load modes)
                    # hovered_this_frame is now a tuple (filename, category) or None
                    hovered_filename = hovered_this_frame[0] if hovered_this_frame else None
                    hovered_category = hovered_this_frame[1] if hovered_this_frame else None
                    current_preview = (self.currently_previewing, self.currently_previewing_category)

                    if hovered_this_frame != current_preview:
                        # First, clear any existing preview
                        if self.currently_previewing:
                            self._request_clear_preview = True

                        if hovered_filename and hovered_category:
                            cache_key = f"{hovered_category}/{hovered_filename}"
                            if cache_key in self.cached_configs:
                                # Apply preview config with watercolor override
                                config = self.cached_configs[cache_key]
                                self.config_saver.apply_config(config, self.state.sim,
                                                              watercolor_override=current_menu_watercolor)
                                self._request_preview_config = True
                                self._preview_filename = hovered_filename
                                self._preview_category = hovered_category
                                self.currently_previewing = hovered_filename
                                self.currently_previewing_category = hovered_category
                        elif hovered_this_frame is None and self.cached_config:
                            # Revert to cached state with watercolor override
                            self.config_saver.load_from_string(
                                self.cached_config, self.state.sim,
                                watercolor_override=current_menu_watercolor)
                            self.currently_previewing = None
                            self.currently_previewing_category = None

                    imgui.end_menu()

                imgui.separator()

                # Preferences toggle
                if imgui.menu_item("Preferences", "", self.state.preferences.show_preferences_window)[0]:
                    self.state.preferences.show_preferences_window = not self.state.preferences.show_preferences_window

                imgui.end_menu()

            # Sidebar toggle button (shows/hides Physics Settings and Preferences)
            if imgui.menu_item("Show/Hide Sidebar (X)", "", self.show_sidebar)[0]:
                self.show_sidebar = not self.show_sidebar

            # Reset menu
            if imgui.begin_menu("Reset...", not self.force_close_main_menus):
                any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                reset_menu_min = imgui.get_window_pos()
                reset_menu_size = imgui.get_window_size()
                menu_rectangles.append((reset_menu_min.x, reset_menu_min.y,
                                       reset_menu_min.x + reset_menu_size.x,
                                       reset_menu_min.y + reset_menu_size.y))

                # Revert to current project (reload the file)
                revert_label = f"Revert to '{self.currently_open_project}'"

                if imgui.menu_item(revert_label, "", False)[0]:
                    # Trigger file load equivalent to File->Load
                    self._load_filename = self.currently_open_project
                    self._request_load_file = True
                    self._load_watercolor_override = None  # Keep current watercolor mode
                self._delayed_tooltip(f"Equivalent to File -> Load {self.currently_open_project}")

                # Reset all slider ranges
                if imgui.menu_item("Reset all slider ranges to defaults", "", False)[0]:
                    # Clear all custom slider ranges, reverting to defaults
                    self.state.sim.slider_ranges.clear()

                # Reset all parameter sweeps
                if imgui.menu_item("Reset all parameter sweeps", "", False)[0]:
                    # Turn off all parameter sweeps
                    for param in list(self.state.sim.x_sweeps.keys()):
                        self.state.sim.x_sweeps[param] = 0.0
                        self.state.sim.y_sweeps[param] = 0.0
                        self.state.sim.cohort_sweeps[param] = 0.0
                self._delayed_tooltip("Set all parameter sweeps to 'off'.")

                # Reset all UI settings
                if imgui.menu_item("Reset all UI settings", "", False)[0]:
                    # Reset preferences to defaults (equivalent to deleting preferences.config)
                    from state.preferences_state import PreferencesState
                    self.state.preferences = PreferencesState()


                self._delayed_tooltip("Restore all preferences and ui state to factory settings. \nEquivalent to deleting preferences.config, or running this\nprogram for the first time. Physics config saves are not affected.")

                imgui.end_menu()

            # Help menu
            if imgui.begin_menu("Help", not self.force_close_main_menus):
                any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                help_menu_min = imgui.get_window_pos()
                help_menu_size = imgui.get_window_size()
                menu_rectangles.append((help_menu_min.x, help_menu_min.y,
                                       help_menu_min.x + help_menu_size.x,
                                       help_menu_min.y + help_menu_size.y))

                if imgui.menu_item("Controls", "", self.state.preferences.show_controls_window)[0]:
                    self.state.preferences.show_controls_window = not self.state.preferences.show_controls_window
                if imgui.menu_item("Parameter Sweeps", "", self.state.preferences.show_parameter_sweeps_window)[0]:
                    self.state.preferences.show_parameter_sweeps_window = not self.state.preferences.show_parameter_sweeps_window
                if imgui.menu_item("Tutorial", "", self.state.preferences.show_tutorial_window)[0]:
                    self.state.preferences.show_tutorial_window = not self.state.preferences.show_tutorial_window
                if imgui.menu_item("Performance", "", self.state.preferences.show_performance_window)[0]:
                    self.state.preferences.show_performance_window = not self.state.preferences.show_performance_window
                imgui.end_menu()

            # Extras menu
            if imgui.begin_menu("Extras", not self.force_close_main_menus):
                any_menu_open_this_frame = True
                # Add this menu's bounding box to the list
                extras_menu_min = imgui.get_window_pos()
                extras_menu_size = imgui.get_window_size()
                menu_rectangles.append((extras_menu_min.x, extras_menu_min.y,
                                       extras_menu_min.x + extras_menu_size.x,
                                       extras_menu_min.y + extras_menu_size.y))

                # Multi Load toggle
                _, self.state.multi_load.multi_load_enabled = imgui.checkbox(
                    "Multi Load - EXPERIMENTAL",
                    self.state.multi_load.multi_load_enabled
                )
                self._delayed_tooltip("Load multiple files at once, so that particles\nfrom different saves can interact.")

                # Strong Determinism toggle
                _, self.state.preferences.strong_determinism = imgui.checkbox(
                    "Strong Determinism",
                    self.state.preferences.strong_determinism
                )
                self._delayed_tooltip("Enables double buffering for the canvas. When checked,\nevents will unfold exactly the same way after every\nsimulation reset. Comes with a small ~3% performance penalty.")

                # Screen Recording Controls
                if imgui.menu_item("Screen Recording Controls", "", self.show_video_recording_window)[0]:
                    self.show_video_recording_window = not self.show_video_recording_window

                # Config Clipboard window
                if imgui.menu_item("Config Clipboard - EXPERIMENTAL", "", self.show_history_window)[0]:
                    self.show_history_window = not self.show_history_window

                imgui.end_menu()

            # After all menus: check mouse distance from all menu rectangles
            # Find the minimum distance to any rectangle
            if self.main_menu_bar_has_open_menu and not self.save_popup_open:
                mouse_pos = imgui.get_mouse_pos()

                # Calculate minimum distance to any menu rectangle
                min_distance = float('inf')
                for min_x, min_y, max_x, max_y in menu_rectangles:
                    dx = max(min_x - mouse_pos.x, 0, mouse_pos.x - max_x)
                    dy = max(min_y - mouse_pos.y, 0, mouse_pos.y - max_y)
                    distance = (dx * dx + dy * dy) ** 0.5
                    min_distance = min(min_distance, distance)

                # If mouse is too far away from all rectangles, signal to close menus
                if min_distance > self.state.preferences.menu_close_threshold:
                    self.force_close_main_menus = True

            imgui.end_main_menu_bar()

        # Update menu tracking state
        self.main_menu_bar_has_open_menu = any_menu_open_this_frame
        # Reset force close flag after processing
        if self.force_close_main_menus and not any_menu_open_this_frame:
            self.force_close_main_menus = False

        # Handle submenu close without selection
        if self.load_submenu_was_open and not load_submenu_open:
            # Submenu just closed - restore cached state (no watercolor override)
            if self.cached_config:
                self.config_saver.load_from_string(self.cached_config, self.state.sim)
            if self.currently_previewing:
                self._request_clear_preview = True
            self.cached_config = None
            self.currently_previewing = None
            self.currently_previewing_category = None
            self.cached_configs = {}
            self.preview_rule_pushed = False
            self.load_menu_watercolor_mode = None  # Clear the watercolor lock

        self.load_submenu_was_open = load_submenu_open
