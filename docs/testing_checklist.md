# Fluoddity Validation Checklist

Use this after large refactors or significant new features. It combines
automated smoke suites with the manual visual, controller, packaging, and
hardware checks that automation cannot establish. Record results against the
surface actually exercised: Python/OpenGL, Rust/wgpu native, or the
self-contained WebGPU artifact.

## Game Prototype Quick Check
- [ ] Use the project Python interpreter for every `python ...` command below. On Windows, if PATH points at another tool venv, substitute `.venv\Scripts\python.exe` for `python`; for the umbrella smoke, also pass `--python .venv\Scripts\python.exe` so child checks use the same environment.
- [ ] Run `python scripts/smoke_game_v1.py`
- [ ] V1 smoke variants can be run in parallel; summary/report smokes write pid-scoped smoke artifacts under `artifacts/`
- [ ] Confirm `smoke_game_v1.py` fails clearly when the selected child interpreter is missing project dependencies and suggests the repo venv; this is covered by `python scripts/smoke_game_v1_dependency_guard.py`
- [ ] Run `python scripts/smoke_trial_definitions.py`
- [ ] Run `python scripts/smoke_trial_definitions_export.py`
- [ ] Run `python scripts/smoke_trial_definitions_schema.py`
- [ ] Run `python scripts/smoke_trial_runtime_contract.py`
- [ ] Run `python scripts/smoke_trial_dish_tuning_reference.py`
- [ ] Run `python scripts/smoke_trial_module_boundaries.py`
- [ ] Run `python scripts/smoke_game_design_alignment.py`
- [ ] Run `python scripts/smoke_game_v1_done_definition.py`
- [ ] Run `python scripts/smoke_game_identity.py`
- [ ] Run `python scripts/smoke_trial_dishes.py`
- [ ] Run `python scripts/smoke_game_controller.py`
- [ ] Run `python scripts/smoke_game_shell_contract.py`
- [ ] Run `python scripts/smoke_steam_input_manifest.py`
- [ ] Run `python scripts/smoke_native_validation_suite.py`
- [ ] Review `artifacts/native_validation_suite.md`; Rust formatting, clippy, unit tests, package smoke, and bounded local timing budget must pass, and `shader_parity` may report expected `incomplete`, but every gate in the suite should pass its allowed status before treating the native runtime as a Steam candidate
- [ ] Run `python scripts/write_steam_input_handoff.py`
- [ ] Run `python scripts/write_trial_dish_playtest_report.py` only to create the initial sheet; it refuses to replace existing evidence unless `--force` is explicitly supplied
- [ ] Run `python scripts/smoke_trial_dish_playtest_summary.py`
- [ ] Run `python scripts/prepare_steam_deck_packet.py`
- [ ] Confirm packet refresh preserves existing `artifacts/trial_dish_playtest.md` and `artifacts/package_validation.md`; use `--replace-manual-reports` only when deliberately resetting both manual reports
- [ ] Confirm a preserved playtest/package report with a mismatched build, tester, or device is listed as not-ready for the current packet rather than credited as fresh evidence
- [ ] Run `python scripts/validate_steam_deck_packet_manifest.py`
- [ ] Confirm packet preparation prints `steam_deck_packet_manifest_status=valid`; rerun the standalone validator after any manual artifact edits
- [ ] Review `artifacts/steam_deck_packet_index.md` before a hardware pass and confirm it points to every generated report
- [ ] Confirm generated packet reports stamp `Xenoculture: Trial Dish` as the game and `Fluoddity` as the engine/package lineage
- [ ] Run `python scripts/summarize_steam_input_handoff.py --require-ready` after filling `artifacts/steam_input_handoff.md`; Steamworks app/branch, imported manifest version, default config name, glyph rendering path, tester/device, and defects/remaps must be filled
- [ ] Run `python scripts/smoke_steam_input_handoff_summary.py`
- [ ] Run `python scripts/summarize_steam_deck_preflight.py --require-ready` after filling `artifacts/steam_deck_preflight.md`; hardware tester, device/OS, launch target, observed FPS, legibility notes, and input/suspend notes must be filled
- [ ] Run `python scripts/smoke_steam_deck_preflight_summary.py`
- [ ] Run `python scripts/smoke_steam_deck_visual_evidence.py`
- [ ] Run `python scripts/summarize_package_validation.py --require-ready` after filling `artifacts/package_validation.md`; tester, device/OS, package path, runtime path, Steam launch target, FPS, and runtime defects must be filled
- [ ] Run `python scripts/smoke_package_validation_summary.py`
- [ ] Run `python scripts/summarize_release_readiness.py --require-ready` before treating the packet as release-ready
- [ ] Run `python scripts/smoke_release_readiness_summary.py`
- [ ] Run `python scripts/smoke_release_readiness_schema.py`
- [ ] Confirm `artifacts/release_readiness_summary.json` and `artifacts/release_readiness.schema.json` are generated and report the same release readiness status as `artifacts/release_readiness_summary.md`
- [ ] Confirm `artifacts/steam_deck_packet_manifest.json` and `artifacts/steam_deck_packet_manifest.schema.json` are generated and list packet evidence artifacts with byte counts and SHA-256 hashes
- [ ] Confirm `artifacts/package_validation.md` and `artifacts/package_validation_summary.md` are generated with the hardware packet for native Linux or Proton launch validation
- [ ] Confirm `artifacts/steam_deck_visual_evidence.md` is generated with the hardware packet and lists visual-smoke image paths plus Capture Review summaries when `--with-visual` is used
- [ ] Confirm `artifacts/trial_definitions.json` and `artifacts/trial_definitions.schema.json` are generated with the hardware packet for future tooling/port checks
- [ ] Review `artifacts/trial_dish_tuning_reference.md` before changing thresholds from playtest findings
- [ ] Run `python scripts/smoke_steam_deck_packet.py`
- [ ] Run `python scripts/prepare_steam_deck_packet.py --run-automated --with-visual --with-fed-results` before a full hardware packet refresh
- [ ] Run `python scripts/smoke_steam_deck_packaging.py`
- [ ] Confirm `smoke_trial_dishes.py` includes the full synthetic three-trial playthrough path
- [ ] Run `python scripts/smoke_game_runtime.py`
- [ ] Run `python scripts/smoke_game_performance.py --extra-arg=--deck-performance --min-fps 30`
- [ ] Run `python scripts/smoke_game_visual.py`
- [ ] Run `python scripts/smoke_game_visual.py --trial 1 --expect-zone-overlays 0 --expect-no-hazard-overlay --expect-no-rival-overlay`
- [ ] Run `python scripts/smoke_game_visual.py --trial 1 --start --frame 25 --expect-active-zones 1 --expect-progress-min 0.01 --expect-status running`
- [ ] Run `python scripts/smoke_game_visual.py --trial 2 --expect-zone-overlays 3 --expect-no-hazard-overlay --expect-no-rival-overlay`
- [ ] Run `python scripts/smoke_game_visual.py --trial 3 --expect-zone-overlays 3 --expect-no-hazard-overlay --expect-no-rival-overlay`
- [ ] Run `python scripts/smoke_game_visual.py --trial 1 --start --frame 45 --controller-cursor --controller-feed --expect-active-zones 1 --expect-progress-min 0.01 --expect-status running --expect-controller-cursor --expect-controller-draw`
- [ ] Run `python scripts/smoke_game_visual.py --trial 1 --start --pause --frame 45 --controller-cursor --controller-feed --expect-status running --expect-paused --expect-no-controller-cursor --expect-no-controller-draw`
- [ ] Run `python scripts/smoke_game_visual.py --trial 2 --start --feed --frame 90 --expect-active-zones 2 --expect-progress-min 0.05 --expect-status running`
- [ ] Run `python scripts/smoke_game_visual.py --trial 3 --start --feed --frame 90 --expect-active-zones 2 --expect-rival-zones 1 --expect-progress-min 0.01 --expect-status running`
- [ ] Run `python scripts/smoke_game_v1.py --with-fed-results`
- [ ] Run `python scripts/smoke_game_visual.py --trial 1 --start --feed --frame 240 --expect-active-zones 1 --expect-progress-min 1.0 --expect-status won`
- [ ] Run `python scripts/smoke_game_visual.py --trial 2 --start --resolve --frame 120 --expect-progress-max 0.99 --expect-status failed`
- [ ] Run `python scripts/smoke_game_visual.py --trial 2 --start --feed --frame 540 --expect-active-zones 2 --expect-progress-min 1.0 --expect-status won`
- [ ] Run `python scripts/smoke_game_visual.py --trial 3 --start --feed --resolve --frame 120 --expect-active-zones 2 --expect-rival-zones 1 --expect-progress-min 1.0 --expect-status won`
- [ ] Run `python scripts/smoke_game_runtime.py --extra-arg=--deck-performance`
- [ ] Run `python scripts/smoke_game_v1.py --with-deck-performance --seconds 5 --min-fps 30`
- [ ] Run `python scripts/steam_deck_preflight.py --with-visual --with-fed-results` before a hardware pass and fill in `artifacts/steam_deck_preflight.md`
- [ ] Confirm the preflight report links to `artifacts/steam_deck_packet_index.md`, `artifacts/trial_dish_tuning_reference.md`, `artifacts/trial_dish_tuning_plan.md`, `artifacts/package_validation.md`, and `artifacts/package_validation_summary.md`, marks automated gate coverage, summarizes controller prompt-mode evidence, and still lists actual Deck hardware, Steamworks Steam Input import, official glyph rendering, and native/Proton package validation as external gates
- [ ] Review `artifacts/steam_input_handoff.md` before the Steamworks import and confirm the recommended TrialDish default bindings match the intended controller layout
- [ ] Fill in `artifacts/trial_dish_playtest.md` during a controller-only playtest before changing thresholds
- [ ] Confirm the playtest report includes ratings for action-feedback loop, meaningful choice, and flow balance before treating the summary as tuning-ready
- [ ] Run `python scripts/summarize_trial_dish_playtest.py --require-ready` after filling the playtest report, then run `python scripts/write_trial_dish_tuning_plan.py --require-ready` before changing threshold/copy/visual tuning
- [ ] Run `python main.py --game`
- [ ] Confirm `python main.py --game` hides raw editor panels/text-entry tools, and `python main.py --game --allow-editor-in-game` exposes them for development
- [ ] Confirm default `python main.py --game` ignores raw editor shortcuts and command flags such as config copy/paste, sidebar toggle, parameter sweeps, recording, screenshots, field loading, and mouse-mode toggles unless `--allow-editor-in-game` is passed
- [ ] Inspect `artifacts/visual_smoke/trial1_briefing.png`, `trial1_running.png`, `trial1_controller_feed.png`, `trial1_paused.png`, `trial1_result_failure.png`, `trial1_fed_win.png`, `trial2_running.png`, `trial2_result.png`, `trial3_running.png`, `trial3_mutated.png`, `trial3_reverted.png`, and `trial3_result.png` for clipped HUD text, objective response, active zone colors, controller reticle visibility, paused/result-state readability, mutation readout clarity, or markers hidden behind the panel
- [ ] Trial 1 briefing starts visually quiet with no objective marker, then the running assay reveals a single marked zone with no editor panels visible
- [ ] Trial 1 HUD shows a specimen readout that changes between dormant, responding, and stabilizing states
- [ ] Trial 1 shows a short `Specimen response detected` feedback cue when the marked culture zone first activates
- [ ] Trial 2 and Trial 3 briefings hold hazard/rival overlays until the assay starts
- [ ] Visual smoke state reports `zone_overlays`, `hazard_overlay`, and `rival_overlay` for onboarding reveal checks
- [ ] Game-mode window title is `Xenoculture: Trial Dish`; editor/build/package paths may still say Fluoddity during V1
- [ ] Each briefing shows a short K-7 story beat before protocol instructions
- [ ] Starting Trial 1 primes a visible specimen response
- [ ] Progress text explains the current objective status, such as active culture sites, hold time, or rival pressure
- [ ] Late Trial 2/3 running HUD states show a timer-pressure readout without adding clutter to Trial 1 onboarding
- [ ] Trial 2 shows the antibiotic band and multiple zones
- [ ] Trial 2 HUD shows an antibiotic route readout that changes between absent, partial, and stable route states
- [ ] Trial 2 shows short route feedback cues when the route starts forming and when it survives the scar
- [ ] Trial 3 shows Rival Bloom, Irradiate Strain, and Revert Strain controls
- [ ] Trial 3 HUD shows mutation state as baseline, mutated/archive-ready, or restored after tool use
- [ ] Trial 3 guidance prioritizes archive/revert decisions after Irradiate, even when culture is currently ahead on site control
- [ ] Trial Dish HUD shows current controller/keyboard prompts for Start, Retry, Next, Irradiate, and Revert states
- [ ] Trial Dish visual smoke output includes active prompt input scheme, chip-style controller prompt text, and glyph paths for Start, Nutrient Gel, Pause, Resume, Exit, Irradiate, Revert, Retry, Next, and Restart states
- [ ] Trial Dish HUD switches from hybrid prompts to controller-only prompts after gamepad input, and back to keyboard/mouse prompts after keyboard or mouse input
- [ ] Controller Menu pauses/resumes an active Trial Dish, and paused state freezes trial time plus Nutrient Gel application
- [ ] Controller View does not exit during active play, but exits from the paused Trial Dish state
- [ ] Controller A/B/Menu/View/Y/L1 actions drive Trial Dish state transitions without keyboard/mouse fallback
- [ ] In game mode, right stick moves the nutrient gel cursor and R2 applies nutrient gel without mouse or touch
- [ ] Trial 3 tool labels distinguish ready, recharge, depleted, archive-ready, no-archive, and spent states
- [ ] Sterilize Dish returns to briefing with visible station feedback
- [ ] Irradiate Strain creates an archive, consumes a charge, and starts cooldown
- [ ] Revert Strain is unavailable before archive and consumes its one charge after use
- [ ] Trial 3 result summary reports culture-site control plus irradiation/revert usage
- [ ] Trial 3 grade changes for clean wins, narrow wins, and stalemates
- [ ] Trial 3 HUD shows a containment margin/readout that changes with culture vs rival site control
- [ ] Result screen explains next assay, retry focus, or sequence completion
- [ ] Result screen includes a next-experiment hint that suggests a concrete retry/comparison choice
- [ ] Winning Trial 3 shows sequence-complete text and can restart from Trial 1

## WebGPU networked.art/everything

- [ ] Run `python scripts/build_webgpu_artifact.py`
- [ ] Run `python scripts/smoke_webgpu_artifact.py --require-thumbnail`
- [ ] Run `python scripts/audit_webgpu_artifact_parity.py --require-complete`
- [ ] Run `python scripts/smoke_webgpu_responsive.py --skip-build`
- [ ] Review `artifacts/webgpu/responsive-smoke.json`; the exact `1280x600`, `800x600`, `680x620`, `390x640`, `320x300`, and scroll-forcing `320x180` iframe sizes must report all four sliders rendered, hit-testable, focusable, and functional
- [ ] At compact iframe heights, confirm the control panel scrolls while Pause, Reset, New Variation, and every slider remain reachable
- [ ] Open `artifacts/networked-art/everything.html` in the intended networked.art/everything embed at 100% browser zoom; no control may require zooming out to reveal or operate it
- [ ] Confirm the artifact remains a single self-contained HTML file with no runtime network or persistence dependency
- [ ] Treat the source-contract audit as bounded WebGPU evidence. Do not report it as full Python editor, Trial Dish, native shader, or pixel parity

## Native High-Resolution Video

- [ ] Run `python scripts/smoke_native_video_export.py`
- [ ] Confirm `artifacts/native_video_export_smoke.json` and `.md` report `pass` for an actual `3840x2160`, 60 FPS export
- [ ] Confirm ffprobe evidence reports MP4/H.264, `yuv420p`, 3840x2160, 60 FPS, the requested frame count/duration, BT.709 primaries/transfer/matrix, and TV color range
- [ ] Confirm the MP4 `moov` atom precedes `mdat` (faststart), and the full MP4 decodes without an FFmpeg error
- [ ] Confirm the decoded final video frame matches the opt-in PPM poster within the smoke threshold
- [ ] Confirm the repeated offline export has the expected deterministic hashes and the output-path collision test neither modifies the completed artifact nor leaves a `.partial.mp4`
- [ ] Inspect `artifacts/native_video_export_smoke.metadata.json`; schema is `fluoddity.native_video_export.v1`, `captures_final_presentation` is true, and render, codec, timeline, trial, frame, duration, CRF, preset, and output-byte fields match the run
- [ ] Run a source export without `--out` and confirm no PPM is created; add a distinct `--out path/to/poster.ppm` only when poster evidence is required
- [ ] Build `dist/FluoddityNative/` with `runtime/rust-wgpu-spike/scripts/package-windows.ps1`, run `run_export_video.ps1 -Seconds 1` from a working directory outside the package, and confirm the wrapper uses package-local data and `ffmpeg.exe`
- [ ] Run `run_record_video.ps1` only as a 60 FPS presented window-frame capture check; confirm one encoded frame and one 60 Hz trial-time step per redraw, and do not report it as wall-clock-real-time recording
- [ ] Keep the offline `run_export_video` workflow as the publishable-master path; changing encoder speed must affect wall-clock export time, not the fixed 60 Hz simulation timeline
- [ ] Treat passing Windows output as Windows-only evidence. Do not mark Deck/Linux video ready until the native package is built and run on the target platform with its own static licensed FFmpeg bundle
- [ ] On actual Deck/Linux hardware, set `FLUODDITY_FFMPEG_BUNDLE` and `FLUODDITY_FFMPEG_LICENSE`, run `runtime/rust-wgpu-spike/scripts/package-deck.sh`, then run package-local `run_export_video.sh`
- [ ] On actual Deck hardware, record the selected Vulkan adapter plus device/OS/storage/thermal observations, ffprobe and full-decode the package-local MP4, and keep this evidence separate from local Windows validation

## 0. Steam Deck Verified Readiness
- [ ] Run `python main.py --steam-deck --game` or the packaged `run_steam_deck.sh`
- [ ] Confirm the packaged `run_steam_deck.sh` launches with `--steam-deck --game`, not the raw editor shell
- [ ] App launches directly at Deck-native `1280x800` fullscreen with no launcher or setup prompt
- [ ] Default settings hold 30 FPS or better at 800p
- [ ] Smallest UI text is legible at handheld distance
- [ ] In the default `--game` player shell, controller can start, feed, pause/resume, retry, complete Trial 1, and exit from paused state
- [ ] In `--allow-editor-in-game` dev mode, controller/editor shortcuts can still pan, zoom, toggle panels, randomize mutations, and use editor tools
- [ ] No normal play path requires keyboard, mouse, touchscreen, or manual controller configuration
- [ ] Text entry is avoided in normal play; any editor/dev text entry must be gated out of the shipped player shell or open a controller-safe on-screen keyboard path
- [ ] See `docs/steam_deck_verified.md` for the release-blocking checklist
- [ ] If the shell default `python` is not the project interpreter, run the package build with `PYTHON=/path/to/python bash scripts/build_linux.sh`
- [ ] Confirm `dist/Fluoddity/steam_input/steam_input_manifest.vdf` is present after `bash scripts/build_linux.sh`
- [ ] Confirm `dist/Fluoddity/steam_input/trial_prompt_glyph_map.json` and `dist/Fluoddity/steam_input/glyphs/*.svg` are present after `bash scripts/build_linux.sh`
- [ ] Confirm `dist/Fluoddity/steam_input/steam_input_handoff.md` is generated after `bash scripts/build_linux.sh`

## 1. Config Save/Load System
- [ ] **a.** File → Save: enter name, verify JSON appears in Custom folder
- [ ] **b.** File → Save existing name: overwrite confirmation dialog works
- [ ] **c.** File → Load: click config, verify rule + sliders + appearance applied
- [ ] **d.** Hover preview: hover over config names, verify live preview (particles change)
- [ ] **e.** Preview restore: move mouse away from menu, verify original state restored
- [ ] **f.** Watercolor lock: right-click in Load submenu toggles watercolor for all previews
- [ ] **g.** Category headers: Core/Custom/Advanced collapse/expand, state persists across opens
- [ ] **h.** N button: shows notes tooltip (blue when notes exist)
- [ ] **i.** X button: opens delete confirmation, file removed on confirm
- [ ] **j.** Clipboard: Ctrl+C copies config, Ctrl+V pastes and applies
- [ ] **k.** Saves preserve: jitter values, custom slider ranges, parameter sweep assignments, notes

## 2. Particle Selection & Rule History
- [ ] **a.** Left click selects particle, applies its mutated rule (1-frame deferred readback)
- [ ] **b.** Right click undoes last selection (pops rule stack)
- [ ] **c.** History window shows colored jersey numbers, newest first
- [ ] **d.** Hover history entry: live preview of that rule
- [ ] **e.** Click history entry: moves rule to top of stack
- [ ] **f.** X button in history: deletes that rule entry
- [ ] **g.** Z key: full reset (zero rule + new seed + push to history)
- [ ] **h.** M key: randomize mutations (same rule, new seed, push to history)
- [ ] **i.** R key: simple reset (particles only, rule unchanged)

## 3. Physics Sliders
- [ ] **a.** All 12 sliders respond and affect simulation in real-time
- [ ] **b.** Right-click context menu opens on each slider
- [ ] **c.** Jitter slider works (orange tint, range shown in label)
- [ ] **d.** Jitter hidden for Hazard Rate and Mutation Scale
- [ ] **e.** Min/Max fields adjust range; "Reset Range" restores defaults
- [ ] **f.** "Reset Value" button works (shows loaded config name if applicable)
- [ ] **g.** Ctrl+click on slider allows direct number entry
- [ ] **h.** Hazard Rate uses power scaling (fine control at low values)
- [ ] **i.** Hard limits enforced: Drag/Sensor Angle (±1.0), Trail Persistence/Diffusion (0-1.0)
- [ ] **j.** Physics tooltips: enable in preferences, hover slider shows animated diagram

## 4. Parameter Sweeps
- [ ] **a.** Enable checkbox toggles X/Y/C buttons on sliders
- [ ] **b.** X button: left-click = normal (bright red), right-click = inverse (dark red)
- [ ] **c.** Y button: same pattern, green
- [ ] **d.** C button (cohort): same pattern, yellow
- [ ] **e.** Left click on canvas: updates slider values from position (XY) or particle cohort (C)
- [ ] **f.** Right click on canvas: enters preview mode (sweeps disabled, window tints blue)
- [ ] **g.** Any click while preview pending: re-enables sweeps
- [ ] **h.** Sweep reticle visible on canvas, hidden during recording/screenshot
- [ ] **i.** Range adjust buttons (^ v): widen/narrow range around current value

## 5. Video Recording
- [ ] **a.** Record key toggles recording on/off
- [ ] **b.** While recording: speedmult/motion blur locked to recording settings
- [ ] **c.** Stop recording: user settings restored
- [ ] **d.** Delayed start: set Video End Frame > 0, recording starts at calculated frame
- [ ] **e.** Pending state: shows countdown, can cancel with record key
- [ ] **f.** Video saved to Documents/Fluoddity/ with timestamp
- [ ] **g.** Recording window shows status (RECORDING / WAITING / idle)

## 6. Screenshots
- [ ] **a.** Shift+P takes screenshot
- [ ] **b.** Settings temporarily overridden (max quality motion blur)
- [ ] **c.** Settings restored after save (including pause state)
- [ ] **d.** File saved to Documents/Fluoddity/screenshots/ with timestamp
- [ ] **e.** Supersample factor applied

## 7. Multi-Load Mode
- [ ] **a.** Extras → Multi Load Mode enables
- [ ] **b.** File → Load adds configs (max 64), menu stays open
- [ ] **c.** Physics window switches to multi-load layout
- [ ] **d.** Mouse mode forced to Draw Trail
- [ ] **e.** Parameter sweeps force-disabled
- [ ] **f.** Simultaneous configs / Progression Pace / Current Progress sliders work
- [ ] **g.** Remove buttons remove individual configs
- [ ] **h.** Per-config toggles (Initial Conditions, Cohorts, Hazard Rate) grey out respective controls

## 8. Appearance & View
- [ ] **a.** Color by Cohort toggle (hides Hue Sensitivity when on)
- [ ] **b.** Watercolor Mode toggle (V key), shows Ink Weight when on
- [ ] **c.** Emboss Mode combo (Off/Canvas/Brush), shows Intensity + Smoothness when on
- [ ] **d.** Brightness slider affects output
- [ ] **e.** Exposure slider works
- [ ] **f.** View option dropdown cycles views
- [ ] **g.** Tiling mode (view option 3): camera wraps, exiting wraps position back to center

## 9. Preferences
- [ ] **a.** World size change triggers full rebuild (expensive, console output)
- [ ] **b.** Physics frequency slider (locked label during recording)
- [ ] **c.** Motion blur toggle + blur quality slider
- [ ] **d.** Mouse mode dropdown (locked text in multi-load)
- [ ] **e.** Draw size / Draw power visible only in Draw Trail mode
- [ ] **f.** Debug arrows toggle + sensitivity slider
- [ ] **g.** Preferences saved on exit, restored on next launch

## 10. Menu Auto-Close
- [ ] **a.** Main menu bar: menus close when mouse moves far away
- [ ] **b.** Physics settings menu bar: same behavior
- [ ] **c.** Slider context menus: same behavior
- [ ] **d.** Save dialog open prevents auto-close

## 11. Camera & Input
- [ ] **a.** WASD movement
- [ ] **b.** QE zoom in/out
- [ ] **c.** Scroll wheel zoom (centered on mouse pointer)
- [ ] **d.** V key: reload shaders (hot reload)
- [ ] **e.** Keybindings from keyboard_controls.json respected

## 12. Help Windows
- [ ] **a.** Help → Controls: lists all shortcuts
- [ ] **b.** Help → Tutorial: all collapsible sections open/close
- [ ] **c.** Help → Parameter Sweeps: info window opens
- [ ] **d.** Help → Performance: opens
- [ ] **e.** Help → Video Recording: shows recording status + all controls
