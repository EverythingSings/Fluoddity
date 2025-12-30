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
CONFIG_VERSION = 4

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

    def to_bytes(self, version: int = 4) -> bytes:
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
        return physics_bytes + rule_bytes + bool_bytes + sim_bytes + seed_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PhysicsConfig':
        """Deserialize config from bytes. Supports version 1 (360), 2 (362), 3 (374), and 4 (378 bytes)."""
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

        # Version 2+: check if we have extra boolean data
        if len(data) >= 362:
            disable_symmetry, absolute_orientation = struct.unpack('??', data[360:362])

        # Version 3+: check if we have simulation settings
        if len(data) >= 374:
            boundary_conditions, initial_conditions, num_cohorts = struct.unpack('3i', data[362:374])

        # Version 4+: check if we have rule_seed
        if len(data) >= 378:
            rule_seed, = struct.unpack('f', data[374:378])

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
            rule=rule.copy()
        )


class ConfigSaver:
    """Service for saving/loading physics configurations."""

    def __init__(self):
        pass

    def create_config(self, sim_state: SimState, rule: np.ndarray | None) -> PhysicsConfig:
        """
        Create a PhysicsConfig from current state.

        Args:
            sim_state: Current simulation state with physics parameters
            rule: Current rule from RuleManager (None = use zeros)
        """
        # Use zero rule if none provided
        if rule is None:
            rule = np.zeros((10, 8), dtype=np.float32)

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
            rule=rule.copy()
        )

    def apply_config(self, config: PhysicsConfig, sim_state: SimState) -> np.ndarray:
        """
        Apply a PhysicsConfig to the simulation state.

        Args:
            config: The config to apply
            sim_state: SimState to update (modified in place)

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
        """
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
        if not rule_seed_default:
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

            if version not in [1, 2, 3, 4]:
                print(f"Unsupported config version: {version}")
                return None

            # Decode
            encoded = config_string[colon_idx + 1:]
            compressed = base64.urlsafe_b64decode(encoded)
            raw_bytes = zlib.decompress(compressed)

            return PhysicsConfig.from_bytes(raw_bytes)

        except Exception as e:
            print(f"Failed to decode config: {e}")
            return None

    def save_to_string(self, sim_state: SimState, rule: np.ndarray | None) -> str:
        """
        Convenience method: create config and encode to string.
        """
        config = self.create_config(sim_state, rule)
        return self.encode_config(config)

    def load_from_string(self, config_string: str, sim_state: SimState) -> np.ndarray | None:
        """
        Convenience method: decode string and apply to state.

        Returns the rule to push, or None if decoding failed.
        """
        config = self.decode_config(config_string)
        if config is None:
            return None
        return self.apply_config(config, sim_state)
