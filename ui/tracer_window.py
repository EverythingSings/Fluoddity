"""Tracer window: volumetric path tracer controls and rendered image display."""
from imgui_bundle import imgui


class TracerWindowMixin:
    """Mixin for the Tracer window. Combined into UI via multiple inheritance."""

    def render_tracer_window(self):
        """Render the Tracer window with volrender controls and image display."""
        visible, opened = imgui.begin("Tracer", True)
        if not opened:
            self.state.preferences.ui_windows.show_tracer_window = False
            imgui.end()
            return
        if not visible:
            imgui.end()
            return

        # Lazy-create TracerInterface
        if self._tracer_interface is None:
            from tracer_interface import TracerInterface
            self._tracer_interface = TracerInterface(self.ctx)
            self._apply_tracer_preferences(self._tracer_interface)

        ti = self._tracer_interface

        # Tick progressive render if active (1 SPP per app frame)
        # Skip during tracer video recording — the orchestrator drives accumulation
        recording_tracer = (self._display_info.get('recording_active', False)
                            and self.state.preferences.recording.tracer_mode)
        if ti.is_rendering and not recording_tracer and ti.realtime_mode == 0:
            ti.tick()

        # ---- Grid Resolutions ----
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

        # ---- Medium ----
        if imgui.collapsing_header("Medium", imgui.TreeNodeFlags_.default_open.value):
            _, ti.colored_extinction = imgui.checkbox(
                "Colored Extinction", ti.colored_extinction)
            if ti.colored_extinction:
                # Colored extinction: RGB picker is albedo, sliders are extinction
                _, ti.extinction_rgb = imgui.color_edit3(
                    "Albedo RGB", ti.extinction_rgb)
                _, ti.albedo_saturation = imgui.slider_float(
                    "Ext Saturation", ti.albedo_saturation, 0.0, 1.0)
                _, ti.albedo_brightness = imgui.slider_float(
                    "Ext Brightness", ti.albedo_brightness, 0.0, 1.0)
            else:
                # Legacy: RGB picker is extinction, sliders are albedo
                _, ti.extinction_rgb = imgui.color_edit3(
                    "Extinction RGB", ti.extinction_rgb)
                _, ti.albedo_saturation = imgui.slider_float(
                    "Albedo Saturation", ti.albedo_saturation, 0.0, 1.0)
                _, ti.albedo_brightness = imgui.slider_float(
                    "Albedo Brightness", ti.albedo_brightness, 0.0, 1.0)
            _, ti.density_scale = imgui.drag_float(
                "Density Scale", ti.density_scale, 0.00001, 0.00001, 10.0, "%.5f")
            _, ti.hg_g = imgui.slider_float(
                "Scattering (g)", ti.hg_g, -1.0, 1.0)
            if imgui.is_item_hovered():
                imgui.set_tooltip("HG phase: -1 back, 0 isotropic, +1 forward")
            _, ti.emission_strength = imgui.drag_float(
                "Emission", ti.emission_strength, 0.01, 0.0, 100.0, "%.3f")
            if imgui.is_item_hovered():
                imgui.set_tooltip("Self-emission intensity (0 = off)")

        # ---- Sun ----
        if imgui.collapsing_header("Sun", imgui.TreeNodeFlags_.default_open.value):
            _, ti.sun_direction = imgui.drag_float3(
                "Direction", ti.sun_direction, 0.01, -1.0, 1.0)
            _, ti.sun_color = imgui.color_edit3(
                "Sun Color", ti.sun_color)
            _, ti.sun_intensity = imgui.slider_float(
                "Sun Intensity", ti.sun_intensity, 0.0, 20.0)

        # ---- Sky ----
        if imgui.collapsing_header("Sky", imgui.TreeNodeFlags_.default_open.value):
            _, ti.sky_color = imgui.color_edit3(
                "Sky Color", ti.sky_color)
            _, ti.sky_intensity = imgui.slider_float(
                "Sky Intensity", ti.sky_intensity, 0.0, 5.0)

            changed_photo, ti.photosphere = imgui.checkbox(
                "Photosphere", ti.photosphere)
            if changed_photo and ti.photosphere:
                if ti._skybox_tex is None:
                    ti._skybox_tex = ti._load_skybox()
                if ti._skybox_tex is None:
                    ti.photosphere = False
            imgui.same_line()
            _, ti.sun_sampling = imgui.checkbox("Sun Sampling", ti.sun_sampling)

        # ---- SDF Scene ----
        if imgui.collapsing_header("SDF Scene", imgui.TreeNodeFlags_.default_open.value):
            _, ti.sdf_enabled = imgui.checkbox("Enable SDF", ti.sdf_enabled)

        # ---- Render ----
        if imgui.collapsing_header("Render", imgui.TreeNodeFlags_.default_open.value):
            _, ti.num_samples = imgui.slider_int(
                "Samples (SPP)", ti.num_samples, 1, 512)
            _, ti.exposure = imgui.slider_float(
                "Exposure", ti.exposure, 0.1, 10.0)
            _, ti.max_bounces = imgui.drag_int(
                "Max Bounces", ti.max_bounces, 0.1, 0, 64)
            if imgui.is_item_hovered():
                imgui.set_tooltip("0 = unbounded (Russian roulette only)")

            _, ti.firefly_clamp = imgui.checkbox(
                "Firefly Clamp", ti.firefly_clamp)
            if ti.firefly_clamp:
                imgui.same_line()
                imgui.set_next_item_width(imgui.get_content_region_avail().x)
                _, ti.firefly_clamp_max = imgui.drag_float(
                    "##clamp_max", ti.firefly_clamp_max, 0.1, 0.1, 1000.0, "Max: %.1f")

            # Resolution scale (applied on Enter key)
            imgui.set_next_item_width(100)
            changed, new_scale = imgui.input_float(
                "Resolution Scale", ti.resolution_scale, 0.0, 0.0, "%.2f"
            )
            if imgui.is_item_deactivated_after_edit():
                ti.resolution_scale = max(0.1, min(4.0, new_scale))
            # Realtime tracer mode cycling button
            mode_labels = ["RT: Off", "RT: 1spp", "RT: Accumulate"]
            if imgui.button(mode_labels[ti.realtime_mode]):
                ti.realtime_mode = (ti.realtime_mode + 1) % 3

            rt_active = ti.realtime_mode > 0
            if rt_active:
                imgui.begin_disabled()
            if imgui.button("Re-render"):
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

        imgui.end()

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
        ti.sun_direction = list(p.tracer.sun_direction)
        ti.sun_color = list(p.tracer.sun_color)
        ti.sun_intensity = p.tracer.sun_intensity
        ti.sky_color = list(p.tracer.sky_color)
        ti.sky_intensity = p.tracer.sky_intensity
        ti.sun_sampling = p.tracer.sun_sampling
        ti.photosphere = p.tracer.photosphere
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

        # Compute view_proj from the FPS controller camera
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
