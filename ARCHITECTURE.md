# Fluoddity Architecture

Fluoddity is a GPU-accelerated particle simulation for generative art. Thousands to millions of particles follow neural-net-like "Rules" that govern how they respond to trail density, producing emergent patterns ranging from flowing rivers to branching lightning. The physics engine is a generalization of [Sage Jenson's physarum transport model](https://cargocollective.com/sagejenson/physarum), extended into a 3D voxel canvas with multiple 3D rendering backends (GL points, an OptiX path tracer with a rasterize preset, and a volumetric path tracer). Built with Python 3.12, ModernGL (OpenGL 4.3 compute), GLFW, Dear ImGui (imgui_bundle), NumPy, FFmpeg, and — for the RTX renderers — OptiX / CUDA.

> **This document is the high-level overview.** For an exhaustive, classified catalogue of every component (with coupling flags and recommended target homes for the ongoing modularity refactor), see [`docs/component_inventory.md`](docs/component_inventory.md).

## Core Architecture: Orchestrator Pattern

```
                              App (main.py)
        ┌───────────────┬──────────┼───────────┬──────────────────┐
        │               │          │           │                  │
  CommandHandler  SimulationRunner │   camera_input /       (lazy) 3D renderers
        │               │          │   controller_input      OptiX / PathTracer /
        └───────┬───────┴──────────┼───────────┘              volumetric Tracer
                │                   │
        ┌───────┴─────┬─────────────┴────┬───────────┬───────────┐
        │             │                  │           │           │
   ┌────┴───┐   ┌─────┴──┐   ┌───────────┴──┐  ┌─────┴────┐  ┌───┴────┐
   │   UI   │   │  Sim   │   │    Camera    │  │ Services │  │ State  │
   │(imgui) │   │ (GPU)  │   │(+ImagePipeline)│ │          │  │(dataclasses)│
   └────────┘   └────────┘   └──────────────┘  └──────────┘  └────────┘
```

**App** (`main.py`) is the orchestrator. Each frame `orchestrate_frame()`:
1. Reads UI state via `ui.get_state()`
2. Polls the gamepad (`controller_input`) and injects one-shot flags
3. Delegates one-shot commands to `CommandHandler`
4. Advances the render-queue (batch render) state machine
5. Delegates camera input to `process_camera_input()`
6. Runs the recording / screenshot state machines
7. Manages the lazy lifecycle of the OptiX / path-tracer interfaces (create, sync, release VRAM)
8. Applies state to Sim and Camera
9. Delegates physics + frame assembly to `SimulationRunner` (or a renderer-specific video path)
10. Runs the realtime tracer tick if active
11. Prepares the Viewer's display texture (finished frame → `viewer.prepare()`, which composites display-only overlays), renders the arrow-debug overlay into a Viewer-owned copy, clears the screen, then renders the UI (which draws the Viewer window into the dockspace central node)

Core components do not talk to each other directly — coordination flows through the orchestrator. (The UI is a partial exception: App passes several service references into it via its constructor, and `CommandHandler` reaches into some UI internals. As of Step 12 `App.__init__` uses constructor injection throughout — `ControllerCam` is built first and injected into `Camera`/`UI`/`CommandHandler`, and the UI-dependent services are `UI` constructor params — so there is no init-time post-construction attribute injection. See the inventory for the remaining coupling notes.)

## Key Design Patterns

### Passive UI
The UI renders ImGui widgets and exposes state via `get_state()`. It does not run simulation logic. It also owns the GLFW input callbacks (keyboard/mouse/scroll) and the ImGui GLFW backend, and holds references (passed in via its constructor by App) to several services and the tracer camera/sim; the active tracer interface is created lazily inside the tracer window mixin.

### One-Shot Flags
UI sets boolean flags (e.g. `request_reset`, `request_save_file`, `toggle_recording`) that the orchestrator reads and clears each frame. These flags all live on `UIState`. `UI.get_state()` builds the input snapshot + core command flags, then delegates to each owning mixin's `_marshal_<feature>_state(state)` hook (copy-into-state + reset), so a feature's flag marshalling lives beside its `_init_*_state()` rather than in one central block (Step 12).

### State Containers
All mutable state lives in dataclasses in `state/`. The UI modifies these via widget bindings; the orchestrator reads them and applies to components. `PreferencesState` is now composed of per-module slices (accessed nested, e.g. `preferences.tracer.sdf_enabled`); `UIState` is still a flag monolith (see [State](#state-state) below).

### GPU Compute Pipeline
Physics runs entirely on the GPU via GLSL compute shaders. `Sim` manages shader programs, buffers, and textures. The CPU-side code dispatches compute calls and reads back results only when needed (e.g. entity picking, rule readback).

## The GPU Pipeline

The simulation canvas is a **cubic 3D voxel texture** (`W = H = D`), double-buffered (ping-ponged) since the compute-shader diffusion pass needs separate read/write buffers. One physics step (`Sim.update()`) runs:

```
entity_update.glsl   (compute)  — particle sense → rule eval → forces/strafe → boundaries;
                                   atomically splats trails into the 3D canvas
        │  (fourier6_6.glsl, volrender/common.glsl, volrender/volume_scene.glsl
        │   are textually prepended into this shader — diffusion helper + SDF collision)
        ▼
   memory_barrier()
        ▼
canvas_update_3d.glsl (compute)  — trail decay + diffusion into the other canvas buffer
```

Then, to display, `Camera.generate_view_texture()` produces the view texture (2D `cam_brush` path, or the 3D path — GL_POINTS or a routed OptiX/path-tracer interface), and the **`ImagePipeline`** (`rendering/image_pipeline.py`) composites it (temporal motion-blur accumulation, tonemap, gamma, emboss, SDF preview) **and applies bloom internally**, returning a *finished, markup-free* frame. That finished frame goes two places: to the **video recorder** (file sink, clean) and to the **`Viewer`** (`viewer/`, display sink). The Viewer owns the **`OverlayCompositor`**, which composites UI markup (sweep reticle, draw-trail ring, advanced-drawing field overlay) over the finished frame **for display only** — so recorded video and screenshots capture the clean frame. (The ImagePipeline/OverlayCompositor split replaced the old monolithic `FrameAssembler` + `frame_assembly.frag` in Step 7; the Viewer window + overlay ownership landed in Step 8 of the modularity refactor.)

> **Note:** Older docs referenced `fourier4_4.glsl` and an `entity_update → fourier4_4 → frame_assembly` chain. That is out of date; the diffusion shader is `fourier6_6.glsl` and it is *prepended into* `entity_update.glsl`, not a separate dispatch stage.

## 3D Rendering Backends (Swappable)

There are **three** implementations of the "render the particle cloud in 3D" role, plus the 2D `cam_brush` path. Exactly one 3D backend is active at a time:

| Backend | Module | App-facing wrapper | Selected by |
|---------|--------|--------------------|-------------|
| GL_POINTS (baseline) | `camera.py` (`_generate_3d_view_texture`), `shaders/points_3d.*` | — (inline in Camera) | `render_3d` on, no OptiX |
| OptiX path tracer | `optix_pathtracer/` | `pathtracer_interface.py` (`PathTracerInterface`) | `camera_state.optix_enabled` |
| Volumetric path tracer | `volrender/` | `tracer_interface.py` (`TracerInterface`) | `tracer_realtime_mode > 0` (realtime) or `tracer_mode` (video) |

The OptiX path tracer is the **single OptiX renderer**. Its `three_d_rt_mode` preference selects a mode: **0 = Rasterize** (a single-hit direct-lighting preset that mimics the old sphere raytracer — pinhole camera, one NEE shadow ray toward the sun, plus an AO-modulated fake-ambient term), **1 = X spp** (reset-per-frame realtime path tracing), **2 = Accumulate** (progressive path tracing). Rasterize and path-trace modes share one BRDF/tonemap/denoise pipeline and one `PathTracerInterface`; the mode only changes raygen (aperture), the bounce loop (single hit), and the ambient term. The sphere renderer (`optix_renderer/` + `optix_interface.py`) was merged into the path tracer and deleted.

The active OptiX renderer is routed to the camera through the single `camera.optix_interface` slot; `Camera` calls `.render_frame()` on it. The volumetric tracer is dispatched separately (fullscreen blit for preview, its own realtime tick, and its own video path).

**Renderer lifecycle + contract (`rendering/` package, Step 7).** A structural `Renderer` protocol (`rendering/renderer.py`) defines the shared contract (`is_available()`, `cleanup()`, `display_texture`, `reset_accumulation`, `force_rebuild`, timing props); both `PathTracerInterface` and `TracerInterface` conform. A **`RendererHost`** (`rendering/host.py`) owns the OptiX interface's whole lifecycle — lazy create, VRAM release on toggle-off, per-frame error recovery, preference sync, and preview — replacing the ~300-line if/else chain that used to live in `orchestrate_frame()`. `App._pathtracer_interface` is now a property aliasing `renderer_host.optix`. The two renderer-specific offline video paths moved behind a **`VideoStrategy`** (`rendering/video_strategies.py`: `TracerVideoStrategy`, `OptixPtVideoStrategy`), built by `SimulationRunner` and driven each frame via `App.active_video_strategy`. The `VolumeRenderer` VRAM leak (dropped renderer on grid-resolution change) is fixed by a `cleanup()` cascade (`VolumeRenderer` → `VoxelGrid` + `MajorantBuilder`) plus `TracerInterface.cleanup()`.

## File Map

Line counts are approximate and will drift; treat them as size signals.

### Orchestration Layer
| File | Lines | Description |
|------|-------|-------------|
| `main.py` | 1175 | App orchestrator: GL/window bootstrap, frame loop, four state machines (screenshot, recording, render-queue, renderer lifecycle) |
| `command_handler.py` | 730 | Processes one-shot UI commands (resets, config save/load, clipboard, mouse picking, previews, render-spec, field-image load) |
| `simulation_runner.py` | ~385 | Physics stepping + normal-path frame assembly; motion-blur/non-blur paths. Builds renderer video strategies (the offline video logic itself lives in `rendering/video_strategies.py`) |
| `camera_input.py` | 196 | WASD/QE camera + scroll-zoom (2D); 3D orbit controls (standalone functions) |
| `controller_input.py` | 236 | Xbox gamepad FPS camera + face-button one-shots |

### 3D Renderer Wrappers (root)
| File | Lines | Description |
|------|-------|-------------|
| `pathtracer_interface.py` | ~830 | App-facing wrapper over the OptiX path tracer (rasterize + path-trace modes, realtime, preview, offline video) |
| `tracer_interface.py` | 497 | App-facing wrapper over the volumetric path tracer |

### Renderer Packages
| Package | Lines | Description |
|---------|-------|-------------|
| `rendering/` | ~700 | Renderer protocol + lifecycle (Step 7): `renderer.py` (`Renderer` protocol, `RenderCamera`, `VideoStrategy`), `host.py` (`RendererHost` — OptiX lifecycle/prefs-sync/preview), `image_pipeline.py` (`ImagePipeline` accumulation+tonemap+bloom), `video_strategies.py` (`TracerVideoStrategy`, `OptixPtVideoStrategy`) |
| `optix_pathtracer/` | ~3700 (excl. tests) | The single OptiX renderer (`renderer.py`, `cuda_src.py`, `sdf_scene.py`, `interop.py`) + step tests. `rt_mode` selects rasterize (0) / X-spp (1) / accumulate (2). |
| `volrender/` | ~1096 | Standalone volumetric path tracer (`renderer.py`, `grid.py`, `majorant.py`, `camera.py`, `params.py`) + `shaders/`, `example/`, `tests/`. `VolumeRenderer`/`VoxelGrid`/`MajorantBuilder` now have a `cleanup()` cascade. |

### UI Package (`ui/`)
Mixin-based architecture. The `UI` class in `core.py` multiple-inherits 17 mixins, so every render method shares `self`. See [`ui/README.md`](ui/README.md).

| File | Lines | Description |
|------|-------|-------------|
| `core.py` | ~730 | UI class, `__init__`, GLFW callbacks, `get_state()` flag marshalling, render dispatch, file-browser state (holds a `ConfigClipboardState` reference) |
| `physics_window.py` | 575 | Physics settings panel: slider groups, parameter-lock alt-click hooks |
| `menu_bar.py` | 477 | File/Reset/Locks/Help/Extras menus; Load-submenu live preview; distance-based auto-close |
| `slider_widgets.py` | 450 | Slider with range menu, jitter, sweep/range context menus |
| `help_windows.py` | 410 | Controls, tutorial, sweeps, performance, video-recording windows |
| `preferences_window.py` | 309 | World size, physics frequency, mouse mode, view, appearance, bloom |
| `scheduled_renders_window.py` | 305 | Render queue: load specs, rename/delete, preview, execute batch |
| `tracer_window.py` | 253 | Volumetric path tracer controls |
| `advanced_drawing_window.py` | 246 | Force/strafe field brush controls, shader-driven field |
| `config_browser.py` | 232 | Config file scan/cache + hierarchical Load submenu |
| `optix_window.py` | ~245 | OptiX renderer controls: rt-mode, Lighting/Material/Rasterize/Path Trace/Post-Process sections, preview |
| `config_clipboard_window.py` | ~110 | **Config Clipboard** window (renamed from `history_window.py`, Step 9): checkpoint list, hover-preview, load/rename/delete |
| `physics_tooltip.py` | ~200 | Physics-slider tooltip: animated shader graphic + hover tracking (split out of `history_window.py`, Step 9) |
| `physics_params.py` | 139 | Data-driven single source of truth for physics slider defs |
| `plotting.py` | 108 | Plotting/histogram window |
| `popup_modals.py` | 85 | Save/Overwrite/Delete confirmation dialogs |
| `three_d_window.py` | 80 | 3D camera + 3D sim params + OptiX (RTX) toggle |
| `field_loader_window.py` | 69 | Load image as force/strafe field |
| `radio_window.py` | 38 | Radio (frequency-band visibility filter) window |
| `generics_window.py` | 26 | Live-coding scratch uniform sliders |

### Simulation & Rendering
| File | Lines | Description |
|------|-------|-------------|
| `sim.py` | 914 | GPU particle simulation: buffers, compute dispatch, physics→uniform mapping, sweeps, rules (**user-owned**) |
| `camera.py` | ~470 | Camera state, coordinate transforms, view-texture generation (2D/3D); owns an `ImagePipeline` and returns a *finished, markup-free* display texture (no screen draw, no overlays — the Viewer owns those) |
| `config_clipboard/` | ~130 | `ConfigClipboardHandler` (Step 9): the config-clipboard preview/load/delete command handlers, operating on the `ConfigClipboardState`. Window lives in `ui/config_clipboard_window.py`; Ctrl+C save-checkpoint stays in `CommandHandler` |
| `viewer/` | ~230 | `Viewer` (Step 8): the always-displayed "Viewer" imgui window (docks into the dockspace central node, immune to hide-windows). Shows the renderer's finished frame. Single display sink (parallel to the video recorder's file sink). `draw_debug_overlay()` blends arrow-debug into a Viewer-owned copy so recordings stay clean |

### Services (`services/`)
| File | Lines | Description |
|------|-------|-------------|
| `config_saver.py` | 571 | `PhysicsConfig` + `ConfigSaver`: JSON (v7) + base64 "SIM7:" clipboard serialization; legacy SIM1–6 decode |
| `render_spec.py` | 428 | `RenderSpec` + `RenderSpecService`: full app + GPU-buffer snapshot (`.frs`) for scheduled/batch video renders |
| `field_handler.py` | 338 | Force/strafe field GPU texture transitions + PNG cache across save/load/preview/clipboard; lock-aware writes |
| `parameter_lock_service.py` | 180 | Freeze parameters across config loads; snapshot/restore; alt-click + styling helpers |
| `entity_picker.py` | 119 | Nearest-particle picking (2D point / 3D ray) via GPU readback |
| `arrow_debug_service.py` | 95 | Velocity-field debug arrow overlay |
| `field_texture_cache.py` | 80 | LRU host-memory cache for field PNGs |
| `rule_manager.py` | 60 | Undo stack of `(rule, seed)` tuples (max 200) |
| `video_recorder.py` | 57 | Thin facade over `VidSaver` |
| `plotting_manager.py` | 138 | GPU histogram reporting manager (moved here from repo root in Step 12) |

### State (`state/`)
Plain dataclasses.

| File | Lines | Description |
|------|-------|-------------|
| `preferences_state.py` | ~470 | Persistent user prefs, now split into **10 per-module slice dataclasses** (`RenderingPrefs`, `BloomPrefs`, `RecordingPrefs`, `AdvancedDrawingPrefs`, `GenericsPrefs`, `ParameterLocksPrefs`, `TracerPrefs`, `OptixPrefs`, `Camera3DPrefs`, `UIWindowsPrefs`) composed into `PreferencesState`. Accessed nested (`preferences.tracer.sdf_enabled`). `save_preferences` writes nested JSON; `load_preferences` also reads legacy flat-key JSON via `_FLAT_KEY_MAP`. `to_flat_dict`/`set_flat` back the flat snapshot used by `render_spec` |
| `sim_state.py` | 121 | Physics params (ALL_CAPS), sweeps/jitter dicts, radio fields, appearance, notes, slider ranges |
| `ui_state.py` | 103 | **Aggregate frame snapshot** nesting Sim/Camera/Recording/Preferences + ~60 one-shot flags. The flags are marshalled per-mixin (Step 12), but still declared on this one aggregate dataclass |
| `camera_state.py` | 29 | 2D + 3D camera state + OptiX/path-tracer enable and timing readouts |
| `config_clipboard_state.py` | ~55 | `ConfigClipboardState` + `ClipboardEntry`: in-memory config checkpoints + preview/rename window state (Step 9; moved off the `UI` object) |
| `recording_state.py` | 18 | `RecordingState`: the `RecordingController`'s live state-machine data (`video_pending`, `video_scheduled_start_frame`, restore-settings; Step 10). Still nested as a fresh unused default in `UIState` for the frame snapshot |

### Utilities (`utilities/`)
| File | Lines | Description |
|------|-------|-------------|
| `advanced_drawing.py` | 359 | `AdvancedDrawingProcessor`: force/strafe field GPU textures + brush ops |
| `ffmpeg_recorder.py` | 272 | Subprocess-pipe FFmpeg H.264 encoder |
| `save_frame_gpu.py` | 251 | GPU screenshot with spatial supersampling |
| `bloom.py` | 229 | Mip-chain bloom post-process (now driven by `rendering/ImagePipeline`) |
| `field_texture_io.py` | 192 | Save/load float32 field as 16-bit PNG with range metadata; polar loader; resize |
| `keybinding_management.py` | 146 | Rebindable keyboard shortcuts from `keyboard_controls.json` |
| `paths.py` | 123 | Platform-aware paths (app dir vs `Documents/Fluoddity`); first-run init |
| `gl_helpers.py` | 151 | `tryset`, `read_shader`, `shader_prepend`, `readback_rule`, grid coords — widely imported |
| `vid_saver.py` | 77 | Frame-buffered video saver wrapping `ffmpeg_recorder` |

### Shaders (`shaders/`)
| File | Description |
|------|-------------|
| `entity_update.glsl` | **Core physics** compute shader; `fourier6_6.glsl` + volrender includes prepended |
| `canvas_update_3d.glsl` | Trail decay + diffusion into the 3D canvas |
| `fourier6_6.glsl` | Diffusion / Fourier feature helper (prepended into `entity_update.glsl`) |
| `canvas.vert/.frag` | (Legacy 2D trail rendering path) |
| `camera.vert/.frag` | View texture → screen |
| `cam_brush.vert/.frag` | Camera-space instanced particle rendering (2D view) |
| `points_3d.vert/.frag` | GL_POINTS 3D particle rendering (baseline 3D backend) |
| `frame_assembly.vert` | Fullscreen-quad vertex shader shared by `image_pipeline.frag` and bloom |
| `image_pipeline.frag` | Image-pipeline core: temporal accumulation + tonemap + gamma + emboss + inline SDF preview (volrender includes prepended). Markup-free. |
| `bloom_downsample.frag / bloom_upsample.frag` | Bloom mip chain |
| `field_drawing.frag` | Force/strafe field painting |
| `field_override/march.frag` | Shader-driven field override (raymarched procedural field) |
| `arrow_debug.vert/.frag` | Debug arrow overlay for velocity field |
| `histogram_render.vert/.frag` | Plotting histogram rendering |
| `tooltip_graphic.frag` | Animated physics-tooltip visualization |

`volrender/shaders/` (`clear3d.comp`, `splat.comp`, `majorant.comp`, `pathtrace.comp`, `resolve.comp`, `tonemap.comp`, `common.glsl`, `volume_scene.glsl`) belong to the volumetric tracer. Note `common.glsl` and `volume_scene.glsl` are also prepended into `entity_update.glsl` and `image_pipeline.frag` — a cross-tree shader coupling.

## Data Flow: Physics Parameter

```
SimState.SENSOR_GAIN                         # state/sim_state.py - dataclass field
    ↓ (UI widget binding)
imgui.slider_float(v=state.sim.SENSOR_GAIN)  # ui/physics_window.py (+ ui/physics_params.py defs)
    ↓ (get_state returns combined state)
ui_state = ui.get_state()                    # ui/core.py → main.py orchestrate_frame
    ↓ (apply state)
sim.apply_state(ui_state.sim)                # main.py → sim.py
    ↓ (set uniform)
tryset(program, 'SENSOR_GAIN', value)        # sim.py entity_update()
    ↓ (GPU)
uniform float SENSOR_GAIN;                   # shaders/entity_update.glsl
```

For a step-by-step guide to adding new parameters, see [`docs/adding_ui_shader_params.md`](docs/adding_ui_shader_params.md).

## Data Flow: One-Shot Command

```
User clicks "Reset" in menu
    ↓  UI sets self._request_reset = True            # ui/menu_bar.py
    ↓  get_state() packages it into UIState          # ui/core.py
    ↓  App reads ui_state.request_reset              # main.py
    ↓  CommandHandler.process_commands() handles it  # command_handler.py
    ↓  sim.reset() called                            # sim.py
```

## Data Flow: Config Save/Load

```
Save: UI → request_save_file → CommandHandler → ConfigSaver.create_config(SimState, rule) → JSON file
Load: UI → request_load_file → CommandHandler → ConfigSaver.load_from_file() → apply_config(SimState) → sim.apply_rule()
Preview: Hover in load menu → push rule to stack → unhover → pop rule (RuleManager)
Clipboard: Ctrl+C encodes a "SIM7:" base64 string AND pushes an in-memory config-clipboard checkpoint
```

## Key Subsystems

### Rule System
A "Rule" is a float32 matrix that parameterizes each particle's neural-net-like behavior. Rules are a stack managed by `RuleManager`:
- **Left click** (Select Particle mode): read back the clicked particle's mutated rule (deferred one frame for GPU readback), push to stack
- **Right click**: pop rule (undo)
- **Full reset (Z)**: push a zero rule
- Config save/load push rules to the stack

### Parameter Sweeps & Jitter
Physics parameters can vary spatially (X/Y sweep), by particle cohort, or by per-frame temporal jitter. Configured via dicts on `SimState` (`x_sweeps`, `y_sweeps`, `cohort_sweeps`, `jitters`). When a sweep is active a reticle shows current values at its position. (A separate proposal, `docs/engine_rewrite_proposal.md`, envisions unifying these into one parameter-resolution framework; that is out of scope for the current modularity refactor.)

### Advanced Drawing / Force-Strafe Fields
`AdvancedDrawingProcessor` maintains a GPU field texture (`.xy` = force vector, `.zw` = strafe vector) painted by the mouse (several brush modes) or generated by a shader-driven override (`field_override/march.frag`). `FieldHandler` manages field texture transitions and a PNG cache across save/load/preview/clipboard, with lock-aware writes. Fields feed into `entity_update.glsl`.

### Parameter Locks
Freeze selected parameters so they survive config loads (snapshot before `apply_config`, restore after). Toggled via Alt-click on widgets; locked widgets render in red. The service is self-contained but its callers are woven through the menu bar, field handler, physics window, slider widgets, and `main.py`.

### Motion Blur
Temporal accumulation: run `speedmult` physics steps per display frame, render every `blur_quality`-th step, and blend via the `ImagePipeline`. `SimulationRunner` handles both motion-blur and non-blur paths through shared helpers.

### Video Recording
State machine (idle → optional pending wait → recording → finished) split between `CommandHandler` (`video_pending`) and `App` (cadence lock, start check, restore). Three video sub-modes: normal (`ImagePipeline`), volumetric-tracer video, and OptiX path-tracer offline video. The two renderer-specific paths live behind `VideoStrategy` (`rendering/video_strategies.py`), driven per frame via `App.active_video_strategy`. Recorded frames are markup-free (overlays composite for display only). Encoding: `VideoRecorderService` → `VidSaver` → `ffmpeg_recorder`.

### Scheduled / Batch Renders
`RenderSpecService` captures a full app + GPU-buffer snapshot as a `.frs` directory. The Scheduled Renders window queues specs; `App`'s render-queue state machine (`loading → start_recording → recording → done`) loads each, records a video, advances, and closes (optionally shuts down the PC) when done.

### Screenshot
2-frame state machine (pending → in_progress → save + restore). On the override frame, settings are temporarily maxed for quality.

### Controller / 3D Camera
`ControllerCam` + `controller_input.py` provide an Xbox-gamepad FPS camera for the 3D view, with face-button one-shots (pause, reset, cycle RT mode, randomize mutations). `camera_input.py` provides keyboard/scroll movement and 3D orbit.

### Bloom, Plotting, Radio, Generics
- **Bloom** — mip-chain post-process (`utilities/bloom.py`).
- **Plotting** — GPU histogram: shader `report()` calls write to an SSBO; `PlottingManager` renders channels to a texture shown in the Plotting window.
- **Radio** — visibility filter hiding particles outside a target frequency ± bandwidth band; a cleanly isolated module (3 `SimState` fields + shader + one window).
- **Generics** — 8 live-coding scratch uniforms exposed as sliders.

## Technologies
- **Python 3.12** — application logic
- **ModernGL** — OpenGL 4.3 compute dispatch + rendering
- **GLFW** — window management, input
- **imgui_bundle** (Dear ImGui) — immediate-mode GUI
- **NumPy** — CPU-side array operations
- **FFmpeg** — video encoding (subprocess pipe)
- **OptiX 9.1 / CUDA** (optional) — RTX path tracer (with a rasterize preset)
