"""Service package exports.

Keep package-level imports light so report/smoke tooling can import
`services.game_identity` or `services.trial_definitions` without pulling in
editor/runtime dependencies such as NumPy, ImGui, or video helpers.
"""
from __future__ import annotations

from .game_identity import ENGINE_NAME, GAME_SUBTITLE, GAME_TITLE
from .trial_definitions import TRIAL_DEFINITIONS

_LAZY_EXPORTS = {
    "RuleManager": ("rule_manager", "RuleManager"),
    "EntityPicker": ("entity_picker", "EntityPicker"),
    "VideoRecorderService": ("video_recorder", "VideoRecorderService"),
    "ConfigSaver": ("config_saver", "ConfigSaver"),
    "ArrowDebugService": ("arrow_debug_service", "ArrowDebugService"),
    "MultiLoadService": ("multi_load_service", "MultiLoadService"),
    "FieldHandler": ("field_handler", "FieldHandler"),
    "TrialService": ("trial_service", "TrialService"),
}

__all__ = [
    "RuleManager",
    "EntityPicker",
    "VideoRecorderService",
    "ConfigSaver",
    "ArrowDebugService",
    "MultiLoadService",
    "FieldHandler",
    "ENGINE_NAME",
    "GAME_SUBTITLE",
    "GAME_TITLE",
    "TRIAL_DEFINITIONS",
    "TrialService",
]


def __getattr__(name: str):
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(f"{__name__}.{module_name}", fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
