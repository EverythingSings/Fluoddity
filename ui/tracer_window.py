"""Tracer window: volumetric path tracer controls and rendered image display."""
from imgui_bundle import imgui


class TracerWindowMixin:
    """Mixin for the Tracer window. Combined into UI via multiple inheritance."""

    def render_tracer_window(self):
        """Render the Tracer window with volrender controls and image display."""
        visible, opened = imgui.begin("Tracer", True)
        if not opened:
            self.state.preferences.show_tracer_window = False
            imgui.end()
            return
        if not visible:
            imgui.end()
            return

        # Lazy-create TracerInterface
        if self._tracer_interface is None:
            from tracer_interface import TracerInterface
            self._tracer_interface = TracerInterface(self.ctx)

        ti = self._tracer_interface

        # Tick progressive render if active (1 SPP per app frame)
        # Skip during tracer video recording — the orchestrator drives accumulation
        recording_tracer = (self._display_info.get('recording_active', False)
                            and self.state.preferences.tracer_mode)
        if ti.is_rendering and not recording_tracer:
            ti.tick()

        # ---- Medium ----
        if imgui.collapsing_header("Medium", imgui.TreeNodeFlags_.default_open.value):
            _, ti.extinction_rgb = imgui.color_edit3(
                "Extinction RGB", ti.extinction_rgb)
            _, ti.albedo_rgb = imgui.color_edit3(
                "Albedo RGB", ti.albedo_rgb)
            _, ti.density_scale = imgui.drag_float(
                "Density Scale", ti.density_scale, 0.00001, 0.00001, 10.0, "%.5f")

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

        # ---- Render ----
        if imgui.collapsing_header("Render", imgui.TreeNodeFlags_.default_open.value):
            _, ti.num_samples = imgui.slider_int(
                "Samples (SPP)", ti.num_samples, 1, 512)
            _, ti.exposure = imgui.slider_float(
                "Exposure", ti.exposure, 0.1, 10.0)

            if imgui.button("Re-render"):
                self._do_tracer_render(ti)

            # Progress indicator
            if ti.is_rendering:
                imgui.same_line()
                imgui.text(f"  [{ti.samples_done}/{ti.num_samples} spp]")
            elif ti.has_result:
                imgui.same_line()
                imgui.text(f"  [done: {ti.last_spp} spp]")

        # ---- Image display ----
        if ti.display_texture is not None:
            imgui.separator()
            tex_id = imgui.ImTextureRef(ti.display_texture.glo)
            avail_width = imgui.get_content_region_avail().x
            tex_w, tex_h = ti.display_texture.size
            aspect = tex_h / tex_w if tex_w > 0 else 1.0
            display_height = avail_width * aspect
            imgui.image(
                tex_id,
                imgui.ImVec2(avail_width, display_height),
            )

        imgui.end()

    def _do_tracer_render(self, ti):
        """Start a progressive tracer render using the current entity buffer and camera."""
        if self.tracer_sim is None or self.tracer_camera is None:
            return

        entity_buffer = self.tracer_sim.get_entity_buffer()
        entity_count = self.tracer_sim.entity_count

        # Compute view_proj from the FPS controller camera
        cam = self.tracer_controller_cam
        if cam is None:
            return
        render_width, render_height = 512, 512
        render_aspect = render_width / render_height
        view_proj = self.tracer_camera.compute_fps_view_proj(
            cam.pos, cam.dir, cam.up, cam.fov, render_aspect
        )

        ti.start_render(entity_buffer, entity_count, view_proj,
                        width=render_width, height=render_height)
