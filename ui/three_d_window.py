"""3D Controls window: FPS camera settings and 3D simulation parameters."""
from imgui_bundle import imgui
from camera_input import sync_orbit_angles_from_camera
from optix_interface import OptiXInterface


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

            # OptiX Spheres toggle
            optix_available = OptiXInterface.is_available()
            if not optix_available:
                imgui.begin_disabled()
            _, self.state.camera.optix_enabled = imgui.checkbox(
                "OptiX Spheres (RTX)", self.state.camera.optix_enabled
            )
            if not optix_available:
                imgui.end_disabled()
                if imgui.is_item_hovered(imgui.HoveredFlags_.allow_when_disabled):
                    imgui.set_tooltip("Requires NVIDIA RTX GPU with OptiX/CUDA installed")

            # OptiX settings (only shown when enabled)
            if self.state.camera.optix_enabled and optix_available:
                _, self.state.preferences.three_d_optix_gas_rebuild_interval = imgui.slider_int(
                    "GAS Rebuild", self.state.preferences.three_d_optix_gas_rebuild_interval,
                    1, 120
                )
                _, self.state.preferences.three_d_optix_sphere_radius_scale = imgui.slider_float(
                    "Sphere Scale", self.state.preferences.three_d_optix_sphere_radius_scale,
                    0.1, 10.0, format="%.1fx"
                )

                # Lighting controls
                if imgui.collapsing_header("Lighting", imgui.TreeNodeFlags_.default_open.value):
                    changed, vals = imgui.drag_float3(
                        "Light Dir", list(self.state.preferences.three_d_optix_light_direction),
                        0.01, -1.0, 1.0
                    )
                    if changed:
                        self.state.preferences.three_d_optix_light_direction = list(vals)

                    _, self.state.preferences.three_d_optix_light_color = imgui.color_edit3(
                        "Light Color", self.state.preferences.three_d_optix_light_color
                    )

                    _, self.state.preferences.three_d_optix_light_intensity = imgui.slider_float(
                        "Intensity", self.state.preferences.three_d_optix_light_intensity,
                        0.0, 5.0
                    )

                    _, self.state.preferences.three_d_optix_shadows_enabled = imgui.checkbox(
                        "Shadows", self.state.preferences.three_d_optix_shadows_enabled
                    )

                    _, self.state.preferences.three_d_optix_ambient = imgui.slider_float(
                        "Ambient", self.state.preferences.three_d_optix_ambient,
                        0.0, 1.0
                    )

                # Sky controls
                if imgui.collapsing_header("Sky", imgui.TreeNodeFlags_.default_open.value):
                    _, self.state.preferences.three_d_optix_sky_color_top = imgui.color_edit3(
                        "Sky Top", self.state.preferences.three_d_optix_sky_color_top
                    )

                    _, self.state.preferences.three_d_optix_sky_color_bottom = imgui.color_edit3(
                        "Sky Bottom", self.state.preferences.three_d_optix_sky_color_bottom
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
