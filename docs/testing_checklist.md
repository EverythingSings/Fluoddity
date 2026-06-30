# Fluoddity Manual Testing Checklist

Use this after large refactors or significant new features. Items roughly ordered by breakage risk.

## Game Prototype Quick Check
- [ ] Run `python scripts/smoke_game_v1.py`
- [ ] Run `python scripts/smoke_trial_definitions.py`
- [ ] Run `python scripts/smoke_trial_definitions_export.py`
- [ ] Run `python scripts/smoke_trial_definitions_schema.py`
- [ ] Run `python scripts/smoke_trial_runtime_contract.py`
- [ ] Run `python scripts/smoke_trial_dish_tuning_reference.py`
- [ ] Run `python scripts/smoke_trial_module_boundaries.py`
- [ ] Run `python scripts/smoke_game_identity.py`
- [ ] Run `python scripts/smoke_trial_dishes.py`
- [ ] Run `python scripts/smoke_game_controller.py`
- [ ] Run `python scripts/smoke_game_shell_contract.py`
- [ ] Run `python scripts/smoke_steam_input_manifest.py`
- [ ] Run `python scripts/write_steam_input_handoff.py`
- [ ] Run `python scripts/write_trial_dish_playtest_report.py`
- [ ] Run `python scripts/smoke_trial_dish_playtest_summary.py`
- [ ] Run `python scripts/prepare_steam_deck_packet.py`
- [ ] Review `artifacts/steam_deck_packet_index.md` before a hardware pass and confirm it points to every generated report
- [ ] Confirm generated packet reports stamp `Xenoculture: Trial Dish` as the game and `Fluoddity` as the engine/package lineage
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
- [ ] Confirm the preflight report links to `artifacts/steam_deck_packet_index.md`, `artifacts/trial_dish_tuning_reference.md`, and `artifacts/trial_dish_tuning_plan.md`, marks automated gate coverage, summarizes controller prompt-mode evidence, and still lists actual Deck hardware, Steamworks Steam Input import, official glyph rendering, and native/Proton package validation as external gates
- [ ] Review `artifacts/steam_input_handoff.md` before the Steamworks import and confirm the recommended TrialDish default bindings match the intended controller layout
- [ ] Fill in `artifacts/trial_dish_playtest.md` during a controller-only playtest before changing thresholds
- [ ] Run `python scripts/summarize_trial_dish_playtest.py --require-ready` after filling the playtest report, then run `python scripts/write_trial_dish_tuning_plan.py --require-ready` before changing threshold/copy/visual tuning
- [ ] Run `python main.py --game`
- [ ] Confirm `python main.py --game` hides raw editor panels/text-entry tools, and `python main.py --game --allow-editor-in-game` exposes them for development
- [ ] Confirm default `python main.py --game` ignores raw editor shortcuts and command flags such as config copy/paste, sidebar toggle, parameter sweeps, recording, screenshots, field loading, and mouse-mode toggles unless `--allow-editor-in-game` is passed
- [ ] Inspect `artifacts/visual_smoke/trial1_briefing.png`, `trial1_running.png`, `trial1_controller_feed.png`, `trial1_paused.png`, `trial2_running.png`, `trial2_result.png`, `trial3_running.png`, and `trial3_result.png` for clipped HUD text, objective response, active zone colors, controller reticle visibility, paused/result-state readability, or markers hidden behind the panel
- [ ] Trial 1 briefing starts visually quiet with no objective marker, then the running assay reveals a single marked zone with no editor panels visible
- [ ] Trial 2 and Trial 3 briefings hold hazard/rival overlays until the assay starts
- [ ] Visual smoke state reports `zone_overlays`, `hazard_overlay`, and `rival_overlay` for onboarding reveal checks
- [ ] Game-mode window title is `Xenoculture: Trial Dish`; editor/build/package paths may still say Fluoddity during V1
- [ ] Each briefing shows a short K-7 story beat before protocol instructions
- [ ] Starting Trial 1 primes a visible specimen response
- [ ] Progress text explains the current objective status, such as active culture sites, hold time, or rival pressure
- [ ] Trial 2 shows the antibiotic band and multiple zones
- [ ] Trial 3 shows Rival Bloom, Irradiate Strain, and Revert Strain controls
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
- [ ] Result screen explains next assay, retry focus, or sequence completion
- [ ] Winning Trial 3 shows sequence-complete text and can restart from Trial 1

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
- [ ] Confirm `dist/Fluoddity/steam_input/steam_input_manifest.vdf` is present after `bash scripts/build_linux.sh`
- [ ] Confirm `dist/Fluoddity/steam_input/trial_prompt_glyph_map.json` and `dist/Fluoddity/steam_input/glyphs/*.svg` are present after `bash scripts/build_linux.sh`

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
