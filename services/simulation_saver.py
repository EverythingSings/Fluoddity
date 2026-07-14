"""
SimulationSaver: standalone save/load of GPU simulation buffers.

Dumps the raw simulation state — the entity SSBO and the packed 3D canvas
texture — to a compressed directory, independent of physics/editor settings.
Also used by RenderSpec as one of its three bundled sub-savers.

File format:
    SimulationSaves/
        MyDump.fsim/                # .fsim = Fluoddity Simulation state (directory)
            metadata.json           # version + sim_metadata (frame_count, etc.)
            entities.npz            # Compressed entity buffer (raw uint8 bytes)
            canvas.npz              # Compressed packed RGBA16F 3D canvas texture
"""
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from utilities.paths import get_simulation_saves_dir

SIM_STATE_VERSION = 1


class SimulationSaver:
    """Read/write the entity + canvas GPU buffers to compressed numpy archives."""

    # --- GPU <-> CPU ------------------------------------------------------

    def read_buffers(self, sim) -> dict:
        """Read the entity + canvas GPU buffers back to CPU as numpy arrays."""
        buffers = {}

        # Entity buffer (raw bytes -> uint8 array for maximal compression)
        buffers['entities'] = np.frombuffer(sim.entities.read(), dtype=np.uint8).copy()

        # 3D canvas texture (packed RGBA16F, only the active read-side)
        read_idx = sim.can_read_index
        buffers['can_packed'] = np.frombuffer(
            sim.can_3d[read_idx].read(), dtype=np.float16).copy()

        return buffers

    def sim_metadata(self, sim) -> dict:
        """Snapshot the small scalar sim state that pairs with the buffers."""
        return {
            'frame_count': sim.frame_count,
            'can_read_index': sim.can_read_index,
            'entity_count': sim.entity_count,
        }

    def write_buffers(self, sim, buffers: dict, sim_metadata: dict | None,
                      rule=None) -> bool:
        """Write buffers back into the running sim, reallocating if world size changed.

        Args:
            sim: Sim instance
            buffers: dict from read_buffers()/load_from_disk() (entities + can_packed,
                or legacy can_x/can_y/can_z)
            sim_metadata: {frame_count, can_read_index, entity_count} or None
            rule: current rule to re-push if shaders are recompiled (optional)

        Returns:
            True if entity_count or canvas_resolution changed (buffers reallocated).
        """
        meta = sim_metadata or {}
        spec_entity_count = meta.get('entity_count', sim.entity_count)
        # canvas_resolution isn't stored in sim_metadata; caller may pass it via
        # the metadata dict under 'canvas_resolution', else keep the live value.
        spec_canvas_res = meta.get('canvas_resolution', sim.canvas_resolution)
        world_size_changed = False

        if spec_entity_count != sim.entity_count or spec_canvas_res != sim.canvas_resolution:
            print(f"[SimulationSaver] World size change: entities "
                  f"{sim.entity_count}->{spec_entity_count}, "
                  f"canvas {sim.canvas_resolution}->{spec_canvas_res}")
            sim._entity_count = spec_entity_count
            sim.canvas_resolution = spec_canvas_res
            sim.setup_simulation_state()  # Reallocate entity buffer + canvas textures
            sim.setup_shaders()           # Recompile with new ENTITY_COUNT #define
            if rule is not None:
                sim.apply_rule(rule)      # Re-push rule to new shader program
            world_size_changed = True

        # Apply sim metadata (frame counter + read index)
        if meta:
            sim.frame_count = meta.get('frame_count', 0)
            sim.can_read_index = meta.get('can_read_index', 0)

        # Entity buffer
        if 'entities' in buffers:
            sim.entities.write(buffers['entities'].tobytes())

        # Canvas 3D texture (packed RGBA16F) — write to BOTH double-buffer textures
        # to prevent stale data in the non-active buffer from corrupting the next swap.
        if 'can_packed' in buffers:
            can_bytes = buffers['can_packed'].tobytes()
            for i in range(2):
                sim.can_3d[i].write(can_bytes)
        elif 'can_x' in buffers:
            # Legacy support: convert old separate R32F channels to packed RGBA16F
            can_x = buffers['can_x'].astype(np.float16)
            can_y = buffers['can_y'].astype(np.float16)
            can_z = buffers['can_z'].astype(np.float16)
            alpha = np.zeros_like(can_x)
            packed = np.stack([can_x, can_y, can_z, alpha], axis=-1).flatten()
            can_bytes = packed.tobytes()
            for i in range(2):
                sim.can_3d[i].write(can_bytes)

        return world_size_changed

    # --- disk I/O ---------------------------------------------------------

    def save_to_disk(self, buffers: dict, sim_metadata: dict,
                     dir_path: Path | None = None, name: str = "simulation") -> Path:
        """Save buffers + metadata to a .fsim directory. Returns the directory path."""
        if dir_path is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dir_path = get_simulation_saves_dir() / f"{name}_{timestamp}.fsim"

        dir_path.mkdir(parents=True, exist_ok=True)

        metadata = {
            'version': SIM_STATE_VERSION,
            'sim_metadata': sim_metadata,
        }
        (dir_path / 'metadata.json').write_text(json.dumps(metadata, indent=2))

        self.save_buffers(buffers, dir_path)

        raw_entities = buffers['entities'].nbytes
        raw_canvas = buffers['can_packed'].nbytes
        comp_entities = (dir_path / 'entities.npz').stat().st_size
        comp_canvas = (dir_path / 'canvas.npz').stat().st_size
        print(f"[SimulationSaver] Saved: {dir_path.name}")
        print(f"  Entities: {raw_entities / 1e6:.1f} MB -> {comp_entities / 1e6:.1f} MB")
        print(f"  Canvas:   {raw_canvas / 1e6:.1f} MB -> {comp_canvas / 1e6:.1f} MB")
        return dir_path

    def save_buffers(self, buffers: dict, dir_path: Path) -> None:
        """Write entities.npz + canvas.npz into an existing directory.

        Used both by save_to_disk and by RenderSpec (which owns metadata.json).
        """
        np.savez_compressed(str(dir_path / 'entities.npz'), data=buffers['entities'])
        np.savez_compressed(str(dir_path / 'canvas.npz'),
                            can_packed=buffers['can_packed'])

    def load_buffers(self, dir_path: Path) -> dict | None:
        """Load entities.npz + canvas.npz from a directory. None on failure."""
        buffers = {}

        entities_path = dir_path / 'entities.npz'
        if not entities_path.exists():
            print(f"[SimulationSaver] No entities.npz found in {dir_path}")
            return None
        try:
            with np.load(str(entities_path)) as data:
                buffers['entities'] = data['data']
        except Exception as e:
            print(f"[SimulationSaver] Failed to load entities: {e}")
            return None

        canvas_path = dir_path / 'canvas.npz'
        if not canvas_path.exists():
            print(f"[SimulationSaver] No canvas.npz found in {dir_path}")
            return None
        try:
            with np.load(str(canvas_path)) as data:
                if 'can_packed' in data:
                    buffers['can_packed'] = data['can_packed']
                else:
                    # Legacy: old separate-channel format
                    buffers['can_x'] = data['can_x']
                    buffers['can_y'] = data['can_y']
                    buffers['can_z'] = data['can_z']
        except Exception as e:
            print(f"[SimulationSaver] Failed to load canvas: {e}")
            return None

        return buffers

    def load_from_disk(self, dir_path: Path) -> tuple[dict, dict] | None:
        """Load (buffers, sim_metadata) from a .fsim directory. None on failure."""
        buffers = self.load_buffers(dir_path)
        if buffers is None:
            return None
        meta_path = dir_path / 'metadata.json'
        sim_metadata = {}
        if meta_path.exists():
            try:
                sim_metadata = json.loads(meta_path.read_text()).get('sim_metadata', {})
            except (json.JSONDecodeError, OSError) as e:
                print(f"[SimulationSaver] Failed to load metadata: {e}")
        return buffers, sim_metadata

    def list_available(self) -> list[Path]:
        """List all .fsim directories in the SimulationSaves folder."""
        saves_dir = get_simulation_saves_dir()
        if not saves_dir.exists():
            return []
        dirs = [d for d in saves_dir.iterdir()
                if d.is_dir() and d.suffix == '.fsim']
        dirs.sort(key=lambda p: p.name.lower())
        return dirs
