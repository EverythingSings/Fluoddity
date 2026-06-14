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
                p = self.state.preferences
                pt_mode = p.three_d_pathtracer_enabled

                # Renderer mode selector
                mode_labels = ["Rasterize", "Path Trace"]
                current_mode = 1 if pt_mode else 0
                changed, new_mode = imgui.combo("Renderer", current_mode, mode_labels)
                if changed:
                    p.three_d_pathtracer_enabled = (new_mode == 1)
                    pt_mode = p.three_d_pathtracer_enabled

                # Shared controls (bind to the active renderer's preferences)
                if pt_mode:
                    _, p.three_d_pt_gas_rebuild_interval = imgui.slider_int(
                        "GAS Rebuild", p.three_d_pt_gas_rebuild_interval, 1, 120)
                    _, p.three_d_pt_sphere_radius_scale = imgui.slider_float(
                        "Sphere Scale", p.three_d_pt_sphere_radius_scale,
                        0.1, 10.0, format="%.1fx")
                else:
                    _, p.three_d_optix_gas_rebuild_interval = imgui.slider_int(
                        "GAS Rebuild", p.three_d_optix_gas_rebuild_interval, 1, 120)
                    _, p.three_d_optix_sphere_radius_scale = imgui.slider_float(
                        "Sphere Scale", p.three_d_optix_sphere_radius_scale,
                        0.1, 10.0, format="%.1fx")

                # Albedo color controls (shared across both modes)
                _, p.three_d_optix_albedo_saturation = imgui.slider_float(
                    "Albedo Saturation", p.three_d_optix_albedo_saturation, 0.0, 1.0)
                _, p.three_d_optix_albedo_brightness = imgui.slider_float(
                    "Albedo Brightness", p.three_d_optix_albedo_brightness, 0.0, 1.0)

                if pt_mode:
                    # ---- Path Trace mode controls ----

                    # Sun
                    if imgui.collapsing_header("Sun##pt", imgui.TreeNodeFlags_.default_open.value):
                        changed, vals = imgui.drag_float3(
                            "Sun Dir", list(p.three_d_pt_sun_direction),
                            0.01, -1.0, 1.0)
                        if changed:
                            p.three_d_pt_sun_direction = list(vals)
                        _, p.three_d_pt_sun_color = imgui.color_edit3(
                            "Sun Color##pt", p.three_d_pt_sun_color)
                        _, p.three_d_pt_sun_intensity = imgui.slider_float(
                            "Sun Intensity", p.three_d_pt_sun_intensity, 0.0, 20.0)
                        _, p.three_d_pt_sun_sampling = imgui.checkbox(
                            "Sun Sampling (NEE)", p.three_d_pt_sun_sampling)

                    # Sky
                    if imgui.collapsing_header("Sky##pt", imgui.TreeNodeFlags_.default_open.value):
                        _, p.three_d_pt_sky_color_top = imgui.color_edit3(
                            "Sky Top##pt", p.three_d_pt_sky_color_top)
                        _, p.three_d_pt_sky_color_bottom = imgui.color_edit3(
                            "Sky Bottom##pt", p.three_d_pt_sky_color_bottom)

                    # Material
                    if imgui.collapsing_header("Material", imgui.TreeNodeFlags_.default_open.value):
                        mat_labels = ["Lambert", "Glossy", "Mirror"]
                        _, p.three_d_pt_global_material = imgui.combo(
                            "Material##combo", p.three_d_pt_global_material, mat_labels)
                        if p.three_d_pt_global_material == 1:  # Glossy
                            _, p.three_d_pt_glossy_ior = imgui.slider_float(
                                "Glossy IOR", p.three_d_pt_glossy_ior, 1.0, 3.0, format="%.2f")

                    # Render
                    if imgui.collapsing_header("Render##pt", imgui.TreeNodeFlags_.default_open.value):
                        _, p.three_d_pt_exposure = imgui.slider_float(
                            "Exposure##pt", p.three_d_pt_exposure, 0.1, 10.0)
                        _, p.three_d_pt_max_bounces = imgui.drag_int(
                            "Max Bounces", p.three_d_pt_max_bounces, 0.1, 0, 64)
                        if imgui.is_item_hovered():
                            imgui.set_tooltip("0 = unbounded (Russian roulette only)")
                        _, p.three_d_pt_rr_start_depth = imgui.slider_int(
                            "RR Start Depth", p.three_d_pt_rr_start_depth, 1, 16)
                        _, p.three_d_pt_firefly_clamp = imgui.checkbox(
                            "Firefly Clamp##pt", p.three_d_pt_firefly_clamp)
                        if p.three_d_pt_firefly_clamp:
                            imgui.same_line()
                            imgui.set_next_item_width(imgui.get_content_region_avail().x)
                            _, p.three_d_pt_firefly_clamp_max = imgui.drag_float(
                                "##pt_clamp_max", p.three_d_pt_firefly_clamp_max,
                                0.1, 0.1, 1000.0, "Max: %.1f")
                        _, p.three_d_pt_denoise_enabled = imgui.checkbox(
                            "Denoise", p.three_d_pt_denoise_enabled)

                    # Timing display (path tracer)
                    gas_ms = self.state.camera.pathtracer_gas_time_ms
                    render_ms = self.state.camera.pathtracer_render_time_ms
                    imgui.text_colored(
                        imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
                        f"GAS {gas_ms:.1f}ms  Render {render_ms:.1f}ms")

                else:
                    # ---- Rasterize mode controls (existing sphere renderer) ----

                    # Lighting
                    if imgui.collapsing_header("Lighting", imgui.TreeNodeFlags_.default_open.value):
                        changed, vals = imgui.drag_float3(
                            "Light Dir", list(p.three_d_optix_light_direction),
                            0.01, -1.0, 1.0)
                        if changed:
                            p.three_d_optix_light_direction = list(vals)
                        _, p.three_d_optix_light_color = imgui.color_edit3(
                            "Light Color", p.three_d_optix_light_color)
                        _, p.three_d_optix_light_intensity = imgui.slider_float(
                            "Intensity", p.three_d_optix_light_intensity, 0.0, 5.0)
                        _, p.three_d_optix_shadows_enabled = imgui.checkbox(
                            "Shadows", p.three_d_optix_shadows_enabled)
                        _, p.three_d_optix_ambient = imgui.slider_float(
                            "Ambient", p.three_d_optix_ambient, 0.0, 1.0)

                    # Sky
                    if imgui.collapsing_header("Sky", imgui.TreeNodeFlags_.default_open.value):
                        _, p.three_d_optix_sky_color_top = imgui.color_edit3(
                            "Sky Top", p.three_d_optix_sky_color_top)
                        _, p.three_d_optix_sky_color_bottom = imgui.color_edit3(
                            "Sky Bottom", p.three_d_optix_sky_color_bottom)

                    # Ambient Occlusion
                    if imgui.collapsing_header("Ambient Occlusion"):
                        _, p.three_d_optix_ao_enabled = imgui.checkbox(
                            "Enable AO", p.three_d_optix_ao_enabled)
                        if p.three_d_optix_ao_enabled:
                            _, p.three_d_optix_ao_num_rays = imgui.slider_int(
                                "AO Rays", p.three_d_optix_ao_num_rays, 1, 16)
                            _, p.three_d_optix_ao_radius = imgui.slider_float(
                                "AO Radius", p.three_d_optix_ao_radius,
                                0.01, 5.0, format="%.2f")

                    # Timing display (sphere renderer)
                    gas_ms = self.state.camera.optix_gas_time_ms
                    render_ms = self.state.camera.optix_render_time_ms
                    imgui.text_colored(
                        imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
                        f"GAS {gas_ms:.1f}ms  Render {render_ms:.1f}ms")

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
