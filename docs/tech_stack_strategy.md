# Tech Stack Strategy

This project should keep Python for the current V1 game prototype, but it should not assume Python is the final shipping runtime.

The core asset is not Python. The core asset is the GPU simulation, the shader pipeline, the rule/mutation model, the visual identity, and the emerging Xenoculture: Trial Dish game loop. Python is currently the fastest way to wrap those assets in enough UI, launch behavior, controller handling, and smoke coverage to learn whether there is a game here.

## Current Stack

- Python 3.12: app orchestration, state containers, UI glue, command handling, packaging scripts.
- ModernGL: OpenGL 4.3 context and compute/fragment shader dispatch.
- GLFW: windowing, keyboard, mouse, and controller polling.
- imgui_bundle / Dear ImGui: immediate-mode editor and prototype HUD.
- NumPy and Pillow: CPU-side data handling and image utility work.
- GLSL shaders: the actual particle update, field processing, frame assembly, hazards, and visual effects.
- FFmpeg: video capture.
- PyInstaller: current standalone packaging path for Windows and Linux/Steam Deck experiments.

In practice, most of the interesting runtime work already happens on the GPU. Python is mostly the conductor.

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

## Port Decision Rule

Do not port while we are still answering "what is the game?"

Start a serious port or runtime split when at least two of these are true:

- Trial Dishes are fun enough that we want a Steam page and public demo.
- The prototype has a stable set of game verbs, not just editor tools renamed as lab tools.
- Steam Deck testing shows packaging, controller, or frame pacing problems caused by Python/GLFW/imgui_bundle rather than game code.
- The UI needs to move away from ImGui into a custom controller-first interface.
- The shader/runtime layer needs a backend that OpenGL cannot comfortably provide.
- We need automated content pipelines, save compatibility, localization, achievements, Steam Input glyphs, or Steamworks integration.

Until then, porting is probably premature.

## Likely Final Runtime Options

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

This is the strongest candidate if the game remains a custom simulation-first thing.

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
2. Keep the simulation logic, trial definitions, onboarding focus, tool names, game identity, and game-state model cleanly separated from editor windows. Trial Dish authored data now lives in `services/trial_definitions.py` and exports as a normalized JSON/schema runtime contract, so tuning/report tools and future ports do not have to depend on service internals.
3. Add smoke tests around game rules, exported trial data, and launch behavior so a future port has a behavioral target.
4. Do one real Steam Deck hardware pass before committing to shipping Python.
5. If V1 is promising, prototype a tiny Rust + wgpu spike that runs one dish shader and one objective overlay.
6. Decide final runtime after that spike, not before.

The important constraint: avoid writing new game systems in a way that only makes sense inside Python ImGui callbacks. V1 can be Python. The game should not become Python-shaped.
