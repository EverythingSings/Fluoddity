"""Config clipboard state container (Step 9 of the modularity refactor).

Holds the in-memory list of config checkpoints (Ctrl+C) plus the small pieces of
window state (preview index, rename buffer) that used to live directly on the
`UI` object. Moving it here matches every other data container's home in
`state/` and lets the handlers (command_handler, field_handler) reference the
state directly instead of reaching into `self.ui.config_clipboard`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import numpy as np
    from services.config_saver import PhysicsConfig


@dataclass
class ClipboardEntry:
    """One config checkpoint: the config, its display label, and an optional
    field-texture snapshot (np.float32 array, or None if no field data)."""
    config: "PhysicsConfig"
    label: str
    field_snapshot: "Optional[np.ndarray]" = None


@dataclass
class ConfigClipboardState:
    """In-memory config clipboard: checkpoints + window interaction state."""
    entries: list[ClipboardEntry] = field(default_factory=list)
    counter: int = 0  # Global "jersey" counter (00, 01, 02, ...)
    previewing_index: int | None = None
    renaming_index: int | None = None  # Which entry is being renamed
    rename_buffer: str = ""  # Text input buffer for the rename popup

    def add(self, config, filename: str, field_snapshot=None) -> None:
        """Append a config snapshot to the clipboard.

        The label format ``f"{filename}*{NN}"`` must stay stable: callers parse
        it back with ``rsplit("*", 1)`` to recover the original filename.
        """
        label = f"{filename}*{self.counter:02d}"
        self.entries.append(ClipboardEntry(config, label, field_snapshot))
        self.counter += 1
