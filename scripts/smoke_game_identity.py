"""Smoke-check the player-facing game identity boundary."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_SUBTITLE, GAME_TITLE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    require(ENGINE_NAME == "Fluoddity", "engine/package identity should stay explicit during V1")
    require(GAME_TITLE == "Xenoculture: Trial Dish", "player-facing V1 title should be stable")
    require("petri-dish" in GAME_SUBTITLE, "subtitle should preserve the alien petri-dish theme")

    main_text = (ROOT / "main.py").read_text(encoding="utf-8")
    require(
        "GAME_TITLE if self.launch_options.game else ENGINE_NAME" in main_text,
        "window creation should use game title only for game shell",
    )
    require(
        "glfw.set_window_title(self.window, GAME_TITLE)" in main_text,
        "game-mode configuration should keep the player title",
    )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    require(GAME_TITLE in readme, "README should name the current game shell")

    prototype_doc = (ROOT / "docs" / "game_v1_prototype.md").read_text(encoding="utf-8")
    require(GAME_TITLE in prototype_doc, "V1 prototype doc should name the current game shell")

    for script_name in [
        "scripts/prepare_steam_deck_packet.py",
        "scripts/write_steam_input_handoff.py",
        "scripts/write_trial_dish_playtest_report.py",
        "scripts/steam_deck_preflight.py",
    ]:
        text = (ROOT / script_name).read_text(encoding="utf-8")
        require("from services.game_identity import ENGINE_NAME, GAME_TITLE" in text, f"{script_name} should stamp game identity")

    print(f"game_identity_smoke=ok title={GAME_TITLE!r} engine={ENGINE_NAME!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
