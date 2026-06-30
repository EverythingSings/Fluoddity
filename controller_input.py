"""Xbox controller input: FPS-style ControllerCam and joystick polling.

Ported from Tracer/ui.py — same button/axis mappings, deadzone, and update logic.
"""
import glfw
import math
import numpy as np


class ControllerCam:
    """FPS-style camera with yaw/pitch control"""
    def __init__(self):
        self.reset()

    def reset(self):
        """Reset camera to default position and orientation."""
        self.pos = np.array([0.0, 0.0, 0.0])
        self.yaw = 0.0      # Rotation around Y axis (radians)
        self.pitch = 0.0    # Rotation around X axis (radians), clamped to ±π/2
        self.fov = 50.
        self._update_vectors()

    def _update_vectors(self):
        """Update direction vectors from yaw and pitch angles."""
        # Direction vector (where camera is looking)
        self.dir = np.array([
            math.cos(self.pitch) * math.sin(self.yaw),
            math.sin(self.pitch),
            math.cos(self.pitch) * math.cos(self.yaw)
        ])

        # Right vector (perpendicular to dir in XZ plane)
        self.right = np.array([
            math.cos(self.yaw),
            0.0,
            -math.sin(self.yaw)
        ])

        # Up vector (cross product of right and dir)
        self.up = np.cross(self.right, self.dir)
        self.up = self.up / np.linalg.norm(self.up)

    def rotate(self, delta_yaw, delta_pitch):
        """Rotate camera by given angles, clamping pitch to ±π/2."""
        self.yaw += delta_yaw
        self.pitch = np.clip(self.pitch + delta_pitch, -math.pi / 2 + 0.01, math.pi / 2 - 0.01)
        self._update_vectors()

    def move_xz(self, forward_amount, right_amount):
        """Move in the XZ plane relative to camera direction."""
        # Get forward direction projected onto XZ plane
        forward_xz = np.array([self.dir[0], 0.0, self.dir[2]])
        forward_len = np.linalg.norm(forward_xz)
        if forward_len > 0.001:
            forward_xz = forward_xz / forward_len
        else:
            forward_xz = np.array([0.0, 0.0, 1.0])

        # Move in XZ plane
        self.pos += forward_xz * forward_amount
        self.pos += self.right * right_amount

    def move_y(self, amount):
        """Move along the Y axis."""
        self.pos[1] += amount

    def get_position(self):
        """Get camera position."""
        return self.pos

    def get_view_vectors(self):
        """Get camera direction, right, and up vectors."""
        return self.dir, self.right, self.up


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
BUTTON_A = 0
BUTTON_B = 1
BUTTON_X = 2
BUTTON_Y = 3


BUTTON_ACTIONS = {
    BUTTON_A: "toggle_pause",
    BUTTON_B: "reset_particles",
    BUTTON_X: "toggle_sidebar",
    BUTTON_Y: "randomize_mutations",
    BUTTON_SELECT: "toggle_mouse_mode",
    BUTTON_START: "reset_controller_camera",
}

GAME_BUTTON_ACTIONS = {
    BUTTON_A: "game_confirm",
    BUTTON_B: "game_retry",
    BUTTON_X: "toggle_sidebar",
    BUTTON_Y: "game_tool",
    BUTTON_LB: "game_revert",
    BUTTON_SELECT: "game_exit",
    BUTTON_START: "game_pause",
}


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
    actions = set()
    joystick_state['left_x'] = 0.0
    joystick_state['left_y'] = 0.0
    joystick_state['right_x'] = 0.0
    joystick_state['right_y'] = 0.0
    joystick_state['lt'] = 0.0
    joystick_state['rt'] = 0.0
    joystick_state['fast'] = False
    jid = joystick_state['joystick_id']

    # Check connection, try to reconnect if lost
    if jid is None or not glfw.joystick_present(jid):
        jid = find_joystick()
        joystick_state['joystick_id'] = jid
        if jid is None:
            return actions

    # Get joystick state
    axes_raw = glfw.get_joystick_axes(jid)
    buttons_raw = glfw.get_joystick_buttons(jid)

    if axes_raw is None or buttons_raw is None:
        return actions

    # GLFW returns (ctypes_pointer, count) tuple
    axes_ptr, axes_count = axes_raw
    buttons_ptr, buttons_count = buttons_raw

    if axes_count == 0 or buttons_count == 0:
        return actions

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

    if prev:
        button_actions = GAME_BUTTON_ACTIONS if joystick_state.get('game_mode') else BUTTON_ACTIONS
        for button, action_name in button_actions.items():
            if len(prev) > button and buttons[button] and not prev[button]:
                actions.add(action_name)

    if "reset_controller_camera" in actions:
        print("Controller: Reset camera!")
        controller_cam.reset()

    joystick_state['prev_buttons'] = buttons.copy()

    # Right bumper held = fast mode
    speed_mult = FAST_MULTIPLIER if buttons[BUTTON_RB] else 1.0
    joystick_state['fast'] = bool(buttons[BUTTON_RB])

    # Left stick - XZ movement
    left_x = apply_deadzone(axes[AXIS_LEFT_X])
    left_y = apply_deadzone(axes[AXIS_LEFT_Y])
    joystick_state['left_x'] = left_x
    joystick_state['left_y'] = left_y

    if left_x != 0 or left_y != 0:
        move_speed = MOVE_SPEED * speed_mult * dt
        # Y axis inverted (up = negative)
        controller_cam.move_xz(-left_y * move_speed, left_x * move_speed)

    # Right stick - rotation
    right_x = apply_deadzone(axes[AXIS_RIGHT_X])
    right_y = apply_deadzone(axes[AXIS_RIGHT_Y])
    joystick_state['right_x'] = right_x
    joystick_state['right_y'] = right_y

    if right_x != 0 or right_y != 0:
        rotate_speed = ROTATE_SPEED * dt
        controller_cam.rotate(right_x * rotate_speed, -right_y * rotate_speed)

    # Triggers - Y movement
    lt = axes[AXIS_LT]
    rt = axes[AXIS_RT]

    # Normalize triggers: convert from [-1, 1] to [0, 1] if needed
    lt_normalized = (lt + 1.0) / 2.0 if lt < 0 else lt
    rt_normalized = (rt + 1.0) / 2.0 if rt < 0 else rt
    joystick_state['lt'] = max(0.0, min(1.0, lt_normalized))
    joystick_state['rt'] = max(0.0, min(1.0, rt_normalized))

    y_movement = (rt_normalized - lt_normalized) * MOVE_SPEED * speed_mult * dt
    if abs(y_movement) > 0.01:
        controller_cam.move_y(y_movement)

    return actions


def apply_controller_to_2d_camera(ui_state, joystick_state, dt):
    """Apply Steam Deck/Xbox continuous controls to the 2D Fluoddity camera."""
    fast_mult = FAST_MULTIPLIER if joystick_state.get('fast') else 1.0
    move_speed = 2.0 * dt * ui_state.camera.zoom * fast_mult
    zoom_speed = 2.2 * dt * fast_mult

    left_x = joystick_state.get('left_x', 0.0)
    left_y = joystick_state.get('left_y', 0.0)
    right_y = joystick_state.get('right_y', 0.0)
    trigger_zoom = joystick_state.get('rt', 0.0) - joystick_state.get('lt', 0.0)

    if left_x != 0.0 or left_y != 0.0:
        ui_state.camera.position[0] += left_x * move_speed
        ui_state.camera.position[1] += left_y * move_speed

    if ui_state.trial.game_mode:
        return

    zoom_input = trigger_zoom - right_y
    if abs(zoom_input) > 0.01:
        zoom_factor = 1.0 - zoom_input * zoom_speed
        zoom_factor = max(0.25, min(4.0, zoom_factor))
        ui_state.camera.zoom *= zoom_factor


def apply_game_cursor_to_state(ui_state, joystick_state, dt, viewport_size, cursor_pos):
    """Apply game-mode controller aim/feed state to the UI snapshot.

    Returns the updated persistent cursor position, or the incoming value when
    the game cursor is inactive.
    """
    if not ui_state.trial.game_mode or ui_state.trial.paused:
        ui_state.game_cursor_active = False
        ui_state.game_draw_held = False
        return cursor_pos

    if joystick_state.get('joystick_id') is None:
        ui_state.game_cursor_active = False
        ui_state.game_draw_held = False
        return cursor_pos

    width, height = viewport_size
    if width <= 0 or height <= 0:
        ui_state.game_cursor_active = False
        ui_state.game_draw_held = False
        return cursor_pos

    if cursor_pos is None:
        cursor_pos = [width * 0.5, height * 0.5]

    right_x = joystick_state.get('right_x', 0.0)
    right_y = joystick_state.get('right_y', 0.0)
    fast_mult = 1.8 if joystick_state.get('fast') else 1.0
    cursor_speed = min(width, height) * 0.72 * fast_mult
    cursor_pos[0] += right_x * cursor_speed * dt
    cursor_pos[1] += right_y * cursor_speed * dt
    cursor_pos[0] = float(np.clip(cursor_pos[0], 0.0, width - 1.0))
    cursor_pos[1] = float(np.clip(cursor_pos[1], 0.0, height - 1.0))

    ui_state.game_cursor_active = True
    ui_state.game_cursor_pos = tuple(cursor_pos)
    ui_state.game_draw_held = joystick_state.get('rt', 0.0) > 0.25
    return cursor_pos
