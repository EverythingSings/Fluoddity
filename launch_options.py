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
    game: bool = False
    allow_editor_in_game: bool = False
    ui_scale: float = 1.0
    deck_performance: bool = False
    visual_smoke_output: str | None = None
    visual_smoke_frame: int = 8
    visual_smoke_trial: int = 1
    visual_smoke_start: bool = False
    visual_smoke_pause: bool = False
    visual_smoke_feed: bool = False
    visual_smoke_resolve: bool = False
    visual_smoke_controller_cursor: bool = False
    visual_smoke_controller_feed: bool = False
    performance_smoke_seconds: float = 0.0


def editor_tools_enabled(options: LaunchOptions) -> bool:
    """Whether raw editor panels should be reachable from the current launch profile."""
    return not options.game or options.allow_editor_in_game


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
    parser.add_argument(
        "--game",
        action="store_true",
        help="Start in the prototype Trial Dish game shell instead of the raw editor.",
    )
    parser.add_argument(
        "--allow-editor-in-game",
        action="store_true",
        help="Expose raw editor panels inside --game. Intended for development, not the player shell.",
    )
    parser.add_argument(
        "--visual-smoke-output",
        default=None,
        help="Save a framebuffer PNG after startup and exit. Intended for automated visual smoke checks.",
    )
    parser.add_argument(
        "--visual-smoke-frame",
        type=int,
        default=8,
        help="Frame number to capture when --visual-smoke-output is set.",
    )
    parser.add_argument(
        "--visual-smoke-trial",
        type=int,
        default=1,
        choices=(1, 2, 3),
        help="Trial Dish number to load before a visual smoke capture.",
    )
    parser.add_argument(
        "--visual-smoke-start",
        action="store_true",
        help="Start the selected Trial Dish automatically before a visual smoke capture.",
    )
    parser.add_argument(
        "--visual-smoke-pause",
        action="store_true",
        help="Pause the selected Trial Dish after smoke startup. Requires --visual-smoke-start.",
    )
    parser.add_argument(
        "--visual-smoke-feed",
        action="store_true",
        help="Apply smoke-only nutrient pulses across objective zones before capture.",
    )
    parser.add_argument(
        "--visual-smoke-resolve",
        action="store_true",
        help="Fast-forward the selected Trial Dish to its result state before a visual smoke capture.",
    )
    parser.add_argument(
        "--visual-smoke-controller-cursor",
        action="store_true",
        help="Show a smoke-only controller lab cursor before capture.",
    )
    parser.add_argument(
        "--visual-smoke-controller-feed",
        action="store_true",
        help="Hold smoke-only controller Nutrient Gel input before capture.",
    )
    parser.add_argument(
        "--performance-smoke-seconds",
        type=float,
        default=0.0,
        help="Run for this many seconds, print frame timing metrics, and exit.",
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
        game=args.game,
        allow_editor_in_game=args.allow_editor_in_game,
        ui_scale=ui_scale,
        deck_performance=steam_deck or args.deck_performance,
        visual_smoke_output=args.visual_smoke_output,
        visual_smoke_frame=max(1, args.visual_smoke_frame),
        visual_smoke_trial=args.visual_smoke_trial,
        visual_smoke_start=args.visual_smoke_start,
        visual_smoke_pause=args.visual_smoke_pause,
        visual_smoke_feed=args.visual_smoke_feed,
        visual_smoke_resolve=args.visual_smoke_resolve,
        visual_smoke_controller_cursor=args.visual_smoke_controller_cursor,
        visual_smoke_controller_feed=args.visual_smoke_controller_feed,
        performance_smoke_seconds=max(0.0, args.performance_smoke_seconds),
    )
