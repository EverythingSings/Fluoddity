# Steam Deck Verified Readiness

This is the project contract for turning Fluoddity from a desktop art toy into a Steam game foundation that targets Steam Deck Verified from day one.

Primary reference: Valve's Steamworks compatibility checklist at <https://partner.steamgames.com/doc/steamdeck/compat>.

## Launch Profile

The Steam launch option should run:

```bash
./run_steam_deck.sh
```

For the Rust/wgpu native package candidate, use the launch contract in
`artifacts/native_steam_launch_contract.md`. The current native package exposes
`XenocultureTrialDish.exe` for Windows/Proton and `XenocultureTrialDish` for
Deck/Linux, with `run_steam_deck.ps1` / `run_steam_deck.sh` as package-local
player launch wrappers.

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

## Native Video Export Validation

High-resolution export is a native-runtime delivery gate separate from the
800p interactive Verified performance gate. The publishable workflow is
package-local offline export: a fixed 60 Hz simulation timeline is rendered at
the requested resolution and encoded to H.264 `yuv420p` MP4 with BT.709
metadata and faststart layout. The export writes a structured JSON report; a
PPM poster is opt-in.

Build the Deck/Linux package with a redistributable static FFmpeg executable
that exposes `libx264` and its matching license:

```bash
FLUODDITY_FFMPEG_BUNDLE=/absolute/path/to/ffmpeg \
FLUODDITY_FFMPEG_LICENSE=/absolute/path/to/LICENSE \
bash runtime/rust-wgpu-spike/scripts/package-deck.sh
```

Then run a short package-local proof on the actual target:

```bash
VIDEO_SECONDS=1 WIDTH=3840 HEIGHT=2160 FPS=60 \
bash dist/FluoddityNative/run_export_video.sh
```

Probe and fully decode the resulting MP4, review its adjacent JSON report, and
record the selected adapter/backend, device/OS, storage, thermal behavior, and
export duration. The adapter should report Vulkan on Steam Deck.

`run_record_video.sh` is a separate 60 FPS presented window-frame capture path.
It writes one encoded frame and advances one 60 Hz trial-time step per redraw;
it is not wall-clock-real-time when GPU readback or encoding cannot sustain the
requested FPS. It must not be described as real-time recording in release
evidence.

A passing Windows 4K/60 smoke proves only the Windows runtime, adapter, and
selected FFmpeg build. It does not satisfy the Linux package, Vulkan, storage,
or actual Deck hardware gates above.

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
- Done: Steam Deck packaging smoke validates that `scripts/build_linux.sh` copies Steam Input artifacts, generates `dist/Fluoddity/steam_input/steam_input_handoff.md`, and generates `run_steam_deck.sh` with the Deck profile.
- Done: the generated Deck launch wrapper runs `--steam-deck --game`, so the packaged Steam target opens the Trial Dish player shell rather than the raw editor.
- Done: shell-contract smoke verifies `--steam-deck --game` combines Deck defaults with player-shell editor gating.
- Done: `scripts/steam_deck_preflight.py` runs the automated Deck-target gates and writes a manual hardware validation report skeleton.
- Done: the preflight report extracts high-signal automated evidence, including controller-mode visual prompt captures and paused controller suppression evidence when visual smokes are run.
- Done: the preflight report links back to the generated packet index, so hardware testers start from the same report order.
- Done: `scripts/write_trial_dish_playtest_report.py` writes a controller-first manual playtest report for game-feel, onboarding, readability, action-feedback timing, meaningful choice, flow balance, friction, and threshold tuning evidence.
- Done: `scripts/prepare_steam_deck_packet.py` writes a packet index, Trial Dish definitions JSON/schema, Steam Input handoff, Trial Dish playtest report, playtest summary, tuning reference, tuning plan, package/runtime validation report, and Deck preflight report together for a hardware pass.
- Done: the Steam Deck packet includes `artifacts/steam_deck_packet_manifest.json` plus a checked schema, giving hardware/Steamworks handoff a hashed inventory of generated evidence.
- Done: packet preparation validates `artifacts/steam_deck_packet_manifest.json` before reporting success, so stale artifact hashes or release-readiness snapshot mismatches block the handoff command.
- Done: generated packet reports stamp the player-facing game title `Xenoculture: Trial Dish` separately from the Fluoddity engine/package lineage.
- Done: `scripts/summarize_steam_input_handoff.py` rejects blank Steam Input handoff reports and requires Steamworks import/default-config/glyph evidence before that gate is ready.
- Done: `scripts/summarize_steam_deck_preflight.py` rejects blank hardware preflight reports, requires key tester/device/FPS/defect notes, and summarizes missing manual Deck/Steamworks evidence.
- Done: `scripts/summarize_package_validation.py` rejects blank package/runtime validation reports and requires native Linux or Proton launch evidence before that gate is ready.
- Done: `scripts/summarize_release_readiness.py` aggregates Steam Input, Deck preflight, package/runtime validation, playtest, and tuning readiness into final blocking markdown and checked-schema JSON release summaries.
- Done: generated packet reports are stamped with branch, commit, clean/dirty state, changed-path count, and a dirty-content fingerprint so hardware notes can be traced back to the exact tested prototype snapshot.
- Done: default `--game` gates raw editor shortcuts and persisted editor/help windows behind `--allow-editor-in-game`.
- Done: default `--game` defensively clears editor-only command flags before command processing, and the shell-contract smoke verifies Trial Dish actions still pass through.
- Done: local Windows Deck-sized performance smoke passed on this workstation: `avg_fps=60.27`, `avg_frame_ms=16.59`, `worst_frame_ms=20.10` for a 5 second `--deck-performance` run at 1280x800. This is local workstation evidence only; the 30 FPS gate still needs actual Steam Deck hardware.

## Known Verified Blockers

- Editor/dev flows still expose keyboard/mouse wording and assumptions; the default player shell gates these away.
- Save/config naming still uses ImGui text input in editor/dev flows, not Steam's on-screen keyboard.
- Controller navigation needs a real end-to-end Trial Dish pass on actual Deck hardware: start, feed, pause/resume, retry, win, restart, and paused exit.
- Game-mode nutrient gel has an automated controller-path smoke, but still needs a real Trial Dish completion pass on actual Deck hardware.
- The current Python/OpenGL stack needs native Linux and/or Proton validation on actual Deck hardware.
- Automated performance smoke passes locally, but the 30 FPS Verified gate still needs actual Deck hardware evidence.
- Steam Input still needs a real Steamworks import/configuration pass and official platform glyph rendering; current controller prompts are mapped to checked placeholder SVG glyph assets.
- Native 4K/60 MP4 export has local validation tooling, but still needs a
  package-local run, probe/full-decode, and performance/thermal notes on actual
  Steam Deck hardware before Deck video export is claimed.

## Manual Deck Test Pass

Run this on Steam Deck hardware or the closest Linux handheld target available.

Before manual testing, run:

```bash
python scripts/prepare_steam_deck_packet.py
```

Use the project Python interpreter for this command. On Windows, if `python`
resolves to another tool environment, run:

```bash
.venv/Scripts/python.exe scripts/prepare_steam_deck_packet.py --python .venv/Scripts/python.exe
```

For Linux package builds, `scripts/build_linux.sh` honors `PYTHON=/path/to/python`
so PyInstaller and generated package reports use the intended environment.

For a packet that also reruns local automated gates:

```bash
python scripts/prepare_steam_deck_packet.py --run-automated --with-visual --with-fed-results
```

These write `artifacts/steam_deck_packet_index.md`,
`artifacts/steam_deck_packet_manifest.json`,
`artifacts/steam_deck_packet_manifest.schema.json`,
`artifacts/trial_definitions.json`, `artifacts/trial_definitions.schema.json`,
`artifacts/steam_input_handoff.md`, `artifacts/trial_dish_playtest.md`,
`artifacts/trial_dish_playtest_summary.md`,
`artifacts/trial_dish_tuning_reference.md`, `artifacts/trial_dish_tuning_plan.md`,
`artifacts/package_validation.md`, `artifacts/package_validation_summary.md`,
and
`artifacts/steam_deck_preflight.md`, `artifacts/steam_deck_preflight_summary.md`,
and `artifacts/steam_deck_visual_evidence.md` with a shared build stamp, a hardware-pass
runbook, the Trial Dish data contract, the Steam Input import checklist, manual playtest sheet,
tuning-readiness summary, current tuning reference, post-playtest tuning plan,
package/runtime validation sheet,
automated smoke output, and the checklist below.
`scripts/prepare_steam_deck_packet.py` validates the generated packet manifest
before reporting success; rerun `python scripts/validate_steam_deck_packet_manifest.py`
after any manual edits to packet artifacts.
Packet refreshes preserve existing `trial_dish_playtest.md` and
`package_validation.md` manual evidence. Pass `--replace-manual-reports` only
to deliberately reset both to blank templates; direct report-writer calls
require `--force` to overwrite. A preserved report with mismatched build,
tester, or device metadata is retained but its summary is marked not-ready for
the current packet.

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
15. Build `dist/FluoddityNative/` on Deck/Linux with the explicit static
    `FLUODDITY_FFMPEG_BUNDLE` and `FLUODDITY_FFMPEG_LICENSE` inputs.
16. Run `VIDEO_SECONDS=1 WIDTH=3840 HEIGHT=2160 FPS=60 bash
    dist/FluoddityNative/run_export_video.sh`; confirm it uses package-local
    data and FFmpeg and writes an MP4 plus adjacent JSON report.
17. Probe and fully decode that MP4; confirm H.264, `yuv420p`, 3840x2160,
    60 FPS, BT.709 tags, faststart layout, requested frame count/duration, and
    no residual partial file.
18. Record Vulkan adapter, export duration, storage location, thermal behavior,
    and any throttling or defects as Deck evidence, not as a continuation of
    the Windows smoke result.

## Next Engineering Steps

1. Import the Steam Input manifest into Steamworks, create the default configuration, and replace placeholder glyph assets with the official Steam/Deck glyph rendering path.
2. Replace editor/dev ImGui text entry with controller-safe naming or Steamworks keyboard calls before exposing those flows in the shipped game.
3. Run the timed performance smoke on actual Steam Deck hardware and record the measured FPS/frame-time result.
4. Run a real controller-only Trial Dish completion pass on Steam Deck hardware.
5. Decide whether the Steam SKU is native Linux first or Windows-through-Proton first, then freeze packaging around that path.
