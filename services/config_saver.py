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
CONFIG_VERSION = 1


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
    # Rule data (10 centers * 8 floats = 80 floats)
    rule: np.ndarray  # shape (10, 8)

    def to_bytes(self) -> bytes:
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
        return physics_bytes + rule_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> 'PhysicsConfig':
        """Deserialize config from bytes."""
        # Unpack physics params (10 floats = 40 bytes)
        physics = struct.unpack('10f', data[:40])
        # Unpack rule (80 floats = 320 bytes)
        rule_data = np.frombuffer(data[40:360], dtype=np.float32)
        rule = rule_data.reshape(10, 8)
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

        return config.rule.copy()

    def encode_config(self, config: PhysicsConfig) -> str:
        """
        Encode a PhysicsConfig to a shareable string.

        Format: "SIM1:" + base64(zlib(bytes))
        """
        raw_bytes = config.to_bytes()
        compressed = zlib.compress(raw_bytes, level=9)
        encoded = base64.urlsafe_b64encode(compressed).decode('ascii')
        return f"SIM{CONFIG_VERSION}:{encoded}"

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

            if version != CONFIG_VERSION:
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
