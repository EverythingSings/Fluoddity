"""Render Reef dynamics as a continuous translucent mycelial density volume."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import time

from search_optix_configs import command, wait_for_recording


VOLUME_STYLE = {
    "tracer_mode": True,
    "tracer_sdf_enabled": True,
    "tracer_colored_extinction": False,
    "tracer_extinction_rgb": [0.86, 0.96, 1.08],
    "tracer_albedo_saturation": 0.11,
    "tracer_albedo_brightness": 0.92,
    "tracer_density_scale": 0.00022,
    "tracer_hg_g": 0.58,
    "tracer_emission_strength": 0.012,
    "tracer_sun_direction": [-0.42, 0.82, -0.38],
    "tracer_sun_color": [0.82, 0.91, 1.0],
    "tracer_sun_intensity": 3.2,
    "tracer_sky_color": [0.025, 0.035, 0.055],
    "tracer_sky_intensity": 0.35,
    "tracer_exposure": 1.35,
    "tracer_max_bounces": 5,
    "tracer_firefly_clamp": True,
    "tracer_firefly_clamp_max": 6.0,
    "tracer_resolution_scale": 1.0,
    "tracer_density_resolution_log2": 8,
    "tracer_color_resolution_log2": 8,
    "tracer_majorant_resolution_log2": 6,
    "tracer_sun_sampling": True,
    "tracer_photosphere": False,
    "recording_motion_blur": False,
    "motion_blur_samples": 1,
    "supersample_k": 1,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--long", action="store_true", help="Render 2,400 frames for a two-minute conformed master")
    parser.add_argument("--segment", type=int, choices=range(4), help="Render one restartable 600-frame long-form segment")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Documents" / "Fluoddity" / "Review" / "Final",
        help="directory for rendered MP4s and optional probe PNGs",
    )
    args = parser.parse_args()
    if args.probe:
        name, frames, samples = "mycelial-gel-probe", 1, 40
        width, height = 1280, 720
    elif args.long or args.segment is not None:
        segment_suffix = f"-segment-{args.segment + 1}" if args.segment is not None else ""
        name, frames, samples = f"mycelial-gel-evolution-source{segment_suffix}", (600 if args.segment is not None else 2400), 12
        width, height = 1280, 720
    else:
        name, frames, samples = "mycelial-gel", 240, 24
        width, height = 1920, 1080

    command(
        settings={"preferences": {**VOLUME_STYLE, "tracer_mode": False}},
        actions=[
            {"name": "window_size", "width": width, "height": height, "hidden": True},
            {"name": "load_config", "filename": "Reef", "category": "Advanced"},
            "pause",
        ],
        label="load mycelial gel parent rule",
    )
    command(
        settings={
            "sim": {
                "initial_conditions": 0,
                "num_cohorts": 25,
                "MUTATION_SCALE": 0.012,
                "rule_seed": 0.73,
                "color_by_cohort": False,
                "hue_sensitivity": 0.0,
            }
        },
        actions=["reset", "resume"],
        label="grow gel source density",
    )
    settle_seconds = 22.0 + (30.0 * args.segment if args.segment is not None else 0.0)
    time.sleep(settle_seconds)

    command(
        settings={
            "preferences": {
                **VOLUME_STYLE,
                "tracer_num_samples": samples,
                "max_frames": frames,
                "filename_prefix": name,
                "motion_blur_samples": 3 if (args.long or args.segment is not None) else 1,
            },
            "camera": {"fov": 43.0, "orbit_rate": 0.0},
            "controller": {"pos": [0.0, 0.12, -3.2], "yaw": 0.0, "pitch": -0.055},
        },
        actions=["pause"],
        label="prepare continuous density render",
    )
    time.sleep(1.0)
    started_at = time.time() - 1.0
    command(actions=["record_start"], label="arm mycelial gel")
    time.sleep(0.5)
    command(actions=["resume"], label="render mycelial gel")
    source = wait_for_recording(name, started_at, timeout=600.0)

    destination_dir = args.output
    destination_dir.mkdir(parents=True, exist_ok=True)
    if args.probe:
        destination = destination_dir / "mycelial-gel-probe.mp4"
    elif args.segment is not None:
        destination = destination_dir / f"mycelial-gel-evolution-segment-{args.segment + 1}-720p60.mp4"
    elif args.long:
        destination = destination_dir / "mycelial-gel-evolution-source-720p60.mp4"
    else:
        destination = destination_dir / "mycelial-gel-1080p60.mp4"
    shutil.copy2(source, destination)
    if args.probe:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(destination), "-frames:v", "1", str(destination.with_suffix(".png"))],
            check=True,
        )
    print(destination, flush=True)
    command(actions=["pause"], label="mycelial gel render complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
