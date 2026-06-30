"""Capture and validate a game-mode framebuffer.

This is still a smoke check, not a human visual QA pass. It proves that the
game-mode renderer produces a nonblank frame with the Trial Dish UI path active.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture a game-mode visual smoke frame.")
    parser.add_argument("--width", type=int, default=800, help="Launch window width.")
    parser.add_argument("--height", type=int, default=600, help="Launch window height.")
    parser.add_argument("--frame", type=int, default=10, help="Rendered frame to capture.")
    parser.add_argument("--trial", type=int, default=1, choices=(1, 2, 3), help="Trial Dish number to capture.")
    parser.add_argument("--start", action="store_true", help="Start the selected trial before capture.")
    parser.add_argument("--pause", action="store_true", help="Pause the selected trial before capture.")
    parser.add_argument("--feed", action="store_true", help="Apply smoke-only nutrient pulses before capture.")
    parser.add_argument("--resolve", action="store_true", help="Fast-forward the selected trial to a result state before capture.")
    parser.add_argument(
        "--controller-cursor",
        action="store_true",
        help="Show a smoke-only controller lab cursor before capture.",
    )
    parser.add_argument(
        "--controller-feed",
        action="store_true",
        help="Hold smoke-only controller Nutrient Gel input before capture.",
    )
    parser.add_argument(
        "--expect-active-zones",
        type=int,
        default=None,
        help="Fail unless at least this many objective zones are active at capture time.",
    )
    parser.add_argument(
        "--expect-rival-zones",
        type=int,
        default=None,
        help="Fail unless at least this many zones are rival-controlled at capture time.",
    )
    parser.add_argument(
        "--expect-progress-min",
        type=float,
        default=None,
        help="Fail unless trial progress is at least this value at capture time.",
    )
    parser.add_argument(
        "--expect-progress-max",
        type=float,
        default=None,
        help="Fail unless trial progress is at most this value at capture time.",
    )
    parser.add_argument(
        "--expect-status",
        default=None,
        help="Fail unless the trial status exactly matches this value.",
    )
    parser.add_argument(
        "--expect-input-scheme",
        choices=("hybrid", "controller", "keyboard_mouse"),
        default=None,
        help="Fail unless the runtime prompt input scheme matches this value.",
    )
    parser.add_argument(
        "--expect-result-title",
        default=None,
        help="Fail unless the normalized result title matches this text.",
    )
    parser.add_argument(
        "--expect-result-readout",
        default=None,
        help="Fail unless the normalized result readout/grade matches this text.",
    )
    parser.add_argument(
        "--expect-result-summary-contains",
        action="append",
        default=[],
        help="Fail unless the normalized result summary contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-prompt-contains",
        action="append",
        default=[],
        help="Fail unless the normalized prompt list contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-display-prompt-contains",
        action="append",
        default=[],
        help="Fail unless the normalized HUD display prompt list contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-glyph-contains",
        action="append",
        default=[],
        help="Fail unless the normalized active prompt glyph list contains this path. Repeatable.",
    )
    parser.add_argument(
        "--expect-paused",
        action="store_true",
        help="Fail unless the trial reports paused=1.",
    )
    parser.add_argument(
        "--expect-controller-cursor",
        action="store_true",
        help="Fail unless the capture reports an active controller cursor.",
    )
    parser.add_argument(
        "--expect-no-controller-cursor",
        action="store_true",
        help="Fail unless the capture reports no active controller cursor.",
    )
    parser.add_argument(
        "--expect-controller-draw",
        action="store_true",
        help="Fail unless the capture reports controller Nutrient Gel input held.",
    )
    parser.add_argument(
        "--expect-no-controller-draw",
        action="store_true",
        help="Fail unless the capture reports no controller Nutrient Gel input held.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="PNG path for the captured frame.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to launch main.py.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Additional argument to pass through to main.py. Repeat for multiple args.",
    )
    return parser.parse_args()


def assert_nonblank_image(path: Path) -> None:
    with Image.open(path) as img:
        pixels = np.asarray(img.convert("RGB"), dtype=np.uint8)

    if pixels.size == 0:
        raise AssertionError("captured image is empty")

    channel_std = float(pixels.std())
    mean_luma = float(pixels.mean())
    unique_sample = np.unique(pixels.reshape(-1, 3)[:: max(1, pixels.shape[0])], axis=0)

    if mean_luma < 2.0:
        raise AssertionError(f"captured image is too dark: mean={mean_luma:0.2f}")
    if channel_std < 2.0:
        raise AssertionError(f"captured image lacks variation: std={channel_std:0.2f}")
    if len(unique_sample) < 8:
        raise AssertionError(f"captured image has too few sampled colors: {len(unique_sample)}")

    print(
        "visual_smoke=nonblank "
        f"path={path} mean={mean_luma:0.2f} std={channel_std:0.2f} colors={len(unique_sample)}"
    )


def assert_controller_reticle_image(path: Path, drawing: bool) -> None:
    """Verify the smoke controller cursor is visibly rendered near screen center."""
    with Image.open(path) as img:
        pixels = np.asarray(img.convert("RGB"), dtype=np.uint8)

    height, width = pixels.shape[:2]
    if width <= 0 or height <= 0:
        raise AssertionError("captured image is empty")

    cx = width // 2
    cy = height // 2
    crop = pixels[
        max(0, cy - 28):min(height, cy + 29),
        max(0, cx - 28):min(width, cx + 29),
    ].astype(np.int16)
    if crop.size == 0:
        raise AssertionError("controller reticle crop is empty")

    red = crop[:, :, 0]
    green = crop[:, :, 1]
    blue = crop[:, :, 2]
    if drawing:
        reticle_mask = (green > 120) & (green > red + 35) & (green > blue + 10)
    else:
        reticle_mask = (blue > 120) & (blue > red + 20) & (blue >= green)

    reticle_pixels = int(reticle_mask.sum())
    if reticle_pixels < 24:
        raise AssertionError(
            f"controller reticle is not visibly rendered near center: pixels={reticle_pixels}"
        )

    print(f"visual_smoke_controller_reticle=ok pixels={reticle_pixels}")


def parse_trial_state(stdout: str) -> dict[str, str]:
    match = re.search(r"visual_smoke_trial_state=(.+)", stdout)
    if not match:
        raise AssertionError("missing visual_smoke_trial_state output")

    fields = {}
    for part in match.group(1).split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key] = value
    return fields


def assert_trial_state(
    stdout: str,
    min_active_zones: int | None,
    min_rival_zones: int | None,
    min_progress: float | None,
    max_progress: float | None,
    expected_status: str | None,
    expected_input_scheme: str | None,
    expected_result_title: str | None,
    expected_result_readout: str | None,
    expected_result_summary_contains: list[str],
    expected_prompt_contains: list[str],
    expected_display_prompt_contains: list[str],
    expected_glyph_contains: list[str],
    expect_paused: bool,
    expect_controller_cursor: bool,
    expect_no_controller_cursor: bool,
    expect_controller_draw: bool,
    expect_no_controller_draw: bool,
) -> None:
    if (
        min_active_zones is None
        and min_rival_zones is None
        and min_progress is None
        and max_progress is None
        and expected_status is None
        and expected_input_scheme is None
        and expected_result_title is None
        and expected_result_readout is None
        and not expected_result_summary_contains
        and not expected_prompt_contains
        and not expected_display_prompt_contains
        and not expected_glyph_contains
        and not expect_paused
        and not expect_controller_cursor
        and not expect_no_controller_cursor
        and not expect_controller_draw
        and not expect_no_controller_draw
    ):
        return

    fields = parse_trial_state(stdout)
    active_value = fields.get("active_zones", "0/0")
    if min_active_zones is not None:
        active_count = int(active_value.split("/", 1)[0])
        if active_count < min_active_zones:
            raise AssertionError(
                f"expected at least {min_active_zones} active zones, got {active_value}"
            )

    rival_value = fields.get("rival_zones", "0")
    if min_rival_zones is not None:
        rival_count = int(rival_value)
        if rival_count < min_rival_zones:
            raise AssertionError(
                f"expected at least {min_rival_zones} rival zones, got {rival_value}"
            )

    progress_value = float(fields.get("progress", "0"))
    if min_progress is not None and progress_value < min_progress:
        raise AssertionError(
            f"expected progress >= {min_progress:.3f}, got {progress_value:.3f}"
        )
    if max_progress is not None and progress_value > max_progress:
        raise AssertionError(
            f"expected progress <= {max_progress:.3f}, got {progress_value:.3f}"
        )

    status_value = fields.get("status", "unknown")
    if expected_status is not None and status_value != expected_status:
        raise AssertionError(
            f"expected status {expected_status!r}, got {status_value!r}"
        )

    input_scheme_value = fields.get("input_scheme", "unknown")
    if expected_input_scheme is not None and input_scheme_value != expected_input_scheme:
        raise AssertionError(
            f"expected input scheme {expected_input_scheme!r}, got {input_scheme_value!r}"
        )

    if expected_result_title is not None:
        title_value = fields.get("result_title", "-")
        expected = normalize_smoke_text(expected_result_title)
        if title_value != expected:
            raise AssertionError(
                f"expected result title {expected!r}, got {title_value!r}"
            )

    if expected_result_readout is not None:
        readout_value = fields.get("result_readout", "-")
        expected = normalize_smoke_text(expected_result_readout)
        if readout_value != expected:
            raise AssertionError(
                f"expected result readout {expected!r}, got {readout_value!r}"
            )

    summary_value = fields.get("result_summary", "-")
    for expected_text in expected_result_summary_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in summary_value:
            raise AssertionError(
                f"expected result summary to contain {expected!r}, got {summary_value!r}"
            )

    prompt_value = fields.get("prompts", "-")
    for expected_text in expected_prompt_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in prompt_value:
            raise AssertionError(
                f"expected prompts to contain {expected!r}, got {prompt_value!r}"
            )

    display_prompt_value = fields.get("display_prompts", "-")
    for expected_text in expected_display_prompt_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in display_prompt_value:
            raise AssertionError(
                f"expected display prompts to contain {expected!r}, got {display_prompt_value!r}"
            )

    glyph_value = fields.get("glyphs", "-")
    for expected_text in expected_glyph_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in glyph_value:
            raise AssertionError(
                f"expected glyphs to contain {expected!r}, got {glyph_value!r}"
            )

    paused_value = fields.get("paused", "0")
    if expect_paused and paused_value != "1":
        raise AssertionError("expected paused trial state")

    cursor_value = fields.get("cursor", "0")
    if expect_controller_cursor and cursor_value != "1":
        raise AssertionError("expected active controller cursor")
    if expect_no_controller_cursor and cursor_value != "0":
        raise AssertionError("expected no active controller cursor")

    cursor_draw_value = fields.get("cursor_draw", "0")
    if expect_controller_draw and cursor_draw_value != "1":
        raise AssertionError("expected controller draw input held")
    if expect_no_controller_draw and cursor_draw_value != "0":
        raise AssertionError("expected no controller draw input held")

    print(
        "visual_smoke_trial_assert=ok "
        f"active_zones={active_value} rival_zones={rival_value} status={status_value} "
        f"progress={progress_value:.3f} "
        f"paused={paused_value} "
        f"input_scheme={input_scheme_value} "
        f"cursor={cursor_value} cursor_draw={cursor_draw_value} "
        f"result_title={fields.get('result_title', '-')} "
        f"result_readout={fields.get('result_readout', '-')} "
        f"prompts={fields.get('prompts', '-')} "
        f"display_prompts={fields.get('display_prompts', '-')} "
        f"glyphs={fields.get('glyphs', '-')}"
    )


def normalize_smoke_text(text: str) -> str:
    return "_".join(str(text or "").strip().split()) or "-"


def main() -> int:
    args = parse_args()
    if args.output:
        output = Path(args.output)
    else:
        if args.pause:
            state_name = "paused"
        elif args.controller_cursor:
            state_name = "controller_feed" if args.controller_feed else "controller_cursor"
        elif args.resolve:
            state_name = "result"
        else:
            state_name = "running" if args.start else "briefing"
        output = ROOT / "artifacts" / "visual_smoke" / f"trial{args.trial}_{state_name}.png"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    cmd = [
        args.python,
        "main.py",
        "--game",
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--visual-smoke-output",
        str(output),
        "--visual-smoke-frame",
        str(max(1, args.frame)),
        "--visual-smoke-trial",
        str(args.trial),
        *args.extra_arg,
    ]
    if args.start:
        cmd.append("--visual-smoke-start")
    if args.pause:
        cmd.append("--visual-smoke-pause")
    if args.feed:
        cmd.append("--visual-smoke-feed")
    if args.resolve:
        cmd.append("--visual-smoke-resolve")
    if args.controller_cursor:
        cmd.append("--visual-smoke-controller-cursor")
    if args.controller_feed:
        cmd.append("--visual-smoke-controller-feed")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        creationflags=creationflags,
        timeout=30,
    )

    if proc.returncode != 0:
        print(f"visual_smoke=exited_{proc.returncode}")
        if proc.stdout:
            print("stdout:")
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("stderr:")
            print(proc.stderr.rstrip())
        return proc.returncode

    if not output.exists():
        print("visual_smoke=missing_output")
        if proc.stdout:
            print("stdout:")
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("stderr:")
            print(proc.stderr.rstrip())
        return 1

    assert_nonblank_image(output)
    if args.expect_controller_cursor:
        assert_controller_reticle_image(output, args.expect_controller_draw)
    assert_trial_state(
        proc.stdout,
        args.expect_active_zones,
        args.expect_rival_zones,
        args.expect_progress_min,
        args.expect_progress_max,
        args.expect_status,
        args.expect_input_scheme,
        args.expect_result_title,
        args.expect_result_readout,
        args.expect_result_summary_contains,
        args.expect_prompt_contains,
        args.expect_display_prompt_contains,
        args.expect_glyph_contains,
        args.expect_paused,
        args.expect_controller_cursor,
        args.expect_no_controller_cursor,
        args.expect_controller_draw,
        args.expect_no_controller_draw,
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print("stderr:")
        print(proc.stderr.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
