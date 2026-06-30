"""Write a Steamworks Steam Input handoff checklist from local artifacts."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from build_metadata import current_build_id


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "steam_input" / "steam_input_manifest.vdf"
GLYPH_MAP = ROOT / "steam_input" / "trial_prompt_glyph_map.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "steam_input_handoff.md"

RECOMMENDED_BINDINGS = [
    ("Right Stick", "AimNutrientGel", "Aim Nutrient Gel"),
    ("R2", "ApplyNutrientGel", "Apply Nutrient Gel"),
    ("A", "StartExperiment", "Start Experiment"),
    ("A", "NextTrial", "Next Trial"),
    ("B", "RetryTrial", "Retry Trial"),
    ("Menu", "PauseExperiment", "Pause / Resume"),
    ("View", "ExitExperiment", "Exit from paused Trial Dish"),
    ("Y", "IrradiateStrain", "Irradiate Strain"),
    ("L1", "RevertStrain", "Revert Strain"),
    ("Left Stick", "PanDish", "Pan Dish"),
]

REQUIRED_TRIAL_ACTIONS = {
    action for _, action, _ in RECOMMENDED_BINDINGS
} | {"ToggleLabPanel", "SterilizeDish"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the Steam Input import handoff report.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown output path.")
    parser.add_argument("--build-id", default="", help="Optional build label to stamp into the report.")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate the handoff sources without writing the report.",
    )
    return parser.parse_args()


def quoted_values(text: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', text))


def localization_pairs(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    in_localization = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == '"localization"':
            in_localization = True
            continue
        if not in_localization:
            continue
        match = re.match(r'"([^"]+)"\s+"([^"]*)"', stripped)
        if match:
            pairs[match.group(1)] = match.group(2)
    return pairs


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_sources() -> tuple[str, dict, set[str], dict[str, str]]:
    require(MANIFEST.exists(), f"missing {MANIFEST}")
    require(GLYPH_MAP.exists(), f"missing {GLYPH_MAP}")
    manifest_text = MANIFEST.read_text(encoding="utf-8")
    glyph_map = json.loads(GLYPH_MAP.read_text(encoding="utf-8"))
    values = quoted_values(manifest_text)
    localizations = localization_pairs(manifest_text)

    require("TrialDish" in values, "manifest missing TrialDish action set")
    require("Editor" in values, "manifest missing Editor action set")
    missing_actions = sorted(REQUIRED_TRIAL_ACTIONS - values)
    require(not missing_actions, f"manifest missing TrialDish actions: {', '.join(missing_actions)}")

    glyph_actions = set(glyph_map.get("actions", {}).keys())
    missing_glyphs = sorted((REQUIRED_TRIAL_ACTIONS - {"PanDish", "ToggleLabPanel", "SterilizeDish"}) - glyph_actions)
    require(not missing_glyphs, f"glyph map missing Trial Dish prompt actions: {', '.join(missing_glyphs)}")

    for action in glyph_actions:
        require(action in values, f"glyph map action missing from manifest: {action}")
        entry = glyph_map["actions"][action]
        require(entry.get("fallback_label"), f"glyph map action missing fallback_label: {action}")
        require(entry.get("glyph_asset"), f"glyph map action missing glyph_asset: {action}")

    missing_localizations = []
    for _, action, _ in RECOMMENDED_BINDINGS:
        token = f"Action_{action}"
        if token not in localizations:
            missing_localizations.append(token)
    require(not missing_localizations, f"manifest missing localization tokens: {', '.join(missing_localizations)}")
    return manifest_text, glyph_map, values, localizations


def write_report(output: Path, glyph_map: dict, localizations: dict[str, str], build_id: str) -> Path:
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")
    glyph_actions = glyph_map.get("actions", {})

    lines = [
        "# Steam Input Handoff",
        "",
        f"- Generated: {now}",
        f"- Build: {build_id or current_build_id(ROOT)}",
        f"- Manifest: `{MANIFEST.relative_to(ROOT).as_posix()}`",
        f"- Glyph map: `{GLYPH_MAP.relative_to(ROOT).as_posix()}`",
        "- Status: local contract only; Steamworks import and default configuration still required.",
        "",
        "## Import Steps",
        "",
        "1. Import `steam_input/steam_input_manifest.vdf` into Steamworks.",
        "2. Create a default Steam Deck configuration for the `TrialDish` action set.",
        "3. Bind the actions below using the recommended Deck controls.",
        "4. Confirm Steam launches the game through `run_steam_deck.sh` or the final packaged launch target.",
        "5. Confirm prompts render with official Steam/Deck glyphs, or with an approved shipped fallback.",
        "6. Run `python scripts/steam_deck_preflight.py --with-visual --with-fed-results` before the hardware pass.",
        "",
        "## Recommended TrialDish Default Bindings",
        "",
        "| Deck control | Action | Localized title | HUD fallback | Placeholder glyph |",
        "| --- | --- | --- | --- | --- |",
    ]

    for deck_control, action, purpose in RECOMMENDED_BINDINGS:
        entry = glyph_actions.get(action, {})
        fallback = entry.get("fallback_label", deck_control)
        glyph = entry.get("glyph_asset", "-")
        localized = localizations.get(f"Action_{action}", purpose)
        lines.append(f"| {deck_control} | `{action}` | {localized} | {fallback} | `{glyph}` |")

    lines.extend(
        [
            "",
            "## Manual Verification",
            "",
            "- [ ] Steam Input selects the `TrialDish` action set for the default player shell.",
            "- [ ] No normal Trial Dish path requires manual remapping.",
            "- [ ] A starts Trial 1 and advances successful result screens.",
            "- [ ] Right Stick aims Nutrient Gel and R2 applies it.",
            "- [ ] Menu pauses and resumes without advancing trial time while paused.",
            "- [ ] View exits only from the paused player shell.",
            "- [ ] B retries the current trial.",
            "- [ ] Y and L1 operate Trial 3 mutation tools when available.",
            "- [ ] Prompt glyphs match the active control device and never fall back to keyboard-only labels during controller play.",
            "",
            "## Known External Gates",
            "",
            "- [ ] Steamworks manifest import.",
            "- [ ] Steam Deck default configuration creation.",
            "- [ ] Official Steam/Deck glyph rendering integration.",
            "- [ ] Actual Steam Deck controller-only playthrough.",
            "",
        ]
    )

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    _, glyph_map, _, localizations = load_sources()
    args = parse_args()
    if args.check_only:
        print(f"steam_input_handoff_check=ok bindings={len(RECOMMENDED_BINDINGS)}")
        return 0
    output = write_report(args.output, glyph_map, localizations, args.build_id)
    print(f"steam_input_handoff_report={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
