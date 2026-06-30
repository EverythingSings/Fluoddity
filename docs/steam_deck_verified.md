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
python main.py --steam-deck
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
- Done: first-pass controller camera and shortcuts:
  - Left stick: move camera
  - Right stick up/down or triggers: zoom
  - Right bumper: fast movement/zoom
  - A: pause/resume
  - B: reset particles
  - X: toggle sidebar
  - Y: randomize mutations
  - Select: toggle mouse mode
  - Start: reset controller camera
- Done: Linux PyInstaller build wrapper and Deck launch script generation.

## Known Verified Blockers

- Most editor-style flows still expose keyboard/mouse wording and assumptions.
- Save/config naming still uses ImGui text input, not Steam's on-screen keyboard.
- Controller navigation needs a real end-to-end pass through menus, presets, sliders, drawing, reset, pause, and exit on actual Deck hardware.
- The current Python/OpenGL stack needs native Linux and/or Proton validation on actual Deck hardware.
- There is no automated performance harness yet.
- Steam Input action manifest and controller glyph mapping are not present yet.

## Manual Deck Test Pass

Run this on Steam Deck hardware or the closest Linux handheld target available.

1. Launch from Steam with `./run_steam_deck.sh`.
2. Confirm the app starts directly, without console prompts, launchers, compatibility warnings, or setup dialogs.
3. Confirm the framebuffer is `1280x800` or the Deck-native fullscreen equivalent.
4. Confirm the default preset starts at 30 FPS or better for five minutes.
5. Confirm all visible text is readable at handheld distance.
6. Use only controls to pause/resume, reset, toggle sidebar, toggle mouse mode, randomize mutations, navigate UI, load a preset, and exit.
7. Confirm no required workflow needs touch, mouse, keyboard, or manual Steam controller configuration.
8. Confirm any text-entry workflow opens a controller-safe text input path or is nonessential for normal play.
9. Confirm suspend/resume does not leave the GL context black or frozen.
10. Confirm a clean restart preserves preferences without corrupting user data.

## Next Engineering Steps

1. Add Steam Input action manifests and route glyph labels through an input-mode abstraction.
2. Replace game-critical ImGui text entry with controller-safe naming or Steamworks keyboard calls.
3. Add a headless or timed smoke command that records average frame time for the Deck profile.
4. Decide whether the Steam SKU is native Linux first or Windows-through-Proton first, then freeze packaging around that path.
5. Build a game-mode shell around the engine so Verified criteria apply to the actual player experience, not just the editor UI.
