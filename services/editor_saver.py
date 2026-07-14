"""
EditorSaver: standalone save/load of non-physics editor state.

Captures everything about the app *except* physics and simulation buffers:
- PreferencesState (renderer/render settings, lighting, bloom, recording,
  generics, window visibility, collapsed-group states, UI interaction prefs)
- imgui window layout / docking (via save_ini_settings_to_memory)

Format: a single JSON file (`<name>.editor.json`) in EditorSaves/.
Also used by RenderSpec as one of its three bundled sub-savers (there the
editor block is embedded in the .frs metadata.json rather than a standalone file).
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from imgui_bundle import imgui

from state.preferences_state import (
    PreferencesState, preferences_from_dict, copy_preferences_into,
)
from utilities.paths import get_editor_saves_dir

EDITOR_SAVE_VERSION = 1


@dataclass
class EditorSave:
    """Non-physics editor state snapshot."""
    version: int = EDITOR_SAVE_VERSION
    preferences: dict = field(default_factory=dict)   # asdict(PreferencesState), nested
    imgui_layout: str = ""                            # save_ini_settings_to_memory()


class EditorSaver:
    """Capture / apply / persist EditorSave snapshots."""

    def create_save(self, prefs: PreferencesState) -> EditorSave:
        """Snapshot preferences + live imgui layout into an EditorSave."""
        return EditorSave(
            version=EDITOR_SAVE_VERSION,
            preferences=asdict(prefs),
            imgui_layout=imgui.save_ini_settings_to_memory() or "",
        )

    def to_dict(self, save: EditorSave) -> dict:
        return {
            'version': save.version,
            'preferences': save.preferences,
            'imgui_layout': save.imgui_layout,
        }

    def from_dict(self, data: dict) -> EditorSave:
        return EditorSave(
            version=data.get('version', EDITOR_SAVE_VERSION),
            preferences=data.get('preferences', {}),
            imgui_layout=data.get('imgui_layout', ''),
        )

    def apply_save(self, save: EditorSave, prefs_target: PreferencesState,
                   apply_visibility: bool = True, apply_layout: bool = True) -> None:
        """Apply an EditorSave onto the live preferences (in place) + imgui layout.

        Args:
            save: the EditorSave to apply
            prefs_target: the live PreferencesState to mutate in place (identity
                preserved so references held elsewhere see the update)
            apply_visibility: if False, keep the current show_*_window flags
                (used by batch/headless render paths so windows aren't toggled)
            apply_layout: if False, skip restoring imgui docking/window layout
        """
        if save.preferences:
            loaded = preferences_from_dict(save.preferences)
            if not apply_visibility:
                # Preserve current window visibility by copying it back onto the
                # freshly-loaded prefs before we push into the live object.
                for fld in type(loaded.ui_windows).__dataclass_fields__:
                    if fld.startswith('show_') and fld.endswith('_window'):
                        setattr(loaded.ui_windows, fld,
                                getattr(prefs_target.ui_windows, fld))
            copy_preferences_into(prefs_target, loaded)

        if apply_layout and save.imgui_layout:
            imgui.load_ini_settings_from_memory(save.imgui_layout)

    def path_for(self, name: str) -> Path:
        """Resolve the .editor.json path a save with this name would use."""
        return get_editor_saves_dir() / f"{name}.editor.json"

    def exists(self, name: str) -> bool:
        """True if an editor save with this name already exists on disk."""
        return self.path_for(name).exists()

    def save_to_file(self, save: EditorSave, path: Path | None = None,
                     name: str = "editor") -> Path:
        """Write an EditorSave to a .editor.json file. Returns the path."""
        if path is None:
            path = self.path_for(name)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(save), indent=2))
        print(f"[EditorSaver] Saved: {path.name}")
        return path

    def load_from_file(self, path: Path | str) -> EditorSave | None:
        """Load an EditorSave from a .editor.json file. None on failure."""
        path = Path(path)
        if not path.exists():
            print(f"[EditorSaver] File not found: {path}")
            return None
        try:
            return self.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[EditorSaver] Failed to load {path}: {e}")
            return None

    def list_available(self) -> list[Path]:
        """List all .editor.json files in the EditorSaves folder."""
        saves_dir = get_editor_saves_dir()
        if not saves_dir.exists():
            return []
        files = [f for f in saves_dir.iterdir()
                 if f.is_file() and f.name.endswith('.editor.json')]
        files.sort(key=lambda p: p.name.lower())
        return files

    def delete(self, path: Path) -> bool:
        """Delete a .editor.json file. Returns True on success."""
        try:
            Path(path).unlink()
            print(f"[EditorSaver] Deleted: {Path(path).name}")
            return True
        except OSError as e:
            print(f"[EditorSaver] Failed to delete {path}: {e}")
            return False
