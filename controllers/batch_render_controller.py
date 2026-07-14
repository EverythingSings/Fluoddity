"""BatchRenderController: owns the render-queue batch state machine (Step 10).

Extracted from ``main.py``. Sequentially loads render specs (.frs), records a
video of each, advances, and closes the app (optionally shutting down the PC)
when the queue is drained. The recording lifecycle itself is driven by
RecordingController; this controller only sequences specs and reacts when a
recording finishes naturally.

Phases: idle -> loading -> start_recording -> recording -> (next spec | done)
"""
import glfw
from pathlib import Path


class BatchRenderController:
    """Owns the render-queue execution state machine."""

    def __init__(self, render_spec_service, video_service, sim, camera,
                 config_saver, rule_manager, entity_picker, ui, window):
        self.render_spec_service = render_spec_service
        self.video_service = video_service
        self.sim = sim
        self.camera = camera
        self.config_saver = config_saver
        self.rule_manager = rule_manager
        self.entity_picker = entity_picker
        self.ui = ui
        self.window = window

        self.executing = False
        self.index = 0
        self.phase = 'idle'   # idle / loading / start_recording / recording / done
        self.queue = []       # list of path strings
        self.queue_names = []  # display names (parallel list)

    def handle_requests(self, ui_state, *, on_before_execute):
        """Process execute / cancel render-queue requests from the UI."""
        # Execute request
        if ui_state.request_execute_render_queue and not self.executing:
            if ui_state.render_queue_paths:
                valid_paths = []
                valid_names = []
                for path, name in zip(ui_state.render_queue_paths,
                                      ui_state.render_queue_names):
                    if Path(path).exists():
                        valid_paths.append(path)
                        valid_names.append(name)
                    else:
                        print(f"[RenderQueue] Spec not found, skipping: {path}")
                if valid_paths:
                    # Save preferences before execution (in case app auto-closes)
                    on_before_execute(ui_state)
                    self.executing = True
                    self.index = 0
                    self.phase = 'loading'
                    self.queue = valid_paths
                    self.queue_names = valid_names
                    print(f"[RenderQueue] Starting batch render of {len(self.queue)} specs")
                else:
                    print("[RenderQueue] No valid specs to render")

        # Cancel request
        if ui_state.request_cancel_render_queue and self.executing:
            if self.video_service.is_active():
                self.video_service.stop()
            self.executing = False
            self.phase = 'idle'
            ui_state.sim.going = False
            print("[RenderQueue] Batch render cancelled")

    def advance(self, ui_state):
        """State machine for sequential batch rendering.

        Called every frame while ``executing``.
        Phases: loading -> start_recording -> recording -> (next spec or done)
        """
        phase = self.phase

        if phase == 'loading':
            idx = self.index
            dir_path = Path(self.queue[idx])
            display_name = self.queue_names[idx]

            print(f"[RenderQueue] Loading spec {idx + 1}/{len(self.queue)}: {display_name}")

            spec = self.render_spec_service.load_metadata(dir_path)
            if spec is None:
                print(f"[RenderQueue] Failed to load metadata for {display_name}, skipping")
                self._advance_or_finish()
                return

            gpu_buffers = self.render_spec_service.load_gpu_buffers(dir_path)
            if gpu_buffers is None:
                print(f"[RenderQueue] Failed to load GPU buffers for {display_name}, skipping")
                self._advance_or_finish()
                return

            world_size_changed = self.render_spec_service.apply_state(
                spec, gpu_buffers,
                self.sim, self.camera, self.ui.tracer_controller_cam, ui_state,
                self.config_saver, self.rule_manager,
                apply_editor_visibility=False,  # headless: don't toggle windows or imgui layout
            )
            if world_size_changed:
                self.entity_picker.update_buffer(self.sim.get_entity_buffer())
                self.ui._last_applied_entity_count = ui_state.preferences.rendering.entity_count
                self.ui._last_applied_canvas_resolution = ui_state.preferences.rendering.canvas_resolution

            # Re-sync tracer interface if it exists
            if self.ui._tracer_interface is not None:
                self.ui._apply_tracer_preferences(self.ui._tracer_interface)

            # Set filename_prefix so VidSaver uses the display name
            ui_state.preferences.recording.filename_prefix = display_name

            # Unpause simulation (recording requires going = True)
            ui_state.sim.going = True

            self.phase = 'start_recording'

        elif phase == 'start_recording':
            # GPU state has settled for one frame. Start recording.
            ui_state.sim.going = True
            self.video_service.start()
            self.phase = 'recording'
            display_name = self.queue_names[self.index]
            print(f"[RenderQueue] Recording started for: {display_name}")

        elif phase == 'recording':
            # Normal frame execution handles physics + recording.
            # Completion detected via on_recording_complete().
            pass

        elif phase == 'done':
            print(f"[RenderQueue] All {len(self.queue)} renders complete. Closing app.")
            if self.ui._shutdown_after_render_queue:
                import os
                print("[RenderQueue] PC shutdown scheduled in 60 seconds (cancel with 'shutdown /a')")
                os.system('shutdown /s /t 60')
            self.executing = False
            glfw.set_window_should_close(self.window, True)

    def on_recording_complete(self):
        """Called when a recording finishes naturally during batch execution."""
        idx = self.index
        display_name = self.queue_names[idx]
        print(f"[RenderQueue] Recording complete for: {display_name} ({idx + 1}/{len(self.queue)})")
        self._advance_or_finish()

    def _advance_or_finish(self):
        """Move to the next spec in the queue, or finish if all done."""
        self.index += 1
        if self.index < len(self.queue):
            self.phase = 'loading'
        else:
            self.phase = 'done'

    def display_status(self):
        """Return the batch-render slice of the UI display-info dict."""
        current_name = ''
        if self.executing and self.index < len(self.queue_names):
            current_name = self.queue_names[self.index]
        return {
            'render_queue_executing': self.executing,
            'render_queue_index': self.index,
            'render_queue_total': len(self.queue),
            'render_queue_phase': self.phase,
            'render_queue_current_name': current_name,
        }
