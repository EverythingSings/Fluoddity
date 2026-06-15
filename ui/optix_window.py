"""OptiX Controls window: raytracing settings for rasterize and path trace modes."""
from imgui_bundle import imgui


class OptiXWindowMixin:
    """Mixin for the OptiX Controls window. Combined into UI via multiple inheritance."""

    # Preview request flag (set by UI, cleared by orchestrator)
    _request_optix_preview: bool = False

    def render_optix_window(self):
        """Render the OptiX Controls window."""
        visible, opened = imgui.begin("OptiX Controls", True)
        if not opened:
            self.state.preferences.show_optix_window = False
            imgui.end()
            return
        if not visible:
            imgui.end()
            return

        p = self.state.preferences

        if not self.state.camera.optix_enabled:
            imgui.text_colored(
                imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
                "Enable OptiX Spheres in 3D Controls")
            imgui.end()
            return

        # ---- RT Mode cycling button ----
        rt_mode = p.three_d_rt_mode
        spp_label = str(p.three_d_rt_realtime_samples)
        mode_labels = ["RT: Rasterize", f"RT: {spp_label} spp", "RT: Accumulate"]
        if imgui.button(mode_labels[rt_mode]):
            p.three_d_rt_mode = (rt_mode + 1) % 3

        # Realtime samples slider (only for X spp mode)
        if p.three_d_rt_mode == 1:
            imgui.same_line()
            imgui.set_next_item_width(100)
            _, p.three_d_rt_realtime_samples = imgui.slider_int(
                "##rt_samples", p.three_d_rt_realtime_samples, 1, 8)

        # Capture SPP + Re-render button
        _, p.three_d_rt_preview_spp = imgui.slider_int(
            "Capture SPP", p.three_d_rt_preview_spp, 1, 512)
        rt_active = p.three_d_rt_mode > 0
        if rt_active:
            imgui.begin_disabled()
        if imgui.button("Re-render Preview"):
            self._request_optix_preview = True
        if rt_active:
            imgui.end_disabled()

        # Progress / status indicator
        pt_interface = getattr(self, '_pathtracer_interface', None)
        if p.three_d_rt_mode == 1:
            imgui.same_line()
            imgui.text(f"  [RT {p.three_d_rt_realtime_samples} spp]")
        elif p.three_d_rt_mode == 2:
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

        imgui.separator()

        # ---- Shared controls ----
        _, p.three_d_optix_gas_rebuild_interval = imgui.slider_int(
            "GAS Rebuild", p.three_d_optix_gas_rebuild_interval, 1, 120)
        _, p.three_d_optix_sphere_radius_scale = imgui.slider_float(
            "Sphere Scale", p.three_d_optix_sphere_radius_scale,
            0.1, 10.0, format="%.1fx")
        _, p.three_d_optix_sphere_size_jitter = imgui.slider_float(
            "Sphere Jitter", p.three_d_optix_sphere_size_jitter,
            0.0, 1.0, format="%.2f")
        if imgui.is_item_hovered():
            imgui.set_tooltip("Per-sphere radius jitter to reduce banding artifacts")

        # Albedo color controls
        _, p.three_d_optix_albedo_saturation = imgui.slider_float(
            "Albedo Saturation", p.three_d_optix_albedo_saturation, 0.0, 1.0)
        _, p.three_d_optix_albedo_brightness = imgui.slider_float(
            "Albedo Brightness", p.three_d_optix_albedo_brightness, 0.0, 1.0)

        # SDF scene
        _, p.three_d_optix_sdf_enabled = imgui.checkbox(
            "Enable SDF", p.three_d_optix_sdf_enabled)

        # ---- Lighting (shared) ----
        if imgui.collapsing_header("Lighting", imgui.TreeNodeFlags_.default_open.value):
            changed, vals = imgui.drag_float3(
                "Light Dir", list(p.three_d_optix_light_direction),
                0.01, -1.0, 1.0)
            if changed:
                p.three_d_optix_light_direction = list(vals)
            _, p.three_d_optix_light_color = imgui.color_edit3(
                "Light Color", p.three_d_optix_light_color)
            _, p.three_d_optix_light_intensity = imgui.slider_float(
                "Intensity", p.three_d_optix_light_intensity, 0.0, 20.0)

        # ---- Sky (shared) ----
        if imgui.collapsing_header("Sky", imgui.TreeNodeFlags_.default_open.value):
            _, p.three_d_optix_sky_color_top = imgui.color_edit3(
                "Sky Top", p.three_d_optix_sky_color_top)
            _, p.three_d_optix_sky_color_bottom = imgui.color_edit3(
                "Sky Bottom", p.three_d_optix_sky_color_bottom)

        # ---- Rasterize-specific (always visible) ----
        if imgui.collapsing_header("Rasterize", imgui.TreeNodeFlags_.default_open.value):
            _, p.three_d_optix_shadows_enabled = imgui.checkbox(
                "Shadows (rasterize)", p.three_d_optix_shadows_enabled)
            _, p.three_d_optix_ambient = imgui.slider_float(
                "Ambient (rasterize)", p.three_d_optix_ambient, 0.0, 1.0)

            # Ambient Occlusion
            _, p.three_d_optix_ao_enabled = imgui.checkbox(
                "Ambient Occlusion (rasterize)", p.three_d_optix_ao_enabled)
            if p.three_d_optix_ao_enabled:
                _, p.three_d_optix_ao_num_rays = imgui.slider_int(
                    "AO Rays", p.three_d_optix_ao_num_rays, 1, 16)
                _, p.three_d_optix_ao_radius = imgui.slider_float(
                    "AO Radius", p.three_d_optix_ao_radius,
                    0.01, 5.0, format="%.2f")

        # ---- Path trace-specific (always visible) ----
        if imgui.collapsing_header("Path Trace", imgui.TreeNodeFlags_.default_open.value):
            _, p.three_d_pt_sun_sampling = imgui.checkbox(
                "Sun Sampling NEE (path trace)", p.three_d_pt_sun_sampling)

            # Material
            mat_labels = ["Lambert", "Glossy", "Mirror"]
            _, p.three_d_pt_global_material = imgui.combo(
                "Material (path trace)", p.three_d_pt_global_material, mat_labels)
            if p.three_d_pt_global_material == 1:  # Glossy
                _, p.three_d_pt_glossy_ior = imgui.slider_float(
                    "Glossy IOR", p.three_d_pt_glossy_ior, 1.0, 3.0, format="%.2f")

            # Render settings
            _, p.three_d_pt_max_bounces = imgui.drag_int(
                "Max Bounces (path trace)", p.three_d_pt_max_bounces, 0.1, 0, 64)
            if imgui.is_item_hovered():
                imgui.set_tooltip("0 = unbounded (Russian roulette only)")
            _, p.three_d_pt_rr_start_depth = imgui.slider_int(
                "RR Start Depth (path trace)", p.three_d_pt_rr_start_depth, 1, 16)
            _, p.three_d_pt_firefly_clamp = imgui.checkbox(
                "Firefly Clamp (path trace)", p.three_d_pt_firefly_clamp)
            if p.three_d_pt_firefly_clamp:
                imgui.same_line()
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                _, p.three_d_pt_firefly_clamp_max = imgui.drag_float(
                    "##pt_clamp_max", p.three_d_pt_firefly_clamp_max,
                    0.1, 0.1, 1000.0, "Max: %.1f")
            _, p.three_d_pt_denoise_enabled = imgui.checkbox(
                "Denoise (path trace)", p.three_d_pt_denoise_enabled)

        # ---- Timing display ----
        if p.three_d_rt_mode > 0:
            gas_ms = self.state.camera.pathtracer_gas_time_ms
            render_ms = self.state.camera.pathtracer_render_time_ms
        else:
            gas_ms = self.state.camera.optix_gas_time_ms
            render_ms = self.state.camera.optix_render_time_ms
        imgui.text_colored(
            imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
            f"GAS {gas_ms:.1f}ms  Render {render_ms:.1f}ms")

        imgui.end()
