"""Advanced Drawing module (Step 11 of the modularity refactor).

Bundles the painted/procedural force-strafe field subsystem that feeds the sim:
the GPU field processor, the field-texture persistence handler + cache + IO, and
the two UI windows. Field-override shaders stay in `shaders/field_override/`
(resolved via `get_app_dir()`); this package references them by path.

See `docs/component_inventory.md` -> Modules -> Advanced Drawing / Force-Strafe Fields.
"""
from .processor import AdvancedDrawingProcessor
from .field_handler import FieldHandler, MAX_FIELD_SNAPSHOTS
from .field_texture_cache import FieldTextureCache
from .window import AdvancedDrawingWindowMixin
from .field_loader_window import FieldLoaderWindowMixin

__all__ = [
    'AdvancedDrawingProcessor',
    'FieldHandler',
    'MAX_FIELD_SNAPSHOTS',
    'FieldTextureCache',
    'AdvancedDrawingWindowMixin',
    'FieldLoaderWindowMixin',
]
