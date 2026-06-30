"""
RenderSpec: complete snapshot of app state for scheduled video rendering.

A RenderSpec captures everything needed to reproduce an exact simulation state:
physics config, camera, preferences, and GPU buffer snapshots (entities, canvas,
field texture). Saved as a directory containing JSON metadata + compressed numpy
binary data.

File format:
    RenderSpecs/
        MyRender.frs/               # .frs = Fluoddity Render Spec (directory)
            metadata.json           # All scalar/dict state
            entities.npz            # Compressed entity buffer
            canvas.npz              # Compressed 3D canvas textures
            field.npz               # Compressed field texture (optional)
"""
import json
from datetime import datetime
import numpy as np
from dataclasses import dataclass, field
from dataclasses import asdict
from pathlib import Path

from services.config_saver import ConfigSaver, PhysicsConfig
from utilities.paths import get_render_specs_dir

RENDER_SPEC_VERSION = 1


@dataclass
class RenderSpec:
    """Complete specification for a scheduled video render."""
    display_name: str = ""
    physics_config_dict: dict = field(default_factory=dict)
    camera_state: dict = field(default_factory=dict)
    controller_cam_state: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=dict)
    sim_metadata: dict = field(default_factory=dict)
    # Path to the .frs directory on disk (set after save/load)
    dir_path: Path | None = None


class RenderSpecService:
    """Service for capturing, saving, loading, and applying RenderSpec snapshots."""

    def capture_current_state(self, sim, camera, controller_cam, ui_state,
                              config_saver: ConfigSaver, rule_manager,
                              adv_draw_processor, name: str) -> tuple[RenderSpec, dict]:
        """Snapshot all app state + GPU buffers into a RenderSpec.

        Args:
            sim: Sim instance (GPU buffers, frame_count)
            camera: Camera instance (not used directly; state comes from ui_state.camera)
            controller_cam: ControllerCam instance (FPS camera pos/yaw/pitch/fov)
            ui_state: UIState with sim, camera, and preferences
            config_saver: ConfigSaver for creating PhysicsConfig
            rule_manager: RuleManager to get current rule
            adv_draw_processor: AdvancedDrawingProcessor for field texture snapshot
            name: Display name for this render spec

        Returns:
            (spec, gpu_buffers) tuple where gpu_buffers is a dict of numpy arrays
        """
        # 1. Physics config (reuse existing serialization)
        rule = rule_manager.get_current_rule()
        # Include field strengths if field texture exists
        field_strengths = None
        if adv_draw_processor and adv_draw_processor.snapshot_field_data() is not None:
            field_strengths = (
                ui_state.preferences.force_field_strength,
                ui_state.preferences.strafe_field_strength,
            )
        physics_config = config_saver.create_config(ui_state.sim, rule, field_strengths)
        physics_config_dict = physics_config.to_dict()

        # 2. Camera state
        cam = ui_state.camera
        camera_state = {
            'position': cam.position.tolist(),
            'zoom': cam.zoom,
            'cam_brush_mode': cam.cam_brush_mode,
            'render_3d': cam.render_3d,
            'orbit_center': cam.orbit_center.tolist(),
            'orbit_rate': cam.orbit_rate,
            'orbit_angle': cam.orbit_angle,
            'orbit_pitch': cam.orbit_pitch,
            'fov': cam.fov,
            'aperture': cam.aperture,
            'focal_plane_depth': cam.focal_plane_depth,
            'move_speed': cam.move_speed,
            'rotate_speed': cam.rotate_speed,
        }

        # 3. Controller cam state (FPS camera)
        controller_cam_state = {
            'pos': controller_cam.pos.tolist(),
            'yaw': controller_cam.yaw,
            'pitch': controller_cam.pitch,
            'fov': controller_cam.fov,
        }

        # 4. Preferences (full snapshot)
        preferences = asdict(ui_state.preferences)

        # 5. Sim metadata
        sim_metadata = {
            'frame_count': sim.frame_count,
            'can_read_index': sim.can_read_index,
            'entity_count': sim.entity_count,
        }

        spec = RenderSpec(
            display_name=name,
            physics_config_dict=physics_config_dict,
            camera_state=camera_state,
            controller_cam_state=controller_cam_state,
            preferences=preferences,
            sim_metadata=sim_metadata,
        )

        # 6. GPU buffer snapshots
        gpu_buffers = self._read_gpu_buffers(sim, adv_draw_processor)

        return spec, gpu_buffers

    def _read_gpu_buffers(self, sim, adv_draw_processor) -> dict:
        """Read all GPU buffers back to CPU as numpy arrays."""
        buffers = {}

        # Entity buffer (raw bytes → uint8 array for maximal compression)
        buffers['entities'] = np.frombuffer(sim.entities.read(), dtype=np.uint8).copy()

        # 3D canvas texture (packed RGBA16F, only the active read-side)
        read_idx = sim.can_read_index
        buffers['can_packed'] = np.frombuffer(
            sim.can_3d[read_idx].read(), dtype=np.float16).copy()

        # Force/strafe field texture (optional)
        if adv_draw_processor is not None:
            field_data = adv_draw_processor.snapshot_field_data()
            if field_data is not None:
                buffers['field'] = field_data

        return buffers

    def save_to_disk(self, spec: RenderSpec, gpu_buffers: dict,
                     dir_path: Path | None = None) -> Path:
        """Save a RenderSpec to a .frs directory on disk.

        Args:
            spec: The RenderSpec metadata
            gpu_buffers: Dict of numpy arrays from capture_current_state()
            dir_path: Override save location. If None, uses RenderSpecs/{name}.frs

        Returns:
            Path to the saved .frs directory
        """
        if dir_path is None:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            dir_path = get_render_specs_dir() / f"{spec.display_name}_{timestamp}.frs"

        dir_path.mkdir(parents=True, exist_ok=True)

        # Save metadata as JSON
        metadata = {
            'version': RENDER_SPEC_VERSION,
            'display_name': spec.display_name,
            'physics_config': spec.physics_config_dict,
            'camera_state': spec.camera_state,
            'controller_cam_state': spec.controller_cam_state,
            'preferences': spec.preferences,
            'sim_metadata': spec.sim_metadata,
        }
        metadata_path = dir_path / 'metadata.json'
        metadata_path.write_text(json.dumps(metadata, indent=2))

        # Save GPU buffers as compressed numpy archives
        entities_path = dir_path / 'entities.npz'
        np.savez_compressed(str(entities_path), data=gpu_buffers['entities'])

        canvas_path = dir_path / 'canvas.npz'
        np.savez_compressed(str(canvas_path),
                            can_packed=gpu_buffers['can_packed'])

        if 'field' in gpu_buffers:
            field_path = dir_path / 'field.npz'
            np.savez_compressed(str(field_path), data=gpu_buffers['field'])

        # Print compression stats
        raw_entities = gpu_buffers['entities'].nbytes
        raw_canvas = gpu_buffers['can_packed'].nbytes
        comp_entities = entities_path.stat().st_size
        comp_canvas = canvas_path.stat().st_size
        total_raw = raw_entities + raw_canvas
        total_comp = comp_entities + comp_canvas

        print(f"[RenderSpec] Saved: {spec.display_name}")
        print(f"  Entities: {raw_entities / 1e6:.1f} MB -> {comp_entities / 1e6:.1f} MB "
              f"({raw_entities / max(comp_entities, 1):.0f}:1)")
        print(f"  Canvas:   {raw_canvas / 1e6:.1f} MB -> {comp_canvas / 1e6:.1f} MB "
              f"({raw_canvas / max(comp_canvas, 1):.0f}:1)")
        if 'field' in gpu_buffers:
            raw_field = gpu_buffers['field'].nbytes
            comp_field = (dir_path / 'field.npz').stat().st_size
            total_raw += raw_field
            total_comp += comp_field
            print(f"  Field:    {raw_field / 1e6:.1f} MB -> {comp_field / 1e6:.1f} MB "
                  f"({raw_field / max(comp_field, 1):.0f}:1)")
        print(f"  Total:    {total_raw / 1e6:.1f} MB -> {total_comp / 1e6:.1f} MB")

        spec.dir_path = dir_path
        return dir_path

    def load_metadata(self, dir_path: Path) -> RenderSpec | None:
        """Load only metadata from a .frs directory (fast, no GPU buffers).

        Args:
            dir_path: Path to the .frs directory

        Returns:
            RenderSpec with metadata populated, or None if load failed
        """
        metadata_path = dir_path / 'metadata.json'
        if not metadata_path.exists():
            print(f"[RenderSpec] No metadata.json found in {dir_path}")
            return None

        try:
            data = json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"[RenderSpec] Failed to load metadata from {dir_path}: {e}")
            return None

        return RenderSpec(
            display_name=data.get('display_name', dir_path.stem),
            physics_config_dict=data.get('physics_config', {}),
            camera_state=data.get('camera_state', {}),
            controller_cam_state=data.get('controller_cam_state', {}),
            preferences=data.get('preferences', {}),
            sim_metadata=data.get('sim_metadata', {}),
            dir_path=dir_path,
        )

    def load_gpu_buffers(self, dir_path: Path) -> dict | None:
        """Load compressed GPU buffer data from a .frs directory.

        Args:
            dir_path: Path to the .frs directory

        Returns:
            Dict of numpy arrays, or None if load failed
        """
        buffers = {}

        # Entity buffer
        entities_path = dir_path / 'entities.npz'
        if not entities_path.exists():
            print(f"[RenderSpec] No entities.npz found in {dir_path}")
            return None
        try:
            with np.load(str(entities_path)) as data:
                buffers['entities'] = data['data']
        except Exception as e:
            print(f"[RenderSpec] Failed to load entities: {e}")
            return None

        # Canvas textures
        canvas_path = dir_path / 'canvas.npz'
        if not canvas_path.exists():
            print(f"[RenderSpec] No canvas.npz found in {dir_path}")
            return None
        try:
            with np.load(str(canvas_path)) as data:
                if 'can_packed' in data:
                    buffers['can_packed'] = data['can_packed']
                else:
                    # Legacy: load old separate-channel format
                    buffers['can_x'] = data['can_x']
                    buffers['can_y'] = data['can_y']
                    buffers['can_z'] = data['can_z']
        except Exception as e:
            print(f"[RenderSpec] Failed to load canvas: {e}")
            return None

        # Field texture (optional)
        field_path = dir_path / 'field.npz'
        if field_path.exists():
            try:
                with np.load(str(field_path)) as data:
                    buffers['field'] = data['data']
            except Exception as e:
                print(f"[RenderSpec] Warning: Failed to load field texture: {e}")
                # Non-fatal — field is optional

        return buffers

    def apply_state(self, spec: RenderSpec, gpu_buffers: dict,
                    sim, camera, controller_cam, ui_state,
                    config_saver: ConfigSaver, rule_manager,
                    adv_draw_processor) -> None:
        """Apply a RenderSpec's state + GPU buffers to the running app.

        This restores the complete simulation state including physics, camera,
        preferences, and all GPU buffers (entities, canvas, field).

        Args:
            spec: RenderSpec with metadata
            gpu_buffers: Dict of numpy arrays from load_gpu_buffers()
            sim: Sim instance
            camera: Camera instance (for any direct camera state)
            controller_cam: ControllerCam instance
            ui_state: UIState to update
            config_saver: ConfigSaver for applying physics config
            rule_manager: RuleManager for pushing rule
            adv_draw_processor: AdvancedDrawingProcessor for field texture
        """
        # 1. Apply physics config (includes rule)
        physics_config = PhysicsConfig.from_dict(spec.physics_config_dict)
        rule = config_saver.apply_config(physics_config, ui_state.sim)
        rule_manager.push_rule(rule, ui_state.sim.rule_seed)
        sim.apply_rule(rule)

        # 2. Apply camera state
        cam_data = spec.camera_state
        if cam_data:
            ui_state.camera.position[:] = cam_data.get('position', [0.0, 0.0])
            ui_state.camera.zoom = cam_data.get('zoom', 1.0)
            ui_state.camera.cam_brush_mode = cam_data.get('cam_brush_mode', True)
            ui_state.camera.render_3d = cam_data.get('render_3d', True)
            ui_state.camera.orbit_center[:] = cam_data.get('orbit_center', [0.0, 0.0, 0.0])
            ui_state.camera.orbit_rate = cam_data.get('orbit_rate', 0.0)
            ui_state.camera.orbit_angle = cam_data.get('orbit_angle', 0.0)
            ui_state.camera.orbit_pitch = cam_data.get('orbit_pitch', 0.0)
            ui_state.camera.fov = cam_data.get('fov', 50.0)
            ui_state.camera.aperture = cam_data.get('aperture', 0.0)
            ui_state.camera.focal_plane_depth = cam_data.get('focal_plane_depth', 5.0)
            ui_state.camera.move_speed = cam_data.get('move_speed', 2.0)
            ui_state.camera.rotate_speed = cam_data.get('rotate_speed', 2.0)

        # 3. Apply controller cam state (FPS camera)
        ccam_data = spec.controller_cam_state
        if ccam_data and controller_cam is not None:
            controller_cam.pos[:] = ccam_data.get('pos', [0.0, 0.0, -3.0])
            controller_cam.yaw = ccam_data.get('yaw', 0.0)
            controller_cam.pitch = ccam_data.get('pitch', 0.0)
            controller_cam.fov = ccam_data.get('fov', 50.0)
            controller_cam._update_vectors()

        # 4. Apply preferences (skip window visibility flags — don't close/open windows)
        prefs_data = spec.preferences
        if prefs_data:
            from state.preferences_state import PreferencesState
            valid_fields = set(PreferencesState.__dataclass_fields__.keys())
            for key, value in prefs_data.items():
                if key.startswith('show_') and key.endswith('_window'):
                    continue  # Don't override which windows are open
                if key in valid_fields and hasattr(ui_state.preferences, key):
                    setattr(ui_state.preferences, key, value)

        # 5. Apply sim metadata
        sim_metadata = spec.sim_metadata
        if sim_metadata:
            sim.frame_count = sim_metadata.get('frame_count', 0)
            sim.can_read_index = sim_metadata.get('can_read_index', 0)

        # 6. Restore GPU buffers
        # Entity buffer
        if 'entities' in gpu_buffers:
            sim.entities.write(gpu_buffers['entities'].tobytes())

        # Canvas 3D texture (packed RGBA16F) — write to BOTH double-buffer textures
        # to prevent stale data in the non-active buffer from corrupting the next swap
        if 'can_packed' in gpu_buffers:
            can_bytes = gpu_buffers['can_packed'].tobytes()
            for i in range(2):
                sim.can_3d[i].write(can_bytes)
        elif 'can_x' in gpu_buffers:
            # Legacy support: convert old separate R32F channels to packed RGBA16F
            can_x = gpu_buffers['can_x'].astype(np.float16)
            can_y = gpu_buffers['can_y'].astype(np.float16)
            can_z = gpu_buffers['can_z'].astype(np.float16)
            alpha = np.zeros_like(can_x)
            packed = np.stack([can_x, can_y, can_z, alpha], axis=-1).flatten()
            can_bytes = packed.tobytes()
            for i in range(2):
                sim.can_3d[i].write(can_bytes)

        # Force/strafe field texture (optional)
        if 'field' in gpu_buffers and adv_draw_processor is not None:
            adv_draw_processor.write_field_data(gpu_buffers['field'])
        elif adv_draw_processor is not None and adv_draw_processor.field_texture is not None:
            # No field in render spec — clear existing field to match saved state
            adv_draw_processor.clear_fields()

    def list_available_specs(self) -> list[Path]:
        """List all .frs directories in the RenderSpecs folder.

        Returns:
            Sorted list of Path objects to .frs directories
        """
        specs_dir = get_render_specs_dir()
        if not specs_dir.exists():
            return []
        dirs = [d for d in specs_dir.iterdir()
                if d.is_dir() and d.suffix == '.frs']
        dirs.sort(key=lambda p: p.name.lower())
        return dirs
