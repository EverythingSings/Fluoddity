"""3D Controls window: FPS camera settings and 3D simulation parameters."""
from imgui_bundle import imgui


class ThreeDWindowMixin:
    """Mixin for the 3D Controls window. Combined into UI via multiple inheritance."""

    def render_three_d_window(self):
        """Render the 3D Controls window."""
        visible, opened = imgui.begin("3D Controls", True)
        if not opened:
            self.state.preferences.show_three_d_window = False
            imgui.end()
            return
        if visible:
            _, self.state.camera.render_3d = imgui.checkbox(
                "3D View", self.state.camera.render_3d
            )

            imgui.separator()
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

            _, self.state.camera.orbit_distance = imgui.slider_float(
                "Orbit Distance", self.state.camera.orbit_distance, 0.1, 20.0, format="%.1f"
            )

            _, self.state.camera.orbit_rate = imgui.slider_float(
                "Orbit Rate", self.state.camera.orbit_rate, -2.0, 2.0, format="%.2f"
            )

            imgui.separator()
            imgui.text("Simulation")

            _, self.state.sim.TESTING_MODE = imgui.checkbox(
                "Testing Mode (2D compat)", self.state.sim.TESTING_MODE
            )

            _, self.state.sim.PLANE_SAMPLES = imgui.slider_int(
                "Plane Samples", self.state.sim.PLANE_SAMPLES, 1, 8
            )

            # Canvas Z Depth (temporarily hidden — not hooked up)
            # _, self.state.sim.canvas_3d_depth = imgui.slider_int(
            #     "Canvas Z Depth", self.state.sim.canvas_3d_depth, 1, 256
            # )

            max_slice = max(0, self.state.sim.canvas_3d_depth - 1)
            _, self.state.sim.canvas_3d_view_slice = imgui.slider_int(
                "Debug View Slice", self.state.sim.canvas_3d_view_slice, 0, max_slice
            )

        imgui.end()
