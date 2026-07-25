# Native Runtime Migration

Fluoddity should not ship to Steam as a Python application unless a later Deck hardware pass proves that the Python/OpenGL package is reliable enough and the project intentionally accepts that risk. The preferred shipping direction is a native runtime, with Rust plus wgpu as the default candidate while the game remains simulation-first.

This document turns that direction into an engineering plan. It does not replace the current Python V1 prototype. It defines how to make the prototype portable enough that a native runtime can inherit the game instead of restarting it.

## Target Runtime

Default target:

- Rust for the game/runtime executable.
- wgpu for graphics and compute, with Vulkan as the primary Steam Deck backend.
- winit or SDL for windowing and display mode control.
- gilrs, SDL game controller APIs, or Steam Input integration for controller input.
- serde-backed JSON or RON contracts for authored data, save data, and tuning values.
- a custom controller-first player UI.
- optional egui or retained Python tools for internal editors, tuning utilities, report generation, and config migration.

This stack is favored because Fluoddity is not a conventional content-heavy game wrapped around a renderer. The renderer and GPU simulation are the product. Owning the compute/render path matters more than inheriting a broad engine feature set.

## Non-Goals

- Do not rewrite `sim.py` during the Python V1 Trial Dish push.
- Do not port editor ImGui windows wholesale into the player shell.
- Do not rename every build, package, path, and data directory as part of the runtime spike.
- Do not build a new general-purpose engine before one Trial Dish is running in the native spike.
- Do not treat a native window that only draws a triangle as proof that the runtime can carry Fluoddity.

## Portable Contracts

The migration boundary should be data and behavior, not Python classes.

Keep these contracts portable:

- Trial definitions exported by `scripts/export_trial_definitions.py`.
- `schemas/trial_definitions.schema.json`.
- Steam Input action ids and prompt metadata under `steam_input/`.
- physics configs under `physics_configs/`.
- shader source and the parameter/rule layout implied by `shaders/entity_update.glsl`, `shaders/fourier4_4.glsl`, and `shaders/frame_assembly.frag`.
- smoke expectations for game launch, controller prompts, Trial Dish progression, visual nonblank frames, and Deck profile behavior.

Avoid adding new game behavior that only exists inside:

- ImGui callback state;
- ad hoc Python object graphs with no export path;
- editor-only command flags;
- undocumented shader uniform side effects;
- generated artifacts that cannot be reproduced by a script.

## Migration Phases

### Phase 1: Keep V1 Portable

Purpose: prove the game loop while keeping the future port feasible.

Required outcomes:

- Trial Dish authored data remains separate from `TrialService` implementation details.
- New game-facing rules and text live in exportable definitions or small services with smoke coverage.
- Controller prompts keep structured action ids instead of hard-coded strings.
- Runtime launch behavior remains testable by scripts without manual editor setup.
- Steam Deck packet generation continues to produce a traceable hardware-pass bundle.

Completion evidence:

- `python scripts/smoke_game_v1.py`
- `python scripts/smoke_trial_runtime_contract.py`
- `python scripts/prepare_steam_deck_packet.py --run-automated --with-visual --with-fed-results`

### Phase 2: Rust + wgpu Spike

Purpose: prove that the native stack can run one real Fluoddity-shaped dish, not just a generic graphics demo.

The spike must:

- open a native 1280x800 window;
- initialize wgpu on the primary adapter and report the selected backend;
- load one exported Trial Dish definition;
- load one existing physics config or a generated minimal equivalent;
- dispatch a compute pass that updates particle-like state on the GPU;
- render a nonblank Fluoddity-like frame;
- accept controller input for at least start, pause, cursor movement, and apply;
- show one controller-first objective overlay;
- record frame timing for a short Deck-sized run.

The spike may simplify:

- exact visual parity;
- full mutation history;
- exact mutation, orientation, symmetry, and multi-load parity;
- all editor tools;
- all shader effects;
- Steamworks integration;
- final save format.

The spike may not simplify away:

- GPU compute;
- controller-first player flow;
- the Trial Dish data contract;
- frame timing evidence;
- nonblank rendered output.

### Phase 3: Runtime Split Decision

Purpose: choose whether to continue porting, defer the port, or switch to an engine path.

Continue Rust + wgpu if:

- the spike runs the core GPU loop at Deck-sized settings;
- controller input and the player shell feel simpler in native code than in Python/ImGui;
- shader translation or rewrite cost is manageable;
- packaging looks cleaner than PyInstaller plus OpenGL dependency handling.

Defer the port if:

- V1 still has unresolved game-design risk;
- the native spike exposes no current Python bottleneck;
- Steam Deck hardware validates the Python package cleanly enough for a demo.

Reconsider Godot if:

- the game shifts toward authored scenes, campaign UI, audio-heavy presentation, and conventional game systems;
- the simulation becomes a contained visual component rather than the dominant runtime;
- GPU compute ownership stops being the critical constraint.

### Phase 4: Production Port

Purpose: replace the player runtime without losing the working prototype.

Port in this order:

1. Data loading and schema validation.
2. GPU simulation buffers and compute dispatch.
3. frame assembly and camera rendering.
4. Trial Dish state machine and objective evaluation.
5. controller input and prompt rendering.
6. result screens and player shell UI.
7. Steam Input, Steamworks, achievements, cloud saves, and packaging.
8. editor/dev tools only after the player shell is stable.

Keep Python tools for:

- migration scripts;
- artifact/report generation;
- config batch analysis;
- screenshots and validation helpers;
- any editor workflow that does not ship to players.

## Native Video Export Contract

The native runtime owns publishable high-resolution capture. The primary path
is offline export, not capture of the desktop window:

- video mode defaults to `3840x2160`, 60 FPS, CRF 15, and the x264 `slow`
  preset;
- export renders the final `present.wgsl` presentation rather than an
  intermediate particle/trail buffer;
- simulation time advances at a fixed 60 Hz and is sampled for the requested
  output FPS, so machine or encoder speed does not alter the encoded timeline;
- FFmpeg writes silent H.264 `yuv420p` MP4 with BT.709 primaries, transfer,
  matrix, TV range, and faststart layout;
- every completed MP4 has a `fluoddity.native_video_export.v1` JSON report with
  render, codec, timeline, trial, and output metadata;
- `--out` is reserved for an optional, distinct PPM poster during video export;
  no poster is created by default;
- the final MP4 path is published only after FFmpeg succeeds, while failed or
  interrupted exports remove their partial output.

The window-video path is intentionally described as 60 FPS presented
frame-sequence capture. It writes one encoded frame and advances one 60 Hz
trial-time step per native-window redraw; it is not a wall-clock-real-time
screen recorder when GPU readback or encoding cannot keep up. Offline export
remains the master workflow.

Native packages must carry a redistributable FFmpeg build with `libx264` plus
its license and provenance. Windows packaging resolves and verifies the chosen
bundle. Linux/Deck packaging requires explicit
`FLUODDITY_FFMPEG_BUNDLE` and `FLUODDITY_FFMPEG_LICENSE` inputs and rejects a
dynamically linked substitute.

## First Spike Acceptance Gates

A Rust + wgpu spike is meaningful only if it passes these gates:

- `cargo run --release -- --trial artifacts/trial_definitions.json --deck-profile` opens a native window.
- The selected backend is logged and is Vulkan on Steam Deck hardware.
- A GPU compute pass mutates particle state every frame.
- A rendered frame capture is nonblank and contains objective overlay pixels.
- A native 4K/60 offline export produces a decodable H.264 `yuv420p` MP4 with
  BT.709 tags, faststart layout, and a matching JSON report.
- Repeating the same offline export on the same validated runtime produces the
  same captured simulation frames; output-path collision and interrupted
  export tests leave no corrupt final artifact.
- Controller-only input can start the dish, move an applicator cursor, apply the tool, pause, and resume.
- A 60-second Deck-sized timing report is written with average FPS, average frame time, and worst frame time.
- The spike has a README that names which Python behaviors it intentionally does and does not match.

Until those gates pass, the spike is research. After they pass, it is evidence for a production port.

## Immediate Repo Tasks

1. Keep `docs/tech_stack_strategy.md` pointed at this migration plan.
2. Continue the checked `runtime/rust-wgpu-spike/` workspace as the Phase 2 native runtime spike.
3. Keep the spike README explicit about which migration gates are proven and which are still open.
4. Export Trial Dish definitions as part of any spike setup script.
5. Preserve Python V1 smoke coverage as the behavioral reference while the native runtime catches up.
6. Validate the native window/controller path on actual Steam Deck hardware, then port the remaining Python shader behavior around mutation, orientation, symmetry, and multi-load selection.
7. Keep repeatable native smoke entry points working: `runtime/rust-wgpu-spike/scripts/smoke-windows.ps1` for local Windows iteration and `runtime/rust-wgpu-spike/scripts/smoke-deck.sh` for Steam Deck/Linux timing passes.
8. Keep native package assembly working: `runtime/rust-wgpu-spike/scripts/package-windows.ps1` and `runtime/rust-wgpu-spike/scripts/package-deck.sh` should produce `dist/FluoddityNative/` with a Steam-facing `XenocultureTrialDish` executable alias, package-local Steam Input handoff files, a bundled licensed FFmpeg executable, `run_export_video` / `run_record_video` wrappers, a player-facing `run_steam_deck` launch wrapper, plus separate bounded smoke/timing wrappers.
9. Keep `python scripts/smoke_native_validation_suite.py` as the default local native gate so the Rust/wgpu runtime builds once, then runs rustfmt/clippy, Rust unit tests, plus config/input/trial/preset/rule/parameter/visual/determinism/video/package/timing checks sequentially without racing generated artifacts.
10. Keep `python scripts/audit_native_shader_parity.py` in the validation loop so the Rust/wgpu runtime reports which Python/GLSL fluid-engine parameters and features are mapped, which are missing, and whether Rust/WGSL uniform layouts still match.
11. Keep `python scripts/check_native_config_contract.py` in the validation loop so native saved-config normalization is compared against the shipped v7 config contract before any runtime is treated as a Python replacement.
12. Keep `python scripts/compare_native_visual_metrics.py` in the validation loop so native rendered-output work is compared against Python visual-smoke evidence instead of judged only by nonblank captures.
13. Keep `python scripts/smoke_native_python_visual_parity.py` in the validation loop so the same Trial Dish scenario has image-level native-vs-Python drift evidence before anyone claims the Rust/wgpu path replicated the Python/OpenGL fluid look.
14. Keep `python scripts/smoke_native_replay_determinism.py` in the validation loop so the same saved native Trial Dish scenario must produce bit-exact headless captures before captures are trusted as regression evidence.
15. Keep `python scripts/smoke_native_trial_matrix.py` in the validation loop so every exported Trial Dish contract has native load/run/render evidence, not only the current Rival Bloom smoke path.
16. Keep `python scripts/smoke_native_package.py` in the validation loop so the native runtime proves package-local launch, bundled data, headless capture, bounded Deck-profile timing, and package content hashing from `dist/FluoddityNative/`.
17. Keep `python scripts/smoke_native_steam_input_alignment.py` in the validation loop so native Rust/gilrs controls are checked against Steam Input `TrialDish` action ids, prompt glyph fallbacks, and package-local input wrappers.
18. Keep `python scripts/smoke_native_parameter_sensitivity.py` in the validation loop so representative mapped physics/settings fields must produce measurable native rendered-output changes, not just appear in the config contract.
19. Keep `python scripts/smoke_native_steam_launch_contract.py` in the validation loop so the native package has an explicit Steam launch target contract that is product-named, Python-free, and not a bounded smoke wrapper.
20. Keep `python scripts/smoke_native_video_export.py` in the validation loop so
    an actual 3840x2160/60 FPS export is probed, fully decoded, compared with
    its opt-in poster, repeated for deterministic evidence, and checked for
    safe failure behavior before the MP4 workflow is treated as healthy.

## Current Spike Evidence

As of this checkpoint, `runtime/rust-wgpu-spike/` has passed local Windows/NVIDIA Vulkan smokes for:

- loading exported Trial Dish definitions;
- loading `physics_configs/Core/Bubbles.json` through `--config`;
- feeding config-derived sensor, drag, force, mutation, trail, and seed values into WGSL;
- feeding saved boundary condition, initial condition, and cohort-count settings into native initialization and WGSL boundary behavior;
- feeding saved hazard-rate settings into WGSL stochastic particle reset behavior;
- feeding saved symmetry/orientation settings into WGSL sensor direction and mirrored rule-input behavior;
- feeding saved hue sensitivity and cohort-color settings into native particle color splats;
- feeding saved slider ranges, parameter sweep axes, and jitter values into a native GPU physics-settings buffer used by WGSL.
- uploading and evaluating the config's 80-float saved 10-center Fourier rule coefficients in WGSL;
- running a nonblank headless frame capture at `1280x800`;
- opening a native `winit` window, presenting the computed buffer, and exiting through a bounded frame smoke.
- writing a Deck-profile JSON timing report with average FPS, average frame time, and worst frame time.
- drawing a primitive native controller/status overlay with objective-zone pips, run progress, pause/apply state, and controller action shapes.
- uploading Trial Dish title/objective/prompt text into a GPU buffer and rendering it with a small WGSL bitmap font.
- emitting native overlay prompt metadata with Steam Input action ids and glyph fallback labels for each player state.
- running a lightweight native Trial Dish state machine with briefing/running/win/fail states.
- sampling the native GPU frame output to detect active objective zones and advance objective progress.
- rendering native result copy that distinguishes next-assay progression from final sequence completion and Trial 1 restart.
- writing `trial_runtime` state into Deck-profile timing reports.
- building and running through a repeatable Windows native smoke script that handles release build, optional local signing, headless capture, and bounded Deck-profile timing output.
- assembling `dist/FluoddityNative/` with a Steam-facing `XenocultureTrialDish` executable alias, the compatibility spike binary, exported Trial Dish contract, shipped Core configs, package-local licensed FFmpeg, package-local Steam Input handoff files, player-facing `run_steam_deck` wrappers, native video wrappers, and package-local smoke/timing/input wrappers.
- exporting final-presentation H.264 `yuv420p` MP4 at independently selected render dimensions and frame rates, with BT.709 metadata, faststart layout, fixed-60-Hz offline timeline, structured JSON evidence, and an opt-in PPM poster.
- generating `artifacts/native_validation_suite.md` and `.json` through `python scripts/smoke_native_validation_suite.py`; the suite requires its local native gates, including `video_export`, to pass while still allowing shader parity to remain explicitly `incomplete` and Python visual parity to remain `measured-drift`.
- generating `artifacts/native_rust_quality.md` and `.json`; the current Rust quality gate reports `pass` for `cargo fmt --check` and `cargo clippy -- -D warnings`.
- generating `artifacts/native_rust_tests.md` and `.json`; the current Rust unit tests report `pass` for native saved-config parsing, bad-rule rejection, exported Rival Bloom trial parsing, and unknown trial rejection.
- generating `artifacts/native_wgpu_runtime.md` inside the Steam Deck hardware packet, with the native smoke commands, current evidence, and Deck hardware checklist included in the packet manifest.
- generating `artifacts/native_shader_parity.md` and `.json` inside the Steam Deck hardware packet; the current audit reports native shader parity as `incomplete`, with 33 of 36 `SimState` fields mapped, Rust/WGSL `Params` layout matching, 31 of 31 replacement-critical saved fields reaching native GPU payloads, replacement-required native player feature groups covered, and deferred editor/gallery gaps named explicitly.
- generating `artifacts/native_config_contract.md` and `.json` inside the Steam Deck hardware packet; the current contract check reports `pass` across all 26 shipped Core presets, comparing Rust/wgpu normalized config inputs against the saved v7 JSON contract for scalar parameters, settings, ranges, sweeps, jitters, rule count, and saved-rule presence.
- generating `artifacts/native_input_contract.md` and `.json` inside the Steam Deck hardware packet; the current contract reports `pass` for the Rust/wgpu `gilrs` mappings for right-stick applicator movement, R2 apply, A start/resume, Start/Menu pause, View exit, and per-state prompt action ids.
- generating `artifacts/native_input_runtime.md` and `.json` inside the Steam Deck hardware packet; the current smoke reports `pass` for scripted native state transitions covering briefing pause, A/South start, R2 apply while running, pause suppression, resume, right-stick cursor movement, result-state entry, structured prompt action metadata, View exit prompt copy, result overlay copy for next-assay progression, final sequence-complete overlay copy, A/South advancing from a completed result to the next exported Trial Dish briefing, and final-trial A/South restarting the sequence at Trial 1.
- generating `artifacts/native_steam_input_alignment.md` and `.json` inside the Steam Deck hardware packet; the current check reports `pass` when native right-stick, R2, A/South, Start/Menu, and View/Select controls plus runtime prompt action metadata align with the Steam Input `TrialDish` manifest, prompt glyph fallbacks, and package-local input report wrappers.
- generating `artifacts/native_visual_metrics.md` and `.json` inside the Steam Deck hardware packet; the current metric report compares coarse native frame metrics against a Python visual-smoke reference when one is available, and otherwise marks the Python reference as missing.
- generating `artifacts/native_python_visual_parity.md` and `.json` inside the Steam Deck hardware packet; the current same-scenario comparison reports `measured-drift`, does not claim exact parity, and records the current 1280x800 native-vs-Python image delta for Rival Bloom / Trial 3.
- generating `artifacts/native_replay_determinism.md` and `.json` inside the Steam Deck hardware packet; the current replay report passes with bit-exact repeated native captures after separating trail reads and writes through ping-pong buffers and retaining commutative atomic deposits/color combines.
- generating `artifacts/native_trial_matrix.md` and `.json` inside the Steam Deck hardware packet; the current matrix reports `pass` for all three exported Trial Dish contracts, with native running-state output and nonblank frame metrics for each trial.
- generating `artifacts/native_preset_matrix.md` and `.json` inside the Steam Deck hardware packet; the current matrix reports `pass` for five representative shipped Core presets, with native config-contract output, nonblank frame metrics, and pairwise rendered-output distances to catch collapsed saved-preset behavior.
- generating `artifacts/native_rule_sensitivity.md` and `.json` inside the Steam Deck hardware packet; the current check reports `pass` when a saved 80-float Fourier rule and a zero-rule variant produce measurable pixel-level native output differences while preserving the same scalar config.
- generating `artifacts/native_parameter_sensitivity.md` and `.json` inside the Steam Deck hardware packet; the current matrix reports `pass` when representative mapped fields for sensor gain, sensor distance, sensor angle, drag, trail persistence, symmetry, and absolute orientation each produce measurable pixel-level native output differences.
- generating `artifacts/native_package_smoke.md` and `.json` inside the Steam Deck hardware packet; package validation covers package-local player/video launch wrappers, licensed FFmpeg presence, Steam Input handoff files, headless capture, bounded Deck-profile timing with a `trial_runtime` snapshot, and package-local native input contract/runtime wrappers.
- generating `artifacts/native_package_manifest.md` and `.json` inside the Steam Deck hardware packet; the manifest lists the Steam-facing executable alias, compatibility executable, launch/video wrappers, bundled FFmpeg license/provenance, bundled Steam Input handoff files, bundled config/trial contract, generated input/timing/frame/video artifacts, byte counts, and SHA-256 hashes.
- generating `artifacts/native_timing_budget.md` and `.json` inside the Steam Deck hardware packet; the current bounded local Deck-profile timing report must stay at 1280x800, include `trial_runtime`, and remain under the configured average/worst frame-time budget, while still not replacing actual Steam Deck hardware validation.
- generating `artifacts/native_steam_launch_contract.md` and `.json` inside the Steam Deck hardware packet; the current contract reports `pass` for Windows/Proton and Deck/Linux native launch targets that use `XenocultureTrialDish`, avoid Python, avoid bounded smoke/timing flags, reject Deck/Linux compatibility-binary fallback, and require `package-deck.sh` to create an executable Linux product alias.

This proves config ingestion, saved rule coefficient ingestion, saved-rule influence on native output, mapped physics/settings parameter influence on native output, saved notes metadata preservation, native saved-config normalization for Core presets, native propagation of saved watercolor/emboss presentation settings, native controller/input mapping export, scripted native controller-state behavior including result-to-next-trial briefing progression, final-trial sequence restart, native overlay copy for next-assay versus sequence-complete results, and structured native prompt action metadata aligned with Steam Input fallback glyphs, alignment between native controller bindings and the Steam Input handoff artifacts, the native compute/present path, deterministic same-scenario native replay on the validation machine, a first controller-first overlay path, minimal native text rendering, native objective-state sampling, all exported Trial Dish contracts reaching native running-state captures, representative saved presets producing distinct native output instead of collapsing to one visual response, a repeatable local native smoke path, coarse rendered-output metric reporting, same-scenario native-vs-Python drift measurement, package-local native player launch/capture/timing/input-report wrappers, package-local Steam Input handoff bundling, explicit native Steam launch target contracts, package assembly and content hashing, and hardware-packet visibility for the native candidate. It does not prove a finished native player shell, retained UI layout, polished result-screen layout, exact visual parity with the Python renderer, real controller hardware behavior, official Steamworks Steam Input rendering, or parity with mutation history, app shell state, or multi-load rule selection.

Local native video evidence proves only the adapter, operating system, runtime
binary, and FFmpeg build used for that run. A Windows 4K/60 export is not
evidence that the Linux package, Vulkan backend, Deck storage path, or Deck
thermal envelope can complete the same export. Those remain separate
target-hardware checks.

The current repeatable local Windows smoke is `runtime/rust-wgpu-spike/scripts/smoke-windows.ps1 -Frames 12 -MaxWindowFrames 3 -ArtifactsDir artifacts/native-wgpu-smoke`; it produced `native_wgpu_smoke=ok`, a nonblank frame capture, and a valid Deck-profile timing report. That is build, format, overlay, text rendering, and plumbing evidence only; it is not a substitute for the required 60-second timing run on actual Steam Deck hardware through `runtime/rust-wgpu-spike/scripts/smoke-deck.sh`.

The current package-local Windows validation is `runtime/rust-wgpu-spike/scripts/package-windows.ps1`, followed by `dist/FluoddityNative/run_headless.ps1 -Frames 24`, `dist/FluoddityNative/run_export_video.ps1 -Seconds 1`, and `dist/FluoddityNative/run_deck_profile.ps1 -MaxWindowFrames 5`. This proves the bundle can run without repo-relative data paths, use its package-local FFmpeg for an offline MP4, and write package-local timing JSON with a `trial_runtime` snapshot. The Windows-built package intentionally does not pretend to contain the Linux `XenocultureTrialDish` binary; its Deck/Linux wrappers exit with a clear `package-deck.sh` instruction if that product alias is missing.

The Steam Deck packet smoke `python scripts/smoke_steam_deck_packet.py` now requires `artifacts/native_wgpu_runtime.md` in the packet index, preflight report, and hashed manifest. The package-validation release gate also requires a `Native wgpu Package` section that blocks readiness until `dist/FluoddityNative/` has package-local launch, data, timing, and overlay/text evidence.
