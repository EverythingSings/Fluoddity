"""Viewer package (Step 8 of the modularity refactor).

The Viewer is the always-displayed ImGui window that shows the active
renderer's finished frame. It is the single *display* sink for renderer
output, parallel to the video recorder (the *file* sink). See
`docs/component_inventory.md` -> Target-State Directives -> Viewer.
"""
from .viewer import Viewer

__all__ = ['Viewer']
