"""Command handler: processes one-shot UI commands each frame."""
import random
import numpy as np
from utilities.gl_helpers import readback_rule


class CommandHandler:
    """Processes one-shot commands from UI state.

    Receives references to app components in __init__ and coordinates
    them in response to UI flags (the "one-shot flag" pattern).
    """

    def __init__(self, sim, camera, ui, rule_manager, entity_picker,
                 video_service, config_saver, multi_load_service, user_configs_dir):
        self.sim = sim
        self.camera = camera
        self.ui = ui
        self.rule_manager = rule_manager
        self.entity_picker = entity_picker
        self.video_service = video_service
        self.config_saver = config_saver
        self.multi_load_service = multi_load_service
        self.user_configs_dir = user_configs_dir

        # Preview state
        self.preview_rule_active = False  # File->load preview
        self.clipboard_preview_active = False  # Config clipboard preview
        self._clipboard_cached_config = None  # Full config saved before clipboard preview

        # Video pending state (waiting for scheduled start frame)
        self.video_pending = False
        self.video_scheduled_start_frame = 0

        # Deferred entity selection state (waits one frame for rule buffer to be written)
        self._pending_entity_selection = None  # Tuple of (entity_id, entity_pos, entity_cohort) or None

    @property
    def has_pending_entity_selection(self):
        """Whether there's a pending entity selection waiting for rule readback."""
        return self._pending_entity_selection is not None

    def try_complete_entity_selection(self, ui_state):
        """Try to complete a pending entity selection after rule buffer update.

        Called from simulation_runner after sim.update() on the first physics step.
        Returns True if selection was completed.
        """
        if self._pending_entity_selection is None:
            return False

        pending_entity_id = self.sim.consume_pending_rule_readback()
        if pending_entity_id is None:
            return False

        entity_id, entity_pos, entity_cohort = self._pending_entity_selection
        self._pending_entity_selection = None

        # Read back the rule (buffer was just written by entity_update)
        rule = readback_rule(self.sim.get_rule_buffer(), entity_id)
        self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
        self.sim.apply_rule(rule)
        self.sim.update_sliders_from_particle(entity_pos, entity_cohort)
        print(f"Deferred rule readback complete for entity {entity_id}")
        return True

    def process_commands(self, ui_state, tiling_mode):
        """Handle one-shot commands from UI state."""

        # Handle world size change
        if ui_state.request_world_size_change:
            self._handle_world_size_change(ui_state)

        # Toggle recording (with delayed start support)
        if ui_state.toggle_recording:
            self._handle_toggle_recording(ui_state)

        # Screenshot request (Shift+P) - set pending flag
        if ui_state.request_screenshot:
            return 'screenshot_pending'

        # Shader reload
        if ui_state.request_reload:
            self.sim.reload()
            if self.rule_manager.has_rules():
                self.sim.apply_rule(self.rule_manager.get_current_rule())
            self.camera.reload()

        # Simple reset (R key)
        if ui_state.request_reset:
            self.sim.reset()

        # Full reset (Z key)
        if ui_state.request_full_reset:
            self._handle_full_reset(ui_state)

        # Randomize mutations (M key)
        if ui_state.request_randomize_mutations:
            self._handle_randomize_mutations(ui_state)

        # Handle sweep preview restore
        restored_sweep_preview = self._handle_sweep_preview_restore(ui_state)

        # Handle mouse clicks
        if not restored_sweep_preview:
            self._handle_mouse_clicks(ui_state, tiling_mode)

        # Handle config save/load/delete
        self._handle_config_commands(ui_state)

        # Handle preview commands (file browser)
        self._handle_preview_commands(ui_state)

        # Handle config clipboard commands
        self._handle_clipboard_commands(ui_state)

        return None

    def _handle_world_size_change(self, ui_state):
        """Handle world size change request."""
        self.sim.world_size = ui_state.preferences.world_size
        self.sim.setup_simulation_state()
        self.sim.setup_shaders()
        self.entity_picker.update_buffer(self.sim.get_entity_buffer())
        if self.rule_manager.has_rules():
            self.sim.apply_rule(self.rule_manager.get_current_rule())
        self.sim.reset()
        self.ui._last_applied_world_size = ui_state.preferences.world_size
        print(f"World size changed to {self.sim.world_size} "
              f"(entity_count: {self.sim.entity_count}, "
              f"canvas: {self.sim.get_canvas_dimensions()}x{self.sim.get_canvas_dimensions()})")

    def _handle_toggle_recording(self, ui_state):
        """Handle video recording toggle with delayed start support."""
        if self.video_pending:
            self.video_pending = False
            self.video_scheduled_start_frame = 0
        elif self.video_service.is_active():
            self.video_service.stop()
        else:
            video_end_frame = ui_state.preferences.video_end_frame
            video_simulation_frames = ui_state.preferences.max_frames * ui_state.preferences.motion_blur_samples
            scheduled_start_frame = video_end_frame - video_simulation_frames

            if video_end_frame == 0 or scheduled_start_frame <= self.sim.frame_count:
                self.video_service.start()
            else:
                self.video_pending = True
                self.video_scheduled_start_frame = scheduled_start_frame

    def _handle_full_reset(self, ui_state):
        """Handle full reset (Z key): reset entities, apply zero rule, randomize, push new state."""
        self.sim.reset()
        zero_rule = np.zeros((10, 8), dtype=np.float32)
        self.sim.apply_rule(zero_rule)
        ui_state.sim.rule_seed = random.random()
        self.rule_manager.push_rule(zero_rule, ui_state.sim.rule_seed)

    def _handle_randomize_mutations(self, ui_state):
        """Handle randomize mutations (M key)."""
        current_rule = self.rule_manager.get_current_rule()
        if current_rule is not None:
            ui_state.sim.rule_seed = random.random()
            self.rule_manager.push_rule(current_rule.copy(), ui_state.sim.rule_seed)
            self.sim.apply_rule(current_rule)

    def _handle_sweep_preview_restore(self, ui_state):
        """Handle sweep preview restore: ANY click re-enables sweeps. Returns True if restored."""
        if ui_state.sim.sweep_preview_pending_restore:
            if ui_state.any_left_click_this_frame or ui_state.any_right_click_this_frame:
                ui_state.sim.parameter_sweeps_enabled = True
                ui_state.sim.sweep_preview_pending_restore = False
                return True
        return False

    def _handle_mouse_clicks(self, ui_state, tiling_mode):
        """Handle left/right mouse click behavior based on mode."""
        if ui_state.left_click_this_frame:
            if ui_state.sim.parameter_sweeps_enabled:
                self._handle_sweep_click(ui_state, tiling_mode)
            elif ui_state.preferences.mouse_mode == "Select Particle":
                self._handle_entity_pick(ui_state, tiling_mode)

        elif ui_state.right_click_this_frame:
            if ui_state.sim.parameter_sweeps_enabled:
                if self.sim.has_active_xy_sweep() or self.sim.has_active_cohort_sweep():
                    ui_state.sim.parameter_sweeps_enabled = False
                    ui_state.sim.sweep_preview_pending_restore = True
            elif ui_state.preferences.mouse_mode == "Select Particle":
                if self.rule_manager.length() > 1:
                    prev_rule, prev_seed = self.rule_manager.pop_rule()
                    if prev_seed is not None:
                        ui_state.sim.rule_seed = prev_seed
                    self.sim.apply_rule(prev_rule)

    def _handle_sweep_click(self, ui_state, tiling_mode):
        """Handle left click when parameter sweeps are enabled."""
        if not (self.sim.has_active_xy_sweep() or self.sim.has_active_cohort_sweep()):
            return

        tex_coords = self.camera.screen_to_tex(
            ui_state.mouse_pos, self.sim.view_tex.size
        )
        if tiling_mode:
            tex_coords = (
                np.fmod(tex_coords[0] + 10.0, 1.0),
                np.fmod(tex_coords[1] + 10.0, 1.0)
            )
        world_pos = (tex_coords[0] * 2 - 1, tex_coords[1] * 2 - 1)

        if self.sim.has_active_cohort_sweep():
            entity_id, entity_pos, entity_cohort = self.entity_picker.find_nearest_entity(tex_coords)
            self.sim.update_sliders_from_particle(world_pos, entity_cohort)
        else:
            self.sim.update_sliders_from_position(world_pos)

    def _handle_entity_pick(self, ui_state, tiling_mode):
        """Handle entity selection via left click in Select Particle mode."""
        tex_coords = self.camera.screen_to_tex(
            ui_state.mouse_pos, self.sim.view_tex.size
        )
        if tiling_mode:
            tex_coords = (
                np.fmod(tex_coords[0] + 10.0, 1.0),
                np.fmod(tex_coords[1] + 10.0, 1.0)
            )
        entity_id, entity_pos, entity_cohort = self.entity_picker.find_nearest_entity(tex_coords)

        if entity_id >= 0 and entity_id < self.sim.entity_count:
            print(f"Entity {entity_id} at pos {entity_pos}, cohort {entity_cohort} - requesting rule buffer update")
            self.sim.request_rule_buffer_update(entity_id)
            self._pending_entity_selection = (entity_id, entity_pos, entity_cohort)
        else:
            print(f"Warning: entity_id {entity_id} out of bounds (max: {self.sim.entity_count - 1})")

    def _handle_config_commands(self, ui_state):
        """Handle config save/load/delete commands."""
        # Config save (Ctrl+C)
        if ui_state.request_save_config:
            current_rule = self.rule_manager.get_current_rule()
            config = self.config_saver.create_config(ui_state.sim, current_rule)
            config_string = self.config_saver.encode_clipboard(config)
            self.ui.set_clipboard(config_string)
            self.ui.add_to_config_clipboard(config, self.ui.currently_open_project)
            print(f"Config copied to clipboard ({len(config_string)} chars)")

        # Config load (Ctrl+V)
        if ui_state.request_load_config:
            config_string = ui_state.clipboard_text
            if config_string:
                rule = self.config_saver.load_from_string(config_string, ui_state.sim)
                if rule is not None:
                    self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
                    self.sim.apply_rule(rule)
                    print("Config loaded from clipboard")
                else:
                    print("Failed to load config from clipboard")

        # File save (menu)
        if ui_state.request_save_file:
            filename = ui_state.save_filename
            if filename:
                current_rule = self.rule_manager.get_current_rule()
                config = self.config_saver.create_config(ui_state.sim, current_rule)
                filepath = self.user_configs_dir / f"{filename}.json"
                self.config_saver.save_to_file(config, filepath)
                print(f"Config saved to {filepath}")
                self.ui.update_physics_defaults(filename)

        # File load (menu)
        if ui_state.request_load_file:
            self._handle_file_load(ui_state)

        # File delete (menu)
        if ui_state.request_delete_file:
            filename = ui_state.delete_filename
            category = ui_state.delete_category
            if filename:
                filepath = self.ui._get_config_path(filename, category)
                if filepath.exists():
                    filepath.unlink()
                    print(f"Config deleted: {filepath}")

    def _handle_file_load(self, ui_state):
        """Handle file load from menu, including multi-load and preview modes."""
        filename = ui_state.load_filename
        category = ui_state.load_category
        if not filename:
            return

        # Multi-load mode
        if ui_state.multi_load.multi_load_enabled:
            filepath = self.ui._get_config_path(filename, category)
            config = self.config_saver.load_from_file(filepath)
            if config is not None:
                success = self.multi_load_service.add_config(config, filename)
                if success:
                    print(f"Config added to multi-load: {filename}")
                else:
                    print(f"Failed to add config: multi-load list is full "
                          f"({self.multi_load_service.get_config_count()}/64)")
            else:
                print(f"Failed to load config from {filepath}")
            return

        # Normal mode
        if self.preview_rule_active:
            # Preview already applied config and pushed rule - just finalize it
            self.preview_rule_active = False
            if ui_state.load_watercolor_override is not None:
                ui_state.sim.watercolor_mode = ui_state.load_watercolor_override
            print(f"Config loaded (from preview): {filename}")
            self.ui.update_physics_defaults(filename)
        else:
            # No preview active - load fresh from file
            filepath = self.ui._get_config_path(filename, ui_state.load_category)
            config = self.config_saver.load_from_file(filepath)
            if config is not None:
                rule = self.config_saver.apply_config(
                    config, ui_state.sim,
                    watercolor_override=ui_state.load_watercolor_override
                )
                self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
                self.sim.apply_rule(rule)
                print(f"Config loaded from {filepath}")
                self.ui.update_physics_defaults(filename)
            else:
                print(f"Failed to load config from {filepath}")

    def _handle_preview_commands(self, ui_state):
        """Handle config preview (hover in Load submenu) and clear preview."""
        # Clear preview must happen before new preview
        if ui_state.request_clear_preview:
            if self.preview_rule_active:
                prev_rule, prev_seed = self.rule_manager.pop_rule()
                if prev_seed is not None:
                    ui_state.sim.rule_seed = prev_seed
                self.sim.apply_rule(prev_rule)
                self.preview_rule_active = False

        # New preview
        if ui_state.request_preview_config:
            filename = ui_state.preview_filename
            category = ui_state.preview_category
            if filename:
                filepath = self.ui._get_config_path(filename, category)
                config = self.config_saver.load_from_file(filepath)
                if config and config.rule is not None:
                    ui_state.sim.rule_seed = config.rule_seed
                    self.rule_manager.push_rule(config.rule, ui_state.sim.rule_seed)
                    self.sim.apply_rule(config.rule)
                    self.preview_rule_active = True

    def _handle_clipboard_commands(self, ui_state):
        """Handle config clipboard preview, load, delete, and import-to-multiload."""
        # Clear clipboard preview (must happen before new preview)
        if ui_state.request_clear_clipboard_preview:
            if self.clipboard_preview_active:
                self.rule_manager.pop_rule()
                # Restore the full cached config (not just the rule)
                if self._clipboard_cached_config is not None:
                    rule = self.config_saver.apply_config(
                        self._clipboard_cached_config, ui_state.sim)
                    self.sim.apply_rule(rule)
                    self._clipboard_cached_config = None
                self.clipboard_preview_active = False

        # New clipboard preview
        if ui_state.request_preview_clipboard_config:
            idx = ui_state.clipboard_config_index
            if 0 <= idx < len(self.ui.config_clipboard):
                # Cache current full config before applying preview
                if not self.clipboard_preview_active:
                    current_rule = self.rule_manager.get_current_rule()
                    self._clipboard_cached_config = self.config_saver.create_config(
                        ui_state.sim, current_rule)
                config, _label = self.ui.config_clipboard[idx]
                rule = self.config_saver.apply_config(config, ui_state.sim)
                self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
                self.sim.apply_rule(rule)
                self.clipboard_preview_active = True

        # Load clipboard config (click)
        if ui_state.request_load_clipboard_config:
            self._load_clipboard_config(ui_state)

        # Delete clipboard entry
        if ui_state.request_delete_clipboard_config:
            self._delete_clipboard_config(ui_state)

        # Import clipboard to multi-load
        if ui_state.request_import_clipboard_to_multiload:
            self._import_clipboard_to_multiload()

    def _load_clipboard_config(self, ui_state):
        """Load a config from the clipboard (apply it permanently)."""
        # Clear preview first (discard cached config since we're committing)
        if self.clipboard_preview_active:
            self.rule_manager.pop_rule()
            self.clipboard_preview_active = False
            self._clipboard_cached_config = None

        idx = ui_state.clipboard_config_index
        if 0 <= idx < len(self.ui.config_clipboard):
            config, label = self.ui.config_clipboard[idx]
            rule = self.config_saver.apply_config(config, ui_state.sim)
            self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
            self.sim.apply_rule(rule)
            # Extract original filename from label (everything before the *)
            original_filename = label.rsplit("*", 1)[0]
            self.ui.update_physics_defaults(original_filename)
            print(f"Config loaded from clipboard: {label}")

    def _delete_clipboard_config(self, ui_state):
        """Delete an entry from the config clipboard."""
        # Clear preview first, restore cached config
        if self.clipboard_preview_active:
            self.rule_manager.pop_rule()
            if self._clipboard_cached_config is not None:
                rule = self.config_saver.apply_config(
                    self._clipboard_cached_config, ui_state.sim)
                self.sim.apply_rule(rule)
                self._clipboard_cached_config = None
            self.clipboard_preview_active = False

        idx = ui_state.clipboard_config_index
        if 0 <= idx < len(self.ui.config_clipboard):
            self.ui.config_clipboard.pop(idx)

    def _import_clipboard_to_multiload(self):
        """Replace multi-load configs with contents of config clipboard."""
        # Clear existing multi-load configs
        while self.multi_load_service.get_config_count() > 0:
            self.multi_load_service.remove_config(0)

        # Add each clipboard entry
        for config, label in self.ui.config_clipboard:
            self.multi_load_service.add_config(config, label)

        print(f"Imported {len(self.ui.config_clipboard)} configs from clipboard to multi-load")
