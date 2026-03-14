"""Xbox controller input: FPS-style ControllerCam and joystick polling.

Camera uses explicit vectors (pos, fwd, up) for arbitrary orientation,
supporting teleportation at cell boundaries for recursive SDF navigation.
"""
import glfw
import math
import numpy as np


# ---------------------------------------------------------------------------
# Vector helpers (ported from demos/self_sim/harness.py)
# ---------------------------------------------------------------------------

def _norm(v):
    """Normalize a vector, returning unchanged if near-zero length."""
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _rodrigues(v, axis, angle):
    """Rotate *v* around *axis* by *angle* radians (Rodrigues' formula)."""
    a = _norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(a, v) * s + a * np.dot(a, v) * (1.0 - c)


def _axis_angle(R):
    """Extract (axis, angle) from a 3x3 rotation matrix."""
    angle = math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0)))
    if abs(angle) < 1e-12:
        return np.array([0.0, 1.0, 0.0]), 0.0
    axis = np.array([R[2, 1] - R[1, 2],
                     R[0, 2] - R[2, 0],
                     R[1, 0] - R[0, 1]])
    return _norm(axis), angle


def _rot_from_axis_angle(axis, angle):
    """Build a 3x3 rotation matrix from axis-angle."""
    a = _norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    x, y, z = a
    return np.array([
        [t*x*x + c,   t*x*y - s*z, t*x*z + s*y],
        [t*x*y + s*z, t*y*y + c,   t*y*z - s*x],
        [t*x*z - s*y, t*y*z + s*x, t*z*z + c  ],
    ])


def rot_mat(x, y, z):
    """Build a 3x3 rotation matrix from Euler angles (X, Y, Z order)."""
    cx, sx = np.cos(x), np.sin(x)
    cy, sy = np.cos(y), np.sin(y)
    cz, sz = np.cos(z), np.sin(z)

    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

    return Rz @ Ry @ Rx


class ControllerCam:
    """FPS-style camera with arbitrary orientation (vector-based).

    Stores orientation as explicit pos/fwd/up vectors so that arbitrary
    rotation matrices (e.g. cell-transition teleports) can be applied directly.
    Also tracks runtime recursion state (world_scale, world_orientation, spiral_phase).
    """
    def __init__(self):
        self.reset()

    def reset(self):
        """Reset camera to default position and orientation."""
        self.pos = np.array([0.0, 2.0, 0.0], dtype=np.float64)
        self.fwd = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        self.up  = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        self.speed = 5.0
        self.sensitivity = 0.003
        # Runtime recursion state (not persisted)
        self.world_scale = 1.0
        self.world_orientation = np.eye(3, dtype=np.float64)
        self.spiral_phase = 0.0

    @property
    def right(self):
        """Right vector, computed from fwd and up."""
        return _norm(np.cross(self.fwd, self.up))

    @property
    def dir(self):
        """Alias for fwd, for backward compatibility."""
        return self.fwd

    def rotate(self, yaw, pitch):
        """Apply yaw (around camera-up) and pitch (around camera-right).

        Uses Rodrigues rotation for arbitrary orientation support.
        Pitch is guarded to prevent fwd from aligning with up.
        """
        if abs(yaw) > 1e-9:
            self.fwd = _rodrigues(self.fwd, self.up, yaw)
        if abs(pitch) > 1e-9:
            r = self.right
            new_fwd = _rodrigues(self.fwd, r, pitch)
            if abs(np.dot(new_fwd, self.up)) < 0.99:
                self.fwd = new_fwd
                self.up  = _rodrigues(self.up, r, pitch)
        self._ortho()

    def _ortho(self):
        """Gram-Schmidt re-orthogonalisation to prevent float drift."""
        self.fwd = _norm(self.fwd)
        self.up  = self.up - np.dot(self.up, self.fwd) * self.fwd
        self.up  = _norm(self.up)

    def move_xz(self, forward_amount, right_amount):
        """Move along camera fwd/right directions, scaled by world_scale."""
        self.pos += self.fwd * forward_amount * self.world_scale
        self.pos += self.right * right_amount * self.world_scale

    def move_y(self, amount):
        """Move along camera up axis, scaled by world_scale."""
        self.pos += self.up * amount * self.world_scale

    def teleport_inward(self, scale, rotation):
        """Camera crossed inner sphere -> zoom into nested cell."""
        self.pos = rotation @ self.pos / scale
        self.fwd = rotation @ self.fwd
        self.up  = rotation @ self.up
        self._ortho()

    def teleport_outward(self, scale, rotation):
        """Camera crossed outer sphere -> zoom out to parent cell."""
        rot_inv = rotation.T
        self.pos = scale * (rot_inv @ self.pos)
        self.fwd = rot_inv @ self.fwd
        self.up  = rot_inv @ self.up
        self._ortho()


# Controller constants (Xbox-style)
MOVE_SPEED = 2.0
FAST_MULTIPLIER = 3.0
ROTATE_SPEED = 2.0
DEADZONE = 0.15

# Axis indices
AXIS_LEFT_X = 0
AXIS_LEFT_Y = 1
AXIS_RIGHT_X = 2
AXIS_RIGHT_Y = 3
AXIS_LT = 4
AXIS_RT = 5

# Button indices
BUTTON_LB = 4
BUTTON_RB = 5
BUTTON_SELECT = 6
BUTTON_START = 7


def find_joystick():
    """Find the first connected joystick."""
    for jid in range(glfw.JOYSTICK_1, glfw.JOYSTICK_LAST + 1):
        if glfw.joystick_present(jid):
            name = glfw.get_joystick_name(jid)
            if name:
                print(f"Found joystick {jid}: {name.decode() if isinstance(name, bytes) else name}")
            return jid
    return None


def apply_deadzone(value):
    """Apply deadzone to axis input."""
    if abs(value) < DEADZONE:
        return 0.0
    # Rescale to 0-1 range after deadzone
    sign = 1.0 if value > 0 else -1.0
    return sign * (abs(value) - DEADZONE) / (1.0 - DEADZONE)


def process_controller_input(controller_cam, joystick_state, dt):
    """Update controller camera based on Xbox controller input.

    Args:
        controller_cam: ControllerCam instance to update.
        joystick_state: Mutable dict with 'joystick_id' and 'prev_buttons'.
        dt: Delta time in seconds.
    """
    jid = joystick_state['joystick_id']

    # Check connection, try to reconnect if lost
    if jid is None or not glfw.joystick_present(jid):
        jid = find_joystick()
        joystick_state['joystick_id'] = jid
        if jid is None:
            return

    # Get joystick state
    axes_raw = glfw.get_joystick_axes(jid)
    buttons_raw = glfw.get_joystick_buttons(jid)

    if axes_raw is None or buttons_raw is None:
        return

    # GLFW returns (ctypes_pointer, count) tuple
    axes_ptr, axes_count = axes_raw
    buttons_ptr, buttons_count = buttons_raw

    if axes_count == 0 or buttons_count == 0:
        return

    # Extract values from ctypes pointers
    axes = [axes_ptr[i] for i in range(axes_count)]
    buttons = [buttons_ptr[i] for i in range(buttons_count)]

    # Pad axes list if needed
    while len(axes) < 6:
        axes.append(0.0)

    # Pad buttons list if needed
    while len(buttons) < 16:
        buttons.append(0)

    # Button edge detection
    prev = joystick_state['prev_buttons']

    # Start button: reset camera
    if len(prev) > BUTTON_START:
        if buttons[BUTTON_START] and not prev[BUTTON_START]:
            print("Controller: Reset camera!")
            controller_cam.reset()

    joystick_state['prev_buttons'] = buttons.copy()

    # Right bumper held = fast mode
    speed_mult = FAST_MULTIPLIER if buttons[BUTTON_RB] else 1.0

    # Left stick - movement along camera fwd/right
    left_x = apply_deadzone(axes[AXIS_LEFT_X])
    left_y = apply_deadzone(axes[AXIS_LEFT_Y])

    if left_x != 0 or left_y != 0:
        move_speed = MOVE_SPEED * speed_mult * dt
        # Y axis inverted (up = negative)
        controller_cam.move_xz(-left_y * move_speed, left_x * move_speed)

    # Right stick - rotation
    right_x = apply_deadzone(axes[AXIS_RIGHT_X])
    right_y = apply_deadzone(axes[AXIS_RIGHT_Y])

    if right_x != 0 or right_y != 0:
        rotate_speed = ROTATE_SPEED * dt
        controller_cam.rotate(-right_x * rotate_speed, -right_y * rotate_speed)

    # Triggers - movement along camera up axis
    lt = axes[AXIS_LT]
    rt = axes[AXIS_RT]

    # Normalize triggers: convert from [-1, 1] to [0, 1] if needed
    lt_normalized = (lt + 1.0) / 2.0 if lt < 0 else lt
    rt_normalized = (rt + 1.0) / 2.0 if rt < 0 else rt

    y_movement = (rt_normalized - lt_normalized) * MOVE_SPEED * speed_mult * dt
    if abs(y_movement) > 0.01:
        controller_cam.move_y(y_movement)
