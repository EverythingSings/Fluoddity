"""3D Controls window: shared FPS/orbit camera settings.

(The renderer-selection checkboxes moved to Preferences -> Renderer in the
3D-only cleanup; this window is folded into the unified "Render settings"
window in a following step.)
"""
from imgui_bundle import imgui
from camera_input import sync_orbit_angles_from_camera


class ThreeDWindowMixin:
    """Mixin for the 3D Controls window. Combined into UI via multiple inheritance."""

    def render_three_d_window(self):
        """Render the 3D Controls window."""
        visible, opened = imgui.begin("3D Controls", True)
        if not opened:
            self.state.preferences.ui_windows.show_three_d_window = False
            imgui.end()
            return
        if visible:
            imgui.text("Camera")

            _, self.state.camera.fov = imgui.slider_float(
                "FOV", self.state.camera.fov, 10.0, 120.0, format="%.0f deg"
            )
            _, self.state.camera.aperture = imgui.slider_float(
                "Aperture", self.state.camera.aperture, 0.0, 0.2, format="%.3f"
            )
            _, self.state.camera.focal_plane_depth = imgui.slider_float(
                "Focal Depth", self.state.camera.focal_plane_depth, 0.1, 50.0, format="%.1f"
            )

            _, self.state.camera.move_speed = imgui.slider_float(
                "Move Speed", self.state.camera.move_speed, 0.1, 10.0, format="%.1f"
            )

            _, self.state.camera.rotate_speed = imgui.slider_float(
                "Rotate Speed", self.state.camera.rotate_speed, 0.1, 10.0, format="%.1f"
            )

            center = self.state.camera.orbit_center
            changed, values = imgui.drag_float3(
                "Orbit Center", list(center), 0.01, format="%.2f"
            )
            if changed:
                center[0], center[1], center[2] = values
                if self.tracer_controller_cam is not None:
                    sync_orbit_angles_from_camera(self.state.camera, self.tracer_controller_cam)

            _, self.state.camera.orbit_rate = imgui.slider_float(
                "Orbit Rate", self.state.camera.orbit_rate, -0.05, 0.05, format="%.4f"
            )

        imgui.end()
