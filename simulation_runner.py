"""Simulation runner: physics stepping and frame assembly (normal render path).

Renderer-specific offline video paths now live behind the VideoStrategy
protocol (see rendering/video_strategies.py); this runner only builds them.
"""
import glfw
import numpy as np


class SimulationRunner:
    """Runs physics simulation steps with frame assembly and video recording.

    Handles both motion-blur (temporal accumulation) and non-motion-blur paths,
    deduplicating the shared physics stepping and frame assembly logic.
    """

    def __init__(self, sim, camera, video_service, command_handler, window,
                 advanced_drawing_processor=None, controller_cam=None,
                 plotting_manager=None):
        self.sim = sim
        self.camera = camera
        self.video_service = video_service
        self.command_handler = command_handler
        self.window = window
        self.advanced_drawing_processor = advanced_drawing_processor
        self.controller_cam = controller_cam
        self.plotting_manager = plotting_manager

        # Mouse tracking for draw trail mode
        self.prev_mouse_tex_coords = (0.0, 0.0)

    def make_video_context(self):
        """Build the shared VideoContext used by renderer video strategies.

        Carries this runner's sim/camera/controller-cam/window plus the
        physics-step callback so a strategy can drive interleaved physics.
        """
        from rendering import VideoContext
        return VideoContext(
            sim=self.sim,
            camera=self.camera,
            controller_cam=self.controller_cam,
            window=self.window,
            run_physics_step=self._run_physics_step,
        )

    def make_tracer_video_strategy(self, tracer_interface):
        """Create a volumetric-tracer video strategy bound to this runner."""
        from rendering import TracerVideoStrategy
        return TracerVideoStrategy(self.make_video_context(), tracer_interface)

    def make_optix_pt_video_strategy(self, pt_interface):
        """Create an OptiX path-tracer offline video strategy bound to this runner."""
        from rendering import OptixPtVideoStrategy
        return OptixPtVideoStrategy(self.make_video_context(), pt_interface)

    def run_simulation_frame(self, ui_state, sweep_mode, sweep_reticle_pos,
                              sweep_reticle_visible, screen_aspect,
                              watercolor_mode=False,
                              screenshot_in_progress=False,
                              skip_view_generation=False):
        """Run simulation step(s) with frame assembly and video recording."""
        self._screenshot_in_progress = screenshot_in_progress
        self.camera.watercolor_mode = watercolor_mode
        speedmult = ui_state.preferences.rendering.speedmult
        motion_blur = ui_state.preferences.rendering.motion_blur

        # Calculate draw mode parameters
        draw_mode, mouse_tex_coords, draw_power_value = self._compute_draw_params(ui_state)

        # Compute erase mode (right-click drag in Draw Trail mode)
        erase_mode = (draw_mode and ui_state.mouse_right_held
                      and not ui_state.mouse_left_held)

        # Advanced Drawing: force/strafe field update (once per render frame, not per physics frame)
        if self.advanced_drawing_processor is not None:
            adv_prefs = ui_state.preferences

            if adv_prefs.advanced_drawing.enabled and adv_prefs.advanced_drawing.shader_driven_field:
                # Shader-driven field: run override shader every render frame
                cam = self.controller_cam
                generics_tuple = (adv_prefs.generics.generic0, adv_prefs.generics.generic1,
                                  adv_prefs.generics.generic2, adv_prefs.generics.generic3,
                                  adv_prefs.generics.generic4, adv_prefs.generics.generic5,
                                  adv_prefs.generics.generic6, adv_prefs.generics.generic7)
                self.advanced_drawing_processor.process_override(
                    canvas_width=self.sim.can.size[0],
                    canvas_height=self.sim.can.size[1],
                    shader_name=adv_prefs.advanced_drawing.field_override_shader,
                    frame_count=self.sim.frame_count,
                    mouse_pos=mouse_tex_coords,
                    prev_mouse_pos=self.prev_mouse_tex_coords,
                    draw_size=adv_prefs.ui_windows.draw_size,
                    draw_power=adv_prefs.ui_windows.draw_power,
                    brush_mode=adv_prefs.advanced_drawing.brush_mode,
                    fixed_direction_heading=adv_prefs.advanced_drawing.fixed_direction_heading,
                    camera_pos=tuple(cam.pos) if cam else (0.0, 0.0, 0.0),
                    camera_dir=tuple(cam.dir) if cam else (0.0, 0.0, 1.0),
                    generics=generics_tuple,
                )
            elif adv_prefs.advanced_drawing.enabled and (
                adv_prefs.advanced_drawing.draw_force_field or adv_prefs.advanced_drawing.draw_strafe_field
            ):
                # Normal drawing mode: draw/erase to field texture
                field_draw_active = (draw_mode and ui_state.mouse_left_held
                                     and draw_power_value > 0.0)
                # Erase scope: only erase fields that are checked as draw targets
                field_erase = (erase_mode and (
                    adv_prefs.advanced_drawing.draw_force_field or adv_prefs.advanced_drawing.draw_strafe_field
                ))
                self.advanced_drawing_processor.process(
                    canvas_width=self.sim.can.size[0],
                    canvas_height=self.sim.can.size[1],
                    draw_mode=field_draw_active,
                    mouse_pos=mouse_tex_coords,
                    prev_mouse_pos=self.prev_mouse_tex_coords,
                    draw_size=adv_prefs.ui_windows.draw_size,
                    draw_power=adv_prefs.ui_windows.draw_power,
                    brush_mode=adv_prefs.advanced_drawing.brush_mode,
                    fixed_direction_heading=adv_prefs.advanced_drawing.fixed_direction_heading,
                    force_field_active=adv_prefs.advanced_drawing.draw_force_field,
                    strafe_field_active=adv_prefs.advanced_drawing.draw_strafe_field,
                    erase_mode=field_erase,
                    fill_mode=ui_state.request_fill_operation,
                    fill_direction_type=ui_state.fill_direction_type,
                )

            # Handle selective field clear requests
            if ui_state.request_clear_force_field:
                self.advanced_drawing_processor.clear_force_field()
            if ui_state.request_clear_strafe_field:
                self.advanced_drawing_processor.clear_strafe_field()

        # Handle clear canvas request
        if ui_state.request_clear_canvas:
            self.sim.clear_canvas()

        # Handle clear canvas + fields request
        if ui_state.request_clear_canvas_and_fields:
            self.sim.clear_canvas()
            self.advanced_drawing_processor.clear_fields()

        # Build shared image-pipeline kwargs (used by both paths)
        assemble_kwargs = self._build_assemble_kwargs(ui_state)

        if motion_blur:
            self._run_with_motion_blur(
                ui_state, speedmult, draw_mode, mouse_tex_coords, draw_power_value,
                assemble_kwargs, erase_mode=erase_mode,
                skip_view_generation=skip_view_generation
            )
        else:
            self._run_without_motion_blur(
                ui_state, speedmult, draw_mode, mouse_tex_coords, draw_power_value,
                assemble_kwargs, erase_mode=erase_mode,
                skip_view_generation=skip_view_generation
            )

        # Update previous mouse position for next frame
        if draw_mode or erase_mode:
            self.prev_mouse_tex_coords = mouse_tex_coords

    def _compute_draw_params(self, ui_state):
        """Calculate draw mode parameters."""
        # Disable trail drawing when parameter sweeps are active
        draw_mode = (ui_state.preferences.ui_windows.mouse_mode == "Draw Trail" and
                     not ui_state.sim.parameter_sweeps_enabled)
        mouse_tex_coords = (0.0, 0.0)
        draw_power_value = 0.0

        if draw_mode:
            mouse_tex_coords = self.camera.screen_to_tex(
                ui_state.mouse_pos, self.sim.can.size
            )
            if ui_state.mouse_left_held or ui_state.request_fill_operation:
                draw_power_value = ui_state.preferences.ui_windows.draw_power

        return draw_mode, mouse_tex_coords, draw_power_value

    def _build_assemble_kwargs(self, ui_state):
        """Build the kwargs dict for image_pipeline.assemble_frame().

        Shared between motion-blur and non-motion-blur paths; only
        total_samples / current_sample_index differ between them. Overlay
        markup (sweep reticle, draw ring, field overlay) is NOT included here —
        it is composited for display only, so recorded frames stay markup-free.
        """
        # SDF preview params (for 3D GL-points mode)
        sdf_enabled = False
        inv_view_proj = None
        sdf_sun_dir = (0.577, 0.577, 0.577)
        sdf_sun_color = (3.0, 3.0, 3.0)
        sdf_sky_color = (0.5, 0.7, 1.0)

        if self.camera.render_3d:
            sdf_enabled = ui_state.preferences.tracer.sdf_enabled
            if sdf_enabled:
                cam = self.controller_cam
                width, height = glfw.get_framebuffer_size(self.window)
                aspect = width / max(height, 1)
                view_proj = self.camera.compute_fps_view_proj(
                    cam.pos, cam.dir, cam.up, cam.fov, aspect
                )
                inv_view_proj = np.linalg.inv(
                    view_proj.astype(np.float64)
                ).astype(np.float32)

                p = ui_state.preferences
                sun_d = np.array(p.tracer.sun_direction, dtype=np.float64)
                sun_len = max(np.linalg.norm(sun_d), 1e-8)
                sdf_sun_dir = tuple((sun_d / sun_len).astype(np.float32))
                sc = p.tracer.sun_color
                si = p.tracer.sun_intensity
                sdf_sun_color = (sc[0] * si, sc[1] * si, sc[2] * si)
                skc = p.tracer.sky_color
                ski = p.tracer.sky_intensity
                sdf_sky_color = (skc[0] * ski, skc[1] * ski, skc[2] * ski)

        return dict(
            brightness=self.camera.BRIGHTNESS,
            exposure=ui_state.preferences.rendering.exposure,
            ink_weight=ui_state.sim.ink_weight,
            watercolor_mode=ui_state.sim.watercolor_mode,
            tonemap_softness=ui_state.preferences.rendering.tonemap_softness,
            sdf_enabled=sdf_enabled,
            inv_view_proj=inv_view_proj,
            sdf_sun_dir=sdf_sun_dir,
            sdf_sun_color=sdf_sun_color,
            sdf_sky_color=sdf_sky_color,
            bloom_enabled=ui_state.preferences.bloom.enabled,
            bloom_threshold=ui_state.preferences.bloom.threshold,
            bloom_intensity=ui_state.preferences.bloom.intensity,
            bloom_radius=ui_state.preferences.bloom.radius,
        )

    def _run_physics_step(self, ui_state, draw_mode, mouse_tex_coords,
                           draw_power_value, step_index,
                           erase_mode=False):
        """Run a single physics step and handle deferred entity selection.

        Args:
            step_index: Current step within the frame (0-based).
                        Entity selection only checked on step 0.
            erase_mode: Whether right-click eraser is active.
        """
        adv_prefs = ui_state.preferences
        advanced_active = adv_prefs.advanced_drawing.enabled

        # Brush mode and heading (only apply when advanced drawing is open)
        brush_mode = adv_prefs.advanced_drawing.brush_mode if advanced_active else 0
        fixed_heading = adv_prefs.advanced_drawing.fixed_direction_heading if advanced_active else 0.0

        # Canvas draw active: when advanced drawing is closed, canvas always gets drawn.
        # When open, only if canvas checkbox is checked.
        canvas_draw_active = (not advanced_active) or adv_prefs.advanced_drawing.draw_canvas

        # Canvas erase scope: erase canvas if it's a draw target
        canvas_erase = erase_mode and canvas_draw_active

        # Fill mode for canvas: only on first physics step to avoid repeating
        canvas_fill = (ui_state.request_fill_operation and canvas_draw_active
                       and step_index == 0)

        # Only send draw_power if canvas is actually a draw target
        effective_draw_power = draw_power_value if canvas_draw_active else 0.0

        # Build generics tuple from preferences
        p = adv_prefs
        generics = (p.generics.generic0, p.generics.generic1, p.generics.generic2, p.generics.generic3,
                     p.generics.generic4, p.generics.generic5, p.generics.generic6, p.generics.generic7)

        self.sim.update(
            self.camera.ctx,
            draw_mode=draw_mode,
            mouse_pos=mouse_tex_coords,
            prev_mouse_pos=self.prev_mouse_tex_coords,
            draw_size=ui_state.preferences.ui_windows.draw_size,
            draw_power=effective_draw_power,
            brush_mode=brush_mode,
            fixed_direction_heading=fixed_heading,
            erase_mode=canvas_erase,
            fill_mode=canvas_fill,
            fill_direction_type=ui_state.fill_direction_type,
            canvas_draw_active=canvas_draw_active,
            field_texture=self.advanced_drawing_processor.field_texture,
            force_field_strength=adv_prefs.advanced_drawing.force_field_strength,
            strafe_field_strength=adv_prefs.advanced_drawing.strafe_field_strength,
            generics=generics,
        )

        # Check for deferred entity selection only on first physics step
        if step_index == 0 and self.command_handler.has_pending_entity_selection:
            self.command_handler.try_complete_entity_selection(ui_state)

    def _process_assembled_frame(self, assembled_tex, ui_state):
        """Handle a completed finished frame: store it and feed to video recorder.

        The frame is markup-free (bloom applied inside the ImagePipeline;
        overlays composited separately for display), so it is exactly what the
        video recorder should capture.
        """
        if assembled_tex is None:
            return
        self.camera.assembled_texture = assembled_tex
        if self.video_service.is_active():
            # 3D view has opposite Y orientation in the FBO compared to 2D;
            # skip the vertical flip so the video comes out right-side-up.
            flip_y = not self.camera.render_3d
            self.video_service.process_frame(
                self.camera.ctx,
                assembled_tex,
                ui_state.preferences.recording.max_frames,
                ui_state.preferences.recording.supersample_k,
                ui_state.preferences.recording.filename_prefix,
                flip_y=flip_y
            )

    def _run_with_motion_blur(self, ui_state, speedmult, draw_mode,
                               mouse_tex_coords, draw_power_value,
                               assemble_kwargs, erase_mode=False,
                               skip_view_generation=False):
        """Motion blur path: temporal accumulation with multiple render calls."""
        if self.plotting_manager is not None:
            self.plotting_manager.pre_physics_frame(self.sim.entity_update_program)

        motion_blur_render_cadence = ui_state.preferences.rendering.blur_quality
        total_render_samples = (speedmult + motion_blur_render_cadence - 1) // motion_blur_render_cadence
        render_sample_index = 0

        for step in range(speedmult):
            self._run_physics_step(
                ui_state, draw_mode, mouse_tex_coords, draw_power_value,
                step, erase_mode=erase_mode
            )
            if self.plotting_manager is not None:
                self.plotting_manager.notify_physics_step()

            # Only render on frames matching the blur quality cadence
            if step % motion_blur_render_cadence != 0:
                continue

            if not skip_view_generation:
                raw_view_tex = self.camera.generate_view_texture()

                assembled_tex = self.camera.image_pipeline.assemble_frame(
                    raw_view_tex,
                    total_samples=total_render_samples,
                    current_sample_index=render_sample_index,
                    **assemble_kwargs
                )
                render_sample_index += 1

                self._process_assembled_frame(assembled_tex, ui_state)

        if self.plotting_manager is not None:
            self.plotting_manager.post_assembly_frame()

    def _run_without_motion_blur(self, ui_state, speedmult, draw_mode,
                                  mouse_tex_coords, draw_power_value,
                                  assemble_kwargs, erase_mode=False,
                                  skip_view_generation=False):
        """Non-motion-blur path: multiple physics steps, single render call."""
        if self.plotting_manager is not None:
            self.plotting_manager.pre_physics_frame(self.sim.entity_update_program)

        for step in range(speedmult):
            self._run_physics_step(
                ui_state, draw_mode, mouse_tex_coords, draw_power_value,
                step, erase_mode=erase_mode
            )
            if self.plotting_manager is not None:
                self.plotting_manager.notify_physics_step()

        if not skip_view_generation:
            raw_view_tex = self.camera.generate_view_texture()

            assembled_tex = self.camera.image_pipeline.assemble_frame(
                raw_view_tex,
                total_samples=1,
                current_sample_index=0,
                **assemble_kwargs
            )

            self._process_assembled_frame(assembled_tex, ui_state)

        if self.plotting_manager is not None:
            self.plotting_manager.post_assembly_frame()

