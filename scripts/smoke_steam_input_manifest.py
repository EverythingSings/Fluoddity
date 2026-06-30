"""Validate the initial Steam Input action manifest artifact."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.trial_prompts import STEAM_INPUT_ACTIONS, TRIAL_PROMPT_GLYPHS

MANIFEST = ROOT / "steam_input" / "steam_input_manifest.vdf"
GLYPH_MAP = ROOT / "steam_input" / "trial_prompt_glyph_map.json"

REQUIRED_ACTION_SETS = {
    "TrialDish",
    "Editor",
}

REQUIRED_ACTIONS = {
    "AimNutrientGel",
    "ApplyNutrientGel",
    "StartExperiment",
    "PauseExperiment",
    "ExitExperiment",
    "RetryTrial",
    "NextTrial",
    "IrradiateStrain",
    "RevertStrain",
    "PanDish",
    "PanView",
    "ZoomView",
}

REQUIRED_INPUT_MODES = {
    "absolute_mouse",
    "joystick_move",
}


def quoted_values(text: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', text))


def localization_keys(text: str) -> set[str]:
    keys: set[str] = set()
    in_localization = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == '"localization"':
            in_localization = True
            continue
        if not in_localization:
            continue
        match = re.match(r'"([^"]+)"\s+"[^"]*"', stripped)
        if match:
            keys.add(match.group(1))
    return keys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    require(MANIFEST.exists(), f"missing {MANIFEST}")
    require(GLYPH_MAP.exists(), f"missing {GLYPH_MAP}")
    text = MANIFEST.read_text(encoding="utf-8")
    values = quoted_values(text)

    require('"Action Manifest"' in text, "missing Action Manifest root")
    require('"actions"' in text, "missing actions section")
    require('"localization"' in text, "missing localization section")
    require('"english"' in text, "missing english localization section")
    require('"configurations"' in text, "missing configurations section")

    missing_sets = sorted(REQUIRED_ACTION_SETS - values)
    require(not missing_sets, f"missing action sets: {', '.join(missing_sets)}")

    missing_actions = sorted(REQUIRED_ACTIONS - values)
    require(not missing_actions, f"missing actions: {', '.join(missing_actions)}")

    missing_modes = sorted(REQUIRED_INPUT_MODES - values)
    require(not missing_modes, f"missing input modes: {', '.join(missing_modes)}")

    referenced_tokens = {
        token.removeprefix("#")
        for token in values
        if token.startswith("#Action_") or token.startswith("#Set_")
    }
    localized = localization_keys(text)
    missing_localizations = sorted(referenced_tokens - localized)
    require(
        not missing_localizations,
        f"missing localization tokens: {', '.join(missing_localizations)}",
    )

    glyph_map = json.loads(GLYPH_MAP.read_text(encoding="utf-8"))
    require(glyph_map.get("schema_version") == 1, "glyph map should declare schema_version 1")
    mapped_actions = set(glyph_map.get("actions", {}).keys())
    prompt_actions = set(STEAM_INPUT_ACTIONS.values())

    missing_prompt_actions = sorted(prompt_actions - mapped_actions)
    require(
        not missing_prompt_actions,
        f"glyph map missing prompt actions: {', '.join(missing_prompt_actions)}",
    )

    unknown_mapped_actions = sorted(mapped_actions - values)
    require(
        not unknown_mapped_actions,
        f"glyph map references actions missing from manifest: {', '.join(unknown_mapped_actions)}",
    )

    bad_entries = [
        action
        for action, entry in glyph_map.get("actions", {}).items()
        if not entry.get("fallback_label") or not entry.get("glyph_asset")
    ]
    require(
        not bad_entries,
        f"glyph map entries need fallback_label and glyph_asset: {', '.join(sorted(bad_entries))}",
    )

    unloaded_actions = sorted(mapped_actions - set(TRIAL_PROMPT_GLYPHS.keys()))
    require(
        not unloaded_actions,
        f"glyph map entries were not loaded by prompt service: {', '.join(unloaded_actions)}",
    )

    bad_loaded_entries = [
        action
        for action, glyph in TRIAL_PROMPT_GLYPHS.items()
        if glyph.fallback_label != glyph_map["actions"][action]["fallback_label"]
        or glyph.glyph_asset != glyph_map["actions"][action]["glyph_asset"]
    ]
    require(
        not bad_loaded_entries,
        f"loaded glyph metadata does not match source map: {', '.join(sorted(bad_loaded_entries))}",
    )

    print(
        "steam_input_manifest_smoke=ok "
        f"sets={len(REQUIRED_ACTION_SETS)} "
        f"required_actions={len(REQUIRED_ACTIONS)} "
        f"localized_tokens={len(referenced_tokens)} "
        f"glyph_actions={len(mapped_actions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
