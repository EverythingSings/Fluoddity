"""Camera input processing: WASD movement, QE zoom, scroll-to-zoom."""
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
        ui_state.camera.position[0] -= move_speed
    if key_d and key_d in keys:
        ui_state.camera.position[0] += move_speed

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

    WASD rotates the camera around the simulation origin [0,0,0].
    E/Q and scroll wheel zoom in/out by adjusting orbit_distance.
    Camera is repositioned on a sphere of radius orbit_distance
    centered at the origin after any keyboard/scroll input.
    """
    orbit_speed = ui_state.camera.rotate_speed * dt
    zoom_speed = 2.6 * dt

    need_reposition = False

    # WASD changes yaw/pitch on the ControllerCam
    if key_a and key_a in keys:
        controller_cam.rotate(-orbit_speed, 0)
        need_reposition = True
    if key_d and key_d in keys:
        controller_cam.rotate(orbit_speed, 0)
        need_reposition = True
    if key_w and key_w in keys:
        controller_cam.rotate(0, orbit_speed)
        need_reposition = True
    if key_s and key_s in keys:
        controller_cam.rotate(0, -orbit_speed)
        need_reposition = True

    # E/Q adjusts orbit_distance (E = zoom in, Q = zoom out)
    if key_e and key_e in keys:
        ui_state.camera.orbit_distance *= (1.0 - zoom_speed)
        need_reposition = True
    if key_q and key_q in keys:
        ui_state.camera.orbit_distance *= (1.0 + zoom_speed)
        need_reposition = True

    # Scroll adjusts orbit_distance
    if ui_state.scroll_delta != 0.0:
        scroll_zoom_speed = 0.1
        zoom_factor = 1.0 - ui_state.scroll_delta * scroll_zoom_speed
        zoom_factor = max(0.5, min(2.0, zoom_factor))
        ui_state.camera.orbit_distance *= zoom_factor
        need_reposition = True

    # Clamp orbit_distance to match slider range
    ui_state.camera.orbit_distance = max(0.1, min(20.0, ui_state.camera.orbit_distance))

    # Reposition camera on orbit sphere centered at origin
    if need_reposition:
        controller_cam.pos[:] = -controller_cam.dir * ui_state.camera.orbit_distance
