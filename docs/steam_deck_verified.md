# Steam Deck Verified Readiness

This is the project contract for turning Fluoddity from a desktop art toy into a Steam game foundation that targets Steam Deck Verified from day one.

Primary reference: Valve's Steamworks compatibility checklist at <https://partner.steamgames.com/doc/steamdeck/compat>.

## Launch Profile

The Steam launch option should run:

```bash
./run_steam_deck.sh
```

For source/development runs:

```bash
python main.py --steam-deck --game
```

The Deck profile sets:

- `1280x800` fullscreen launch target.
- `1.35` ImGui global scale for handheld legibility.
- conservative performance defaults: smaller world size, lower physics frequency, motion blur disabled, bloom disabled.
- gamepad and keyboard navigation flags for ImGui.

The same profile can be enabled with `FLUODDITY_STEAM_DECK=1`.

## Verified Gates

These are release-blocking gates for a Steam build.

- Input: all core game functions must be reachable with the Steam Deck physical controls using the default configuration.
- Glyphs: when controller input is active, UI copy must use controller names/glyphs instead of keyboard-only prompts.
- Text input: save/config naming must either avoid required text entry in the shipped game flow or open Steam's on-screen keyboard through Steamworks/Steam Input.
- Display: the default build must support `1280x800`; `1280x720` may be a fallback, not the preferred path.
- Legibility: the smallest on-screen font must stay at least 9 px high at `1280x800`; target 12 px or larger.
- Performance: default settings must hold at least 30 FPS at 800p on Steam Deck.
- Seamlessness: no compatibility warnings, external launchers, setup dialogs, or desktop-only first-run steps.
- Proton/Linux: either ship a native Linux build or validate the Windows build through Proton without middleware/runtime blockers.

## Current Implementation Status

- Done: explicit `--steam-deck` launch profile.
- Done: 1280x800 fullscreen target and larger UI scale.
- Done: Deck performance preset.
- Done: ImGui keyboard/gamepad navigation flags.
- Done: first-pass editor controller camera and shortcuts:
  - Left stick: move camera
  - Right stick up/down or triggers: zoom in editor mode
  - Right bumper: fast movement/zoom
  - A: pause/resume
  - B: reset particles
  - X: toggle sidebar
  - Y: randomize mutations
  - Select: toggle mouse mode
  - Start: reset controller camera
- Done: game-mode lab applicator controls:
  - Left stick: pan dish view
  - Right stick: aim nutrient gel cursor
  - R2: apply nutrient gel
  - R1: faster cursor movement
  - A: start, next, restart, or retry
  - B: retry / sterilize current dish
  - Y: irradiate strain when unlocked
  - L1: revert strain when archive is available
  - Menu: pause or resume the active assay
  - View: exit from a paused assay
- Done: Linux PyInstaller build wrapper and Deck launch script generation.
- Done: timed performance smoke records average FPS, average frame time, and worst frame time for the Deck-sized game profile.
- Done: Trial Dish HUD prompts are routed through a centralized prompt formatter that reads configured keyboard labels.
- Done: Trial Dish HUD prompts switch between hybrid, controller-only, and keyboard/mouse-only labels based on recent input.
- Done: Trial Dish HUD prompts carry structured controller labels and Steam Input action ids for future glyph rendering.
- Done: Trial Dish HUD renders controls from structured prompt specs, preserving a direct renderer hook for future glyph textures.
- Done: default `--game` launch hides raw editor panels and text-entry save/config tools; `--allow-editor-in-game` is required for game-mode development access.
- Done: game-mode pause/resume is reachable from the Menu button and freezes trial time, simulation, and nutrient gel application.
- Done: default game mode has a controller-safe exit path through the View button while paused, without exposing editor panels.
- Done: visual smoke captures paused game-mode HUD state and verifies controller Nutrient Gel input is suppressed while paused.
- Done: visual smoke emits the active prompt input scheme and asserts controller-mode prompts for controller cursor and paused controller captures.
- Done: controller smoke verifies app-level controller actions drive Trial Dish state transitions for start, pause/resume, paused exit, retry, advance, mutation tools, and final restart.
- Done: initial Steam Input action manifest artifact exists under `steam_input/` and is copied into Linux/Deck builds.
- Done: Steam Input manifest smoke validates required Trial Dish/editor actions, input modes, and localization tokens.
- Done: Trial Dish prompt glyph map exists at `steam_input/trial_prompt_glyph_map.json` and is smoke-checked against the manifest plus HUD prompt action ids.
- Done: Trial Dish glyph map now resolves to checked placeholder SVG assets under `steam_input/glyphs/`, and packaging smoke fails if any mapped glyph file is missing, malformed, unlabeled, or externally referenced.
- Done: visual smoke checks the displayed controller prompt fallback text, so the Deck-facing HUD path is covered before the official Steam glyph renderer is wired in.
- Done: Steam Input handoff report generation validates the manifest/glyph map and writes the recommended TrialDish default bindings for the Steamworks import pass.
- Done: Steam Deck packaging smoke validates that `scripts/build_linux.sh` copies Steam Input artifacts and generates `run_steam_deck.sh` with the Deck profile.
- Done: the generated Deck launch wrapper runs `--steam-deck --game`, so the packaged Steam target opens the Trial Dish player shell rather than the raw editor.
- Done: shell-contract smoke verifies `--steam-deck --game` combines Deck defaults with player-shell editor gating.
- Done: `scripts/steam_deck_preflight.py` runs the automated Deck-target gates and writes a manual hardware validation report skeleton.
- Done: the preflight report extracts high-signal automated evidence, including controller-mode visual prompt captures and paused controller suppression evidence when visual smokes are run.
- Done: the preflight report links back to the generated packet index, so hardware testers start from the same report order.
- Done: `scripts/write_trial_dish_playtest_report.py` writes a controller-first manual playtest report for game-feel, onboarding, readability, and threshold tuning evidence.
- Done: `scripts/prepare_steam_deck_packet.py` writes a packet index, Steam Input handoff, Trial Dish playtest report, playtest summary, tuning reference, tuning plan, and Deck preflight report together for a hardware pass.
- Done: generated packet reports are stamped with branch, commit, clean/dirty state, and changed-path count so hardware notes can be traced back to the tested prototype snapshot.
- Done: default `--game` gates raw editor shortcuts and persisted editor/help windows behind `--allow-editor-in-game`.
- Done: default `--game` defensively clears editor-only command flags before command processing, and the shell-contract smoke verifies Trial Dish actions still pass through.
- Done: local Windows Deck-sized performance smoke passed on this workstation: `avg_fps=452.74`, `avg_frame_ms=2.21`, `worst_frame_ms=5.37` for a 5 second `--deck-performance` run at 1280x800.

## Known Verified Blockers

- Editor/dev flows still expose keyboard/mouse wording and assumptions; the default player shell gates these away.
- Save/config naming still uses ImGui text input in editor/dev flows, not Steam's on-screen keyboard.
- Controller navigation needs a real end-to-end Trial Dish pass on actual Deck hardware: start, feed, pause/resume, retry, win, restart, and paused exit.
- Game-mode nutrient gel has an automated controller-path smoke, but still needs a real Trial Dish completion pass on actual Deck hardware.
- The current Python/OpenGL stack needs native Linux and/or Proton validation on actual Deck hardware.
- Automated performance smoke passes locally, but the 30 FPS Verified gate still needs actual Deck hardware evidence.
- Steam Input still needs a real Steamworks import/configuration pass and official platform glyph rendering; current controller prompts are mapped to checked placeholder SVG glyph assets.

## Manual Deck Test Pass

Run this on Steam Deck hardware or the closest Linux handheld target available.

Before manual testing, run:

```bash
python scripts/prepare_steam_deck_packet.py
```

For a packet that also reruns local automated gates:

```bash
python scripts/prepare_steam_deck_packet.py --run-automated --with-visual --with-fed-results
```

These write `artifacts/steam_deck_packet_index.md`,
`artifacts/steam_input_handoff.md`, `artifacts/trial_dish_playtest.md`,
`artifacts/trial_dish_playtest_summary.md`,
`artifacts/trial_dish_tuning_reference.md`, `artifacts/trial_dish_tuning_plan.md`,
and
`artifacts/steam_deck_preflight.md` with a shared build stamp, a hardware-pass
runbook, the Steam Input import checklist, manual playtest sheet,
tuning-readiness summary, current tuning reference, post-playtest tuning plan,
automated smoke output, and the checklist below.

1. Launch from Steam with `./run_steam_deck.sh` and confirm it opens the Trial Dish player shell.
2. Confirm the app starts directly, without console prompts, launchers, compatibility warnings, or setup dialogs.
3. Confirm the framebuffer is `1280x800` or the Deck-native fullscreen equivalent.
4. Confirm the default preset starts at 30 FPS or better for five minutes.
5. Confirm all visible text is readable at handheld distance.
6. In `python main.py --game`, use only controls to start Trial 1, aim nutrient gel with right stick, apply it with R2, pause/resume with Menu, retry with B, and exit from the paused state with View.
7. Complete Trial 1 without opening the raw editor.
8. Confirm `--game` does not expose editor panels, config save/load, text-entry popups, parameter sweeps, or field-loading windows unless `--allow-editor-in-game` is passed.
9. Confirm no required player-shell workflow needs touch, mouse, keyboard, or manual Steam controller configuration.
10. Confirm any dev/editor text-entry workflow is nonessential for normal play or opens a controller-safe text input path before exposure in a shipped build.
11. Confirm Steam Input is using the imported `TrialDish` action set and default configuration described in `artifacts/steam_input_handoff.md`.
12. Confirm controller prompts use official Steam/Deck glyph rendering or an approved shipped fallback.
13. Confirm suspend/resume does not leave the GL context black or frozen.
14. Confirm a clean restart preserves preferences without corrupting user data.

## Next Engineering Steps

1. Import the Steam Input manifest into Steamworks, create the default configuration, and replace placeholder glyph assets with the official Steam/Deck glyph rendering path.
2. Replace editor/dev ImGui text entry with controller-safe naming or Steamworks keyboard calls before exposing those flows in the shipped game.
3. Run the timed performance smoke on actual Steam Deck hardware and record the measured FPS/frame-time result.
4. Run a real controller-only Trial Dish completion pass on Steam Deck hardware.
5. Decide whether the Steam SKU is native Linux first or Windows-through-Proton first, then freeze packaging around that path.
