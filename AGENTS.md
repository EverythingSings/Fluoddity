# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Fluoddity is a GPU-accelerated 2D particle simulation for generative art. Thousands of particles follow neural-net-like "Rules" governing their response to trail density, producing emergent patterns.

The repository maintains three runtime/delivery surfaces:

- The Python 3.12 / ModernGL / OpenGL prototype and editor at the repository root.
- The Rust/wgpu native shipping candidate under `runtime/rust-wgpu-spike/`.
- A self-contained WebGPU HTML artifact for networked.art/everything under `runtime/webgpu/`, built into `artifacts/networked-art/everything.html`.

## Commands

```bash
# Run (development)
pip install -r requirements.txt
python main.py

# Build distributable (Windows, PowerShell)
.\build.ps1

# Manual build
python -m PyInstaller --clean --noconfirm Fluoddity.spec
Move-Item -Path "dist\Fluoddity\_internal\shaders" -Destination "dist\Fluoddity\shaders"

# Automated validation entry points
python scripts/smoke_game_v1.py
python scripts/smoke_native_validation_suite.py
python scripts/build_webgpu_artifact.py
python scripts/smoke_webgpu_artifact.py --require-thumbnail
python scripts/smoke_webgpu_responsive.py --skip-build
```

The repository has automated Python smoke suites, Rust formatting/clippy/unit tests, native runtime gates, and WebGPU artifact checks. Use `docs/testing_checklist.md` for the remaining visual, controller, packaging, and hardware checks. Passing local checks does not establish full native shader parity or Steam Deck hardware validation.

## Python/OpenGL Prototype Architecture

**Orchestrator pattern** — the `App` class in `main.py` coordinates all components. Components never talk to each other directly.

Each frame:
1. `ui.get_state()` — UI exposes its state as a snapshot
2. `CommandHandler.process_commands()` — handles one-shot flags (reset, save, load, etc.)
3. `process_camera_input()` — WASD/scroll camera
4. `sim.apply_state()` / `camera.apply_state()` — push state to GPU and renderer
5. `SimulationRunner.step_and_assemble()` — dispatch compute shaders, assemble frame
6. Render camera view, then UI on top

**Key design rules:**
- **UI is passive** — renders ImGui widgets and exposes state via `get_state()`, never runs sim logic
- **One-shot flags** — booleans set by UI (e.g. `request_reset`), read and cleared by orchestrator each frame
- **State containers** — all mutable state lives in dataclasses under `state/`
- **GPU-first** — physics runs in GLSL compute shaders; CPU just dispatches and reads back when needed

### UI Package (`ui/`)

Uses **mixin-based decomposition** (multiple inheritance). The `UI` class in `core.py` inherits 8 mixins so all render methods share `self.*` — chosen because ImGui's immediate-mode paradigm requires shared widget state. Import via `from ui import UI`.

### GPU Pipeline

```
entity_update.glsl (compute) → fourier4_4.glsl (compute) → frame_assembly.frag (fragment)
```

Uniforms are set from Python via `tryset(program, 'UNIFORM_NAME', value)` which gracefully handles missing uniforms during shader development. Press `V` to hot-reload shaders.

## Naming Conventions

- **SimState fields / shader uniforms**: `ALL_CAPS_UNDERSCORE` (e.g. `SENSOR_DISTANCE`)
- **UI labels**: Title Case with spaces (e.g. "Sensor Distance")
- **Private UI state**: `_snake_case` (e.g. `_request_reset`)
- Names must match exactly between SimState fields and GLSL uniforms

## Adding a New Physics Parameter

Four-step process (detailed in `docs/adding_ui_shader_params.md`):

1. **`state/sim_state.py`** — add field to `SimState` dataclass
2. **`shaders/*.glsl`** — declare `uniform` and use it
3. **`sim.py`** — add `tryset()` call in `entity_update()`
4. **`ui/physics_window.py`** — add ImGui widget (use `slider_float_with_range_menu` for full context menu support)

No additional wiring needed — the orchestrator pattern handles the rest.

## Important Caveats

- **`sim.py` is user-owned** — do not restructure without asking. It has its own hardcoded param lists in `entity_update()` and `_write_multi_load_ssbo()`.
- **Windows platform** — use forward slashes or `os.path`; use `rm` not `del` in bash commands.
- **Layered validation** — run the relevant automated smoke suite, then complete the applicable manual checks in `docs/testing_checklist.md`.
- **Shaders must be in `shaders/`** relative to the executable for builds to work.

## Key Documentation

- `ARCHITECTURE.md` — comprehensive architecture, file map, data flows, subsystem docs
- `ui/README.md` — mixin architecture, how to add windows/sliders
- `docs/adding_ui_shader_params.md` — step-by-step guide for new parameters
- `BUILD.md` — PyInstaller build instructions
