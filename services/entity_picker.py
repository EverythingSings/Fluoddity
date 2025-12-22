import numpy as np
import moderngl


class EntityPicker:
    """Handles entity selection from screen coordinates.

    Encapsulates the entity buffer structure (12 floats per entity stride).
    """

    ENTITY_STRIDE = 12  # 12 floats per entity: pos(2) + vel(2) + size(1) + padding(3) + color(4)

    def __init__(self, entity_buffer: moderngl.Buffer):
        self.entity_buffer = entity_buffer

    def find_nearest_entity(self, tex_coords: tuple[float, float]) -> int:
        """Find the entity closest to given texture coordinates.

        Args:
            tex_coords: (x, y) in texture space where (0,0) is top-left

        Returns:
            Index of the nearest entity
        """
        ent_cache = np.frombuffer(self.entity_buffer.read(), dtype=np.float32)

        # Extract positions (every 12th float starting at 0 and 1)
        xs = ent_cache[0::self.ENTITY_STRIDE].copy()
        ys = ent_cache[1::self.ENTITY_STRIDE].copy()

        # Convert from [-1,1] to [0,1] texture space
        xs = xs / 2.0 + 0.5
        ys = ys / 2.0 + 0.5

        # Compute squared distances
        dx = xs - tex_coords[0]
        dy = ys - tex_coords[1]
        distances_sq = dx * dx + dy * dy

        return int(distances_sq.argmin())
