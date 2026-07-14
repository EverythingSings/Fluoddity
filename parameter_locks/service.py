"""Parameter lock service: freezes selected parameters across config loads.

When enabled, locked parameters retain their values when configs are loaded
via File->Load, Config Clipboard, or Ctrl+V paste. Supports Alt-click
toggling on UI widgets, snapshot/restore around apply_config calls, and
visual styling helpers for locked elements.
"""
from imgui_bundle import imgui


# The lockable-param lists are derived from the shared param registry in
# ui/physics_params.py. That module is imported LAZILY (inside _registry())
# rather than at top level: importing `ui.physics_params` eagerly runs
# ui/__init__ -> ui.core, which imports back into this package, so a top-level
# import here creates a circular-import cycle. The registry is a leaf module
# with no such deps; fetching it on first use (well after all packages have
# finished importing) breaks the cycle.
_REGISTRY_CACHE = None


def _registry():
    """Lazily import and cache the lockable-param lists from the registry."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        from ui.physics_params import (
            LOCKABLE_SIM_PARAMS,
            LOCKABLE_PREF_PARAMS,
            LOCKABLE_PARAM_LABELS,
        )
        _REGISTRY_CACHE = (
            LOCKABLE_SIM_PARAMS, LOCKABLE_PREF_PARAMS, LOCKABLE_PARAM_LABELS)
    return _REGISTRY_CACHE


class ParameterLockService:
    """Tracks locked parameters and provides snapshot/restore for config loads."""

    def __init__(self):
        sim_params, pref_params, _labels = _registry()
        self._locks: dict[str, bool] = {
            p: False for p in sim_params + pref_params}
        self.lock_rule: bool = False
        self.enabled: bool = False

    @property
    def any_locked(self) -> bool:
        return any(self._locks.values()) or self.lock_rule

    def is_locked(self, param_name: str) -> bool:
        if not self.enabled:
            return False
        return self._locks.get(param_name, False)

    def toggle_lock(self, param_name: str):
        if param_name in self._locks:
            self._locks[param_name] = not self._locks[param_name]

    def lock_all(self):
        for key in self._locks:
            self._locks[key] = True
        self.lock_rule = True

    def unlock_all(self):
        for key in self._locks:
            self._locks[key] = False
        self.lock_rule = False

    def reset(self):
        self.unlock_all()
        self.enabled = False

    # --- Snapshot / Restore ---

    def snapshot_locked(self, sim_state, prefs_state) -> dict:
        """Capture current values of all locked parameters before apply_config.

        Returns a dict that should be passed to restore_locked() after apply_config.
        Returns empty dict if master is disabled or nothing is locked.
        """
        if not self.enabled:
            return {}
        sim_params, pref_params, labels = _registry()
        snapshot = {}
        for param_name in sim_params:
            if self.is_locked(param_name):
                snapshot[param_name] = getattr(sim_state, param_name)
                label = labels.get(param_name)
                if label and label in sim_state.slider_ranges:
                    snapshot[f'_range_{param_name}'] = sim_state.slider_ranges[label].copy()
        for param_name in pref_params:
            if self.is_locked(param_name):
                snapshot[param_name] = getattr(prefs_state, param_name)
        return snapshot

    def restore_locked(self, sim_state, prefs_state, snapshot: dict):
        """Re-apply locked parameter values after apply_config."""
        if not snapshot:
            return
        sim_params, pref_params, labels = _registry()
        for param_name in sim_params:
            if param_name in snapshot:
                setattr(sim_state, param_name, snapshot[param_name])
                range_key = f'_range_{param_name}'
                if range_key in snapshot:
                    label = labels.get(param_name)
                    if label:
                        sim_state.slider_ranges[label] = snapshot[range_key]
        for param_name in pref_params:
            if param_name in snapshot:
                setattr(prefs_state, param_name, snapshot[param_name])

    # --- Guard methods ---

    def should_block_rule_push(self) -> bool:
        return self.enabled and self.lock_rule

    # --- UI helpers ---

    def check_alt_click(self) -> bool:
        """Check if Alt+left-click on the last rendered ImGui item. Call after widget."""
        return (self.enabled
                and imgui.is_item_clicked(imgui.MouseButton_.left)
                and imgui.get_io().key_alt)

    def handle_alt_click(self, param_name: str) -> bool:
        """Check for Alt+click on the last widget, toggle lock, return True if intercepted.

        When True is returned, the caller should discard any value change from
        the widget so the alt-click only toggles the lock without affecting the
        control's value.  Call this immediately after the widget.
        """
        if self.check_alt_click():
            self.toggle_lock(param_name)
            return True
        return False

    def begin_combo_alt_click(self, param_name: str) -> bool:
        """Handle alt-click on a begin_combo widget that just opened.

        Call immediately after begin_combo() returns True.  If the combo was
        opened via Alt+click, this closes it immediately and toggles the lock.
        Returns True if the alt-click was intercepted (caller should skip
        rendering combo contents and NOT call end_combo).
        """
        if self.check_alt_click():
            self.toggle_lock(param_name)
            imgui.end_combo()  # close the combo we just opened
            return True
        return False

    def get_display_label(self, param_name: str, base_label: str) -> str:
        """Return label with [L] prefix and ## ID trick if locked."""
        if self.is_locked(param_name):
            return f"[L]{base_label}##{base_label}"
        return base_label

    def push_locked_style(self, param_name: str) -> int:
        """Push red color styling if parameter is locked. Returns colors pushed."""
        if not self.is_locked(param_name):
            return 0
        imgui.push_style_color(imgui.Col_.frame_bg, imgui.ImVec4(0.5, 0.15, 0.15, 0.54))
        imgui.push_style_color(imgui.Col_.frame_bg_hovered, imgui.ImVec4(0.6, 0.2, 0.2, 0.7))
        imgui.push_style_color(imgui.Col_.frame_bg_active, imgui.ImVec4(0.7, 0.25, 0.25, 0.8))
        imgui.push_style_color(imgui.Col_.slider_grab, imgui.ImVec4(0.9, 0.3, 0.3, 1.0))
        imgui.push_style_color(imgui.Col_.slider_grab_active, imgui.ImVec4(1.0, 0.4, 0.4, 1.0))
        imgui.push_style_color(imgui.Col_.check_mark, imgui.ImVec4(1.0, 0.3, 0.3, 1.0))
        return 6

    def pop_locked_style(self, count: int):
        if count > 0:
            imgui.pop_style_color(count)
