# Scheduled Renders Feature — Implementation Plan

## Context

Rendering in Fluoddity can take a long time. This feature lets users save complete simulation snapshots ("render specs") to disk, then queue multiple specs for back-to-back unattended rendering. After all renders complete, the app closes itself. This enables overnight/weekend batch rendering with no human intervention.

## File Format

Each RenderSpec is a `.frs` directory (Fluoddity Render Spec) in `Documents/Fluoddity/RenderSpecs/`:
```
MyRender.frs/
    metadata.json       # All scalar state (physics, camera, preferences)
    entities.npz        # Compressed entity buffer (~128MB raw -> ~5-20MB compressed)
    canvas.npz          # Compressed 3D canvas textures (~201MB raw -> ~10-40MB compressed)
    field.npz           # Compressed force/strafe field texture (~1MB, optional)
```

---

## Step 1: RenderSpec Data Model + Serialization (COMPLETE)

**Goal**: Define the `RenderSpec` dataclass and `RenderSpecService` with capture/save/load/apply methods. No UI -- just the data layer.

### Files created
- **`services/render_spec.py`** -- `RenderSpec` dataclass + `RenderSpecService` class

### Files modified
- **`utilities/paths.py`** -- Added `get_render_specs_dir()`, added `.mkdir()` call in `initialize_user_data()`
- **`services/__init__.py`** -- Added `RenderSpecService` export

### RenderSpec captures
| Category | Source | Serialized as |
|----------|--------|--------------|
| Physics config + rule | `ConfigSaver.create_config()` -> `PhysicsConfig.to_dict()` | `metadata.json -> physics_config` |
| Camera state | `CameraState` fields | `metadata.json -> camera_state` |
| Controller cam state | `ControllerCam.pos/yaw/pitch/fov` | `metadata.json -> controller_cam_state` |
| Preferences | `dataclasses.asdict(PreferencesState)` | `metadata.json -> preferences` |
| Sim metadata | `frame_count`, `can_read_index`, entity_count | `metadata.json -> sim_metadata` |
| Entity buffer | `sim.entities.read()` -> numpy uint8 | `entities.npz` (compressed) |
| 3D canvas (3 channels) | `sim.can_x/y/z_3d[read_idx].read()` -> numpy float32 | `canvas.npz` (compressed) |
| Force/strafe field | `adv_draw.snapshot_field_data()` | `field.npz` (compressed, optional) |

### Key methods on `RenderSpecService`
- `capture_current_state(sim, camera, controller_cam, ui_state, config_saver, rule_manager, adv_draw, name)` -> `(RenderSpec, gpu_buffers dict)`
- `save_to_disk(spec, gpu_buffers, dir_path)` -- writes metadata.json + .npz files, prints compression stats
- `load_metadata(dir_path)` -> `RenderSpec` -- fast load, metadata only
- `load_gpu_buffers(dir_path)` -> `dict[str, np.ndarray]` -- load compressed GPU data
- `apply_state(spec, buffers, sim, camera, controller_cam, ui_state, config_saver, rule_manager, adv_draw)` -- restore everything to GPU + state containers
- `list_available_specs()` -> `list[Path]` -- scan RenderSpecs dir for .frs directories

### Restore details
- Entity buffer: `sim.entities.write(data)`
- Canvas: write to **both** double-buffer textures (index 0 and 1) to prevent stale data
- Field: `adv_draw.write_field_data(data)`
- Frame count: `sim.frame_count = saved_value`
- Rule: apply via `rule_manager` / `config_saver.apply_config()`
- Camera: set all `CameraState` fields + `controller_cam` pos/yaw/pitch

### How to verify
- Run app, set up interesting state, call `capture_current_state()` from a debug hook
- Verify `.frs` directory on disk with valid JSON and .npz files
- Load back and verify field round-trip fidelity

---

## Step 2: Save Render Spec Action

**Goal**: Add a "Save Render Spec" button in the Screen Recording window (under "Tracer Mode") that captures and saves a spec to disk.

### Files to modify
- **`ui/help_windows.py`** -- Add "Save Render Spec" button + name input after Tracer Mode checkbox (~line 367)
- **`state/ui_state.py`** -- Add `request_save_render_spec: bool`, `save_render_spec_name: str`
- **`ui/core.py`** -- Add one-shot flags, transfer in `get_state()`
- **`command_handler.py`** -- Add handler in `process_commands()` that calls `RenderSpecService.capture_current_state()` + `save_to_disk()`
- **`main.py`** -- Create `RenderSpecService` in `App.__init__`, pass to `CommandHandler`

### UI behavior
- Button labeled "Save Render Spec" with a text input for the name (defaulting to `filename_prefix` or "render")
- On click: captures state, saves to `Documents/Fluoddity/RenderSpecs/{name}.frs/`
- Prints compression stats to console
- Shows brief status text "Saved!" for a couple seconds

### How to verify
- Run app, configure simulation, enter a name, click Save Render Spec
- Check `Documents/Fluoddity/RenderSpecs/` for the `.frs` directory
- Verify `metadata.json` has correct content
- Save multiple specs, verify separate directories

---

## Step 3: Scheduled Renders Window UI

**Goal**: New window (Extras menu) showing a render queue. Load specs from dropdown, rename/delete, click to preview (destructive apply).

### Files to create
- **`ui/scheduled_renders_window.py`** -- `ScheduledRendersWindowMixin` with `render_scheduled_renders_window()`

### Files to modify
- **`state/preferences_state.py`** -- Add `show_scheduled_renders_window: bool = False`
- **`state/ui_state.py`** -- Add one-shot flags for preview/load/delete
- **`ui/core.py`** -- Import mixin, add to UI inheritance, init flags, transfer in `get_state()`, add render dispatch
- **`ui/menu_bar.py`** -- Add "Scheduled Renders" checkbox in Extras menu
- **`command_handler.py`** -- Add handlers for preview (loads GPU buffers + applies state)
- **`main.py`** -- Wire up preview handling, pass necessary refs to CommandHandler

### Window layout
```
+----------------------------------------------+
| Scheduled Renders                         [X] |
+----------------------------------------------+
| Available: [___dropdown___]  [Load]           |
+----------------------------------------------+
| Render Queue:                                 |
|   MyRender                             [X]    |
|   AnotherRender                        [X]    |
|   (right-click to rename)                     |
+----------------------------------------------+
| [Execute All Renders]                         |
+----------------------------------------------+
```

### State (in the mixin, like config_clipboard)
- `_render_queue: list[tuple[RenderSpec, str, Path]]` -- (metadata, display_name, dir_path)
- `_render_spec_files: list[str]` -- scanned `.frs` directory names
- Rename: right-click popup with text input (same pattern as `history_window.py`)
- Delete: red X button removes from queue (does NOT delete from disk)

### Preview behavior (destructive)
- Click a spec -> UI sets flag -> CommandHandler loads GPU buffers from disk + calls `apply_state()`
- This permanently applies the state. Simulation pauses (`going = False`).

### Execute button
- Present but greyed out / non-functional in this step (wired up in Step 4)

### How to verify
- Save 2-3 render specs (Step 2)
- Open Extras -> Scheduled Renders
- Verify dropdown lists available `.frs` directories
- Load specs into queue, verify list populates
- Click a spec -> particles/canvas snap to saved positions
- Rename via right-click, verify name updates
- Delete from queue, verify removal

---

## Step 4: Execute Pipeline -- Sequential Batch Rendering

**Goal**: Execute button loads each spec sequentially, records video, advances to next, closes app when done.

### Files to modify
- **`main.py`** -- Render pipeline state machine in `App`:
  - New fields: `render_queue_executing`, `render_queue_index`, `render_queue_phase`, `render_queue` (list of Paths), `render_queue_names` (display names for filenames)
  - New method: `_advance_render_pipeline(ui_state)` -- state machine with phases: `loading` -> `start_recording` -> `recording` -> (next spec or `done`)
  - Hook into `orchestrate_frame()` after `process_commands()` (step 2.5)
  - Modify recording-completion detection (the `not is_recording and was_recording` block) to call `_on_render_spec_complete()` instead of just pausing
  - On `done` phase: `glfw.set_window_should_close(self.window, True)`
- **`state/ui_state.py`** -- Add `request_execute_render_queue: bool`, `render_queue_paths: list`, `render_queue_names: list`
- **`ui/core.py`** -- Transfer execute flags in `get_state()`
- **`ui/scheduled_renders_window.py`** -- Wire up Execute button: sets flag + populates paths/names from queue

### State machine phases
1. **`loading`**: Load spec from disk (metadata + GPU buffers), apply to sim/camera/prefs, set `filename_prefix` = display_name
2. **`start_recording`**: Wait one frame for GPU state to settle, then `video_service.start()`
3. **`recording`**: Normal frame execution. Detect completion via existing `finished_naturally()` logic
4. **`done`**: All specs complete -> save preferences -> close window

### Video naming
Each spec's display_name becomes `filename_prefix` -> output file is `{display_name}-{HH-MM-SS}.mp4` in `Documents/Fluoddity/Videos/`

### How to verify
- Save 2-3 specs with short video lengths (e.g., 5 seconds each) and distinct physics
- Load into render queue
- Click Execute
- Verify: first spec loads, recording starts, video finishes
- Verify: second spec loads automatically, recording starts, finishes
- Verify: after last spec, app closes
- Verify: output videos exist with correct filenames and show correct simulations
- Test closing app mid-execution -- verify clean shutdown

---

## Step 5: Polish and Edge Cases

### 5a. Execution progress UI
- During execution, window shows: current spec name, progress (frame X of max_frames), remaining specs count
- Cancel button -> stops current recording, sets `render_queue_executing = False`, app stays open
- Display info fields: `render_queue_executing`, `render_queue_index`, `render_queue_total`, `render_queue_current_name`

### 5b. Validation before execute
- Check all spec paths still exist on disk
- Verify at least one spec in queue
- Warn about world_size mismatches (require GPU reallocation)

### 5c. Pre-execution preferences save
- Save preferences before starting execution (in case app auto-closes, user settings are preserved)

### 5d. Disable interaction during execution
- Disable physics sliders, reset/load menus during execution
- Only cancel button and window close work

### 5e. Render spec file management
- Option to delete `.frs` directories from disk (with confirmation dialog)

---

## Verification (End-to-End)

1. Set up distinct simulations, save 3 render specs with different physics/camera/recording settings
2. Open Scheduled Renders window, load all 3 specs
3. Rename one to test custom video filename
4. Click one to preview -- verify initial conditions match
5. Click Execute -- walk away
6. Come back to find: app closed, 3 videos in Videos/ folder, each showing the correct simulation
