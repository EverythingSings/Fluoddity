"""Camera input processing: WASD movement, QE zoom, scroll-to-zoom."""
import math
import glfw
import numpy as np


def process_camera_input(ui_state, window, keybindings, sim_view_tex, dt, controller_cam=None):
    """Handle continuous WASD/QE input for camera and scroll zoom.

    Args:
        ui_state: Combined UI state from ui.get_state()
        window: GLFW window handle (for framebuffer size)
        keybindings: KeybindingManager instance
        sim_view_tex: Simulation view texture (for aspect ratio)
        dt: Delta time since last frame in seconds
    """
    keys = ui_state.keys_pressed

    # Get key bindings
    key_w = keybindings.get_key("camera_forward")
    key_s = keybindings.get_key("camera_backward")
    key_a = keybindings.get_key("camera_left")
    key_d = keybindings.get_key("camera_right")
    key_e = keybindings.get_key("camera_in")
    key_q = keybindings.get_key("camera_out")

    # 3D orbital camera mode (keyboard fallback for joystick)
    if ui_state.camera.render_3d:
        if controller_cam is not None:
            _process_3d_orbit_input(ui_state, keys, controller_cam, dt,
                                    key_w, key_s, key_a, key_d, key_e, key_q)
        return

    # 2D camera mode
    move_speed = 2.0 * dt * ui_state.camera.zoom
    zoom_speed = 2.6 * dt

    if key_w and key_w in keys:
        ui_state.camera.position[1] -= move_speed
    if key_s and key_s in keys:
        ui_state.camera.position[1] += move_speed
    if key_a and key_a in keys:
        ui_state.camera.position[0] += move_speed
    if key_d and key_d in keys:
        ui_state.camera.position[0] -= move_speed

    if key_e and key_e in keys:
        ui_state.camera.zoom *= (1.0 - zoom_speed)
    if key_q and key_q in keys:
        ui_state.camera.zoom *= (1.0 + zoom_speed)

    # Handle scroll zoom (zoom around mouse pointer - "Factorio-style")
    if ui_state.scroll_delta != 0.0:
        width, height = glfw.get_framebuffer_size(window)

        # Convert mouse to NDC
        x_screen, y_screen = ui_state.mouse_pos
        x_ndc = (x_screen / width) * 2 - 1
        y_ndc = (1 - y_screen / height) * 2 - 1

        # Calculate aspect ratios
        tex_size = sim_view_tex.size
        tex_aspect = tex_size[0] / tex_size[1]
        window_aspect = width / height

        if tex_aspect > window_aspect:
            scale_x = 1.0
            scale_y = window_aspect / tex_aspect
        else:
            scale_x = tex_aspect / window_aspect
            scale_y = 1.0

        # Get world position under mouse BEFORE zoom
        old_zoom = ui_state.camera.zoom
        old_pos = ui_state.camera.position.copy()

        scale_x_old = scale_x / old_zoom
        scale_y_old = scale_y / old_zoom
        x_ndc_adj = x_ndc + old_pos[0] / old_zoom
        y_ndc_adj = y_ndc - old_pos[1] / old_zoom
        world_x = x_ndc_adj / scale_x_old
        world_y = y_ndc_adj / scale_y_old

        # Apply zoom (scroll up = zoom in = smaller zoom value)
        scroll_zoom_speed = 0.1
        zoom_factor = 1.0 - ui_state.scroll_delta * scroll_zoom_speed
        zoom_factor = max(0.5, min(2.0, zoom_factor))  # Clamp zoom step
        new_zoom = old_zoom * zoom_factor
        ui_state.camera.zoom = new_zoom

        # Calculate where the world point would now appear in NDC
        scale_x_new = scale_x / new_zoom
        scale_y_new = scale_y / new_zoom
        new_x_ndc_adj = world_x * scale_x_new
        new_y_ndc_adj = world_y * scale_y_new

        # Adjust camera position so the world point stays at the same screen position
        ui_state.camera.position[0] = (new_x_ndc_adj - x_ndc) * new_zoom
        ui_state.camera.position[1] = -(new_y_ndc_adj - y_ndc) * new_zoom


def _process_3d_orbit_input(ui_state, keys, controller_cam, dt,
                            key_w, key_s, key_a, key_d, key_e, key_q):
    """Handle 3D orbital camera controls via keyboard.

    WASD rotates the camera around orbit_center (A/D = yaw, W/S = pitch).
    E/Q and scroll wheel zoom in/out by adjusting distance from orbit_center.
    Camera is repositioned on a sphere around orbit_center after any input.
    """
    cam = ui_state.camera
    orbit_speed = cam.rotate_speed * dt
    zoom_speed = 2.6 * dt
    center = cam.orbit_center

    # Current distance from orbit center
    offset = controller_cam.pos - center
    dist = float(np.linalg.norm(offset))
    if dist < 0.01:
        dist = 3.0  # fallback if camera is at center

    need_reposition = False

    # A/D adjusts orbit yaw angle
    if key_a and key_a in keys:
        cam.orbit_angle -= orbit_speed
        need_reposition = True
    if key_d and key_d in keys:
        cam.orbit_angle += orbit_speed
        need_reposition = True

    # W/S adjusts orbit pitch (elevation)
    if key_w and key_w in keys:
        cam.orbit_pitch += orbit_speed
        need_reposition = True
    if key_s and key_s in keys:
        cam.orbit_pitch -= orbit_speed
        need_reposition = True

    # Clamp pitch to avoid gimbal lock
    cam.orbit_pitch = max(-math.pi / 2 + 0.01, min(math.pi / 2 - 0.01, cam.orbit_pitch))

    # E/Q adjusts distance from orbit center (E = closer, Q = farther)
    if key_e and key_e in keys:
        dist *= (1.0 - zoom_speed)
        need_reposition = True
    if key_q and key_q in keys:
        dist *= (1.0 + zoom_speed)
        need_reposition = True

    # Scroll adjusts distance from orbit center
    if ui_state.scroll_delta != 0.0:
        scroll_zoom_speed = 0.1
        zoom_factor = 1.0 - ui_state.scroll_delta * scroll_zoom_speed
        zoom_factor = max(0.5, min(2.0, zoom_factor))
        dist *= zoom_factor
        need_reposition = True

    dist = max(0.1, min(100.0, dist))

    # Reposition camera on orbit sphere around orbit_center
    if need_reposition:
        _reposition_orbit_camera(controller_cam, center, dist, cam.orbit_angle, cam.orbit_pitch)


def reposition_orbit_camera(controller_cam, cam_state):
    """Reposition camera on orbit sphere from current state (for external callers)."""
    center = cam_state.orbit_center
    offset = controller_cam.pos - center
    dist = float(np.linalg.norm(offset))
    if dist < 0.01:
        dist = 3.0
    _reposition_orbit_camera(controller_cam, center, dist, cam_state.orbit_angle, cam_state.orbit_pitch)


def sync_orbit_angles_from_camera(cam_state, controller_cam):
    """Compute orbit_angle and orbit_pitch from camera's position relative to orbit_center.

    Call this after changing orbit_center so the camera doesn't jump.
    """
    offset = controller_cam.pos - cam_state.orbit_center
    dist_xz = math.sqrt(offset[0] ** 2 + offset[2] ** 2)
    cam_state.orbit_angle = math.atan2(offset[0], -offset[2])
    cam_state.orbit_pitch = math.atan2(offset[1], dist_xz) if dist_xz > 1e-6 else 0.0


def _reposition_orbit_camera(controller_cam, center, dist, angle, pitch):
    """Place camera on a sphere around center and aim at center."""
    cos_p = math.cos(pitch)
    controller_cam.pos[0] = center[0] + dist * math.sin(angle) * cos_p
    controller_cam.pos[1] = center[1] + dist * math.sin(pitch)
    controller_cam.pos[2] = center[2] - dist * math.cos(angle) * cos_p

    # Aim camera at center (negate both: position offset is opposite to look direction)
    controller_cam.yaw = -angle
    controller_cam.pitch = -pitch
    controller_cam._update_vectors()
