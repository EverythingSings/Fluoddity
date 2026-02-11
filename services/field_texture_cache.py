"""LRU cache for field texture PNG data loaded from disk.

Stores numpy float32 arrays in host memory. Does NOT preload -- only
loads from disk on demand (when hovering over a config file in the
Load menu). Caches ``None`` results too so we don't re-stat missing files.
"""
from collections import OrderedDict
from pathlib import Path
import numpy as np

from utilities.field_texture_io import load_field_png


class FieldTextureCache:
    """LRU cache mapping JSON config filepaths to decoded field data."""

    def __init__(self, max_size: int = 20):
        self._cache: OrderedDict[str, np.ndarray | None] = OrderedDict()
        self._max_size = max_size

    def get(self, json_filepath: Path) -> np.ndarray | None:
        """Get field data for a config file. Loads from disk on cache miss.

        Derives the PNG path as ``{stem}_fields.png`` next to the JSON file.
        Returns None if no ``_fields.png`` exists (and caches that result).
        """
        key = str(json_filepath)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        # Cache miss -- load from disk
        fields_path = json_filepath.with_name(json_filepath.stem + "_fields.png")
        data = load_field_png(fields_path)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = data
        return data

    def invalidate(self, json_filepath: Path) -> None:
        """Remove a specific entry (e.g. after saving a new version)."""
        self._cache.pop(str(json_filepath), None)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()
