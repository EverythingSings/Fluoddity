"""LRU cache for field texture PNG data loaded from disk.

Stores numpy float32 arrays in host memory, pre-resized to the target
GPU texture dimensions. Does NOT preload -- only loads from disk on
demand (when hovering over a config file in the Load menu).
Caches ``None`` results too so we don't re-stat missing files.
"""
from collections import OrderedDict
from pathlib import Path
import numpy as np

from utilities.field_texture_io import load_field_png, _bilinear_resize


class FieldTextureCache:
    """LRU cache mapping (filepath, target_dims) to decoded+resized field data."""

    def __init__(self, max_size: int = 20):
        self._cache: OrderedDict[tuple, np.ndarray | None] = OrderedDict()
        self._max_size = max_size

    def get(self, json_filepath: Path, target_h: int, target_w: int) -> np.ndarray | None:
        """Get field data for a config file, resized to target dimensions.

        Derives the PNG path as ``{stem}_fields.png`` next to the JSON file.
        Returns None if no ``_fields.png`` exists (and caches that result).
        The returned array is guaranteed to match (target_h, target_w, 4).
        """
        key = (str(json_filepath), target_h, target_w)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        # Cache miss -- load from disk
        fields_path = json_filepath.with_name(json_filepath.stem + "_fields.png")
        data = load_field_png(fields_path)

        # Resize if needed
        if data is not None:
            data_h, data_w = data.shape[0], data.shape[1]
            if data_h != target_h or data_w != target_w:
                data = _bilinear_resize(data, target_h, target_w)
            

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = data
        return data

    def invalidate(self, json_filepath: Path) -> None:
        """Remove all entries for a filepath (any target dimensions)."""
        prefix = str(json_filepath)
        keys_to_remove = [k for k in self._cache if k[0] == prefix]
        for k in keys_to_remove:
            del self._cache[k]

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
