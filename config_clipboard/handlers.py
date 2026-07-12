"""Config clipboard command handlers: preview, load, delete.

Extracted from `command_handler.py` (Step 9). Handles the one-shot flags the
clipboard window raises each frame (preview / clear-preview / load / delete),
operating on a `ConfigClipboardState`. Reuses the parent CommandHandler's
lock-aware config primitives (`apply_config_with_locks`, `push_and_apply_rule`)
so parameter-lock and rule-lock behaviour stays identical to the fresh-load path.

The Ctrl+C **save-checkpoint** path stays in `CommandHandler._handle_config_commands`
(it's part of the config-save flow); this module owns only the preview/load/delete
half.
"""


class ConfigClipboardHandler:
    """Processes config-clipboard one-shot commands each frame."""

    def __init__(self, sim, rule_manager, config_saver, clipboard_state,
                 apply_config_with_locks, push_and_apply_rule,
                 update_physics_defaults,
                 field_handler=None, param_lock_service=None):
        self.sim = sim
        self.rule_manager = rule_manager
        self.config_saver = config_saver
        self.state = clipboard_state
        # Shared lock-aware primitives, bound from the parent CommandHandler.
        self._apply_config_with_locks = apply_config_with_locks
        self._push_and_apply_rule = push_and_apply_rule
        # Updates the UI's project name after a permanent clipboard load
        # (bound from ui.update_physics_defaults). Keeps this module UI-free.
        self._update_physics_defaults = update_physics_defaults
        self.field_handler = field_handler
        self.param_lock_service = param_lock_service

        # Preview state (was on CommandHandler)
        self.preview_active = False
        self._rule_was_pushed = False  # Whether preview actually pushed a rule
        self._cached_config = None  # Full config saved before preview

    def process(self, ui_state):
        """Handle clipboard preview, load, and delete for this frame."""
        fh = self.field_handler

        # Clear preview (must happen before a new preview)
        if ui_state.request_clear_clipboard_preview:
            if self.preview_active:
                if self._rule_was_pushed:
                    self.rule_manager.pop_rule()
                # Restore the full cached config (not just the rule)
                if self._cached_config is not None:
                    rule = self._apply_config_with_locks(self._cached_config, ui_state)
                    self.sim.apply_rule(rule)
                    self._cached_config = None

                if fh:
                    fh.restore_from_clipboard_preview(ui_state)

                self.preview_active = False
                self._rule_was_pushed = False

        # New preview
        if ui_state.request_preview_clipboard_config:
            idx = ui_state.clipboard_config_index
            if 0 <= idx < len(self.state.entries):
                # Cache current full config before applying preview
                if not self.preview_active:
                    current_rule = self.rule_manager.get_current_rule()
                    self._cached_config = self.config_saver.create_config(
                        ui_state.sim, current_rule)
                    if fh:
                        fh.cache_for_clipboard_preview(ui_state)

                entry = self.state.entries[idx]
                rule = self._apply_config_with_locks(entry.config, ui_state)
                pls = self.param_lock_service
                if not (pls and pls.should_block_rule_push()):
                    self.rule_manager.push_rule(rule, ui_state.sim.rule_seed)
                    self.sim.apply_rule(rule)
                    self._rule_was_pushed = True
                self.preview_active = True

                if fh:
                    fh.apply_snapshot(entry.field_snapshot, entry.config, ui_state)

        # Load (click)
        if ui_state.request_load_clipboard_config:
            self._load(ui_state)

        # Delete
        if ui_state.request_delete_clipboard_config:
            self._delete(ui_state)

    def _load(self, ui_state):
        """Load a config from the clipboard (apply it permanently)."""
        fh = self.field_handler

        # Clear preview first (discard cached config since we're committing)
        if self.preview_active:
            if self._rule_was_pushed:
                self.rule_manager.pop_rule()
            self.preview_active = False
            self._rule_was_pushed = False
            self._cached_config = None
            if fh:
                fh.discard_clipboard_preview_cache()

        idx = ui_state.clipboard_config_index
        if 0 <= idx < len(self.state.entries):
            entry = self.state.entries[idx]
            rule = self._apply_config_with_locks(entry.config, ui_state)
            self._push_and_apply_rule(rule, ui_state)

            if fh:
                fh.apply_snapshot(entry.field_snapshot, entry.config, ui_state)

            # Extract original filename from label (everything before the *)
            original_filename = entry.label.rsplit("*", 1)[0]
            self._update_physics_defaults(original_filename)
            print(f"Config loaded from clipboard: {entry.label}")

    def _delete(self, ui_state):
        """Delete an entry from the config clipboard."""
        fh = self.field_handler

        # Clear preview first, restore cached config
        if self.preview_active:
            if self._rule_was_pushed:
                self.rule_manager.pop_rule()
            if self._cached_config is not None:
                rule = self._apply_config_with_locks(self._cached_config, ui_state)
                self.sim.apply_rule(rule)
                self._cached_config = None

            if fh:
                fh.restore_from_clipboard_preview(ui_state)

            self.preview_active = False
            self._rule_was_pushed = False

        idx = ui_state.clipboard_config_index
        if 0 <= idx < len(self.state.entries):
            self.state.entries.pop(idx)
