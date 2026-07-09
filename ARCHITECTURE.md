# Fluoddity Architecture

Fluoddity is a GPU-accelerated particle simulation for generative art. Thousands to millions of particles follow neural-net-like "Rules" that govern how they respond to trail density, producing emergent patterns ranging from flowing rivers to branching lightning. The physics engine is a generalization of [Sage Jenson's physarum transport model](https://cargocollective.com/sagejenson/physarum), extended into a 3D voxel canvas with multiple 3D rendering backends (GL points, OptiX raytraced spheres, an OptiX path tracer, and a volumetric path tracer). Built with Python 3.12, ModernGL (OpenGL 4.3 compute), GLFW, Dear ImGui (imgui_bundle), NumPy, FFmpeg, and — for the RTX renderers — OptiX / CUDA.

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
   │(imgui) │   │ (GPU)  │   │(+FrameAssembler)│ │          │  │(dataclasses)│
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
11. Renders the camera view, arrow-debug overlay, and UI

Core components do not talk to each other directly — coordination flows through the orchestrator. (The UI is a partial exception: App injects several service references onto it, and `CommandHandler` reaches into some UI internals. See the inventory for these coupling notes.)

## Key Design Patterns

### Passive UI
The UI renders ImGui widgets and exposes state via `get_state()`. It does not run simulation logic. It also owns the GLFW input callbacks (keyboard/mouse/scroll) and the ImGui GLFW backend, and holds references (injected by App) to several services and the active tracer interface.

### One-Shot Flags
UI sets boolean flags (e.g. `request_reset`, `request_save_file`, `toggle_recording`) that the orchestrator reads and clears each frame. These flags all live on `UIState` and are marshalled in `UI.get_state()`.

### State Containers
All mutable state lives in dataclasses in `state/`. The UI modifies these via widget bindings; the orchestrator reads them and applies to components. Note that `PreferencesState` and `UIState` have grown into monoliths (see [State](#state-state) below).

### GPU Compute Pipeline
Physics runs entirely on the GPU via GLSL compute shaders. `Sim` manages shader programs, buffers, and textures. The CPU-side code dispatches compute calls and reads back results only when needed (e.g. entity picking, rule readback).

## The GPU Pipeline

The simulation canvas is a **cubic 3D voxel texture** (`W = H = D`), double-buffered for optional strong determinism. One physics step (`Sim.update()`) runs:

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

Then, to display, `Camera.generate_view_texture()` produces the view texture (2D `cam_brush` path, or the 3D path — GL_POINTS or a routed OptiX/path-tracer interface), and `FrameAssembler.assemble_frame()` composites it (temporal motion-blur accumulation, tonemap, gamma, emboss, reticle overlays). Bloom is applied as a post step.

> **Note:** Older docs referenced `fourier4_4.glsl` and an `entity_update → fourier4_4 → frame_assembly` chain. That is out of date; the diffusion shader is `fourier6_6.glsl` and it is *prepended into* `entity_update.glsl`, not a separate dispatch stage.

## 3D Rendering Backends (Swappable)

There are **four** implementations of the "render the particle cloud in 3D" role, plus the 2D `cam_brush` path. Exactly one 3D backend is active at a time:

| Backend | Module | App-facing wrapper | Selected by |
|---------|--------|--------------------|-------------|
| GL_POINTS (baseline) | `camera.py` (`_generate_3d_view_texture`), `shaders/points_3d.*` | — (inline in Camera) | `render_3d` on, no OptiX |
| OptiX raytraced spheres | `optix_renderer/` | `optix_interface.py` (`OptiXInterface`) | `camera_state.optix_enabled`, `three_d_rt_mode == 0` |
| OptiX path tracer | `optix_pathtracer/` | `pathtracer_interface.py` (`PathTracerInterface`) | `optix_enabled` + `three_d_rt_mode > 0` |
| Volumetric path tracer | `volrender/` | `tracer_interface.py` (`TracerInterface`) | `tracer_realtime_mode > 0` (realtime) or `tracer_mode` (video) |

The active OptiX/path-tracer wrapper is routed to the camera through the single `camera.optix_interface` slot; `Camera` calls `.render_frame()` on whichever is set. The volumetric tracer is dispatched separately (fullscreen blit for preview, its own realtime tick, and its own video path).

**There is currently no common renderer interface.** The three wrapper classes (`OptiXInterface`, `PathTracerInterface`, `TracerInterface`) independently re-implement the same informal contract (`is_available()`, `cleanup()`, `display_texture`, timing props, entity-buffer change detection) by copy-paste. Their ~220-line create/sync/release lifecycle lives inline in `orchestrate_frame()`. Unifying this behind one `Renderer` protocol with one owner is a primary goal of the refactor — see the inventory's Swappable section.

## File Map

Line counts are approximate and will drift; treat them as size signals.

### Orchestration Layer
| File | Lines | Description |
|------|-------|-------------|
| `main.py` | 1175 | App orchestrator: GL/window bootstrap, frame loop, four state machines (screenshot, recording, render-queue, renderer lifecycle) |
| `command_handler.py` | 730 | Processes one-shot UI commands (resets, config save/load, clipboard, mouse picking, previews, render-spec, field-image load) |
| `simulation_runner.py` | 624 | Physics stepping + frame assembly; motion-blur/non-blur paths; renderer-specific video paths (tracer, OptiX PT) |
| `camera_input.py` | 196 | WASD/QE camera + scroll-zoom (2D); 3D orbit controls (standalone functions) |
| `controller_input.py` | 236 | Xbox gamepad FPS camera + face-button one-shots |

### 3D Renderer Wrappers (root)
| File | Lines | Description |
|------|-------|-------------|
| `optix_interface.py` | 277 | App-facing wrapper over the OptiX sphere renderer |
| `pathtracer_interface.py` | 784 | App-facing wrapper over the OptiX path tracer (realtime, preview, offline video) |
| `tracer_interface.py` | 497 | App-facing wrapper over the volumetric path tracer |
| `plotting_manager.py` | 138 | GPU histogram reporting manager (lives at root; see inventory) |
| `compile_ptx.py` | 41 | Offline PTX build helper (dev tool) |

### Renderer Packages
| Package | Lines | Description |
|---------|-------|-------------|
| `optix_renderer/` | ~1470 | Standalone OptiX raytraced-sphere renderer (`renderer.py`, `cuda_src.py`, `interop.py`) |
| `optix_pathtracer/` | ~3600 (excl. tests) | Standalone OptiX path tracer (`renderer.py`, `cuda_src.py`, `sdf_scene.py`) + step tests |
| `volrender/` | ~1096 | Standalone volumetric path tracer (`renderer.py`, `grid.py`, `majorant.py`, `camera.py`, `params.py`) + `shaders/`, `example/`, `tests/` |

### UI Package (`ui/`)
Mixin-based architecture. The `UI` class in `core.py` multiple-inherits 17 mixins, so every render method shares `self`. See [`ui/README.md`](ui/README.md).

| File | Lines | Description |
|------|-------|-------------|
| `core.py` | 795 | UI class, `__init__`, GLFW callbacks, `get_state()` flag marshalling, render dispatch, config-clipboard + file-browser state, tooltip shader |
| `physics_window.py` | 575 | Physics settings panel: slider groups, parameter-lock alt-click hooks |
| `menu_bar.py` | 477 | File/Reset/Locks/Help/Extras menus; Load-submenu live preview; distance-based auto-close |
| `slider_widgets.py` | 450 | Slider with range menu, jitter, sweep/range context menus |
| `help_windows.py` | 410 | Controls, tutorial, sweeps, performance, video-recording windows |
| `preferences_window.py` | 309 | World size, physics frequency, mouse mode, view, appearance, bloom |
| `scheduled_renders_window.py` | 305 | Render queue: load specs, rename/delete, preview, execute batch |
| `tracer_window.py` | 253 | Volumetric path tracer controls |
| `advanced_drawing_window.py` | 246 | Force/strafe field brush controls, shader-driven field |
| `config_browser.py` | 232 | Config file scan/cache + hierarchical Load submenu |
| `optix_window.py` | 227 | OptiX sphere + path tracer controls, preview |
| `history_window.py` | 219 | **Config Clipboard** window (misnamed) + physics tooltip shader rendering |
| `physics_params.py` | 139 | Data-driven single source of truth for physics slider defs |
| `plotting.py` | 108 | Plotting/histogram window |
| `popup_modals.py` | 85 | Save/Overwrite/Delete confirmation dialogs |
| `three_d_window.py` | 84 | 3D camera + 3D sim params + OptiX-spheres toggle |
| `field_loader_window.py` | 69 | Load image as force/strafe field |
| `radio_window.py` | 38 | Radio (frequency-band visibility filter) window |
| `generics_window.py` | 26 | Live-coding scratch uniform sliders |

### Simulation & Rendering
| File | Lines | Description |
|------|-------|-------------|
| `sim.py` | 914 | GPU particle simulation: buffers, compute dispatch, physics→uniform mapping, sweeps, rules (**user-owned**) |
| `camera.py` | 557 | Camera state, coordinate transforms, view-texture generation (2D/3D), tiling, bloom hookup, screen rendering; owns `FrameAssembler` |

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

### State (`state/`)
Plain dataclasses.

| File | Lines | Description |
|------|-------|-------------|
| `preferences_state.py` | 218 | **Persistent user prefs (~150 fields spanning ~10 subsystems)** + `save/load_preferences`. The single biggest coupling hotspot |
| `sim_state.py` | 121 | Physics params (ALL_CAPS), sweeps/jitter dicts, radio fields, appearance, notes, slider ranges |
| `ui_state.py` | 103 | **Aggregate frame snapshot** nesting Sim/Camera/Recording/Preferences + ~60 one-shot flags |
| `camera_state.py` | 29 | 2D + 3D camera state + OptiX/path-tracer enable and timing readouts |
| `recording_state.py` | 7 | **Empty shell** — fields migrated to `PreferencesState`; kept for structure/back-compat |

### Utilities (`utilities/`)
| File | Lines | Description |
|------|-------|-------------|
| `advanced_drawing.py` | 359 | `AdvancedDrawingProcessor`: force/strafe field GPU textures + brush ops |
| `ffmpeg_recorder.py` | 272 | Subprocess-pipe FFmpeg H.264 encoder |
| `save_frame_gpu.py` | 251 | GPU screenshot with spatial supersampling |
| `bloom.py` | 229 | Mip-chain bloom post-process |
| `frame_assembler.py` | 226 | Motion-blur temporal accumulation + final composite; inline SDF preview raymarch |
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
| `canvas_slice.glsl` | Extract a Z-slice of the 3D canvas for the debug canvas view |
| `canvas.vert/.frag` | (Legacy 2D trail rendering path) |
| `camera.vert/.frag` | View texture → screen |
| `cam_brush.vert/.frag` | Camera-space instanced particle rendering (2D view) |
| `points_3d.vert/.frag` | GL_POINTS 3D particle rendering (baseline 3D backend) |
| `frame_assembly.vert/.frag` | Final composite: tonemap, gamma, emboss, reticle; inline SDF preview (volrender includes prepended) |
| `bloom_downsample.frag / bloom_upsample.frag` | Bloom mip chain |
| `field_drawing.frag` | Force/strafe field painting |
| `field_override/march.frag` | Shader-driven field override (raymarched procedural field) |
| `arrow_debug.vert/.frag` | Debug arrow overlay for velocity field |
| `histogram_render.vert/.frag` | Plotting histogram rendering |
| `tooltip_graphic.frag` | Animated physics-tooltip visualization |

`volrender/shaders/` (`clear3d.comp`, `splat.comp`, `majorant.comp`, `pathtrace.comp`, `resolve.comp`, `tonemap.comp`, `common.glsl`, `volume_scene.glsl`) belong to the volumetric tracer. Note `common.glsl` and `volume_scene.glsl` are also prepended into `entity_update.glsl` and `frame_assembly.frag` — a cross-tree shader coupling.

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
Temporal accumulation: run `speedmult` physics steps per display frame, render every `blur_quality`-th step, and blend via `FrameAssembler`. `SimulationRunner` handles both motion-blur and non-blur paths through shared helpers.

### Video Recording
State machine (idle → optional pending wait → recording → finished) split between `CommandHandler` (`video_pending`) and `App` (cadence lock, start check, restore). Three video sub-modes: normal (FrameAssembler), volumetric-tracer video, and OptiX path-tracer offline video. Encoding: `VideoRecorderService` → `VidSaver` → `ffmpeg_recorder`.

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
- **OptiX 9.1 / CUDA** (optional) — RTX sphere renderer and path tracer
