"""UI package - ImGui user interface for Fluoddity.

The UI class uses a mixin architecture: each module defines a mixin class,
and the UI class in core.py inherits all of them. This keeps files short
while preserving simple self.* access to shared state.
"""

__all__ = ['UI']


def __getattr__(name):
    if name == 'UI':
        from .core import UI
        return UI
    raise AttributeError(name)
