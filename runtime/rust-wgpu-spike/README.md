# Fluoddity Rust/wgpu Native Candidate

This crate is the active native shipping candidate. Its historical directory
and binary names still contain `spike`, but it has graduated beyond the initial
feasibility experiment. It remains isolated from the Python V1 prototype while
the explicit parity and real-hardware gates below are still open.

The candidate currently validates both the headless GPU side of the migration and a native window path:

- initializes `wgpu`;
- reports the selected adapter/backend;
- loads the exported Trial Dish JSON contract;
- selects a Trial Dish by `trial_id`;
- loads an existing Python physics config with `--config`;
- loads saved boundary condition, initial condition, and cohort-count settings from the config;
- loads saved hazard-rate settings from the config and applies stochastic particle resets in WGSL;
- loads saved symmetry/orientation settings and applies them to sensor direction and mirrored rule input in WGSL;
- loads saved hue sensitivity and cohort-color settings and applies them to native particle color splats;
- loads saved slider ranges, sweep axes, and jitter values into a native physics-settings buffer used by WGSL;
- uploads the config's 80-float saved rule coefficient array to the GPU when present;
- dispatches a WGSL background pass for the dish/overlay frame;
- keeps persistent particle state in a GPU storage buffer;
- keeps persistent trail state in a GPU storage buffer;
- dispatches a second WGSL particle pass that samples nearby trail sensors, evaluates the saved 10-center Fourier rule coefficients when present, falls back to a compact deterministic rule when absent, updates particles, writes trail, and splats particles into the frame;
- applies config-driven bounce/reset/wrap boundary behavior and grid/random/ring reset positions;
- draws up to three authored objective zones, hazard band, rival source, and applicator from contract/input state;
- reads back the final presentation pass and rejects blank output;
- writes a simple PPM frame capture;
- exports configurable-resolution MP4 video through FFmpeg, with a `3840x2160`
  60 FPS default when `--video-out` is present;
- advances offline video exports on a fixed 60 Hz simulation timeline so
  rendering and encoding speed do not change simulation time;
- writes H.264 `yuv420p` MP4 with BT.709 color metadata and faststart layout;
- writes a structured native video JSON report and, only when requested with
  `--out`, an uncompressed PPM poster frame;
- records frame timing for a Deck-sized `1280x800` profile, including average FPS, average frame time, and worst frame time;
- writes a JSON timing report when `--timing-report` is provided;
- opens a native `1280x800` window with `winit`;
- presents the computed GPU buffer to the window surface;
- draws a primitive native controller/status overlay with objective pips, run progress, pause/apply state, and controller action shapes;
- uploads Trial Dish title/objective/prompt text into a GPU buffer and renders it with a small WGSL bitmap font;
- emits per-state native prompt metadata with Steam Input action ids and glyph fallback labels;
- runs a lightweight native Trial Dish state machine with briefing/running/win/fail states;
- advances a result state to the next exported Trial Dish briefing through the native A/StartOrResume path;
- restarts the sequence at Trial 1 from the final exported trial result;
- renders result copy that distinguishes next-assay progression from final sequence completion and Trial 1 restart;
- samples its own GPU frame output to detect active objective zones and advance objective progress;
- writes a `trial_runtime` snapshot into Deck-profile timing reports;
- routes keyboard input and `gilrs` controller input into cursor/apply/pause state.

It does not yet prove the full native player shell:

- no retained layout system, menu system, polished result layout, or full HUD layout;
- no Steam Input or Steamworks integration;
- no exact port of the existing GLSL mutation history, orientation modes, symmetry handling, or multi-load rule selection;
- no exact visual parity with the Python renderer;
- no real Steam Deck hardware controller pass.

Those missing pieces are deliberate gates, not hidden completion. This crate should be promoted only after the headless compute path is reliable.

## Setup

From the repo root, export the Trial Dish contract first:

```bash
python scripts/export_trial_definitions.py
```

On Windows, run the checked smoke entry point:

```powershell
.\runtime\rust-wgpu-spike\scripts\smoke-windows.ps1
```

The Windows smoke builds the release binary, signs/copies it into `artifacts/native-wgpu/` when a local code-signing certificate is available, runs a headless nonblank capture, and runs a bounded Deck-profile window timing pass.

Build a self-contained Windows native package:

```powershell
.\runtime\rust-wgpu-spike\scripts\package-windows.ps1
```

The package is written to `dist/FluoddityNative/` with a Steam-facing executable alias (`XenocultureTrialDish.exe` on Windows, `XenocultureTrialDish` on Deck/Linux), the compatibility spike binary, exported Trial Dish contract, shipped Core configs, a package-local FFmpeg build with license/provenance, Steam Input handoff files under `steam_input/`, player launch wrappers (`run_steam_deck.ps1` / `run_steam_deck.sh`), native video wrappers, and bounded smoke/timing wrappers. A Windows-built package carries the Deck shell wrappers for handoff, but the actual Linux product alias and executable FFmpeg bundle are created by `package-deck.sh`; the Deck wrappers fail clearly instead of falling back to `fluoddity-wgpu-spike`.

On Steam Deck or Linux, run:

```bash
bash runtime/rust-wgpu-spike/scripts/smoke-deck.sh
```

The Deck/Linux smoke builds the native release binary and writes `artifacts/native-wgpu/wgpu_deck_timing.json`. Override `MAX_WINDOW_FRAMES=300` for a shorter local run, or leave the default `3600` for a roughly 60-second 60 FPS target run.
Deck-profile runs auto-start the assay so the timing report can include live `trial_runtime` state in addition to frame timing.

Build a self-contained Deck/Linux package:

```bash
bash runtime/rust-wgpu-spike/scripts/package-deck.sh
```

Inside a package, use `run_steam_deck.ps1` on Windows or `run_steam_deck.sh` on Deck/Linux as the player-facing launch target. These wrappers open the native window through the `XenocultureTrialDish` executable alias without a bounded frame count. Use `run_deck_profile.ps1` or `run_deck_profile.sh` for timing and validation runs.

## Native High-Resolution Video

The primary master workflow is an offline native export. It captures the final
`present.wgsl` presentation, including configured watercolor/emboss state, at
the requested output resolution. The simulation advances on a fixed 60 Hz
timeline and frames are sampled for the requested output FPS, so a slow GPU or
encoder affects export duration, not the encoded simulation timing.

From source, export a ten-second 4K/60 master with:

```bash
cargo run --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release -- --trial artifacts/trial_definitions.json --trial-id rival_bloom --config physics_configs/Core/Bubbles.json --video-out artifacts/native-4k60.mp4 --video-report artifacts/native-4k60.json --video-seconds 10 --render-width 3840 --render-height 2160 --video-fps 60 --video-crf 15 --video-preset slow
```

The explicit resolution, FPS, CRF, and preset above match video-mode defaults;
they are shown to make the master contract visible. `--frames N` may replace
`--video-seconds N`. Output dimensions must be even for H.264 `yuv420p`.

The MP4 is silent H.264 encoded by `libx264`, tagged BT.709 with TV range, and
written with its `moov` atom ahead of media data for faststart delivery. The
JSON report uses schema `fluoddity.native_video_export.v1` and records the
output byte count, render resolution and particle count, presentation settings,
codec settings, frame/duration/timeline data, and Trial Dish state.

Poster generation is deliberately opt-in. Add a distinct PPM path only when a
lossless final-frame reference is useful:

```bash
--out artifacts/native-4k60.ppm
```

The MP4, JSON report, and optional PPM paths must all be distinct. All outputs
are staged beside their destinations and published together only after the
final frame, FFmpeg result, poster, and report validate. Existing regular-file
artifacts are protected with backup-and-restore rollback.

The package wrappers are the shortest player-facing entry points:

```powershell
.\dist\FluoddityNative\run_export_video.ps1 -Seconds 10
```

```bash
VIDEO_SECONDS=10 bash dist/FluoddityNative/run_export_video.sh
```

On Windows the default output is under
`Documents/Fluoddity/Videos/`. On Deck/Linux it is under
`${XDG_VIDEOS_DIR:-$HOME/Videos}/Fluoddity/`. Both wrappers write the JSON
report beside the MP4.

`run_record_video.ps1` and `run_record_video.sh` provide native window-frame
capture at 60 FPS. This mode records one encoded frame for each presented
redraw and advances recorded trial time by one 60 Hz frame, so a slow encoder
does not jump gameplay ahead inside the resulting video. It preserves frame
order but is not a wall-clock-real-time screen recorder when
GPU readback or FFmpeg cannot sustain the requested rate; interaction can play
back faster than it occurred. Use offline `run_export_video` for publishable
masters and the window-frame mode only when the interactive frame sequence is
the desired evidence.

Source runs resolve FFmpeg from `--ffmpeg`, then
`FLUODDITY_FFMPEG`, then beside the executable, then `PATH`. The Windows package
script requires an FFmpeg distribution exposing `libx264` and an accompanying
license file, then bundles and optionally signs `ffmpeg.exe`. Deck/Linux
packaging requires explicit redistributable static inputs:

```bash
FLUODDITY_FFMPEG_BUNDLE=/absolute/path/to/ffmpeg \
FLUODDITY_FFMPEG_LICENSE=/absolute/path/to/LICENSE \
bash runtime/rust-wgpu-spike/scripts/package-deck.sh
```

The Deck package rejects a dynamically linked substitute and an FFmpeg build
without `libx264`. License and provenance material are copied to
`third_party/ffmpeg/`.

Run the focused validation from the repo root:

```bash
python scripts/smoke_native_video_export.py
```

The smoke uses an actual 3840x2160, 60 FPS export by default. It probes the
codec, pixel format, rate, color tags, frame count, duration, and faststart
layout; performs a full decode; compares the decoded final frame with the
optional poster; repeats the export to test deterministic artifacts; and checks
that invalid output-path collisions or a failed sidecar publication cannot
overwrite a completed artifact.

Passing that smoke on Windows proves the local Windows adapter, native binary,
and selected FFmpeg path only. It does not prove Linux/Deck packaging, the
Vulkan backend, Deck storage throughput, thermals, or successful 4K encoding on
actual Steam Deck hardware. Those need a separate package-local run on the
target device.

The lower-level command for a headless frame capture is:

```bash
cargo run --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release -- --trial artifacts/trial_definitions.json --trial-id bloom --config physics_configs/Core/Bubbles.json --frames 120 --out artifacts/wgpu_spike_frame.ppm
```

Run the native window smoke:

```bash
cargo run --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release -- --trial artifacts/trial_definitions.json --trial-id antibiotic_band --config physics_configs/Core/Bubbles.json --window --max-window-frames 300
```

Run a Deck-profile timing pass:

```bash
cargo run --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release -- --trial artifacts/trial_definitions.json --trial-id rival_bloom --config physics_configs/Core/Bubbles.json --deck-profile --timing-report artifacts/wgpu_deck_timing.json
```

For a quick bounded smoke, combine `--deck-profile` with `--max-window-frames 5` and a separate report path.

The spike logs `trial_contract_result`, `config_contract_result`, `rule_contract_result`, and the selected `wgpu_adapter`. On Steam Deck hardware, the selected backend should be Vulkan. On Windows development machines, DX12 is acceptable for local iteration, though Vulkan is also valid.

Run the parity audit when changing shader parameters or claiming fluid-engine progress:

```bash
python scripts/audit_native_shader_parity.py
```

The audit intentionally reports `incomplete` while Python app-shell features such as multi-load, notes, transient preview state, and retained view state are not ported. It fails if the Rust `Params` layout and WGSL `Params` layouts drift apart, or if a replacement-critical saved field no longer reaches the native GPU parameter payload.

Run the ordered local native suite before treating the Rust/wgpu candidate as healthy:

```bash
python scripts/smoke_native_validation_suite.py
```

That suite builds the native runtime once, runs rustfmt/clippy, Rust unit tests, package-local smoke, bounded timing-budget validation, and native evidence gates sequentially, and writes `artifacts/native_validation_suite.md` plus `.json`. It avoids racing generated packet artifacts and keeps expected non-final states, such as `shader_parity=incomplete` and `python_visual_parity=measured-drift`, explicit.

Run the saved-config contract check when changing the native config parser:

```bash
python scripts/check_native_config_contract.py
```

That check builds the Rust runtime, asks it to dump its normalized config contract without starting the GPU path, and compares all shipped Core presets against the saved v7 config schema for scalar parameters, settings, ranges, sweeps, jitters, rule count, and saved-rule presence.

Run the coarse visual metric report when renderer output changes:

```bash
python scripts/compare_native_visual_metrics.py --run-native
```

The report compares the native PPM capture against `artifacts/visual_smoke/trial3_running.png` when that Python visual-smoke reference exists. It is drift evidence only; exact Python/GLSL parity still requires stronger frame-level comparison.

Run the same-scenario native-vs-Python drift harness before claiming visual parity:

```bash
python scripts/smoke_native_python_visual_parity.py --no-build
```

That report refreshes a native Rival Bloom capture and a Python Trial 3 visual-smoke capture at 1280x800, computes pixel deltas, and explicitly records that exact parity is not claimed. A `measured-drift` status is useful evidence, not a pass on full engine replication.

Run the native replay determinism smoke when changing particle writes, compute order, or capture code:

```bash
python scripts/smoke_native_replay_determinism.py --no-build
```

That smoke runs the same saved native Trial Dish scenario twice and requires
bit-exact headless output. Trail simulation reads from one stable buffer and
writes the next through a ping-pong pair; commutative atomic deposits and color
combines keep native captures usable as regression evidence.

Run the native Trial Dish matrix when changing trial loading, objective sampling, or the headless render path:

```bash
python scripts/smoke_native_trial_matrix.py
```

That smoke runs every exported Trial Dish contract through the native headless runtime and records per-trial running-state output plus nonblank frame metrics.

Run the package-local smoke before treating `dist/FluoddityNative/` as a Steam candidate:

```bash
python scripts/smoke_native_package.py --no-sign
```

That smoke assembles the Windows native package, verifies bundled data and player launch wrappers, runs `run_headless.ps1`, and runs a bounded `run_deck_profile.ps1` timing pass from inside the package directory.
It also writes `artifacts/native_package_manifest.md` and `.json` with byte counts and SHA-256 hashes for the package-local files.

Window controls:

- Arrow keys: move the applicator cursor.
- Enter: apply.
- Space: pause/resume.
- Escape: exit.
- Controller right stick: move the applicator cursor through `gilrs`.
- Controller R2/right trigger: apply.
- Controller Start/Menu: pause/resume.
- Controller A/South: start/resume.
- Controller View/Select: exit.

## Promotion Gates

The next version of this spike should add:

- a 60-second Deck timing run on actual hardware;
- a README update that compares the spike behavior against the Python `--steam-deck --game` path.
- a real Steam Deck controller-only pass for start, pause, cursor movement, and apply.
- a retained UI pass for actual objective copy, wrapping, localization, menus, and results.
- closer parity with the Python shader's mutation history, presentation modes, and multi-load behavior.
- a native shader parity audit that moves materially toward `complete`, not just a runnable approximation.
- side-by-side visual or frame-metric comparison against the Python/GLSL renderer for the same saved config and rule seed.
