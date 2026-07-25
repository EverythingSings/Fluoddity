# Tech Stack Strategy

This project keeps Python for the current V1 game prototype while actively developing a Rust/wgpu native shipping candidate. The native work is no longer a hypothetical future spike; its operational migration plan lives in `docs/native_runtime_migration.md`. A separate self-contained WebGPU artifact serves networked.art/everything and is not the complete game shell.

The policy is to keep Python for the current V1 game prototype and not assume Python is the final shipping runtime.
Promote the native candidate only against explicit parity and hardware evidence.

The core asset is not Python. The core asset is the GPU simulation, the shader pipeline, the rule/mutation model, the visual identity, and the emerging Xenoculture: Trial Dish game loop. Python is currently the fastest way to wrap those assets in enough UI, launch behavior, controller handling, and smoke coverage to learn whether there is a game here.

## Current Surfaces

### Python/OpenGL Prototype

- Python 3.12: app orchestration, state containers, UI glue, command handling, packaging scripts.
- ModernGL: OpenGL 4.3 context and compute/fragment shader dispatch.
- GLFW: windowing, keyboard, mouse, and controller polling.
- imgui_bundle / Dear ImGui: immediate-mode editor and prototype HUD.
- NumPy and Pillow: CPU-side data handling and image utility work.
- GLSL shaders: the actual particle update, field processing, frame assembly, hazards, and visual effects.
- FFmpeg: video capture.
- PyInstaller: current standalone packaging path for Windows and Linux/Steam Deck experiments.

In practice, most of the interesting runtime work already happens on the GPU. Python is mostly the conductor.

### Rust/wgpu Native Candidate

- Rust: native application, Trial Dish state, input, packaging, validation, and video-export logic.
- wgpu + WGSL: native compute and presentation pipeline across modern GPU backends.
- Exported Trial Dish definitions and Core physics configs: data contracts shared with the Python prototype.
- Automated rustfmt, clippy, unit, config, input, trial, rendering, determinism, video, package, and timing gates.

The native runtime is the current shipping candidate, but the repository still records expected incomplete Python/GLSL shader parity. Local Windows and headless validation must not be described as Steam Deck hardware proof.

### WebGPU networked.art Artifact

- WebGPU + WGSL + JavaScript in one generated HTML file.
- Embedded config and shaders with no runtime network or persistence dependency.
- A bounded generative-art control surface for networked.art/everything, not a port of every editor or Trial Dish feature.

At compact embed sizes, all controls must remain reachable in a scrollable panel at normal browser zoom. The responsive browser smoke is part of this surface's release check.

## Why Keep Python For V1

- The repo already runs this way.
- The shader pipeline is already productive.
- ImGui is excellent for fast tool creation and tuning.
- The game design is still unproven; porting before the loop is fun would slow down learning.
- The V1 risks are design risks: goals, friction, onboarding, tuning, and controller feel. A new engine will not solve those by itself.

For the next prototype phase, Python is acceptable if we keep changes layered around the existing orchestrator and avoid binding game logic too deeply to editor-only ImGui assumptions.

## Why Python Is Risky For The Final Steam Game

- Distribution is heavier and more fragile than a native game binary.
- PyInstaller builds need platform-specific handling and can fail for dependency or dynamic-library reasons.
- Steam Deck Verified usually rewards predictable controller, fullscreen, text input, suspend/resume, and packaging behavior.
- Python stack traces, import-time failures, missing shared libraries, and OpenGL driver differences are poor release-day failure modes.
- ImGui is useful for tools, but a shipped game UI probably wants a deliberate controller-first presentation layer.
- OpenGL compute is viable, but Vulkan/WebGPU/wgpu-style backends are more modern portability targets.

The concern is not raw performance first. The concern is product reliability, portability, input polish, and long-term maintainability.

## Runtime Decision Rule

Do not discard the productive Python prototype while we are still answering "what is the game?" The native port can advance in parallel only when it preserves explicit behavior/data contracts and proves each capability with bounded evidence.

The runtime split is now active because the prototype has enough stable verbs
and exported data contracts to define a behavioral target, while a shipping
candidate needs:

- native packaging and predictable launch behavior;
- a custom controller-first presentation layer rather than editor-first ImGui;
- a modern cross-platform GPU backend;
- explicit content, save, localization, achievement, Steam Input, and Steamworks boundaries;
- target-platform evidence for frame pacing, suspend/resume, input, and package behavior.

The remaining decision is promotion, not whether to start. Treat Rust/wgpu as the shipping candidate only to the extent its current validation covers; keep the Python prototype as the tuning and comparison surface until parity gaps are resolved or consciously accepted.

## Runtime Options and Current Direction

### Rust + wgpu

Best technical fit if we want a custom engine with modern GPU portability.

Pros:
- native binaries;
- strong data modeling;
- wgpu targets Vulkan/Metal/DX12/WebGPU-style backends;
- good fit for compute-heavy simulation;
- much better long-term Steam Deck story than Python packaging.

Cons:
- more engine work;
- slower iteration than Python;
- all current ImGui/editor glue must be rewritten or bridged.

This is the active shipping candidate because the game remains a custom simulation-first thing.

### Godot

Best fit if we decide the simulation is only one part of a broader game with menus, campaign structure, story scenes, audio, and conventional UI.

Pros:
- good game packaging story;
- fast iteration;
- built-in UI/audio/input/resource workflows;
- Steam Deck and controller work are familiar paths.

Cons:
- GPU compute integration is less direct than owning the runtime;
- porting the current shader pipeline may become awkward;
- the simulation may fight the engine if it remains the center of the game.

This is a good candidate if the game becomes more authored and less engine-experimental.

### C++ + OpenGL/Vulkan

Most control, least appealing unless there is a hard technical reason.

Pros:
- native and battle-tested;
- full graphics control;
- many library options.

Cons:
- more manual memory/build complexity;
- slower feature work;
- less ergonomic than Rust for this codebase direction.

## Recommended Path

1. Keep the Python/ModernGL prototype through V1 Trial Dishes.
2. Advance `runtime/rust-wgpu-spike/` as the native shipping candidate despite its legacy directory name. Close or explicitly accept shader-parity gaps before calling the port complete.
3. Keep simulation logic, trial definitions, onboarding focus, tool names, game identity, and game-state models separate from editor windows. Trial Dish authored data in `services/trial_definitions.py` exports as a normalized JSON/schema runtime contract so Python and native validation target the same content.
4. Keep automated game-rule, exported-data, launch, native-runtime, and package checks as behavioral gates rather than treating compilation as parity.
5. Maintain the WebGPU artifact as a focused networked.art/everything delivery surface. Preserve its self-contained sandbox contract and normal-zoom responsive controls without implying full game/editor parity.
6. Do one real Steam Deck hardware pass, then complete Steamworks input, glyph,
   suspend/resume, package, and performance evidence before making Deck or
   store-readiness claims.

The important constraint: avoid writing new game systems in a way that only makes sense inside Python ImGui callbacks. V1 can be Python. The game should not become Python-shaped.

## Native Runtime Candidate Gates

The original native spike gate established the minimum shape of a useful port:

- native 1280x800 launch profile;
- wgpu compute pass mutating particle-like state on the GPU;
- nonblank Fluoddity-like frame output;
- one exported Trial Dish definition loaded through the data contract;
- controller-only start, pause, applicator movement, and apply;
- one objective overlay;
- short frame-timing report.

The active candidate now goes beyond that minimum, but promotion still depends on the full migration gates, explicit shader-parity status, target-platform packaging, and hardware evidence. `docs/native_runtime_migration.md` is the source of truth for those phases and acceptance gates.
