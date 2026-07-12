# Fluoddity Component Inventory

An exhaustive, classified catalogue of every functional component in Fluoddity, for use as the working reference during the modularity refactor. For each component this doc records: **what it is**, **where it currently lives**, **its classification bucket**, **coupling / scatter flags** (where its logic leaks or is duplicated), and a **recommended target home / missing abstraction**.

This is a *catalogue + target state* document — the target-state notes are the intended end point of the refactor, not the current reality. The committed design decisions are collected in **[Target-State Directives](#target-state-directives)**, and the executable plan in **[Refactor Step Plan](#refactor-step-plan)** (12 steps). For the high-level overview see [`../ARCHITECTURE.md`](../ARCHITECTURE.md).

> Scope note: `docs/engine_rewrite_proposal.md` proposes a separate rewrite of the *physics parameter* systems (sweeps/jitter → one parameter table). That is a **different axis** from top-level modularity and is deliberately **not** referenced as the target state for those components here — they are classified on their own merits. (Note that proposal predates the decision to cut multi-load; multi-load is simply removed here, see Target-State Directives → CUTS.)

---

## Classification Buckets

| Bucket | Meaning |
|--------|---------|
| **Always** | Core; the simulation cannot run without it. GL context, sim, runner, camera, orchestrator, command handler, rule manager. |
| **Modules** | Self-contained features that can be cleanly gated/disabled and should each own a file or folder holding *all* their logic (state + UI + handlers + prefs slice). |
| **Swappable** | A role with exactly one active implementation at a time, requiring resource lifecycle on swap. The 3D renderer; the field-override shader. |
| **Shared Infrastructure / Utilities** | Stateless helpers used broadly. Not core components, not optional modules. |
| **State Containers** | The `state/` dataclasses. Data, not behavior — but the primary coupling surface. |
| **Cross-cutting Concerns** | Logic deliberately woven through many components; resists single-file ownership. |
| **Dev / Standalone Tools** | Scripts, demos, and tests not part of the running app. |

### At-a-glance target structure
The intended end state: **every Module owns a folder** containing its logic, its preference slice (a small dataclass), its state container, its UI window, and its command handlers. **Swappable renderers sit behind one `Renderer` protocol with one owner** that instantiates one at a time and frees the previous. **The orchestrator shrinks** to wiring + the frame loop, delegating each state machine to the module that owns it.

---

## Target-State Directives

Explicit design decisions that shape the refactor beyond "give each thing a home." These are commitments, not options.

### Renderers own their whole pipeline; hand back finished frames
The simulation rendering pipeline is one of the oldest, muddiest parts of the codebase. In the target state **each renderer owns its full image pipeline** — tonemapping, temporal supersample / motion blur, bloom, and denoise all live inside the renderer. A renderer's only output is a **completed frame** ready to go straight to the video recorder and/or the display. Renderers are **markup-agnostic**: overlays (trail-draw reticle, parameter-sweep indicator, draw cursor) are added *after* the renderer, by the Viewer (below). This kills the current split where `FrameAssembler`/`frame_assembly.frag` do tonemap + motion blur + overlays for the 2D path while each 3D renderer does its own thing.

### The "Viewer" window
Rendering currently draws to the whole app window. Target: an **always-displayed imgui window named "Viewer"** that displays the render output. It is **immune to the show/hide-windows button**. The Viewer runs a small **overlay pass** that composites finished renderer output + markup (reticle, sweep indicator, draw cursor). Overlays therefore work uniformly over any backend.

### 3D-only direction
The app is heading toward **3D-only**. The 3D GL-points renderer takes over the role the 2D `cam_brush` view played, so the **2D `cam_brush` path is cut** along with the tiled/debug view modes. This is a *direction*: the step plan routes everything through the 3D renderer + Viewer and removes the tiled/debug/2D-assembler cleanly, but does not force-remove every last 2D vestige if that risks breaking mouse trail-drawing. **Open (deferred) question:** the fate of mouse trail-drawing and the 2D pan/zoom camera — both currently tied to the 2D view and `screen_to_tex` mapping — is resolved at the cam_brush-removal step (`screen_to_ray_3d` already exists as a 3D-pick alternative). ⚠️ `camera.cam_brush_target` is a **shared FBO** that the OptiX renderers blit *into* and `FrameAssembler` wraps, so "cut 2D" is a disentangling job, not a clean delete.

### Unify the two OptiX renderers into the path tracer
`optix_renderer/` (sphere/rasterize) and `optix_pathtracer/` (path tracer) share a lot of duplicated code (the hand-computed `PARAMS_DTYPE` CUDA-struct mirror, `_camera_basis_from_vectors`, GAS build, interop). Target: **delete `optix_renderer/`; the path tracer is the single OptiX renderer.** The old "rasterize mode" becomes a **checkbox** that changes ONLY three things:
- **Raygen:** no aperture / depth-of-field (pinhole).
- **Bounce procedure:** terminate after the first hit (no bounces).
- **NEE procedure:** launch one deterministic shadow ray toward the sun (perfect directional light) + the configured number of AO samples — matching the old rasterize look.

Everything else — BRDF/lighting, tonemapping, denoising, the whole rest of the pipeline — **follows path-tracer mode unchanged.**

### Explicit CUTS
Removed outright (sequenced first in the step plan — see end):
- **Multi-Load** — cut entirely, including its bloat in `entity_update.glsl` and `sim.py`. If the functionality is wanted again it will be rebuilt from scratch, likely after the separate sim parameter-system rewrite.
- **Tiled + debug/legacy view modes** — no more `Camera [Tiled]` or DEBUG `current_view_option`s.
- **Strong determinism** — remove the Extras → Strong Determinism control (no longer needed; drop canvas double-buffering gated on it).
- **GAS rebuild interval slider + refit code** — always rebuild the GAS every frame (the value was always 1 in practice). Delete the slider, the interval scheduling, and the `refit_accel` path.

### Simplified preview
The preview system is over-complicated. Target behavior is exactly:
- **On enter preview:** cache the current config, load the preview config (a full normal load).
- **On change preview** (already previewing, user hovers another): load the new preview config; the cached original is left untouched.
- **On leave preview:** load the cached config.

No separate rule-only push/pop stack for preview — preview is just "load, remembering what to restore."

---

## Always

Core components. Not candidates for removal; the refactor goal here is to *shrink* them (especially the orchestrator) and make dependencies explicit.

### App / Orchestrator
- **Purpose:** Owns the GLFW window + GL context and every component/service; drives the frame loop.
- **Location:** `main.py` (1175 lines). `App.__init__` (`:29`), `run()` (`:207`), `orchestrate_frame()` (`:215`–`:864`, ~650 lines), `cleanup()` (`:1114`).
- **Entry points:** `orchestrate_frame()` (the whole per-frame pipeline).
- **Coupling / scatter flags:**
  - `orchestrate_frame()` carries **four interleaved state machines**: screenshot (`:308`), recording lock/restore (`:324`–`:390`), render-queue batch (`:258`–`:296`, `:1026`+), and renderer lifecycle (`:409`–`:647`, ~220 lines).
  - **Post-construction attribute injection** hides the dependency graph: `controller_cam`, `plotting_manager`, `param_lock_service`, `_tracer_interface`, `tracer_sim/camera/controller_cam` are set on already-built objects (`:104,115,118–119,130–132`).
  - `cleanup()` hand-copies ~40 tracer fields back into `PreferencesState` (`:1130`–`:1158`) — a symptom of the prefs monolith.
- **Target home / abstraction:** Keep as the wiring + frame-loop owner, but extract each state machine into the module that owns it (recording → a RecordingController, render-queue → RenderSpec module, renderer lifecycle → a RendererHost behind the `Renderer` protocol). Prefer constructor injection over attribute injection.

### GL Context + Window
- **Purpose:** GLFW window creation, GL context, vsync, buffer swap, teardown.
- **Location:** Inline in `App.__init__` (`main.py:31`–`43`) and `run()`/`cleanup()`. **GLFW input callbacks live in the UI** (`ui/core.py`, `setup_callbacks()`), not here.
- **Coupling / scatter flags:** No dedicated context/window owner; App is implicitly it. Window creation (App) and input callbacks (UI) are split.
- **Target home / abstraction:** A small `AppWindow` / context-owner class that both App and UI receive, consolidating window + input-callback ownership.

### Sim (simulation core)
- **Purpose:** GPU particle simulation — buffers, compute dispatch, physics→uniform mapping, sweeps, multi-load SSBO packing, rules.
- **Location:** `sim.py` (914 lines). Key: `update()` (`:315`), `entity_update()` (`:148`), `can_update_3d()` (`:220`), `apply_state()` (`:377`), `apply_rule()` (`:704`), `_write_multi_load_ssbo` / multi-load weighting (`:495`–`702`).
- **Coupling / scatter flags:** **User-owned — do not restructure without asking.** Mixes "simulation engine" with "UI parameter interpretation" (`calculate_setting`/`_assign_physics_setting`, `:408`–`476`) and multi-load blending. Has its own hardcoded param lists duplicated against `physics_params.py` / `config_saver.py`.
- **Target home / abstraction:** Stays `sim.py`. The param-interpretation duplication is the subject of the separate parameter-rewrite proposal; leave alone for the modularity refactor.

### SimulationRunner
- **Purpose:** Physics stepping + frame assembly; motion-blur/non-blur paths; renderer-specific video paths.
- **Location:** `simulation_runner.py` (624 lines). `run_simulation_frame()` (`:29`), `_run_with/without_motion_blur()` (`:367`/`:407`), `run_tracer_video_frame()` (`:448`), `run_optix_pt_video_frame()` (`:549`).
- **Coupling / scatter flags:** Reaches back into `command_handler` (entity-selection completion, `:338`) and `multi_load_service`. Independently recomputes SDF/FPS view-proj, duplicating logic in `main.py._render_camera_view` and the realtime-tracer block. Renderer-specific video paths live here rather than behind the renderer abstraction.
- **Target home / abstraction:** Keep the physics/assembly core; move the two renderer-specific video paths behind the `Renderer` protocol (each swappable renderer supplies its own video strategy).

### Camera + FrameAssembler
- **Purpose:** View-texture generation (2D `cam_brush` / 3D GL_POINTS / routed OptiX interface), coordinate transforms, tiling, bloom hookup, screen rendering. Owns `FrameAssembler` (temporal accumulation + composite).
- **Location:** `camera.py` (557 lines); `utilities/frame_assembler.py` (226).
- **Coupling / scatter flags:** `camera.optix_interface` is an **aliased slot** holding either the OptiX sphere renderer OR the path tracer, disambiguated only by scattered `pt_active`/`three_d_rt_mode` checks in `main.py`. `frame_assembler.py` textually prepends `volrender/shaders/common.glsl` + `volume_scene.glsl` for an inline SDF preview — cross-tree shader coupling.
- **Target home / abstraction:** Route the active 3D renderer through a typed `Renderer` handle rather than the ambiguous `optix_interface` slot.

### Viewer (NEW — target state)
- **Purpose:** An always-displayed imgui window that shows the active renderer's finished frame, plus an overlay pass for markup. Immune to the show/hide-windows button.
- **Location:** Does not exist yet. Replaces the current "draw to the whole app window" approach (`main.py._render_camera_view`, `camera.render`).
- **Entry points (target):** `Viewer.display(finished_frame)` + `Viewer.overlay(reticle, sweep_indicator, draw_cursor)`.
- **Coupling / scatter flags:** Absorbs the overlay markup currently baked into `frame_assembly.frag` (reticle, sweep) so markup is renderer-agnostic; consumes the `Renderer` protocol's finished frame.
- **Target home / abstraction:** A `viewer/` module owning the window + overlay pass. It is the single sink for renderer output (display) that parallels the video recorder (file). See Target-State Directives → Viewer.

### CommandHandler
- **Purpose:** Processes one-shot UI flags each frame (reset/reload, recording toggle, mouse picking, config save/load/delete, clipboard, preview, render-spec, field-image load).
- **Location:** `command_handler.py` (730 lines). `process_commands()` (`:98`).
- **Coupling / scatter flags:** Owns `video_pending`/`video_scheduled_start_frame` but the "start when frame reached" check lives in `main.py` — video scheduling split across two files. Reaches deep into UI internals (`ui.config_clipboard`, `ui._get_config_path`, `ui._tracer_interface`).
- **Target home / abstraction:** Keep as the one-shot dispatcher, but let each Module register/own its handlers so this file stops growing per-feature.

### camera_input / controller_input
- **Purpose:** Continuous camera movement — keyboard/scroll/orbit (`camera_input.py`, 196) and Xbox-gamepad FPS camera + face-button one-shots (`controller_input.py`, 236).
- **Classification:** Always (input is core), though the gamepad half is closer to a Module.
- **Coupling / scatter flags:** Gamepad face-button one-shots are injected into `ui_state` back in `main.py:230`–`238` rather than owned here.
- **Target home / abstraction:** Consolidate gamepad one-shot injection into `controller_input` so `main.py` doesn't reach into `joystick_state` dict keys.

### RuleManager
- **Purpose:** Undo stack of `(rule, seed)` tuples (max 200).
- **Location:** `services/rule_manager.py` (60). `push_rule`, `push_zero_rule`, `pop_rule`, `get_current_rule/seed`, `clear`.
- **Coupling / scatter flags:** Clean data structure, but rule *preview push/pop* logic is spread across `menu_bar.py`, `command_handler.py:473`–513, and `config_browser.py`.
- **Target home / abstraction:** Stays as-is (good model). **Preview is being simplified** (see Target-State Directives): drop the rule preview push/pop stack; preview becomes "cache current config, load preview; on leave, reload cached." Centralize the cache/restore in one small preview helper the load-menu callers share.

---

## Modules

Self-contained features that should each become a folder owning all their logic. Ordered roughly by how tangled they currently are.

### Preferences System
- **Purpose:** Persistent user state saved as JSON to `Documents/Fluoddity`.
- **Location:** `state/preferences_state.py` (218). `save_preferences`/`load_preferences` (`:191`/`:201`); loaded `main.py:52`, saved `:274,:1159`.
- **Coupling / scatter flags:** **THE #1 coupling hotspot.** One `PreferencesState` dataclass holds ~150 fields for ~10 unrelated subsystems (rendering, bloom, recording, advanced drawing, generics, radio, plotting, ~30 `tracer_*`, ~30 `three_d_optix_*`, `three_d_pt_*`, 3D camera, every `show_*_window` flag). Every window mixin reads/writes `self.state.preferences.*` directly. Splitting any Module out cleanly first requires carving its fields out of this monolith.
- **Target home / abstraction:** Keep a `PreferencesState` *aggregate*, but compose it from **per-module preference slices** (e.g. `TracerPrefs`, `OptixPrefs`, `RecordingPrefs`, `AdvancedDrawingPrefs`) each owned by its module. Persist by asdict-ing the slices. This is the enabling move for most other module extractions.

### Save / Load System (Config Serialization)
- **Purpose:** `PhysicsConfig` + `ConfigSaver` — JSON (v7) + base64 "SIM7:" clipboard string; legacy SIM1–6 decode.
- **Location:** `services/config_saver.py` (571). Depends on `ui/physics_params.py` for param defs.
- **Coupling / scatter flags:** Every saved field is **hand-listed in 5 methods** (`PhysicsConfig` fields, `to_dict`, `from_dict`, `create_config`, `apply_config`, `:105`–`375`). Adding a saved field means editing all five. Legacy binary decode (`_from_legacy_bytes`, `:462`–571) is self-contained and separately deletable.
- **Target home / abstraction:** Drive serialization from a single field registry (ideally the same `physics_params.py` source) so add-a-field is one edit. Split legacy decode into its own module.

### Multi-Load System — ⛔ CUT
- **Purpose:** Mix up to 64 configs simultaneously across cohorts; progression/assignment.
- **Location:** `services/multi_load_service.py` (150) + `state/multi_load_state.py` (24).
- **Coupling / scatter flags:** **Scattered across service + sim + UI + command_handler.** Python state in the service; the actual SSBO write in user-owned `sim.py` (`_write_multi_load_ssbo`); config-add in `ui/config_browser.py:209`; clipboard import in `command_handler.py:628`; forces mouse mode + greys out param locks via prefs/menu. `multi_load_enabled` on `MultiLoadState`, per-config flags on the service. Touching ≥5 files to enable/disable.
- **Decision: CUT ENTIRELY.** Too tangled to salvage; will be rebuilt from scratch later (likely after the sim parameter-system rewrite) if wanted. Remove the service, the `MultiLoadState`, the SSBO packing + all `get_particle_*`/config-index/weighted-trail bloat in `entity_update.glsl` and `sim.py`, the config-add path in `config_browser.py`, the clipboard-import handler, the `UIState`/prefs coupling, and the mouse-mode/param-lock interlocks. See CUT directive above and Step 1 of the plan.

### Parameter Lock Service
- **Purpose:** Freeze parameters across config loads; snapshot/restore around `apply_config`; Alt-click toggle; red styling.
- **Location:** `services/parameter_lock_service.py` (180).
- **Coupling / scatter flags:** Self-contained service, but callers woven through `ui/menu_bar.py:8`–24 (snapshot wrappers), `services/field_handler.py` (lock-aware writes), `main.py:667`–672, `physics_window.py`/`slider_widgets.py` (inline alt-click hooks), plus hardcoded lockable-param lists (`:13`–28) that must track `SimState`/`PreferencesState`. One of the most tangled features to disable.
- **Target home / abstraction:** A `parameter_locks/` module. Replace inline alt-click hooks with a single wrapper the physics widgets call; derive lockable params from the shared param registry instead of a hardcoded list.

### Config Clipboard
- **Purpose:** In-memory list of `(PhysicsConfig, label, field_snapshot)` checkpoints (Ctrl+C); hover-preview, load, rename, delete, import-all-to-multiload.
- **Location:** State on the **`UI` object** (`ui/core.py:109`–115) — not in `state/`. Window in **misnamed** `ui/history_window.py`. Handlers in `command_handler.py:515`–635. Snapshots + 20-entry cap in `services/field_handler.py` (`enforce_snapshot_cap`, `:327`).
- **Coupling / scatter flags:** **Scattered across 4 places**; architectural inconsistency (state on UI, not `state/`); `show_history_window` is a plain UI attribute, not a pref; Ctrl+C does double duty (system clipboard string + in-memory checkpoint).
- **Target home / abstraction:** A `config_clipboard/` module with its own state container in `state/`, its own correctly-named window, and its handlers. Move the physics-tooltip rendering currently sharing `history_window.py` elsewhere.

### Video Recorder
- **Purpose:** Buffer GPU frames and pipe to FFmpeg.
- **Location:** `services/video_recorder.py` (57, facade) → `utilities/vid_saver.py` (77) → `utilities/ffmpeg_recorder.py` (272) + `utilities/save_frame_gpu.py` (251).
- **Coupling / scatter flags:** The **service layering is clean**, but the recording *state machine* is scattered: `command_handler.py:204`–220 (`video_pending`) + `main.py` (cadence lock, start check, restore). Settings spread across `PreferencesState` (`max_frames`, `motion_blur_samples`, `supersample_k`, `recording_*`, `video_end_frame`, `tracer_mode`, `filename_prefix`).
- **Target home / abstraction:** A `RecordingController` owning the idle→pending→recording→finished machine and a `RecordingPrefs` slice, so `main.py`/`command_handler.py` just call `start/stop/tick`.

### Scheduled / Batch Renders (RenderSpec)
- **Purpose:** Capture full app + GPU-buffer snapshots (`.frs` dirs); queue and batch-render them unattended.
- **Location:** `services/render_spec.py` (428) + `ui/scheduled_renders_window.py` (305) + render-queue state machine in `main.py:258`–296, `:1026`–1112.
- **Entry points:** `capture_current_state` (`:46`), `save_to_disk` (`:146`), `load_metadata` (`:214`), `load_gpu_buffers` (`:244`), `apply_state` (`:297`), `list_available_specs` (`:416`).
- **Coupling / scatter flags:** The service is fairly clean and touches many components only at capture/apply time (sim, camera, controller_cam, config_saver, rule_manager, adv_draw). The batch state machine lives in `main.py`.
- **Target home / abstraction:** Move the render-queue state machine out of `main.py` into this module (a `BatchRenderController`). Uses the good `_init_*_state()` window pattern already.

### Entity Picker
- **Purpose:** Nearest-particle picking (2D point / 3D ray) via GPU readback.
- **Location:** `services/entity_picker.py` (119). `find_nearest_entity`, `find_nearest_entity_3d`, `update_buffer`.
- **Coupling / scatter flags:** Low and clean (good model). Buffer must be re-pointed on world-size change (`command_handler.py:190`).
- **Target home / abstraction:** Stays as-is.

### Advanced Drawing / Force-Strafe Fields
- **Purpose:** Painted/procedural force+strafe field texture feeding the sim.
- **Location:** `utilities/advanced_drawing.py` (`AdvancedDrawingProcessor`, 359) + `services/field_handler.py` (338) + `services/field_texture_cache.py` (80) + `ui/advanced_drawing_window.py` (246) + `ui/field_loader_window.py` (69) + `utilities/field_texture_io.py` (192) + shaders `field_drawing.frag`, `field_override/march.frag`.
- **Coupling / scatter flags:** `FieldHandler` is large and coupling-heavy (field transitions + PNG cache + lock-aware writes across save/load/preview/clipboard). Field view modes override `sim.view_tex` inline in `main.py:654`–661. The processor is reached into directly from `preferences_window.py:167`.
- **Target home / abstraction:** An `advanced_drawing/` module bundling the processor, field handler, caches, IO, windows, and its prefs slice. The field-override shader is a Swappable sub-role (see Swappable).

### Arrow Debug
- **Purpose:** Velocity-field debug arrow overlay.
- **Location:** `services/arrow_debug_service.py` (95). Rendered from `main.py:820`–843.
- **Coupling / scatter flags:** Clean, self-contained (good model).
- **Target home / abstraction:** Stays as-is; a candidate to live under a `debug/` grouping.

### Plotting
- **Purpose:** GPU histogram reporting — shader `report()` → SSBO (binding 5) → rendered histogram texture.
- **Location:** `plotting_manager.py` (138, **at repo root**) + `ui/plotting.py` (108) + shaders `histogram_render.*`. Hooked in `simulation_runner.py` (6 call sites), enabled `main.py:221`, reloaded `command_handler.py:126`.
- **Coupling / scatter flags:** Manager owns its GPU resources cleanly; living at repo root (not `services/`) is a minor inconsistency.
- **Target home / abstraction:** Move to a `plotting/` module (or `services/`). Otherwise a good model.

### Radio
- **Purpose:** Visibility filter hiding particles outside a target frequency ± bandwidth band.
- **Location:** `ui/radio_window.py` (38) + `SimState` fields (`RADIO_ENABLED/TARGET_FREQ/BANDWIDTH`, `sim_state.py:29`–32) + `tryset` in `sim.py:199`–201 + shader `entity_update.glsl` + menu toggle `menu_bar.py:418` + pref `show_radio_window`.
- **Coupling / scatter flags:** **Low — the cleanest optional module in the codebase** (a good model to emulate).
- **Target home / abstraction:** Already near-ideal; the 3 `SimState` fields could move to a radio-owned slice.

### Generics
- **Purpose:** 8 live-coding scratch uniforms exposed as sliders.
- **Location:** `ui/generics_window.py` (26) + `PreferencesState.generic0..7` + threaded through `sim.update(generics=...)`.
- **Coupling / scatter flags:** Small; prefs-monolith dependency only.
- **Target home / abstraction:** Own prefs slice; otherwise fine.

### 3D Controls Window
- **Purpose:** FPS/orbit camera settings + 3D sim params (TESTING_MODE, PLANE_SAMPLES, debug slice) + OptiX-spheres toggle.
- **Location:** `ui/three_d_window.py` (84).
- **Coupling / scatter flags:** One of a **cluster of four interrelated 3D/renderer windows** (`three_d_window`, `optix_window` 227, `tracer_window` 253) all sharing the huge `three_d_*` / `three_d_optix_*` / `tracer_*` pref blocks and importing the renderer interfaces for availability checks.
- **Target home / abstraction:** These windows should move next to their renderers (each Swappable renderer owns its control window + prefs slice).

### UI Window Host + Passive Windows
- **Purpose:** The imgui mixin architecture and the remaining passive windows not owned by a specific module above.
- **Location:** `ui/core.py` (795, the mixin host: `__init__`, GLFW callbacks, `get_state()`, render dispatch) + the physics/config UI (`physics_window.py` 575, `slider_widgets.py` 450, `physics_params.py` 139, `config_browser.py` 232, `menu_bar.py` 477) + passive helper windows **`ui/help_windows.py`** (410, Controls/Tutorial/Sweeps/Performance/Video-recording) and **`ui/popup_modals.py`** (85, Save/Overwrite/Delete dialogs — clean).
- **Coupling / scatter flags:** `UI` multiple-inherits 17 mixins so all render methods share `self` (chosen because imgui immediate-mode needs shared widget state — see `ui/README.md`). `core.py` has god-object tendencies (holds config-clipboard + file-browser + menu state); `get_state()` and the Load-submenu preview are cross-cutting (see Cross-cutting Concerns). `popup_modals.py` and `help_windows.py` are clean, passive, and low-coupling.
- **Target home / abstraction:** Keep the mixin host, but let each Module contribute its own window mixin + own its flags/state so `core.py` and `get_state()` stop growing per feature. Passive help/modal windows can stay as shared UI infrastructure.

---

## Swappable

A role with exactly one active implementation at a time; switching must free the previous implementation's GPU resources.

### 3D Renderer (the headline swappable role)
Today there are **four** implementations of "render the particle cloud." After the refactor there are **two swappable renderers** (unified OptiX; volumetric tracer), with GL-points as a lightweight preview and the 2D `cam_brush` path cut. See the Target-State Directives above.

| Impl | Module | Wrapper | `cleanup()`? | Fate |
|------|--------|---------|--------------|------|
| 2D `cam_brush` | `camera.py` (`generate_view_texture`), `cam_brush.*` | inline in Camera | n/a | ⛔ CUT (3D-only) |
| GL_POINTS (baseline 3D) | `camera.py:209` (`_generate_3d_view_texture`), `points_3d.*` | inline in Camera | n/a | Keep as light preview renderer |
| OptiX sphere raytracer | `optix_renderer/` (`renderer.py` 920, `cuda_src.py` 360, `interop.py` 170) | `optix_interface.py` (277, `OptiXInterface`) | yes (`renderer.py:845`) | ⛔ MERGE into path tracer (rasterize checkbox) |
| OptiX path tracer | `optix_pathtracer/` (`renderer.py` 2214, `cuda_src.py` 1068, `sdf_scene.py` 203) | `pathtracer_interface.py` (784, `PathTracerInterface`) | yes | Becomes THE OptiX renderer |
| Volumetric path tracer | `volrender/` (`renderer.py` 637, `grid.py`, `majorant.py`, `camera.py`, `params.py`) | `tracer_interface.py` (497, `TracerInterface`) | **service has none** | Keep; give it `cleanup()` |

- **Selection state:** `camera_state.optix_enabled`, `preferences.three_d_rt_mode` (0=sphere,1=X-spp PT,2=accumulate PT), `preferences.tracer_realtime_mode`, `preferences.tracer_mode`. UI toggles in `three_d_window`, `optix_window`, `tracer_window`. (Post-merge, `three_d_rt_mode==0` becomes the "rasterize" *checkbox* within the unified OptiX renderer, not a separate renderer.)
- **Dispatch:** Lifecycle + selection is a ~220-line `if/else` chain in `main.py:409`–647; active OptiX/PT wrapper routed to `camera.optix_interface`; volumetric tracer dispatched separately (blit `main.py:889`–903, realtime tick `:762`–787, video `:704`–744).
- **Coupling / scatter flags:**
  1. **No common interface.** The three wrapper classes re-implement the same informal contract (`is_available`, `cleanup`, `display_texture`, timing, entity-buffer change detection) by copy-paste, not inheritance.
  2. **`VolumeRenderer` leak.** `TracerInterface._ensure_renderer()` drops the old renderer by reassigning `self._renderer = None` on resolution change (`tracer_interface.py:142`–146), but `VolumeRenderer` exposes **no `cleanup()`/`release()`** — its 3D textures and compute programs are reclaimed only by GC. `main.py` never tears down `_tracer_interface` on mode exit either.
  3. **Aliased slot.** `camera.optix_interface` holds either the sphere renderer OR the path tracer; `camera.py:214` calls `.render_frame()` on whichever is set with no type check.
  4. **Duplicated fragile CUDA-struct mirroring:** a hand-computed `PARAMS_DTYPE` numpy struct that must byte-match the CUDA `Params` in both `optix_renderer/renderer.py:61` and `optix_pathtracer/renderer.py`, plus a duplicated `_camera_basis_from_vectors()`. (Eliminated by the merge.)
  5. **Renderer-specific video + GAS-rebuild logic in the orchestrator** (`simulation_runner.py:448,549`; motion-blur GAS-rebuild hack `main.py:802`–813). GAS-refit path is being cut (always rebuild).
- **Target home / abstraction:**
  - **Merge the two OptiX renderers.** Delete `optix_renderer/`; the path tracer is the sole OptiX renderer. "Rasterize" is a checkbox that only alters raygen (pinhole, no DOF), the bounce loop (terminate after first hit), and NEE (deterministic sun shadow ray + AO samples). BRDF/lighting/tonemap/denoise/pipeline are shared. This removes the duplicated `PARAMS_DTYPE`/`_camera_basis_from_vectors`/GAS/interop code.
  - **One `Renderer` protocol + one `RendererHost`.** Methods: `render_frame → finished frame`, `is_available`, `cleanup`, `display_texture`, timing, plus the renderer's own **video strategy** (offline/motion-blur). The host instantiates one renderer at a time and **always frees the previous on swap**. Replace the aliased `camera.optix_interface` with a typed handle from the host.
  - **Renderers own the whole image pipeline** (tonemap, temporal SS/motion blur, bloom, denoise) and return finished frames. `FrameAssembler` and the 2D `frame_assembly` motion-blur/tonemap role dissolve into the renderers; overlays move to the Viewer's overlay pass.
  - **Give `VolumeRenderer` a real `cleanup()`.**
  - **Always rebuild the GAS.** Delete the rebuild-interval slider, scheduling, and `refit_accel`.

### Field-Override Shader
- **Purpose:** Selectable fragment shader that procedurally generates the force/strafe field (`shaders/field_override/*.frag`).
- **Location:** Selected by `preferences.field_override_shader`; toggled by `shader_driven_field`; consumed in the advanced-drawing pipeline.
- **Coupling / scatter flags:** Minor; currently only `march.frag` exists.
- **Target home / abstraction:** A small registry of override shaders under the advanced-drawing module, swapped by filename.

---

## Shared Infrastructure / Utilities

Stateless (or near-stateless) helpers used broadly. Not app modules; keep in `utilities/`.

| Component | Location | Purpose |
|-----------|----------|---------|
| GL helpers | `utilities/gl_helpers.py` (151) | `tryset`, `read_shader`, `shader_prepend`, `readback_rule`, grid coords. Widely imported. |
| Paths | `utilities/paths.py` (123) | Platform-aware app vs `Documents/Fluoddity` paths; first-run init. |
| Keybinding management | `utilities/keybinding_management.py` (146) | Rebindable shortcuts from `keyboard_controls.json`. |
| FFmpeg recorder | `utilities/ffmpeg_recorder.py` (272) | Subprocess-pipe H.264 encoder. |
| Vid saver | `utilities/vid_saver.py` (77) | Frame-buffered saver wrapping ffmpeg_recorder. |
| Save frame (GPU) | `utilities/save_frame_gpu.py` (251) | GPU screenshot with supersampling. |
| Frame assembler | `utilities/frame_assembler.py` (226) | Motion-blur accumulation + composite. *Cross-tree flag:* prepends volrender shader includes for inline SDF preview. **Target: dissolves into renderers** (each renderer owns tonemap + motion blur); overlay markup moves to the Viewer. |
| Bloom | `utilities/bloom.py` (229) | Mip-chain bloom post-process. **Target: becomes a stage each renderer applies internally**, not a Camera-level post step. |
| Field texture IO | `utilities/field_texture_io.py` (192) | Float32 field ↔ 16-bit PNG with range metadata; polar loader; resize. |
| Field texture cache | `services/field_texture_cache.py` (80) | LRU host cache for field PNGs (good model). |

> `frame_assembler` and `bloom` straddle the line between utility and Always-rendering; they're grouped here because they're stateless-ish helpers instantiated by `Camera`.

---

## State Containers

The `state/` dataclasses. Data, not behavior — but the primary coupling surface of the whole app.

| Container | Location | Notes |
|-----------|----------|-------|
| `SimState` | `state/sim_state.py` (121) | Physics params, sweep/jitter dicts, radio fields, appearance, notes, slider ranges. Radio + sweep data embedded here rather than owned by their modules. |
| `PreferencesState` | `state/preferences_state.py` (218) | **Monolith, ~150 fields / ~10 subsystems — #1 coupling hotspot.** See Preferences module above. |
| `UIState` | `state/ui_state.py` (103) | **Flag god-object:** nests Sim/Camera/Recording/Preferences/MultiLoad + ~60 one-shot `request_*`/click/input flags. Primary UI↔orchestrator coupling surface. |
| `CameraState` | `state/camera_state.py` (29) | 2D + 3D camera; also carries UI-display-only telemetry (`optix_*_time_ms`, `pathtracer_sample_count`) — mixes input with output. |
| `MultiLoadState` | `state/multi_load_state.py` (24) | Multi-load toggle + progression/assignment. **⛔ CUT with multi-load.** |
| `RecordingState` | `state/recording_state.py` (7) | **Empty shell** — fields migrated to `PreferencesState`; kept for structure/back-compat. Candidate for removal or revival as the RecordingController's state. |

**Target:** Break `PreferencesState` into per-module slices; move one-shot flags out of the monolithic `UIState` so each Module marshals its own; move `CameraState` telemetry out to a read-only render-stats struct; either delete `RecordingState` or repurpose it for the RecordingController. Delete `MultiLoadState` (multi-load cut) and drop the `strong_determinism` pref (control cut).

---

## Cross-cutting Concerns

Logic deliberately woven through many components. These resist becoming a single Module; the refactor goal is to give each a **single owner + a thin, well-defined touch-point** at each site rather than duplicated inline logic.

- **Parameter Locks** — service is clean; callers woven through menu bar, field handler, `main.py`, physics window, slider widgets, plus hardcoded param lists. (Also listed under Modules; the cross-cutting part is the alt-click hooks + lock-aware writes.)
- **Parameter Sweeps + Jitter** — dicts on `SimState`; `calculate_setting()` triplicated across `entity_update.glsl`, `canvas.frag`, `sim.py`; reticle logic in `main.py`. (Target design belongs to the separate parameter rewrite — out of scope here.)
- **Config Save/Load field duplication** — every saved field hand-listed in 5 methods of `config_saver.py`.
- **`ui/core.py get_state()` flag marshalling** — a long, hand-maintained block (`:440`–595) that grows ~4 lines per feature (set + reset). Each Module should marshal its own flags.
- **`ui/menu_bar.py` Load-submenu preview** — config apply + watercolor + field strengths + parameter-lock snapshot tangled into menu rendering (`:68`–179). Highest-complexity UI file.
- **`ui/history_window.py` double duty** — renders the Config Clipboard AND the physics tooltip shader (`update_tooltip_texture`, `render_physics_tooltip`) in one file. Split.
- **Renderer lifecycle in the orchestrator** — see Swappable; ~220 lines in `orchestrate_frame`.
- **Recording / screenshot state machines** — split between `main.py` and `command_handler.py`.
- **Post-construction attribute injection** — see App/Orchestrator.
- **Reticle / sweep-indicator markup** — currently baked into `frame_assembly.frag` + computed in `main.py`. Target: moves to the Viewer's overlay pass so it renders over any backend (see Target-State Directives → Viewer).
- **View modes / tiling / debug / strong-determinism / GAS-refit** — ⛔ all CUT (see CUT directive). `current_view_option` collapses to non-tiled/non-debug; `strong_determinism` and its canvas double-buffer path removed; GAS always rebuilds.

---

## Dev / Standalone Tools

Not part of the running app; catalogued so they aren't mistaken for app modules.

| Item | Location | Purpose |
|------|----------|---------|
| Config migration scripts | `scripts/migrate_configs.py`, `scripts/update_orientation_and_hazard.py`, `scripts/update_slider_ranges.py`, `scripts/make_distance_field.py` | One-off maintenance scripts. |
| OptiX demo | `demos/optix_demo.py` | ModernGL↔OptiX bridge reference. |
| PTX build helper | `compile_ptx.py` | Offline PTX compilation (dev). |
| Volrender demo | `volrender/example/demo.py` (+ its own shaders) | Standalone volumetric-tracer harness. |
| Volrender tests | `volrender/tests/test_step*.py` | Step-by-step validation of the volumetric tracer — the only real test suite in the repo. |
| Path-tracer step tests | `optix_pathtracer/test_step3..7.py` | Step validation for the OptiX path tracer. |
| Config analysis | `utilities/analyze_physics_configs.py` | Standalone matplotlib analysis (dev). |
| ImGui texture demo | `utilities/imgui_gltexture_demo.py` | GL-texture-in-ImGui reference (not imported). |
| Launcher debug | `launcher_debug.py` | Debug launcher helper. |

> The main app has "no automated tests" (per `CLAUDE.md`); the `volrender/tests/` and `optix_pathtracer/test_step*` suites test those standalone renderer packages in isolation, not the integrated app.

---

## Refactor Step Plan

The refactor is broken into **12 steps**, each sized to fit a single Claude Code context window. A different Claude handles each step; the human checks and tests between steps. **Cuts come first** (they shrink the surface every later step must wrestle with), then simplifications, then the foundational preferences split, then the renderer/Viewer rework, then module extractions, then cleanup.

Each step below lists its **goal**, the **main files touched**, and a **verify** (how the human confirms it before moving on — run `python main.py` and exercise the named features unless noted). The app has no automated test suite for the integrated app, so verification is manual. Keep each step's diff self-contained; do not start the next step's work early. `sim.py` is user-owned — the steps that touch it stay minimal and ask before restructuring.

> Sequencing rationale: Steps 1–4 delete dead/unwanted systems so the codebase is smaller and simpler before the structural work. Step 5 (prefs split) is foundational — it unblocks clean module extraction. Steps 6–8 do the renderer unification, the `Renderer` protocol + host, and the Viewer. Steps 9–11 extract the tangled modules. Step 12 is final cleanup + doc refresh.

### Step 1 — Cut Multi-Load
- **Goal:** Remove the multi-load system entirely, including its bloat in the sim.
- **Files:** delete `services/multi_load_service.py`, `state/multi_load_state.py`, `ui`/menu multi-load entries; strip multi-load from `sim.py` (`_write_multi_load_ssbo`, `get_particle_*`, config-index, weighted-trail helpers), `shaders/entity_update.glsl` (the `MultiLoadConfig` struct + getters), `command_handler.py` (clipboard→multiload import), `ui/config_browser.py` (add-config path), `ui/preferences_window.py` / `ui/menu_bar.py` (mouse-mode + param-lock interlocks), `services/__init__.py`, `state/ui_state.py`, `state/__init__.py`, `main.py` wiring.
- **Verify:** App launches; load configs normally; sim runs; parameter locks + sweeps still work; no references to `multi_load` remain (`grep -ri multi_load` clean except comments/history).

### Step 2 — Cut tiled / debug / legacy view modes
- **Goal:** Collapse `current_view_option` to the live views only; remove `Camera [Tiled]` and DEBUG modes and their tiling math.
- **Files:** `state/sim_state.py` (`current_view_option` semantics), `camera.py` (tiling view-bounds/scale, `tiling_mode` plumbing), `main.py` (tiling branches, leave-tiling reposition), `simulation_runner.py` (tiling kwargs), `ui/preferences_window.py` / view selectors, relevant shader `tiling_mode` uniforms.
- **Verify:** App launches; remaining view options work; no tiling seams/branches; camera behaves normally.

### Step 3 — Cut Strong Determinism + GAS rebuild-interval/refit
- **Goal:** Remove two always-on-or-never knobs. Delete the Extras → Strong Determinism control and its canvas double-buffer gating (pick one determinism behavior and keep it). Delete the GAS rebuild-interval slider, its scheduling, and the `refit_accel` path — always rebuild.
- **Files:** `state/preferences_state.py` (`strong_determinism`, `three_d_optix_gas_rebuild_interval`), `sim.py` (double-buffer gating), `ui/preferences_window.py` / `ui/menu_bar.py` (control), `optix_renderer/renderer.py` + `optix_pathtracer/renderer.py` (`refit_accel`, `gas_rebuild_interval`, scheduling), the interfaces, `main.py` (rebuild-scheduling + motion-blur-pause-rebuild hack).
- **Verify:** App launches; 3D OptiX render still correct after sim reset / config change / pause (GAS always fresh); determinism behavior acceptable.

### Step 4 — Simplify Preview
- **Goal:** Replace the preview system with: enter → cache current config + load preview; change → load new preview (cache untouched); leave → load cached. Drop the rule preview push/pop stack.
- **Files:** `command_handler.py` (`_handle_preview_commands`, `:473`–513), `ui/menu_bar.py` + `ui/config_browser.py` (hover preview push/pop), `services/rule_manager.py` (remove preview-specific push/pop usage), `services/field_handler.py` (preview cache paths — align to the new model), `state/ui_state.py` preview flags.
- **Verify:** Hover configs in the Load menu → preview loads; hover another → switches; unhover → original restored exactly (physics + rule + fields). No leftover preview state after leaving.

### Step 5 — Split `PreferencesState` into per-module slices (foundational)
- **Goal:** Break the ~150-field monolith into composed per-module slice dataclasses (e.g. `RenderingPrefs`, `RecordingPrefs`, `OptixPrefs`, `TracerPrefs`, `AdvancedDrawingPrefs`, `UIWindowsPrefs`, `CameraPrefs`). `PreferencesState` becomes an aggregate of slices; `save/load_preferences` (de)serializes the slices with the same backward-compat filtering.
- **Files:** `state/preferences_state.py` (define slices + aggregate), then mechanical rename of `self.state.preferences.X` access across `ui/*`, `main.py`, `command_handler.py`, `simulation_runner.py`, `camera.py`, interfaces. Keep field names stable inside slices to preserve JSON keys (or add a migration in `load_preferences`).
- **Verify:** Prefs round-trip (save, restart, all settings restored); every window reads/writes its slice; existing `preferences.config` still loads (migration if keys moved).

### Step 6 — Merge the two OptiX renderers ✅ DONE
- **Goal:** Delete `optix_renderer/`; make the path tracer the sole OptiX renderer. Add a "rasterize" checkbox that only changes raygen (pinhole, no DOF), the bounce loop (terminate after first hit), and NEE (deterministic sun shadow ray + N AO samples). Everything else follows path-tracer mode.
- **Outcome:** `optix_renderer/` + `optix_interface.py` + `compile_ptx.py` deleted; `interop.py` moved into `optix_pathtracer/`. `rt_mode == 0` is now a **rasterize preset** on the path tracer (`params.rasterize`): pinhole (aperture forced 0), single hit, directional-sun NEE, plus a new AO-modulated fake-ambient term (`ambient_color` × `ambient`, AO rays reuse `sample_cosine_hemisphere`). The OptiX Controls window was reorganized into Lighting / Material / Rasterize / Path Trace / Post-Process with mode-based greying; NEE + Cos-lobe Sky + Photosphere moved to Lighting (work in both modes); Denoise split into path-trace + rasterize toggles. `main.py`'s dual-interface lifecycle collapsed to one `PathTracerInterface` (see `_sync_pathtracer_prefs`). New prefs: `optix.ambient_color`, `optix.rz_denoise_enabled`. Dead `camera_state.optix_gas_time_ms`/`optix_render_time_ms` removed.
- **Files:** delete `optix_renderer/`, `optix_interface.py`; extend `optix_pathtracer/renderer.py` + `optix_pathtracer/cuda_src.py` with the rasterize branch (raygen/bounce/NEE); fold AO controls into the path tracer; `pathtracer_interface.py`; `main.py` (remove the sphere-renderer lifecycle branch, route all OptiX through the path tracer); `ui/optix_window.py` / `ui/three_d_window.py` (rasterize checkbox + AO); `camera.py` (single OptiX handle).
- **Verify:** Rasterize checkbox ON ≈ the old sphere look (pinhole + sun shadow + AO, single bounce); OFF = full path tracer; DOF only in PT mode; no `optix_renderer` references remain; VRAM released on toggle-off.

### Step 7 — `Renderer` protocol + `RendererHost` + renderer-owned pipeline
- **Goal:** Define one `Renderer` protocol (`render_frame → finished frame`, `is_available`, `cleanup`, `display_texture`, timing, `force_rebuild`, `video_strategy`). Make the OptiX renderer, the volumetric tracer, and GL-points implement it. A single `RendererHost` owns the active renderer, creates one at a time, and **always frees the previous on swap**. Move tonemap + temporal SS/motion blur + bloom + denoise **into** each renderer so it returns finished frames. Give `VolumeRenderer` a real `cleanup()`.
- **Files:** new `rendering/` (protocol + host); `optix_pathtracer/`, `volrender/renderer.py` (+ `cleanup`), GL-points path; `pathtracer_interface.py` / `tracer_interface.py` (collapse into protocol impls); `simulation_runner.py` (renderer-specific video → `video_strategy`); `main.py` (replace the ~220-line lifecycle chain with the host); `camera.py` (drop `optix_interface` alias); begin dissolving `utilities/frame_assembler.py` / `bloom.py` into renderers.
- **Verify:** All render backends still display + record video via the host; switching backends frees the previous (watch VRAM); motion blur + bloom + tonemap look correct per backend; no `VolumeRenderer` leak on resolution change.

### Step 8 — Viewer window + overlay pass; begin 3D-only ✅ DONE (Viewer); cam_brush cut DEFERRED
- **Goal:** Add the always-displayed "Viewer" imgui window (immune to show/hide-windows) that displays the renderer's finished frame and runs an overlay pass (reticle, sweep indicator, draw cursor). Route all display through the Viewer instead of drawing to the whole window. Cut the tiled/2D-composite overlay path from `frame_assembly`. **Begin 3D-only:** remove the 2D `cam_brush` display role in favor of GL-points; ⚠️ resolve the deferred question of mouse trail-drawing + 2D camera here (e.g. drawing via `screen_to_ray_3d`), or explicitly defer with a tracking note if it risks breaking drawing.
- **Outcome:** New `viewer/` package (`Viewer` class) — the always-drawn "Viewer" imgui window docked into the dockspace central node, immune to the show/hide-windows toggle (rendered from `ui/core.py`'s dispatch, not gated by `show_sidebar`). It owns the `OverlayCompositor` (moved off `Camera`) and is the single **display** sink, parallel to the video recorder's **file** sink. `camera.render()` no longer draws to `ctx.screen` or composites overlays — it returns the finished, markup-free display texture; `main._render_camera_view` hands that to `viewer.prepare()` (which composites display-only overlays) and the three display paths (normal, realtime-tracer fullscreen, OptiX-preview fullscreen) all route through the Viewer. Arrow-debug renders into a Viewer-owned display copy via `viewer.draw_debug_overlay()` so it stays out of recordings. `main` clears the default framebuffer before `ui.render()` (the renderer no longer blits to screen). Recording/screenshot capture is unchanged (still reads `camera.assembled_texture`, still markup-free).
- **⚠️ DEFERRED — 2D `cam_brush` cut + 3D-only:** The "begin 3D-only" half (remove the 2D `cam_brush` display role, route the default view through GL-points, move mouse trail-drawing to `screen_to_ray_3d`) was **explicitly deferred** per the plan's own escape hatch. Reason: `camera.cam_brush_target` is a shared FBO that the OptiX renderers blit into and that all display paths funnel through; trail-drawing still depends on the 2D `screen_to_tex` mapping (see `command_handler._handle_entity_pick`/`_handle_sweep_click`). Cutting it risks silently breaking mouse drawing/picking, which cannot be verified in the dev environment. The Viewer + overlay-pass goal is complete and self-contained; the `cam_brush`→GL-points migration is a clean follow-up (its own step). Mouse math stays in full-window screen space because the Viewer image fills the central node 1:1.
- **Files:** new `viewer/`; `main.py` (`_render_camera_view` → Viewer, screen clear, arrow-debug via Viewer, `viewer.cleanup()`); `camera.py` (`render()` returns finished tex, dropped `overlay_compositor`); `ui/core.py` (Viewer in render dispatch, exempt from hide-all); `overlay.frag` already carried the markup (from Step 7).
- **Verify:** Viewer window always visible, survives "hide windows"; reticle/sweep/draw-cursor overlays render over the output; recording still captures the clean (markup-free) frame; drawing still works (2D `cam_brush` path retained). ⚠️ If the Viewer image is vertically inverted, flip the `imgui.image` uv args in `viewer/viewer.py:render_window` (uv0/uv1) — the flip couldn't be verified without a display.

### Step 9 — Modularize Config Clipboard ✅ DONE
- **Goal:** Give the config clipboard a real home: a `config_clipboard/` module with its own state container in `state/` (move it off the `UI` object), its correctly-named window, and its handlers. Split the physics-tooltip rendering out of `history_window.py`.
- **Outcome:** New `state/config_clipboard_state.py` (`ConfigClipboardState` + `ClipboardEntry` — the checkpoint list/counter + preview/rename window state, moved off `UI`; entries are now named `ClipboardEntry` dataclasses instead of `(config, label, field)` tuples). New `config_clipboard/` package with `ConfigClipboardHandler` owning the preview/load/delete handlers (extracted from `command_handler.py`; reuses the parent's `_apply_config_with_locks`/`_push_and_apply_rule` via injected callables, and `ui.update_physics_defaults`). `ui/history_window.py` deleted and split into `ui/config_clipboard_window.py` (`ConfigClipboardWindowMixin`, `render_config_clipboard_window`) and `ui/physics_tooltip.py` (`PhysicsTooltipMixin`, which now also owns `setup_tooltip_shader` + the shared `last_hovered_slider`/`physics_window_interaction` hover state). `show_history_window` (a plain UI attr) is now the persisted pref `UIWindowsPrefs.show_config_clipboard_window` (with a `_FLAT_KEY_MAP` entry). The Ctrl+C save-checkpoint path stays in `CommandHandler._handle_config_commands` (part of the save flow) but writes to `ui.clipboard_state.add(...)`. `field_handler.enforce_snapshot_cap` now operates on `ClipboardEntry` attributes. The `UIState` one-shot flag plumbing was already clean and is unchanged.
- **Files:** new `state/config_clipboard_state.py`, `config_clipboard/{__init__,handlers}.py`, `ui/config_clipboard_window.py`, `ui/physics_tooltip.py`; edited `ui/core.py`, `ui/menu_bar.py`, `command_handler.py`, `state/{__init__,preferences_state}.py`, `services/field_handler.py`; deleted `ui/history_window.py`.
- **Verify:** Ctrl+C checkpoints; hover-preview, load, rename, delete, still work; physics tooltip still renders; `show_history_window` replaced by a proper pref/flag.

### Step 10 — Extract Recording + Batch-Render controllers
- **Goal:** Move the recording state machine (idle→pending→recording→finished) and the render-queue batch state machine out of `main.py`/`command_handler.py` into owning controllers.
- **Files:** new `RecordingController` (owns `video_pending`, cadence lock, start check, restore; uses `RecordingPrefs` slice); new `BatchRenderController` (owns the render-queue phases, currently `main.py:258`–296 + `:1026`–1112); `main.py`, `command_handler.py`, `simulation_runner.py`, `services/video_recorder.py`, `services/render_spec.py`, `ui/scheduled_renders_window.py`.
- **Verify:** Normal recording (incl. scheduled start + max-frames auto-stop) works; screenshot still works; scheduled batch render loads/records/advances/closes correctly; settings restored after recording.

### Step 11 — Modularize Advanced Drawing + Parameter Locks
- **Goal:** Bundle advanced-drawing (processor + field handler + caches + IO + windows + prefs slice) into an `advanced_drawing/` module. Give parameter locks a `parameter_locks/` module with one shared alt-click wrapper (replacing inline hooks) and a lockable-param list derived from the shared param registry rather than hardcoded.
- **Files:** new `advanced_drawing/` gathering `utilities/advanced_drawing.py`, `services/field_handler.py`, `services/field_texture_cache.py`, `utilities/field_texture_io.py`, `ui/advanced_drawing_window.py`, `ui/field_loader_window.py`, the field-override shader registry; new `parameter_locks/` from `services/parameter_lock_service.py` + the alt-click hooks in `physics_window.py`/`slider_widgets.py`/`menu_bar.py`.
- **Verify:** Force/strafe field painting, image load, shader-driven override, save/load/preview field round-trip; parameter lock alt-click toggling + lock-aware config loads still work.

### Step 12 — Cleanup + docs refresh
- **Goal:** De-duplicate the `config_saver.py` field list (drive from one registry); let each Module marshal its own `get_state()` flags so `ui/core.py get_state()` stops being a monolith; move `plotting_manager.py` into a module/`services/`; relocate the remaining renderer control windows next to their renderers; prefer constructor injection over post-construction attribute injection in `App.__init__`. Update `ARCHITECTURE.md` + this inventory to the new reality; delete/repurpose `RecordingState`.
- **Files:** `services/config_saver.py`, `ui/core.py`, `plotting_manager.py`, `main.py` wiring, `ARCHITECTURE.md`, `docs/component_inventory.md`.
- **Verify:** Full pass through `docs/testing_checklist.md`; add-a-saved-field is one edit; App wiring reads clearly; docs match the code.

---

Clean models already in the tree to emulate throughout: **Radio**, **Entity Picker**, **Arrow Debug**, **Field Texture Cache**, **Plotting**, the `volrender/` package, and the `_init_*_state()` pattern used by `field_loader`/`scheduled_renders`.
