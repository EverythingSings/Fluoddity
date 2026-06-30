"""Startup options for desktop and Steam Deck launch profiles."""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


DEFAULT_WINDOW_SIZE = (800, 600)
STEAM_DECK_SIZE = (1280, 800)


@dataclass(frozen=True)
class LaunchOptions:
    width: int = DEFAULT_WINDOW_SIZE[0]
    height: int = DEFAULT_WINDOW_SIZE[1]
    fullscreen: bool = False
    steam_deck: bool = False
    ui_scale: float = 1.0
    deck_performance: bool = False


def parse_launch_options(argv: list[str] | None = None) -> LaunchOptions:
    """Parse command-line and environment launch options."""
    parser = argparse.ArgumentParser(description="Fluoddity")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--windowed", action="store_true")
    parser.add_argument("--ui-scale", type=float, default=None)
    parser.add_argument(
        "--steam-deck",
        action="store_true",
        help="Use Steam Deck defaults: 1280x800 fullscreen, larger UI, and lighter simulation defaults.",
    )
    parser.add_argument(
        "--deck-performance",
        action="store_true",
        help="Apply the Steam Deck performance preset without forcing fullscreen/window size.",
    )
    args = parser.parse_args(argv)

    steam_deck_env = os.environ.get("FLUODDITY_STEAM_DECK", "").strip().lower()
    steam_deck = args.steam_deck or steam_deck_env in {"1", "true", "yes", "on"}

    if steam_deck:
        default_width, default_height = STEAM_DECK_SIZE
        default_fullscreen = True
        default_ui_scale = 1.35
    else:
        default_width, default_height = DEFAULT_WINDOW_SIZE
        default_fullscreen = False
        default_ui_scale = 1.0

    width = max(args.width or default_width, 320)
    height = max(args.height or default_height, 240)
    fullscreen = default_fullscreen or args.fullscreen
    if args.windowed:
        fullscreen = False

    ui_scale = args.ui_scale if args.ui_scale is not None else default_ui_scale
    ui_scale = max(0.75, min(ui_scale, 3.0))

    return LaunchOptions(
        width=width,
        height=height,
        fullscreen=fullscreen,
        steam_deck=steam_deck,
        ui_scale=ui_scale,
        deck_performance=steam_deck or args.deck_performance,
    )
