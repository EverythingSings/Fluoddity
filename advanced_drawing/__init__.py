"""Legacy force/strafe field persistence (post-cleanup remnant).

The live force/strafe field runtime (GPU processor, brush painting, the
Drawing/Field-loader windows, the "Draw Trail" mouse mode) was removed in the
3D-only cleanup. What remains here are the pure host-side codecs used to
*read* field data persisted by old saves:

- ``field_texture_io``  — encode/decode a float32 field <-> 16-bit PNG (with
  per-channel range metadata) and the polar-image loader.
- ``field_texture_cache`` — LRU cache over ``{config}_fields.png`` files.

These are retained so a future step can load an old config/render-spec that
carried a field, extract a simple description (e.g. the center pixel — many
fields are constant), and reproduce it as a force/strafe effect. Nothing in
the running app consumes a live field texture anymore.
"""
from .field_texture_cache import FieldTextureCache

__all__ = [
    'FieldTextureCache',
]
