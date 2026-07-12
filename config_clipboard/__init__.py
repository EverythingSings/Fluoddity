"""Config clipboard module (Step 9 of the modularity refactor).

The Config Clipboard is an in-memory list of config checkpoints (Ctrl+C) with
hover-preview, load, rename, and delete. This package owns its command handlers;
its state lives in `state/config_clipboard_state.py` and its window in
`ui/config_clipboard_window.py`. See `docs/component_inventory.md` -> Modules ->
Config Clipboard.
"""
from .handlers import ConfigClipboardHandler

__all__ = ['ConfigClipboardHandler']
