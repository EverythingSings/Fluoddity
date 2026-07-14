import numpy as np
import moderngl


class EntityPicker:
    """Handles entity selection from screen coordinates."""

    def __init__(self, entity_buffer: moderngl.Buffer, entity_stride: int):
        """Initialize EntityPicker.

        Args:
            entity_buffer: GPU buffer containing entity data
            entity_stride: Number of floats per entity (e.g., 8 for pos:2 + vel:2 + hue:1 + size:1 + padding:2)
        """
        self.entity_buffer = entity_buffer
        self.entity_stride = entity_stride

    def update_buffer(self, entity_buffer: moderngl.Buffer):
        """Update the entity buffer reference.

        Call this when the buffer is reallocated (e.g., world size change).

        Args:
            entity_buffer: New GPU buffer containing entity data
        """
        self.entity_buffer = entity_buffer

    def get_entity_by_index(self, idx: int, num_cohorts: int = 1,
                            active_count: int = 1) -> tuple[tuple[float, float], float]:
        """Return ((pos_x, pos_y), cohort_value) for a known entity index.

        Used when an external picker (e.g. the OptiX ray) already has the hit
        entity index and only needs the position + cohort, derived the same way
        find_nearest_entity_3d does.
        """
        ent_cache = np.frombuffer(self.entity_buffer.read(), dtype=np.float32)
        base = idx * self.entity_stride
        pos_x = float(ent_cache[base + 0])
        pos_y = float(ent_cache[base + 1])
        cohort_value = float(num_cohorts) * float(idx) / float(max(active_count, 1))
        return ((pos_x, pos_y), cohort_value)

    def find_nearest_entity(self, tex_coords: tuple[float, float], canvas_aspect_ratio: float,
                            num_cohorts: int = 1, active_count: int = 1) -> tuple[int, tuple[float, float], float]:
        """Find the entity closest to given texture coordinates.

        Args:
            tex_coords: (x, y) in texture space where (0,0) is top-left
            canvas_aspect_ratio: Width/height ratio of canvas
            num_cohorts: Number of cohorts (for computing cohort from index)
            active_count: Number of active entities (for computing cohort from index)

        Returns:
            Tuple of (entity_index, (pos_x, pos_y), cohort_value)
            - entity_index: Index of the nearest entity
            - (pos_x, pos_y): World-space position of the entity (in [-1, 1] range)
            - cohort_value: Cohort value computed from index (in [0, num_cohorts) range)
        """
        ent_cache = np.frombuffer(self.entity_buffer.read(), dtype=np.float32)

        # Extract positions (every Nth float starting at 0, 1, 2)
        # Entity structure: px(1) + py(1) + pz(1) + vx(1) + vy(1) + vz(1) + hue(1) + size(1)
        xs = ent_cache[0::self.entity_stride].copy()
        ys = ent_cache[1::self.entity_stride].copy()
        # zs = ent_cache[2::self.entity_stride].copy()  # Available for 3D picking later
        xs *= (canvas_aspect_ratio)**.5
        ys *= (1./canvas_aspect_ratio)**.5
        # Convert from [-1,1] to [0,1] texture space
        xs_tex = xs / 2.0 + 0.5
        ys_tex = ys / 2.0 + 0.5

        # Compute squared distances
        dx = xs_tex - tex_coords[0]
        dy = ys_tex - tex_coords[1]
        distances_sq = dx * dx + dy * dy

        nearest_idx = int(distances_sq.argmin())

        pos_x = float(xs[nearest_idx])  # Already in world space [-1, 1]
        pos_y = float(ys[nearest_idx])
        # Cohort computed from index (no longer stored in entity struct)
        cohort_value = float(num_cohorts) * float(nearest_idx) / float(max(active_count, 1))

        return (nearest_idx, (pos_x, pos_y), cohort_value)

    def find_nearest_entity_3d(self, ray_origin: np.ndarray, ray_direction: np.ndarray,
                                num_cohorts: int = 1, active_count: int = 1) -> tuple[int, tuple[float, float], float, float]:
        """Find the entity closest to a 3D ray (for 3D view picking).

        Args:
            ray_origin: (3,) camera position in world space
            ray_direction: (3,) unit direction vector of the ray
            num_cohorts: Number of cohorts (for computing cohort from index)
            active_count: Number of active entities (for computing cohort from index)

        Returns:
            Tuple of (entity_index, (pos_x, pos_y), cohort_value, depth)
            - entity_index: Index of the nearest entity
            - (pos_x, pos_y): World-space position of the entity (z dropped for downstream compat)
            - cohort_value: Cohort value computed from index
            - depth: Distance along the ray from camera to entity
        """
        ent_cache = np.frombuffer(self.entity_buffer.read(), dtype=np.float32)

        # Extract 3D positions
        xs = ent_cache[0::self.entity_stride]
        ys = ent_cache[1::self.entity_stride]
        zs = ent_cache[2::self.entity_stride]

        # Build (N, 3) positions array and compute vectors from ray origin
        positions = np.column_stack((xs, ys, zs))
        vs = positions - ray_origin  # (N, 3)

        # Scalar projection onto ray direction
        ts = vs @ ray_direction  # (N,)

        # Squared angular distance to ray (screen-space proximity).
        # perpendicular_dist^2 / depth^2 = tan^2(angle) ≈ screen offset^2
        perp_sq = (vs * vs).sum(axis=1) - ts * ts
        # Clamp ts to avoid division by zero for particles near the camera
        ts_safe = np.maximum(ts, 1e-10)
        distances_sq = perp_sq / (ts_safe * ts_safe)

        # Exclude entities behind the camera
        distances_sq[ts <= 0] = np.inf

        nearest_idx = int(distances_sq.argmin())

        pos_x = float(xs[nearest_idx])
        pos_y = float(ys[nearest_idx])
        cohort_value = float(num_cohorts) * float(nearest_idx) / float(max(active_count, 1))
        depth = float(ts[nearest_idx])

        return (nearest_idx, (pos_x, pos_y), cohort_value, depth)
