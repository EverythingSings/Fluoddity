"""Parameter Locks module (Step 11 of the modularity refactor).

Freezes selected parameters so they survive config loads (snapshot before
apply_config, restore after). The lockable-param list is derived from the shared
registry in `ui/physics_params.py`. UI call sites use the shared alt-click
wrappers in `widgets.py` instead of open-coding the push-style / label /
handle-alt-click / pop-style dance at every widget.

See `docs/component_inventory.md` -> Modules -> Parameter Lock Service.
"""
# Import widgets FIRST: it has no `ui` dependency, so binding lock_widget/
# lock_begin_combo before service.py triggers `import ui.physics_params` (which
# eagerly runs ui/__init__ -> ui.core -> slider_widgets, and that module does
# `from parameter_locks import lock_widget`). Ordering this way keeps the shared
# wrappers available when the UI mixins load, avoiding a partially-initialized
# circular import.
from .widgets import lock_widget, lock_begin_combo
from .service import ParameterLockService

__all__ = ['ParameterLockService', 'lock_widget', 'lock_begin_combo']
