"""Render settings window: unified per-renderer controls.

One window that shows the active renderer's settings (Preferences -> Renderer):
- OpenGL: the volumetric path tracer (medium / lighting / sky / post-process).
- Optix:  the OptiX path tracer (geometry / material / lighting / sky /
          rasterize / path-trace / post-process).

The first two sections (RT mode + capture, then Camera) are shared and use the
OptiX Controls labeling/layout. Merged from the former 3D Controls, OptiX
Controls, and Tracer windows in the 3D-only cleanup.
"""
from imgui_bundle import imgui
from camera_input import sync_orbit_angles_from_camera


class RenderSettingsWindowMixin:
    """Mixin for the unified Render settings window."""

    # Preview request flag (set by UI, cleared by orchestrator) — OptiX preview.
    _request_optix_preview: bool = False

    def render_render_settings_window(self):
        """Render the unified Render settings window for the active renderer."""
        visible, opened = imgui.begin("Render settings", True)
        if not opened:
            self.state.preferences.ui_windows.show_render_settings_window = False
            imgui.end()
            return
        if not visible:
            imgui.end()
            return

        # Shared appearance controls at the very top (both renderers).
        self._render_appearance_top()
        imgui.separator()

        if self.state.preferences.rendering.renderer == 1:
            self._render_optix_settings()
        else:
            self._render_opengl_settings()

        imgui.end()

    # ------------------------------------------------------------------ shared
    def _render_appearance_top(self):
        """Brightness + Tonemap Softness — shown at the top for both renderers."""
        r = self.state.preferences.rendering
        _, r.brightness = imgui.slider_float(
            "Brightness", r.brightness, 0.01, 10.0, format="%.2f")
        if imgui.is_item_hovered():
            imgui.set_tooltip("Global brightness multiplier for the output.")
        _, r.tonemap_softness = imgui.slider_float(
            "Tonemap Softness", r.tonemap_softness, 0.1, 5.0, format="%.2f")
        if imgui.is_item_hovered():
            imgui.set_tooltip(
                "Controls highlight compression (asinh stretch).\n"
                "Low = more linear (brighter highlights).\n"
                "High = more logarithmic (reveals faint detail).")

    def _render_bloom_controls(self):
        """Bloom checkbox + sliders — shared, shown inside Post-Process.

        Disabled in watercolor mode (bloom does not apply there).
        """
        b = self.state.preferences.bloom
        watercolor_active = self.state.sim.watercolor_mode
        if watercolor_active:
            imgui.begin_disabled()
        _, b.enabled = imgui.checkbox("Bloom", b.enabled)
        if imgui.is_item_hovered():
            imgui.set_tooltip("Bloom is disabled in Watercolor mode."
                              if watercolor_active else
                              "Add a glow effect around bright areas.")
        if b.enabled and not watercolor_active:
            imgui.indent(20)
            _, b.threshold = imgui.slider_float("Threshold", b.threshold, 0.0, 2.0, format="%.2f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Brightness cutoff for bloom extraction.\nLower = more glow everywhere.")
            _, b.intensity = imgui.slider_float("Intensity", b.intensity, 0.0, 3.0, format="%.2f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Strength of the bloom glow.")
            _, b.radius = imgui.slider_float("Radius", b.radius, 0.1, 3.0, format="%.2f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Spread of the bloom blur kernel.")
            imgui.unindent(20)
        if watercolor_active:
            imgui.end_disabled()

    def _render_camera_section(self):
        """Camera section — identical for both renderers (shared camera state)."""
        default_open = imgui.TreeNodeFlags_.default_open.value
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

    def _render_lighting_section(self):
        """Lighting section — shared LightingPrefs, identical for both renderers.

        (Photosphere + Enable NEE live here; the OptiX-only Cos-lobe Sky toggle
        is added by the OptiX path.)
        """
        default_open = imgui.TreeNodeFlags_.default_open.value
        if imgui.collapsing_header("Lighting", default_open):
            lit = self.state.preferences.lighting
            changed, vals = imgui.drag_float3(
                "Light Dir", list(lit.light_direction), 0.01, -1.0, 1.0)
            if changed:
                lit.light_direction = list(vals)
            _, lit.light_color = imgui.color_edit3(
                "Light Color", lit.light_color)
            _, lit.light_intensity = imgui.slider_float(
                "Intensity", lit.light_intensity, 0.0, 20.0)

            _, lit.nee = imgui.checkbox("Enable NEE", lit.nee)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Next Event Estimation: trace a shadow ray toward the\n"
                    "light for direct lighting. In rasterize mode, turning\n"
                    "this off leaves only the ambient + AO term.")
            # OptiX-only cos-lobe sky toggle (added by caller when in Optix mode)
            if self.state.preferences.rendering.renderer == 1:
                _, self.state.preferences.optix.pt_env_sky_nee = imgui.checkbox(
                    "Cos-lobe Sky", self.state.preferences.optix.pt_env_sky_nee)
                if imgui.is_item_hovered():
                    imgui.set_tooltip(
                        "Replace legacy directional sun + gradient sky\n"
                        "with a cosine-lobe environment model.\n"
                        "Sky color controls hemisphere glow,\n"
                        "sun direction/color/intensity control sun disk.")
            changed_photo, lit.photosphere = imgui.checkbox(
                "Photosphere", lit.photosphere)
            if imgui.is_item_hovered():
                imgui.set_tooltip(
                    "Use equirectangular environment map for the sky\n"
                    "(queried on primary-ray miss, i.e. the background).")
            # On the OpenGL side the photosphere needs its skybox texture loaded.
            if (changed_photo and lit.photosphere
                    and self.state.preferences.rendering.renderer == 0):
                ti = self._tracer_interface
                if ti is not None:
                    if ti._skybox_tex is None:
                        ti._skybox_tex = ti._load_skybox()
                    if ti._skybox_tex is None:
                        lit.photosphere = False

    def _render_sky_section(self):
        """Sky section — two-tone gradient from the shared LightingPrefs."""
        default_open = imgui.TreeNodeFlags_.default_open.value
        if imgui.collapsing_header("Sky", default_open):
            lit = self.state.preferences.lighting
            _, lit.sky_color_top = imgui.color_edit3("Sky Top", lit.sky_color_top)
            _, lit.sky_color_bottom = imgui.color_edit3("Sky Bottom", lit.sky_color_bottom)
            if self.state.preferences.rendering.renderer == 0:
                # Sky intensity applies to the volumetric tracer's gradient.
                _, lit.sky_intensity = imgui.slider_float(
                    "Sky Intensity", lit.sky_intensity, 0.0, 5.0)

    # ------------------------------------------------------------------- OptiX
    def _render_optix_settings(self):
        p = self.state.preferences
        default_open = imgui.TreeNodeFlags_.default_open.value

        # ---- RT Mode cycling button + unlabeled samples slider ----
        rt_mode = p.optix.rt_mode
        spp_label = str(p.optix.rt_realtime_samples)
        mode_labels = ["RT: Rasterize", f"RT: {spp_label} spp", "RT: Accumulate"]
        if imgui.button(mode_labels[rt_mode]):
            p.optix.rt_mode = (rt_mode + 1) % 3
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

        # ---- Capture SPP + Re-render Preview ----
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

        # ---- Resolution Scale (applied on Enter key) ----
        imgui.set_next_item_width(100)
        changed, new_scale = imgui.input_float(
            "Resolution Scale##optix", p.optix.resolution_scale, 0.0, 0.0, "%.2f")
        if imgui.is_item_deactivated_after_edit():
            p.optix.resolution_scale = max(0.1, min(4.0, new_scale))

        imgui.separator()

        rasterize = (p.optix.rt_mode == 0)

        # ---- Camera (shared) ----
        self._render_camera_section()

        # ---- Geometry ----
        if imgui.collapsing_header("Geometry", default_open):
            _, p.optix.sphere_radius_scale = imgui.slider_float(
                "Sphere Scale", p.optix.sphere_radius_scale,
                0.1, 10.0, format="%.1fx")
            _, p.optix.sphere_size_jitter = imgui.slider_float(
                "Sphere Jitter", p.optix.sphere_size_jitter,
                0.0, 1.0, format="%.2f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Per-sphere radius jitter to reduce banding artifacts")

            _, p.optix.use_curves = imgui.checkbox("Curves", p.optix.use_curves)
            if imgui.is_item_hovered():
                imgui.set_tooltip("Render entities as round linear curves oriented along velocity")
            if p.optix.use_curves:
                _, p.optix.curve_length = imgui.slider_float(
                    "Curve Length", p.optix.curve_length, 0.0, 10.0, format="%.2f")
                _, p.optix.curve_r0 = imgui.slider_float(
                    "Curve R0", p.optix.curve_r0, 0.01, 5.0, format="%.2f")
                _, p.optix.curve_r1 = imgui.slider_float(
                    "Curve R1", p.optix.curve_r1, 0.01, 5.0, format="%.2f")

            _, p.optix.sdf_enabled = imgui.checkbox("Enable SDF", p.optix.sdf_enabled)

        # ---- Material (moved to between Geometry and Lighting) ----
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

        # ---- Lighting (shared) + Sky (shared) ----
        self._render_lighting_section()
        self._render_sky_section()

        # ---- Rasterize-specific (greyed out in path-trace modes) ----
        if imgui.collapsing_header("Rasterize", default_open):
            if not rasterize:
                imgui.begin_disabled()
            # (The "Shadows (rasterize)" checkbox was removed — always on.)
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
                    "Use the thin-lens camera (Aperture / Focal Depth in the\n"
                    "Camera section) in rasterize mode. Nearly free with the denoiser on.")

            _, p.optix.ao_enabled = imgui.checkbox(
                "Ambient Occlusion (rasterize)", p.optix.ao_enabled)
            if p.optix.ao_enabled:
                _, p.optix.ao_num_rays = imgui.slider_int(
                    "AO Rays", p.optix.ao_num_rays, 1, 16)
                _, p.optix.ao_radius = imgui.slider_float(
                    "AO Radius", p.optix.ao_radius, 0.01, 5.0, format="%.2f")
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

        # ---- Post-Process ----
        if imgui.collapsing_header("Post-Process", default_open):
            _, p.optix.pt_firefly_clamp = imgui.checkbox(
                "Firefly Clamp", p.optix.pt_firefly_clamp)
            if p.optix.pt_firefly_clamp:
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                _, p.optix.pt_firefly_clamp_max = imgui.drag_float(
                    "##pt_clamp_max", p.optix.pt_firefly_clamp_max,
                    0.1, 0.1, 1000.0, "Max: %.1f")

            _, p.optix.pt_denoise_enabled = imgui.checkbox(
                "Denoise (path trace)", p.optix.pt_denoise_enabled)
            _, p.optix.rz_denoise_enabled = imgui.checkbox(
                "Denoise (rasterize)", p.optix.rz_denoise_enabled)

            self._render_bloom_controls()

        # ---- Timing display ----
        gas_ms = self.state.camera.pathtracer_gas_time_ms
        render_ms = self.state.camera.pathtracer_render_time_ms
        imgui.text_colored(
            imgui.ImVec4(0.6, 0.6, 0.6, 1.0),
            f"GAS {gas_ms:.1f}ms  Render {render_ms:.1f}ms")

    # ------------------------------------------------------------------ OpenGL
    def _render_opengl_settings(self):
        default_open = imgui.TreeNodeFlags_.default_open.value

        # Lazy-create the TracerInterface (owns the volumetric renderer).
        if self._tracer_interface is None:
            from tracer_interface import TracerInterface
            self._tracer_interface = TracerInterface(self.ctx)
            self._apply_tracer_preferences(self._tracer_interface)
        ti = self._tracer_interface

        # Tick progressive render if active (1 SPP per app frame). Skip during
        # tracer video recording — the orchestrator drives accumulation.
        recording_tracer = (self._display_info.get('recording_active', False)
                            and self.state.preferences.tracer.realtime_mode > 0)
        if ti.is_rendering and not recording_tracer and ti.realtime_mode == 0:
            ti.tick()

        # ---- RT Mode cycling button ----
        # OpenGL RT modes: Off / 1spp / Accumulate. (The volumetric tracer has no
        # per-frame sample count, so the RT-adjacent samples slot OptiX shows is
        # omitted here — Capture SPP below is the only sample control.)
        rt_labels = ["RT: Off", "RT: 1spp", "RT: Accumulate"]
        if imgui.button(rt_labels[ti.realtime_mode]):
            ti.realtime_mode = (ti.realtime_mode + 1) % 3

        # ---- Capture SPP + Re-render ----
        _, ti.num_samples = imgui.slider_int("Capture SPP", ti.num_samples, 1, 512)
        rt_active = ti.realtime_mode > 0
        if rt_active:
            imgui.begin_disabled()
        if imgui.button("Re-render Preview"):
            self._do_tracer_render(ti)
        if rt_active:
            imgui.end_disabled()

        # Progress / status indicator
        if ti.realtime_mode == 1:
            imgui.same_line()
            imgui.text("  [RT 1spp]")
        elif ti.realtime_mode == 2:
            imgui.same_line()
            imgui.text(f"  [RT accum: {ti.samples_done} spp]")
        elif ti.is_rendering:
            imgui.same_line()
            imgui.text(f"  [{ti.samples_done}/{ti.num_samples} spp]")
        elif ti.has_result:
            imgui.same_line()
            imgui.text(f"  [done: {ti.last_spp} spp]")

        # ---- Resolution Scale (applied on Enter key) ----
        imgui.set_next_item_width(100)
        changed, new_scale = imgui.input_float(
            "Resolution Scale", ti.resolution_scale, 0.0, 0.0, "%.2f")
        if imgui.is_item_deactivated_after_edit():
            ti.resolution_scale = max(0.1, min(4.0, new_scale))

        imgui.separator()

        # ---- Camera (shared) ----
        self._render_camera_section()

        # ---- Medium (Enable SDF moved to the bottom of this section) ----
        if imgui.collapsing_header("Medium", default_open):
            _, ti.colored_extinction = imgui.checkbox(
                "Colored Extinction", ti.colored_extinction)
            if ti.colored_extinction:
                _, ti.extinction_rgb = imgui.color_edit3("Albedo RGB", ti.extinction_rgb)
                _, ti.albedo_saturation = imgui.slider_float(
                    "Ext Saturation", ti.albedo_saturation, 0.0, 1.0)
                _, ti.albedo_brightness = imgui.slider_float(
                    "Ext Brightness", ti.albedo_brightness, 0.0, 1.0)
            else:
                _, ti.extinction_rgb = imgui.color_edit3("Extinction RGB", ti.extinction_rgb)
                _, ti.albedo_saturation = imgui.slider_float(
                    "Albedo Saturation", ti.albedo_saturation, 0.0, 1.0)
                _, ti.albedo_brightness = imgui.slider_float(
                    "Albedo Brightness", ti.albedo_brightness, 0.0, 1.0)
            _, ti.density_scale = imgui.drag_float(
                "Density Scale", ti.density_scale, 0.00001, 0.00001, 10.0, "%.5f")
            _, ti.hg_g = imgui.slider_float("Scattering (g)", ti.hg_g, -1.0, 1.0)
            if imgui.is_item_hovered():
                imgui.set_tooltip("HG phase: -1 back, 0 isotropic, +1 forward")
            _, ti.emission_strength = imgui.drag_float(
                "Emission", ti.emission_strength, 0.01, 0.0, 100.0, "%.3f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Self-emission intensity (0 = off)")
            _, ti.exposure = imgui.slider_float("Exposure", ti.exposure, 0.1, 10.0)
            _, ti.max_bounces = imgui.drag_int("Max Bounces", ti.max_bounces, 0.1, 0, 64)
            if imgui.is_item_hovered():
                imgui.set_tooltip("0 = unbounded (Russian roulette only)")
            # Enable SDF at the bottom of Medium (was a separate "SDF Scene" header)
            _, ti.sdf_enabled = imgui.checkbox("Enable SDF", ti.sdf_enabled)

        # ---- Lighting (shared) + Sky (shared) ----
        self._render_lighting_section()
        self._render_sky_section()

        # ---- Post Process (Firefly clamp, OptiX formatting; + shared Bloom) ----
        if imgui.collapsing_header("Post Process", default_open):
            _, ti.firefly_clamp = imgui.checkbox("Firefly Clamp", ti.firefly_clamp)
            if ti.firefly_clamp:
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                _, ti.firefly_clamp_max = imgui.drag_float(
                    "##clamp_max", ti.firefly_clamp_max, 0.1, 0.1, 1000.0, "Max: %.1f")

            self._render_bloom_controls()

        # Advanced grid resolutions (kept, collapsed by default).
        if imgui.collapsing_header("Grid Resolutions"):
            _, ti.density_resolution_log2 = imgui.slider_int(
                "Density (2^n)", ti.density_resolution_log2, 5, 10)
            if imgui.is_item_hovered():
                d = 2 ** ti.density_resolution_log2
                imgui.set_tooltip(f"{d}x{d}x{d}  ({d**3 * 4 / 1024**2:.0f} MB)")
            _, ti.color_resolution_log2 = imgui.slider_int(
                "Color (2^n)", ti.color_resolution_log2, 5, 10)
            if imgui.is_item_hovered():
                c = 2 ** ti.color_resolution_log2
                imgui.set_tooltip(f"{c}x{c}x{c}  ({c**3 * 4 * 2 / 1024**2:.0f} MB, 2 channels)")
            _, ti.majorant_resolution_log2 = imgui.slider_int(
                "Majorant (2^n)", ti.majorant_resolution_log2, 3, 8)
            if imgui.is_item_hovered():
                m = 2 ** ti.majorant_resolution_log2
                imgui.set_tooltip(f"{m}x{m}x{m}")
            d = 2 ** ti.density_resolution_log2
            c = 2 ** ti.color_resolution_log2
            m = 2 ** ti.majorant_resolution_log2
            vram_mb = (d**3 * 4 + c**3 * 4 * 2 + m**3 * 4) / 1024**2
            imgui.text(f"VRAM: ~{vram_mb:.0f} MB")

        # ---- Image display (only in Off mode; realtime renders fullscreen) ----
        if ti.realtime_mode == 0 and ti.display_texture is not None:
            imgui.separator()
            tex_id = imgui.ImTextureRef(ti.display_texture.glo)
            avail_width = imgui.get_content_region_avail().x
            tex_w, tex_h = ti.display_texture.size
            aspect = tex_h / tex_w if tex_w > 0 else 1.0
            display_height = avail_width * aspect
            imgui.image(
                tex_id,
                imgui.ImVec2(avail_width, display_height),
                uv0=imgui.ImVec2(0, 1),
                uv1=imgui.ImVec2(1, 0),
            )

    # ---------------------------------------------------- tracer helpers (moved)
    def _apply_tracer_preferences(self, ti):
        """Apply saved tracer preferences to a newly created TracerInterface."""
        p = self.state.preferences
        ti.colored_extinction = p.tracer.colored_extinction
        ti.sdf_enabled = p.tracer.sdf_enabled
        ti.extinction_rgb = list(p.tracer.extinction_rgb)
        ti.albedo_saturation = p.tracer.albedo_saturation
        ti.albedo_brightness = p.tracer.albedo_brightness
        ti.density_scale = p.tracer.density_scale
        ti.hg_g = p.tracer.hg_g
        ti.emission_strength = p.tracer.emission_strength
        # Sun + sky from the shared LightingPrefs slice (unified across renderers)
        ti.sun_direction = list(p.lighting.light_direction)
        ti.sun_color = list(p.lighting.light_color)
        ti.sun_intensity = p.lighting.light_intensity
        ti.sky_color_top = list(p.lighting.sky_color_top)
        ti.sky_color_bottom = list(p.lighting.sky_color_bottom)
        ti.sky_intensity = p.lighting.sky_intensity
        ti.sun_sampling = p.lighting.nee
        ti.photosphere = p.lighting.photosphere
        if ti.photosphere:
            ti._skybox_tex = ti._load_skybox()
            if ti._skybox_tex is None:
                ti.photosphere = False
        ti.num_samples = p.tracer.num_samples
        ti.exposure = p.tracer.exposure
        ti.realtime_mode = p.tracer.realtime_mode
        ti.max_bounces = p.tracer.max_bounces
        ti.firefly_clamp = p.tracer.firefly_clamp
        ti.firefly_clamp_max = p.tracer.firefly_clamp_max
        ti.resolution_scale = p.tracer.resolution_scale
        ti.density_resolution_log2 = p.tracer.density_resolution_log2
        ti.color_resolution_log2 = p.tracer.color_resolution_log2
        ti.majorant_resolution_log2 = p.tracer.majorant_resolution_log2

    def _do_tracer_render(self, ti):
        """Start a progressive tracer render using the current entity buffer and camera."""
        if self.tracer_sim is None or self.tracer_camera is None:
            return

        entity_buffer = self.tracer_sim.get_entity_buffer()
        entity_count = self.tracer_sim.entity_count

        # Sync DOF from camera state
        ti.aperture = self.state.camera.aperture
        ti.focal_plane_depth = self.state.camera.focal_plane_depth

        cam = self.tracer_controller_cam
        if cam is None:
            return
        scale = max(0.1, ti.resolution_scale)
        render_width = max(1, int(512 * scale))
        render_height = max(1, int(512 * scale))
        render_aspect = render_width / render_height
        view_proj = self.tracer_camera.compute_fps_view_proj(
            cam.pos, cam.dir, cam.up, cam.fov, render_aspect
        )
        cam_right, cam_up = self.tracer_camera.compute_fps_camera_basis(
            cam.dir, cam.up
        )

        ti.start_render(entity_buffer, entity_count, view_proj,
                        width=render_width, height=render_height,
                        camera_right=cam_right, camera_up=cam_up)
