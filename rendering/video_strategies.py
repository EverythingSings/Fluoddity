"""Renderer-specific offline video strategies (Step 7, Phase D).

Moves the two renderer-specific video paths out of ``simulation_runner`` and
behind the ``VideoStrategy`` contract:

- ``TracerVideoStrategy``   — volumetric tracer (progressive SPP + re-splat motion blur).
- ``OptixPtVideoStrategy``  — OptiX path tracer offline (substep motion blur).

Both share a ``VideoContext`` carrying the sim / camera / controller-cam / window
and a ``run_physics_step`` callback (still owned by ``SimulationRunner``). Each
strategy owns its own per-output-frame accumulation state and returns a finished,
tonemapped texture from ``run_frame`` when an output frame is complete (else None).
The behavior is a faithful move of the original methods — no logic change.
"""
from __future__ import annotations

from dataclasses import dataclass

import glfw


@dataclass
class VideoContext:
    """Shared plumbing a video strategy needs to drive physics + camera."""
    sim: object
    camera: object
    controller_cam: object
    window: object
    run_physics_step: object  # callable(ui_state, step_index)

    def compute_view_proj(self):
        cam = self.controller_cam
        width, height = glfw.get_framebuffer_size(self.window)
        aspect = width / max(height, 1)
        return self.camera.compute_fps_view_proj(
            cam.pos, cam.dir, cam.up, cam.fov, aspect
        )


class TracerVideoStrategy:
    """Volumetric tracer video: progressive SPP with re-splat motion blur."""

    def __init__(self, ctx: VideoContext, tracer_interface):
        self.ctx = ctx
        self.ti = tracer_interface
        self.init_frame_state()

    def init_frame_state(self):
        self._samples_done = 0
        self._frame_started = False
        self._physics_steps_done = 0
        self._schedule = []

    def run_frame(self, ui_state):
        c = self.ctx
        ti = self.ti
        spp = ti.num_samples
        physics_rate = ui_state.preferences.recording.motion_blur_samples

        # --- Start a new output frame if needed ---
        if not self._frame_started:
            # Distribute physics_rate steps as evenly as possible across spp
            # samples; schedule[i] = total steps that must run before sample i.
            self._schedule = []
            for i in range(spp):
                self._schedule.append(((i + 1) * physics_rate) // spp)
            self._schedule[0] = max(self._schedule[0], 1)

            # Initial physics step
            c.run_physics_step(ui_state, 0)

            view_proj = c.compute_view_proj()
            width, height = glfw.get_framebuffer_size(c.window)
            scale = max(0.1, ti.resolution_scale)
            rt_width = max(1, int(width * scale))
            rt_height = max(1, int(height * scale))
            cam_right, cam_up = c.camera.compute_fps_camera_basis(
                c.controller_cam.dir, c.controller_cam.up
            )
            ti.start_video_render(
                c.sim.get_entity_buffer(), c.sim.entity_count,
                view_proj, rt_width, rt_height,
                camera_right=cam_right, camera_up=cam_up
            )
            self._frame_started = True
            self._samples_done = 0
            self._physics_steps_done = 1

        # --- Run any physics steps needed before this sample ---
        target_steps = self._schedule[self._samples_done]
        while self._physics_steps_done < target_steps:
            c.run_physics_step(ui_state, self._physics_steps_done)
            self._physics_steps_done += 1
            # Re-splat entities with updated positions (keeps accumulation)
            view_proj = c.compute_view_proj()
            ti.re_splat(c.sim.get_entity_buffer(), c.sim.entity_count, view_proj)

        # --- Accumulate 1 SPP ---
        frame_complete = ti.tick_video()
        self._samples_done += 1

        if frame_complete:
            display_tex = ti.tonemap_for_video()
            self._frame_started = False
            return display_tex
        return None


class OptixPtVideoStrategy:
    """OptiX path tracer offline video: substep motion blur."""

    def __init__(self, ctx: VideoContext, pt_interface):
        self.ctx = ctx
        self.pt = pt_interface
        self.init_frame_state()

    def init_frame_state(self):
        self._frame_started = False
        self._substeps_done = 0
        self._physics_steps_done = 0
        self._total_substeps = 0
        self._physics_per_substep = 0

    def run_frame(self, ui_state):
        c = self.ctx
        pt = self.pt
        capture_spp = ui_state.preferences.optix.rt_preview_spp
        physics_rate = ui_state.preferences.recording.motion_blur_samples

        if ui_state.preferences.recording.recording_motion_blur:
            blur_quality = ui_state.preferences.recording.recording_blur_quality
            total_substeps = max(1, physics_rate // max(blur_quality, 1))
            physics_per_substep = blur_quality
        else:
            total_substeps = 1
            physics_per_substep = physics_rate

        spp_per_substep = max(1, capture_spp // max(total_substeps, 1))

        # --- Start a new output frame if needed ---
        if not self._frame_started:
            self._total_substeps = total_substeps
            self._physics_per_substep = physics_per_substep

            for i in range(physics_per_substep):
                c.run_physics_step(ui_state, i)

            width, height = glfw.get_framebuffer_size(c.window)
            scale = max(0.1, ui_state.preferences.optix.resolution_scale)
            width = max(1, int(width * scale))
            height = max(1, int(height * scale))
            pt.start_offline_render(
                entity_buffer=c.sim.get_entity_buffer(),
                entity_count=c.sim.entity_count,
                width=width,
                height=height,
                total_substeps=total_substeps,
                spp_per_substep=spp_per_substep,
            )

            cam = c.controller_cam
            pt.offline_substep(cam.pos, cam.dir, cam.up, cam.fov)

            self._frame_started = True
            self._substeps_done = 1
            self._physics_steps_done = physics_per_substep
            return None

        # --- Subsequent substeps: physics step(s) + offline_substep ---
        if self._substeps_done < self._total_substeps:
            for i in range(self._physics_per_substep):
                c.run_physics_step(ui_state, self._physics_steps_done)
                self._physics_steps_done += 1
            cam = c.controller_cam
            pt.offline_substep(cam.pos, cam.dir, cam.up, cam.fov)
            self._substeps_done += 1
            return None

        # --- All substeps done: finish and return ---
        display_tex = pt.finish_offline_render(flip_y=False)
        self._frame_started = False
        return display_tex
