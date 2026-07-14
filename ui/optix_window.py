"""OptiX Controls window: raytracing settings for rasterize and path trace modes."""
from imgui_bundle import imgui
from camera_input import sync_orbit_angles_from_camera


class OptiXWindowMixin:
    """Mixin for the OptiX Controls window. Combined into UI via multiple inheritance."""

    # Preview request flag (set by UI, cleared by orchestrator)
    _request_optix_preview: bool = False

    def render_optix_window(self):
        """Render the OptiX Controls window."""
        visible, opened = imgui.begin("OptiX Controls", True)
        if not opened:
            self.state.preferences.ui_windows.show_optix_window = False
            imgui.end()
            return
        if not visible:
            imgui.end()
            return

        p = self.state.preferences

        if not self.state.camera.optix_enabled:
            imgui.text_colored(
                imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
                "Set Renderer to Optix in Preferences")
            imgui.end()
            return

        # ---- RT Mode cycling button ----
        rt_mode = p.optix.rt_mode
        spp_label = str(p.optix.rt_realtime_samples)
        mode_labels = ["RT: Rasterize", f"RT: {spp_label} spp", "RT: Accumulate"]
        if imgui.button(mode_labels[rt_mode]):
            p.optix.rt_mode = (rt_mode + 1) % 3

        # Samples slider (per-mode: rasterize and X-spp each keep their own value)
        if p.optix.rt_mode == 0:
            imgui.same_line()
            imgui.set_next_item_width(100)
            _, p.optix.rz_samples = imgui.slider_int(
                "##rz_samples", p.optix.rz_samples, 1, 8)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Rasterize samples per frame (averaged before denoise)")
        elif p.optix.rt_mode == 1:
            imgui.same_line()
            imgui.set_next_item_width(100)
            _, p.optix.rt_realtime_samples = imgui.slider_int(
                "##rt_samples", p.optix.rt_realtime_samples, 1, 8)

        # Capture SPP + Re-render button
        _, p.optix.rt_preview_spp = imgui.slider_int(
            "Capture SPP", p.optix.rt_preview_spp, 1, 512)
        rt_active = p.optix.rt_mode > 0
        if rt_active:
            imgui.begin_disabled()
        if imgui.button("Re-render Preview"):
            self._request_optix_preview = True
        if rt_active:
            imgui.end_disabled()

        # Progress / status indicator
        pt_interface = getattr(self, '_pathtracer_interface', None)
        if p.optix.rt_mode == 1:
            imgui.same_line()
            imgui.text(f"  [RT {p.optix.rt_realtime_samples} spp]")
        elif p.optix.rt_mode == 2:
            imgui.same_line()
            count = self.state.camera.pathtracer_sample_count
            imgui.text(f"  [accum: {count} spp]")
        elif pt_interface is not None and pt_interface.preview_active:
            imgui.same_line()
            done = pt_interface.preview_samples_done
            target = pt_interface.preview_target_spp
            imgui.text(f"  [{done}/{target} spp]")
        elif pt_interface is not None and pt_interface.preview_has_result:
            imgui.same_line()
            imgui.text(f"  [done: {pt_interface.preview_last_spp} spp]")

        # Resolution scale (applied on Enter key)
        imgui.set_next_item_width(100)
        changed, new_scale = imgui.input_float(
            "Resolution Scale##optix", p.optix.resolution_scale, 0.0, 0.0, "%.2f"
        )
        if imgui.is_item_deactivated_after_edit():
            p.optix.resolution_scale = max(0.1, min(4.0, new_scale))

        imgui.separator()

        # Active lighting model: rasterize (rt_mode 0) vs path trace (rt_mode > 0).
        # Both run on the single OptiX path tracer; the "Rasterize" and
        # "Path Trace" subheadings grey out when the other model is active.
        rasterize = (p.optix.rt_mode == 0)
        default_open = imgui.TreeNodeFlags_.default_open.value

        # ---- Camera (mirrors the 3D Controls "Camera" section; same values) ----
        if imgui.collapsing_header("Camera", default_open):
            cam = self.state.camera
            _, cam.fov = imgui.slider_float(
                "FOV", cam.fov, 10.0, 120.0, format="%.0f deg")
            _, cam.aperture = imgui.slider_float(
                "Aperture", cam.aperture, 0.0, 0.2, format="%.3f")
            _, cam.focal_plane_depth = imgui.slider_float(
                "Focal Depth", cam.focal_plane_depth, 0.1, 50.0, format="%.1f")
            _, cam.move_speed = imgui.slider_float(
                "Move Speed", cam.move_speed, 0.1, 10.0, format="%.1f")
            _, cam.rotate_speed = imgui.slider_float(
                "Rotate Speed", cam.rotate_speed, 0.1, 10.0, format="%.1f")
            changed, values = imgui.drag_float3(
                "Orbit Center", list(cam.orbit_center), 0.01, format="%.2f")
            if changed:
                cam.orbit_center[0], cam.orbit_center[1], cam.orbit_center[2] = values
                if self.tracer_controller_cam is not None:
                    sync_orbit_angles_from_camera(cam, self.tracer_controller_cam)
            _, cam.orbit_rate = imgui.slider_float(
                "Orbit Rate", cam.orbit_rate, -0.05, 0.05, format="%.4f")

        # ---- Geometry (shared) ----
        if imgui.collapsing_header("Geometry", default_open):
            _, p.optix.sphere_radius_scale = imgui.slider_float(
                "Sphere Scale", p.optix.sphere_radius_scale,
                0.1, 10.0, format="%.1fx")
            _, p.optix.sphere_size_jitter = imgui.slider_float(
                "Sphere Jitter", p.optix.sphere_size_jitter,
                0.0, 1.0, format="%.2f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Per-sphere radius jitter to reduce banding artifacts")

            # Curve primitives
            _, p.optix.use_curves = imgui.checkbox(
                "Curves", p.optix.use_curves)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Render entities as round linear curves oriented along velocity")
            if p.optix.use_curves:
                _, p.optix.curve_length = imgui.slider_float(
                    "Curve Length", p.optix.curve_length,
                    0.0, 10.0, format="%.2f")
                _, p.optix.curve_r0 = imgui.slider_float(
                    "Curve R0", p.optix.curve_r0,
                    0.01, 5.0, format="%.2f")
                _, p.optix.curve_r1 = imgui.slider_float(
                    "Curve R1", p.optix.curve_r1,
                    0.01, 5.0, format="%.2f")

            # SDF scene
            _, p.optix.sdf_enabled = imgui.checkbox(
                "Enable SDF", p.optix.sdf_enabled)

        # ---- Lighting (shared LightingPrefs: applies in both modes/renderers) ----
        if imgui.collapsing_header("Lighting", default_open):
            lit = p.lighting
            changed, vals = imgui.drag_float3(
                "Light Dir", list(lit.light_direction),
                0.01, -1.0, 1.0)
            if changed:
                lit.light_direction = list(vals)
            _, lit.light_color = imgui.color_edit3(
                "Light Color", lit.light_color)
            _, lit.light_intensity = imgui.slider_float(
                "Intensity", lit.light_intensity, 0.0, 20.0)

            _, lit.nee = imgui.checkbox(
                "Enable NEE", lit.nee)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Next Event Estimation: trace a shadow ray toward the\n"
                    "light for direct lighting. In rasterize mode, turning\n"
                    "this off leaves only the ambient + AO term.")
            _, p.optix.pt_env_sky_nee = imgui.checkbox(
                "Cos-lobe Sky", p.optix.pt_env_sky_nee)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Replace legacy directional sun + gradient sky\n"
                    "with a cosine-lobe environment model.\n"
                    "Sky color controls hemisphere glow,\n"
                    "sun direction/color/intensity control sun disk.")
            _, lit.photosphere = imgui.checkbox(
                "Photosphere", lit.photosphere)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Use equirectangular environment map for the sky\n"
                    "(queried on primary-ray miss, i.e. the background).")

        # ---- Sky (shared LightingPrefs) ----
        if imgui.collapsing_header("Sky", default_open):
            _, p.lighting.sky_color_top = imgui.color_edit3(
                "Sky Top", p.lighting.sky_color_top)
            _, p.lighting.sky_color_bottom = imgui.color_edit3(
                "Sky Bottom", p.lighting.sky_color_bottom)

        # ---- Material (shared) ----
        if imgui.collapsing_header("Material", default_open):
            mat_labels = ["Lambert", "Glossy", "Mirror"]
            _, p.optix.pt_global_material = imgui.combo(
                "BRDF", p.optix.pt_global_material, mat_labels)
            if p.optix.pt_global_material == 1:  # Glossy
                _, p.optix.pt_glossy_ior = imgui.slider_float(
                    "Glossy IOR", p.optix.pt_glossy_ior, 1.0, 3.0, format="%.2f")
            _, p.optix.albedo_saturation = imgui.slider_float(
                "Albedo Saturation", p.optix.albedo_saturation, 0.0, 1.0)
            _, p.optix.albedo_brightness = imgui.slider_float(
                "Albedo Brightness", p.optix.albedo_brightness, 0.0, 1.0)

        # ---- Rasterize-specific (greyed out in path-trace modes) ----
        if imgui.collapsing_header("Rasterize", default_open):
            if not rasterize:
                imgui.begin_disabled()
            _, p.optix.shadows_enabled = imgui.checkbox(
                "Shadows (rasterize)", p.optix.shadows_enabled)
            _, p.optix.ambient = imgui.slider_float(
                "Ambient (rasterize)", p.optix.ambient, 0.0, 1.0)
            _, p.optix.ambient_color = imgui.color_edit3(
                "Ambient Color", p.optix.ambient_color)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Ambient tint (scaled by Ambient), modulated by AO")

            _, p.optix.rz_depth_of_field = imgui.checkbox(
                "Depth of Field", p.optix.rz_depth_of_field)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Use the thin-lens camera (Aperture / Focal Depth in 3D\n"
                    "Controls) in rasterize mode. Nearly free with the denoiser on.")

            # Ambient Occlusion
            _, p.optix.ao_enabled = imgui.checkbox(
                "Ambient Occlusion (rasterize)", p.optix.ao_enabled)
            if p.optix.ao_enabled:
                _, p.optix.ao_num_rays = imgui.slider_int(
                    "AO Rays", p.optix.ao_num_rays, 1, 16)
                _, p.optix.ao_radius = imgui.slider_float(
                    "AO Radius", p.optix.ao_radius,
                    0.01, 5.0, format="%.2f")
            if not rasterize:
                imgui.end_disabled()

        # ---- Path trace-specific (greyed out in rasterize mode) ----
        if imgui.collapsing_header("Path Trace", default_open):
            if rasterize:
                imgui.begin_disabled()
            _, p.optix.pt_max_bounces = imgui.drag_int(
                "Max Bounces", p.optix.pt_max_bounces, 0.1, 0, 64)
            if imgui.is_item_hovered():
                imgui.set_tooltip("0 = unbounded (Russian roulette only)")
            _, p.optix.pt_rr_start_depth = imgui.slider_int(
                "RR Start Depth", p.optix.pt_rr_start_depth, 1, 16)
            _, p.optix.pt_emission_intensity = imgui.slider_float(
                "Emission Intensity", p.optix.pt_emission_intensity,
                0.0, 100.0, format="%.1f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Radiance multiplier for emissive entities (negative hue)")
            if rasterize:
                imgui.end_disabled()

        # ---- Post-Process (shared) ----
        if imgui.collapsing_header("Post-Process", default_open):
            _, p.optix.pt_firefly_clamp = imgui.checkbox(
                "Firefly Clamp", p.optix.pt_firefly_clamp)
            if p.optix.pt_firefly_clamp:
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                _, p.optix.pt_firefly_clamp_max = imgui.drag_float(
                    "##pt_clamp_max", p.optix.pt_firefly_clamp_max,
                    0.1, 0.1, 1000.0, "Max: %.1f")

            # Denoise: separate toggles per lighting model
            _, p.optix.pt_denoise_enabled = imgui.checkbox(
                "Denoise (path trace)", p.optix.pt_denoise_enabled)
            _, p.optix.rz_denoise_enabled = imgui.checkbox(
                "Denoise (rasterize)", p.optix.rz_denoise_enabled)

        # ---- Timing display ----
        gas_ms = self.state.camera.pathtracer_gas_time_ms
        render_ms = self.state.camera.pathtracer_render_time_ms
        imgui.text_colored(
            imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
            f"GAS {gas_ms:.1f}ms  Render {render_ms:.1f}ms")

        imgui.end()
