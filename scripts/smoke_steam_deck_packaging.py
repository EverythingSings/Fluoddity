"""Validate Steam Deck packaging contract without running a full PyInstaller build."""
from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_linux.sh"
MANIFEST = ROOT / "steam_input" / "steam_input_manifest.vdf"
GLYPH_MAP = ROOT / "steam_input" / "trial_prompt_glyph_map.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_svg_glyph(asset_path: Path) -> None:
    """Validate local placeholder glyphs are portable, self-contained SVGs."""
    try:
        root = ET.fromstring(asset_path.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise AssertionError(f"invalid SVG XML in {asset_path}: {exc}") from exc

    tag = root.tag.rsplit("}", 1)[-1]
    require(tag == "svg", f"glyph asset should have svg root: {asset_path}")
    require(root.attrib.get("width"), f"glyph asset missing width: {asset_path}")
    require(root.attrib.get("height"), f"glyph asset missing height: {asset_path}")
    require(root.attrib.get("viewBox"), f"glyph asset missing viewBox: {asset_path}")
    require(root.attrib.get("aria-label"), f"glyph asset missing aria-label: {asset_path}")

    forbidden_tags = {"script", "foreignObject", "image"}
    for node in root.iter():
        node_tag = node.tag.rsplit("}", 1)[-1]
        require(
            node_tag not in forbidden_tags,
            f"glyph asset should not contain <{node_tag}>: {asset_path}",
        )
        for attr_value in node.attrib.values():
            value = str(attr_value).strip().lower()
            require(
                not value.startswith(("http://", "https://", "file:")),
                f"glyph asset should not reference external resources: {asset_path}",
            )


def main() -> int:
    require(BUILD_SCRIPT.exists(), f"missing {BUILD_SCRIPT}")
    require(MANIFEST.exists(), f"missing {MANIFEST}")
    require(GLYPH_MAP.exists(), f"missing {GLYPH_MAP}")
    glyph_map = json.loads(GLYPH_MAP.read_text(encoding="utf-8"))
    missing_glyph_assets = []
    for action, entry in glyph_map.get("actions", {}).items():
        asset = entry.get("glyph_asset", "")
        if not asset:
            missing_glyph_assets.append(f"{action}:<empty>")
            continue
        asset_path = ROOT / asset
        if not asset_path.exists():
            missing_glyph_assets.append(f"{action}:{asset}")
            continue
        validate_svg_glyph(asset_path)
    require(
        not missing_glyph_assets,
        f"glyph map references missing files: {', '.join(missing_glyph_assets)}",
    )

    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    require("set -euo pipefail" in text, "build script should fail on packaging errors")
    require(
        "rm -rf dist/Fluoddity/steam_input" in text,
        "build script should clear stale packaged Steam Input artifacts",
    )
    require(
        "mkdir -p dist/Fluoddity/steam_input" in text,
        "build script should create packaged Steam Input directory",
    )
    require(
        "cp -R steam_input/* dist/Fluoddity/steam_input/" in text,
        "build script should copy Steam Input artifacts into the distribution",
    )
    require(
        "cat > dist/Fluoddity/run_steam_deck.sh" in text,
        "build script should generate Steam Deck launch wrapper",
    )
    require(
        "export FLUODDITY_STEAM_DECK=1" in text,
        "Steam Deck launch wrapper should set the Deck environment profile",
    )
    require(
        'exec ./Fluoddity --steam-deck --game "$@"' in text,
        "Steam Deck launch wrapper should run the app with --steam-deck --game",
    )
    require(
        "chmod +x dist/Fluoddity/run_steam_deck.sh" in text,
        "Steam Deck launch wrapper should be executable",
    )

    print("steam_deck_packaging_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
