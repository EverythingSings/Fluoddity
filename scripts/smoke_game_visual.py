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
    parser.add_argument("--elapsed", type=float, default=0.0, help="Seed trial elapsed time before capture.")
    parser.add_argument("--pause", action="store_true", help="Pause the selected trial before capture.")
    parser.add_argument("--feed", action="store_true", help="Apply smoke-only nutrient pulses before capture.")
    parser.add_argument("--resolve", action="store_true", help="Fast-forward the selected trial to a result state before capture.")
    parser.add_argument(
        "--transition-action",
        choices=("retry", "next", "restart", "sterilize"),
        default="",
        help="Apply a smoke-only Trial Dish transition before capture.",
    )
    parser.add_argument("--mutate", action="store_true", help="Apply one smoke-only Irradiate Strain request before capture.")
    parser.add_argument("--revert", action="store_true", help="Apply smoke-only Irradiate Strain, then Revert Strain before capture.")
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
        "--expect-zone-overlays",
        type=int,
        default=None,
        help="Fail unless exactly this many objective-zone overlays are reported at capture time.",
    )
    parser.add_argument(
        "--expect-hazard-overlay",
        action="store_true",
        help="Fail unless the capture reports a visible hazard overlay.",
    )
    parser.add_argument(
        "--expect-no-hazard-overlay",
        action="store_true",
        help="Fail unless the capture reports no visible hazard overlay.",
    )
    parser.add_argument(
        "--expect-rival-overlay",
        action="store_true",
        help="Fail unless the capture reports a visible rival overlay.",
    )
    parser.add_argument(
        "--expect-no-rival-overlay",
        action="store_true",
        help="Fail unless the capture reports no visible rival overlay.",
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
        "--expect-result-summary-not-contains",
        action="append",
        default=[],
        help="Fail if the normalized result summary contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-result-hint-contains",
        action="append",
        default=[],
        help="Fail unless the normalized result experiment hint contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-result-hint-not-contains",
        action="append",
        default=[],
        help="Fail if the normalized result experiment hint contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-result-next-contains",
        action="append",
        default=[],
        help="Fail unless the normalized result next-step line contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-result-next-not-contains",
        action="append",
        default=[],
        help="Fail if the normalized result next-step line contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-transition-contains",
        action="append",
        default=[],
        help="Fail unless the normalized briefing transition message contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-containment-contains",
        action="append",
        default=[],
        help="Fail unless the normalized containment readout contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-route-contains",
        action="append",
        default=[],
        help="Fail unless the normalized antibiotic route readout contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-specimen-contains",
        action="append",
        default=[],
        help="Fail unless the normalized Trial 1 specimen readout contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-mutation-contains",
        action="append",
        default=[],
        help="Fail unless the normalized mutation readout contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-guidance-contains",
        action="append",
        default=[],
        help="Fail unless the normalized station guidance message contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-feedback-contains",
        action="append",
        default=[],
        help="Fail unless the normalized transient lab feedback line contains this text. Repeatable.",
    )
    parser.add_argument(
        "--expect-timer-contains",
        action="append",
        default=[],
        help="Fail unless the normalized timer pressure readout contains this text. Repeatable.",
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
    expected_zone_overlays: int | None,
    expect_hazard_overlay: bool,
    expect_no_hazard_overlay: bool,
    expect_rival_overlay: bool,
    expect_no_rival_overlay: bool,
    min_progress: float | None,
    max_progress: float | None,
    expected_status: str | None,
    expected_input_scheme: str | None,
    expected_result_title: str | None,
    expected_result_readout: str | None,
    expected_result_summary_contains: list[str],
    expected_result_summary_not_contains: list[str],
    expected_result_hint_contains: list[str],
    expected_result_hint_not_contains: list[str],
    expected_result_next_contains: list[str],
    expected_result_next_not_contains: list[str],
    expected_transition_contains: list[str],
    expected_containment_contains: list[str],
    expected_route_contains: list[str],
    expected_specimen_contains: list[str],
    expected_mutation_contains: list[str],
    expected_guidance_contains: list[str],
    expected_feedback_contains: list[str],
    expected_timer_contains: list[str],
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
        and expected_zone_overlays is None
        and not expect_hazard_overlay
        and not expect_no_hazard_overlay
        and not expect_rival_overlay
        and not expect_no_rival_overlay
        and min_progress is None
        and max_progress is None
        and expected_status is None
        and expected_input_scheme is None
        and expected_result_title is None
        and expected_result_readout is None
        and not expected_result_summary_contains
        and not expected_result_summary_not_contains
        and not expected_result_hint_contains
        and not expected_result_hint_not_contains
        and not expected_result_next_contains
        and not expected_result_next_not_contains
        and not expected_transition_contains
        and not expected_containment_contains
        and not expected_route_contains
        and not expected_specimen_contains
        and not expected_mutation_contains
        and not expected_guidance_contains
        and not expected_feedback_contains
        and not expected_timer_contains
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

    zone_overlay_value = int(fields.get("zone_overlays", "0"))
    if expected_zone_overlays is not None and zone_overlay_value != expected_zone_overlays:
        raise AssertionError(
            f"expected {expected_zone_overlays} zone overlays, got {zone_overlay_value}"
        )

    hazard_overlay_value = fields.get("hazard_overlay", "0")
    if expect_hazard_overlay and hazard_overlay_value != "1":
        raise AssertionError("expected visible hazard overlay")
    if expect_no_hazard_overlay and hazard_overlay_value != "0":
        raise AssertionError("expected no visible hazard overlay")

    rival_overlay_value = fields.get("rival_overlay", "0")
    if expect_rival_overlay and rival_overlay_value != "1":
        raise AssertionError("expected visible rival overlay")
    if expect_no_rival_overlay and rival_overlay_value != "0":
        raise AssertionError("expected no visible rival overlay")

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
    for rejected_text in expected_result_summary_not_contains:
        rejected = normalize_smoke_text(rejected_text)
        if rejected in summary_value:
            raise AssertionError(
                f"expected result summary not to contain {rejected!r}, got {summary_value!r}"
            )

    hint_value = fields.get("result_hint", "-")
    for expected_text in expected_result_hint_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in hint_value:
            raise AssertionError(
                f"expected result hint to contain {expected!r}, got {hint_value!r}"
            )
    for rejected_text in expected_result_hint_not_contains:
        rejected = normalize_smoke_text(rejected_text)
        if rejected in hint_value:
            raise AssertionError(
                f"expected result hint not to contain {rejected!r}, got {hint_value!r}"
            )

    next_value = fields.get("result_next", "-")
    for expected_text in expected_result_next_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in next_value:
            raise AssertionError(
                f"expected result next step to contain {expected!r}, got {next_value!r}"
            )
    for rejected_text in expected_result_next_not_contains:
        rejected = normalize_smoke_text(rejected_text)
        if rejected in next_value:
            raise AssertionError(
                f"expected result next step not to contain {rejected!r}, got {next_value!r}"
            )

    transition_value = fields.get("transition", "-")
    for expected_text in expected_transition_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in transition_value:
            raise AssertionError(
                f"expected transition message to contain {expected!r}, got {transition_value!r}"
            )

    containment_value = fields.get("containment", "-")
    for expected_text in expected_containment_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in containment_value:
            raise AssertionError(
                f"expected containment readout to contain {expected!r}, got {containment_value!r}"
            )

    route_value = fields.get("route", "-")
    for expected_text in expected_route_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in route_value:
            raise AssertionError(
                f"expected route readout to contain {expected!r}, got {route_value!r}"
            )

    specimen_value = fields.get("specimen", "-")
    for expected_text in expected_specimen_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in specimen_value:
            raise AssertionError(
                f"expected specimen readout to contain {expected!r}, got {specimen_value!r}"
            )

    mutation_value = fields.get("mutation", "-")
    for expected_text in expected_mutation_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in mutation_value:
            raise AssertionError(
                f"expected mutation readout to contain {expected!r}, got {mutation_value!r}"
            )

    guidance_value = fields.get("guidance", "-")
    for expected_text in expected_guidance_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in guidance_value:
            raise AssertionError(
                f"expected guidance to contain {expected!r}, got {guidance_value!r}"
            )

    feedback_value = fields.get("feedback", "-")
    for expected_text in expected_feedback_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in feedback_value:
            raise AssertionError(
                f"expected feedback to contain {expected!r}, got {feedback_value!r}"
            )

    timer_value = fields.get("timer", "-")
    for expected_text in expected_timer_contains:
        expected = normalize_smoke_text(expected_text)
        if expected not in timer_value:
            raise AssertionError(
                f"expected timer readout to contain {expected!r}, got {timer_value!r}"
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
        f"zone_overlays={zone_overlay_value} "
        f"hazard_overlay={hazard_overlay_value} "
        f"rival_overlay={rival_overlay_value} "
        f"progress={progress_value:.3f} "
        f"paused={paused_value} "
        f"input_scheme={input_scheme_value} "
        f"cursor={cursor_value} cursor_draw={cursor_draw_value} "
        f"result_title={fields.get('result_title', '-')} "
        f"result_readout={fields.get('result_readout', '-')} "
        f"result_hint={fields.get('result_hint', '-')} "
        f"result_next={fields.get('result_next', '-')} "
        f"transition={fields.get('transition', '-')} "
        f"specimen={specimen_value} "
        f"route={route_value} "
        f"mutation={mutation_value} "
        f"guidance={guidance_value} "
        f"feedback={feedback_value} "
        f"timer={timer_value} "
        f"containment={containment_value} "
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
        elif args.transition_action:
            state_name = f"{args.transition_action}_transition"
        elif args.revert:
            state_name = "reverted"
        elif args.mutate:
            state_name = "mutated"
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
    if args.elapsed > 0.0:
        cmd.extend(["--visual-smoke-elapsed", str(args.elapsed)])
    if args.pause:
        cmd.append("--visual-smoke-pause")
    if args.feed:
        cmd.append("--visual-smoke-feed")
    if args.resolve:
        cmd.append("--visual-smoke-resolve")
    if args.transition_action:
        cmd.extend(["--visual-smoke-transition-action", args.transition_action])
    if args.mutate:
        cmd.append("--visual-smoke-mutate")
    if args.revert:
        cmd.append("--visual-smoke-revert")
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
        args.expect_zone_overlays,
        args.expect_hazard_overlay,
        args.expect_no_hazard_overlay,
        args.expect_rival_overlay,
        args.expect_no_rival_overlay,
        args.expect_progress_min,
        args.expect_progress_max,
        args.expect_status,
        args.expect_input_scheme,
        args.expect_result_title,
        args.expect_result_readout,
        args.expect_result_summary_contains,
        args.expect_result_summary_not_contains,
        args.expect_result_hint_contains,
        args.expect_result_hint_not_contains,
        args.expect_result_next_contains,
        args.expect_result_next_not_contains,
        args.expect_transition_contains,
        args.expect_containment_contains,
        args.expect_route_contains,
        args.expect_specimen_contains,
        args.expect_mutation_contains,
        args.expect_guidance_contains,
        args.expect_feedback_contains,
        args.expect_timer_contains,
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
