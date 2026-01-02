"""
ConfigSaver service for saving/loading physics configurations.

Handles serialization of physics parameters + rule data to shareable strings.
"""
import base64
import zlib
import struct
import numpy as np
from dataclasses import dataclass, fields
from state import SimState


# Physics parameter names in order (for serialization)
PHYSICS_PARAMS = [
    'AXIAL_FORCE', 'LATERAL_FORCE', 'SENSOR_GAIN', 'MUTATION_SCALE',
    'DRAG', 'STRAFE_POWER', 'SENSOR_ANGLE', 'GLOBAL_FORCE_MULT',
    'SENSOR_DISTANCE', 'TRAIL_PERSISTENCE'
]

# Version byte for future compatibility
# Version 1: Original format (10 floats + 80 floats = 360 bytes)
# Version 2: Adds DISABLE_SYMMETRY and ABSOLUTE_ORIENTATION booleans (362 bytes)
# Version 3: Adds boundary_conditions, initial_conditions, num_cohorts (362 + 3*4 = 374 bytes)
# Version 4: Adds rule_seed float (374 + 4 = 378 bytes)
# Version 5: Adds appearance settings + parameter sweep data (22-byte appearance, variable length)
# Version 6: Adds emboss_mode to appearance settings (26-byte appearance, variable length)
CONFIG_VERSION = 6

# Default rule_seed for backward compatibility (fixed value for reproducibility)
DEFAULT_RULE_SEED = 0.42


@dataclass
class PhysicsConfig:
    """Complete physics configuration: parameters + rule."""
    # Physics parameters
    axial_force: float
    lateral_force: float
    sensor_gain: float
    mutation_scale: float
    drag: float
    strafe_power: float
    sensor_angle: float
    global_force_mult: float
    sensor_distance: float
    trail_persistence: float
    # Extra options (version 2+)
    disable_symmetry: bool = False
    absolute_orientation: bool = False
    # Simulation settings (version 3+)
    boundary_conditions: int = 0  # 0=Bounce, 1=Reset, 2=Wrap
    initial_conditions: int = 0   # 0=Grid, 1=Random, 2=Ring
    num_cohorts: int = 64         # 1-144
    # Rule seed (version 4+)
    rule_seed: float = DEFAULT_RULE_SEED  # Seed for procedural rule generation
    # Rule data (10 centers * 8 floats = 80 floats)
    rule: np.ndarray = None  # shape (10, 8)

    # Appearance settings (version 5+)
    # Note: brightness is kept in format for backward compat but not used (now in preferences)
    brightness: float = 1.0  # Placeholder for backward compat, always 1.0
    ink_weight: float = 1.0  # Watercolor mode: controls optical density in exp()
    hue_sensitivity: float = 0.5
    color_by_cohort: bool = True  # Default True so old saves use cohort coloring
    watercolor_mode: bool = False
    emboss_mode: int = 0  # 0=Off, 1=Canvas (Trails), 2=Brush (Particles)
    emboss_intensity: float = 0.5
    emboss_smoothness: float = 0.1

    # Parameter sweep settings (version 5+)
    parameter_sweeps_enabled: bool = False
    # Active sweeps: (param_name, direction, cur_min, cur_max) or None
    x_sweep_data: tuple | None = None
    y_sweep_data: tuple | None = None
    cohort_sweep_data: tuple | None = None

    def to_bytes(self, version: int = 5) -> bytes:
        """Serialize config to bytes."""
        # Pack physics params as 10 floats
        physics_bytes = struct.pack(
            '10f',
            self.axial_force, self.lateral_force, self.sensor_gain,
            self.mutation_scale, self.drag, self.strafe_power,
            self.sensor_angle, self.global_force_mult,
            self.sensor_distance, self.trail_persistence
        )
        # Flatten and pack rule as 80 floats
        rule_flat = self.rule.flatten().astype(np.float32)
        rule_bytes = rule_flat.tobytes()

        # Version 1: just physics + rule
        if version == 1:
            return physics_bytes + rule_bytes

        # Version 2: add booleans
        bool_bytes = struct.pack('??', self.disable_symmetry, self.absolute_orientation)
        if version == 2:
            return physics_bytes + rule_bytes + bool_bytes

        # Version 3: add simulation settings (3 ints)
        sim_bytes = struct.pack('3i', self.boundary_conditions, self.initial_conditions, self.num_cohorts)
        if version == 3:
            return physics_bytes + rule_bytes + bool_bytes + sim_bytes

        # Version 4: add rule_seed (1 float)
        seed_bytes = struct.pack('f', self.rule_seed)
        if version == 4:
            return physics_bytes + rule_bytes + bool_bytes + sim_bytes + seed_bytes

        # Version 5: 22-byte appearance format without emboss_mode
        # Version 6: 26-byte appearance format with emboss_mode
        if version >= 6:
            # Use little-endian format '<fff??ffi' (26 bytes)
            appearance_bytes = struct.pack(
                '<fff??ffi',
                self.brightness, self.ink_weight, self.hue_sensitivity,
                self.color_by_cohort, self.watercolor_mode,
                self.emboss_intensity, self.emboss_smoothness, self.emboss_mode
            )
        else:
            # Version 5: Use little-endian format '<fff??ff' (22 bytes)
            appearance_bytes = struct.pack(
                '<fff??ff',
                self.brightness, self.ink_weight, self.hue_sensitivity,
                self.color_by_cohort, self.watercolor_mode,
                self.emboss_intensity, self.emboss_smoothness
            )
        sweep_enabled_bytes = struct.pack('?', self.parameter_sweeps_enabled)
        sweep_bytes = (
            self._encode_sweep(self.x_sweep_data) +
            self._encode_sweep(self.y_sweep_data) +
            self._encode_sweep(self.cohort_sweep_data)
        )
        return physics_bytes + rule_bytes + bool_bytes + sim_bytes + seed_bytes + appearance_bytes + sweep_enabled_bytes + sweep_bytes

    def _encode_sweep(self, sweep: tuple | None) -> bytes:
        """Encode a single sweep as bytes."""
        if sweep is None:
            return struct.pack('B', 0)  # 0 = no sweep
        param_name, direction, cur_min, cur_max = sweep
        name_bytes = param_name.encode('utf-8')
        return struct.pack('B', len(name_bytes)) + name_bytes + struct.pack('3f', direction, cur_min, cur_max)

    @classmethod
    def _decode_sweep(cls, data: bytes, offset: int) -> tuple[tuple | None, int]:
        """Decode a single sweep from bytes. Returns (sweep_data, new_offset)."""
        name_len = struct.unpack('B', data[offset:offset + 1])[0]
        offset += 1
        if name_len == 0:
            return None, offset
        param_name = data[offset:offset + name_len].decode('utf-8')
        offset += name_len
        direction, cur_min, cur_max = struct.unpack('3f', data[offset:offset + 12])
        offset += 12
        return (param_name, direction, cur_min, cur_max), offset

    @classmethod
    def from_bytes(cls, data: bytes, version: int = 5) -> 'PhysicsConfig':
        """Deserialize config from bytes. Supports versions 1-6."""
        # Unpack physics params (10 floats = 40 bytes)
        physics = struct.unpack('10f', data[:40])
        # Unpack rule (80 floats = 320 bytes)
        rule_data = np.frombuffer(data[40:360], dtype=np.float32)
        rule = rule_data.reshape(10, 8)

        # Default values for backward compatibility
        disable_symmetry = False
        absolute_orientation = False
        boundary_conditions = 0  # Bounce
        initial_conditions = 0   # Grid
        num_cohorts = 64
        rule_seed = DEFAULT_RULE_SEED  # Fixed default for reproducibility

        # Version 5 defaults (color_by_cohort=True so old saves use cohort coloring)
        brightness = 1.0
        ink_weight = 1.0
        hue_sensitivity = 0.5
        color_by_cohort = True
        watercolor_mode = False
        emboss_mode = 0  # 0=Off, 1=Canvas, 2=Brush
        emboss_intensity = 0.5
        emboss_smoothness = 0.1
        parameter_sweeps_enabled = False
        x_sweep_data = None
        y_sweep_data = None
        cohort_sweep_data = None

        # Version 2+: check if we have extra boolean data
        if len(data) >= 362:
            disable_symmetry, absolute_orientation = struct.unpack('??', data[360:362])

        # Version 3+: check if we have simulation settings
        if len(data) >= 374:
            boundary_conditions, initial_conditions, num_cohorts = struct.unpack('3i', data[362:374])

        # Version 4+: check if we have rule_seed
        if len(data) >= 378:
            rule_seed, = struct.unpack('f', data[374:378])

        # Version 5+: check if we have appearance and sweep data
        # Version 6+: 26-byte appearance format with emboss_mode (fff??ffi)
        # Version 5: 22-byte appearance format without emboss_mode (fff??ff)
        if version >= 6 and len(data) >= 405:  # 378 + 26 (appearance) + 1 (sweep enabled)
            brightness, ink_weight, hue_sensitivity, color_by_cohort, watercolor_mode, \
                emboss_intensity, emboss_smoothness, emboss_mode = struct.unpack('<fff??ffi', data[378:404])
            parameter_sweeps_enabled, = struct.unpack('?', data[404:405])
            # Decode sweeps (variable length)
            offset = 405
            x_sweep_data, offset = cls._decode_sweep(data, offset)
            y_sweep_data, offset = cls._decode_sweep(data, offset)
            cohort_sweep_data, offset = cls._decode_sweep(data, offset)
        elif len(data) >= 401:  # Version 5 format: 22 bytes (fff??ff) without emboss_mode
            brightness, ink_weight, hue_sensitivity, color_by_cohort, watercolor_mode, \
                emboss_intensity, emboss_smoothness = struct.unpack('<fff??ff', data[378:400])
            emboss_mode = 0  # Default for version 5
            parameter_sweeps_enabled, = struct.unpack('?', data[400:401])
            # Decode sweeps (variable length)
            offset = 401
            x_sweep_data, offset = cls._decode_sweep(data, offset)
            y_sweep_data, offset = cls._decode_sweep(data, offset)
            cohort_sweep_data, offset = cls._decode_sweep(data, offset)
        elif len(data) >= 397:  # Very old format: 18 bytes (ff??ff) without ink_weight or emboss_mode
            brightness, hue_sensitivity, color_by_cohort, watercolor_mode, \
                emboss_intensity, emboss_smoothness = struct.unpack('<ff??ff', data[378:396])
            ink_weight = 1.0  # Default for old format
            emboss_mode = 0  # Default for old format
            parameter_sweeps_enabled, = struct.unpack('?', data[396:397])
            # Decode sweeps (variable length)
            offset = 397
            x_sweep_data, offset = cls._decode_sweep(data, offset)
            y_sweep_data, offset = cls._decode_sweep(data, offset)
            cohort_sweep_data, offset = cls._decode_sweep(data, offset)

        return cls(
            axial_force=physics[0],
            lateral_force=physics[1],
            sensor_gain=physics[2],
            mutation_scale=physics[3],
            drag=physics[4],
            strafe_power=physics[5],
            sensor_angle=physics[6],
            global_force_mult=physics[7],
            sensor_distance=physics[8],
            trail_persistence=physics[9],
            disable_symmetry=disable_symmetry,
            absolute_orientation=absolute_orientation,
            boundary_conditions=boundary_conditions,
            initial_conditions=initial_conditions,
            num_cohorts=num_cohorts,
            rule_seed=rule_seed,
            rule=rule.copy(),
            brightness=brightness,
            ink_weight=ink_weight,
            hue_sensitivity=hue_sensitivity,
            color_by_cohort=color_by_cohort,
            watercolor_mode=watercolor_mode,
            emboss_mode=emboss_mode,
            emboss_intensity=emboss_intensity,
            emboss_smoothness=emboss_smoothness,
            parameter_sweeps_enabled=parameter_sweeps_enabled,
            x_sweep_data=x_sweep_data,
            y_sweep_data=y_sweep_data,
            cohort_sweep_data=cohort_sweep_data
        )


class ConfigSaver:
    """Service for saving/loading physics configurations."""

    def __init__(self):
        pass

    def _extract_active_sweep(self, sweeps: dict[str, float], slider_ranges: dict[str, list[float]],
                               param_to_label: dict[str, str]) -> tuple | None:
        """Extract active sweep data (param_name, direction, cur_min, cur_max) or None."""
        for param_name, direction in sweeps.items():
            if direction != 0.0:
                # Found an active sweep - get its slider range
                label = param_to_label.get(param_name, param_name)
                if label in slider_ranges:
                    cur_min, cur_max = slider_ranges[label][:2]
                else:
                    # Use defaults if no custom range
                    cur_min, cur_max = 0.0, 1.0
                return (param_name, direction, cur_min, cur_max)
        return None

    def create_config(self, sim_state: SimState, rule: np.ndarray | None,
                      slider_ranges: dict[str, list[float]] | None = None) -> PhysicsConfig:
        """
        Create a PhysicsConfig from current state.

        Args:
            sim_state: Current simulation state with physics parameters
            rule: Current rule from RuleManager (None = use zeros)
            slider_ranges: Optional slider range customizations for sweep data
        """
        # Use zero rule if none provided
        if rule is None:
            rule = np.zeros((10, 8), dtype=np.float32)

        # Map parameter names to slider labels
        param_to_label = {
            'AXIAL_FORCE': 'Axial Force',
            'LATERAL_FORCE': 'Lateral Force',
            'SENSOR_GAIN': 'Sensor Gain',
            'MUTATION_SCALE': 'Mutation Scale',
            'DRAG': 'Drag',
            'STRAFE_POWER': 'Strafe Power',
            'SENSOR_ANGLE': 'Sensor Angle',
            'GLOBAL_FORCE_MULT': 'Global Force Mult',
            'SENSOR_DISTANCE': 'Sensor Distance',
            'TRAIL_PERSISTENCE': 'Trail Persistence',
        }

        # Extract active sweeps
        ranges = slider_ranges or {}
        x_sweep = self._extract_active_sweep(sim_state.x_sweeps, ranges, param_to_label)
        y_sweep = self._extract_active_sweep(sim_state.y_sweeps, ranges, param_to_label)
        cohort_sweep = self._extract_active_sweep(sim_state.cohort_sweeps, ranges, param_to_label)

        return PhysicsConfig(
            axial_force=sim_state.AXIAL_FORCE,
            lateral_force=sim_state.LATERAL_FORCE,
            sensor_gain=sim_state.SENSOR_GAIN,
            mutation_scale=sim_state.MUTATION_SCALE,
            drag=sim_state.DRAG,
            strafe_power=sim_state.STRAFE_POWER,
            sensor_angle=sim_state.SENSOR_ANGLE,
            global_force_mult=sim_state.GLOBAL_FORCE_MULT,
            sensor_distance=sim_state.SENSOR_DISTANCE,
            trail_persistence=sim_state.TRAIL_PERSISTENCE,
            disable_symmetry=sim_state.DISABLE_SYMMETRY,
            absolute_orientation=sim_state.ABSOLUTE_ORIENTATION,
            boundary_conditions=sim_state.boundary_conditions,
            initial_conditions=sim_state.initial_conditions,
            num_cohorts=sim_state.num_cohorts,
            rule_seed=sim_state.rule_seed,
            rule=rule.copy(),
            brightness=1.0,  # Placeholder for backward compat (brightness now in preferences)
            ink_weight=sim_state.ink_weight,
            hue_sensitivity=sim_state.hue_sensitivity,
            color_by_cohort=sim_state.color_by_cohort,
            watercolor_mode=sim_state.watercolor_mode,
            emboss_mode=sim_state.emboss_mode,
            emboss_intensity=sim_state.emboss_intensity,
            emboss_smoothness=sim_state.emboss_smoothness,
            parameter_sweeps_enabled=sim_state.parameter_sweeps_enabled,
            x_sweep_data=x_sweep,
            y_sweep_data=y_sweep,
            cohort_sweep_data=cohort_sweep
        )

    def _apply_sweep_to_state(self, sweep_data: tuple | None, sweeps_dict: dict[str, float],
                               slider_ranges: dict[str, list[float]], param_to_label: dict[str, str]) -> None:
        """Apply sweep data to state, updating sweep dict and slider ranges."""
        # Clear all sweeps first
        for key in sweeps_dict:
            sweeps_dict[key] = 0.0

        if sweep_data is not None:
            param_name, direction, cur_min, cur_max = sweep_data
            if param_name in sweeps_dict:
                sweeps_dict[param_name] = direction
                # Update slider range for this parameter
                label = param_to_label.get(param_name, param_name)
                if label in slider_ranges:
                    # Keep default min/max, update current min/max
                    slider_ranges[label][0] = cur_min
                    slider_ranges[label][1] = cur_max
                else:
                    # Create new range entry
                    slider_ranges[label] = [cur_min, cur_max, cur_min, cur_max]

    def apply_config(self, config: PhysicsConfig, sim_state: SimState,
                     slider_ranges: dict[str, list[float]] | None = None) -> np.ndarray:
        """
        Apply a PhysicsConfig to the simulation state.

        Args:
            config: The config to apply
            sim_state: SimState to update (modified in place)
            slider_ranges: Optional slider ranges to update with sweep ranges

        Returns:
            The rule to push to RuleManager
        """
        sim_state.AXIAL_FORCE = config.axial_force
        sim_state.LATERAL_FORCE = config.lateral_force
        sim_state.SENSOR_GAIN = config.sensor_gain
        sim_state.MUTATION_SCALE = config.mutation_scale
        sim_state.DRAG = config.drag
        sim_state.STRAFE_POWER = config.strafe_power
        sim_state.SENSOR_ANGLE = config.sensor_angle
        sim_state.GLOBAL_FORCE_MULT = config.global_force_mult
        sim_state.SENSOR_DISTANCE = config.sensor_distance
        sim_state.TRAIL_PERSISTENCE = config.trail_persistence
        sim_state.DISABLE_SYMMETRY = config.disable_symmetry
        sim_state.ABSOLUTE_ORIENTATION = config.absolute_orientation
        sim_state.boundary_conditions = config.boundary_conditions
        sim_state.initial_conditions = config.initial_conditions
        sim_state.num_cohorts = config.num_cohorts
        sim_state.rule_seed = config.rule_seed

        # Apply appearance settings (brightness not applied - it's now in preferences)
        sim_state.ink_weight = config.ink_weight
        sim_state.hue_sensitivity = config.hue_sensitivity
        sim_state.color_by_cohort = config.color_by_cohort
        sim_state.watercolor_mode = config.watercolor_mode
        sim_state.emboss_mode = config.emboss_mode
        sim_state.emboss_intensity = config.emboss_intensity
        sim_state.emboss_smoothness = config.emboss_smoothness

        # Apply sweep settings
        sim_state.parameter_sweeps_enabled = config.parameter_sweeps_enabled

        # Map parameter names to slider labels
        param_to_label = {
            'AXIAL_FORCE': 'Axial Force',
            'LATERAL_FORCE': 'Lateral Force',
            'SENSOR_GAIN': 'Sensor Gain',
            'MUTATION_SCALE': 'Mutation Scale',
            'DRAG': 'Drag',
            'STRAFE_POWER': 'Strafe Power',
            'SENSOR_ANGLE': 'Sensor Angle',
            'GLOBAL_FORCE_MULT': 'Global Force Mult',
            'SENSOR_DISTANCE': 'Sensor Distance',
            'TRAIL_PERSISTENCE': 'Trail Persistence',
        }

        ranges = slider_ranges if slider_ranges is not None else {}
        self._apply_sweep_to_state(config.x_sweep_data, sim_state.x_sweeps, ranges, param_to_label)
        self._apply_sweep_to_state(config.y_sweep_data, sim_state.y_sweeps, ranges, param_to_label)
        self._apply_sweep_to_state(config.cohort_sweep_data, sim_state.cohort_sweeps, ranges, param_to_label)

        return config.rule.copy()

    def encode_config(self, config: PhysicsConfig) -> str:
        """
        Encode a PhysicsConfig to a shareable string.

        Format: "SIMn:" + base64(zlib(bytes))
        Uses minimal version needed for backward compatibility:
        - Version 1: All extras are default (360 bytes)
        - Version 2: Only booleans are non-default (362 bytes)
        - Version 3: Simulation settings are non-default (374 bytes)
        - Version 4: Rule seed is non-default (378 bytes)
        - Version 5: Appearance or sweep settings are non-default (variable)
        """
        # Check if version 6 features are non-default (emboss_mode)
        emboss_mode_used = config.emboss_mode != 0

        # Check if version 5 features are non-default
        # Note: brightness is always 1.0 (now in preferences), not checked
        appearance_default = (
            config.ink_weight == 1.0 and
            config.hue_sensitivity == 0.5 and
            config.color_by_cohort and  # Default is True
            not config.watercolor_mode and
            config.emboss_intensity == 0.5 and
            config.emboss_smoothness == 0.1
        )
        sweeps_default = (
            not config.parameter_sweeps_enabled and
            config.x_sweep_data is None and
            config.y_sweep_data is None and
            config.cohort_sweep_data is None
        )
        # Check if rule_seed is non-default
        rule_seed_default = config.rule_seed == DEFAULT_RULE_SEED
        # Check if simulation settings are non-default
        sim_settings_default = (
            config.boundary_conditions == 0 and
            config.initial_conditions == 0 and
            config.num_cohorts == 64
        )
        # Check if booleans are default
        booleans_default = not config.disable_symmetry and not config.absolute_orientation

        # Use minimal version for backward compatibility
        if emboss_mode_used:
            version = 6
        elif not appearance_default or not sweeps_default:
            version = 5
        elif not rule_seed_default:
            version = 4
        elif not sim_settings_default:
            version = 3
        elif not booleans_default:
            version = 2
        else:
            version = 1

        raw_bytes = config.to_bytes(version)
        compressed = zlib.compress(raw_bytes, level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode('ascii')
        return f"SIM{version}:{encoded}"

    def decode_config(self, config_string: str | bytes) -> PhysicsConfig | None:
        """
        Decode a shareable string to a PhysicsConfig.

        Returns None if decoding fails.
        """
        try:
            # Handle bytes input (glfw clipboard returns bytes on Windows)
            if isinstance(config_string, bytes):
                config_string = config_string.decode('utf-8')

            # Parse version prefix
            if not config_string.startswith('SIM'):
                print("Invalid config string: missing SIM prefix")
                return None

            colon_idx = config_string.index(':')
            version = int(config_string[3:colon_idx])

            if version not in [1, 2, 3, 4, 5, 6]:
                print(f"Unsupported config version: {version}")
                return None

            # Decode
            encoded = config_string[colon_idx + 1:]
            compressed = base64.urlsafe_b64decode(encoded)
            raw_bytes = zlib.decompress(compressed)

            return PhysicsConfig.from_bytes(raw_bytes, version)

        except Exception as e:
            print(f"Failed to decode config: {e}")
            return None

    def save_to_string(self, sim_state: SimState, rule: np.ndarray | None,
                       slider_ranges: dict[str, list[float]] | None = None) -> str:
        """
        Convenience method: create config and encode to string.
        """
        config = self.create_config(sim_state, rule, slider_ranges)
        return self.encode_config(config)

    def load_from_string(self, config_string: str, sim_state: SimState,
                         slider_ranges: dict[str, list[float]] | None = None) -> np.ndarray | None:
        """
        Convenience method: decode string and apply to state.

        Returns the rule to push, or None if decoding failed.
        """
        config = self.decode_config(config_string)
        if config is None:
            return None
        return self.apply_config(config, sim_state, slider_ranges)
