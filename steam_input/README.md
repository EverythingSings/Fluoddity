# Steam Input Artifacts

This folder holds the current local Steam Input contract for the Trial Dish prototype.

- `steam_input_manifest.vdf`: action sets and actions intended for Steamworks import.
- `trial_prompt_glyph_map.json`: mapping from Trial Dish prompt action ids to fallback controller labels and local placeholder glyph assets.
- `glyphs/*.svg`: checked placeholder glyphs used by local packaging and HUD smoke tests.

Run `python scripts/write_steam_input_handoff.py` to generate `artifacts/steam_input_handoff.md`, which lists the recommended `TrialDish` default bindings for the Steamworks import pass.

These files are not the final Steamworks setup. The local tests only prove that prompt action ids, fallback labels, glyph metadata, packaged files, HUD display text, and the import handoff stay aligned. A real Steamworks import, default configuration, and official Steam/Deck glyph rendering pass are still required before release packaging.
