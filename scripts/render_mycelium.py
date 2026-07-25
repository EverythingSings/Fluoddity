"""Render a pale, branching Reef-derived colony as a mycelial network."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import time

from search_optix_configs import command, wait_for_recording


STYLE = {
    "three_d_optix_sdf_enabled": True,
    "three_d_optix_resolution_scale": 1.0,
    "three_d_optix_capture_width": 1920,
    "three_d_optix_capture_height": 1080,
    "three_d_optix_use_curves": True,
    "three_d_optix_curve_length": 1.45,
    "three_d_optix_curve_r0": 0.92,
    "three_d_optix_curve_r1": 0.055,
    "three_d_optix_sphere_size_jitter": 0.18,
    "three_d_optix_sky_color_top": [0.018, 0.025, 0.038],
    "three_d_optix_sky_color_bottom": [0.004, 0.006, 0.009],
    "three_d_optix_light_direction": [-0.38, 0.86, -0.32],
    "three_d_optix_light_color": [0.82, 0.91, 1.0],
    "three_d_optix_light_intensity": 4.2,
    "three_d_pt_denoise_enabled": True,
    "three_d_pt_max_bounces": 4,
    "three_d_pt_global_material": 1,
    "three_d_optix_albedo_saturation": 0.07,
    "three_d_optix_albedo_brightness": 1.0,
    "recording_motion_blur": False,
    "motion_blur_samples": 1,
    "supersample_k": 1,
    "brightness": 0.82,
    "tonemap_softness": 2.4,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Documents" / "Fluoddity" / "Review" / "Final",
        help="directory for the rendered MP4 and optional probe PNG",
    )
    args = parser.parse_args()
    name = "mycelial-network-probe" if args.probe else "mycelial-network"
    frames = 1 if args.probe else 360
    spp = 20 if args.probe else 16

    command(
        settings={"preferences": {**STYLE, "three_d_rt_mode": 0}},
        actions=[
            {"name": "window_size", "width": 1920, "height": 1080, "hidden": True},
            {"name": "load_config", "filename": "Reef", "category": "Advanced"},
            "pause",
        ],
        label="load mycelial parent rule",
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
        label="grow mycelial network",
    )
    time.sleep(22.0)

    command(
        settings={
            "preferences": {
                **STYLE,
                "three_d_rt_mode": 1,
                "three_d_rt_preview_spp": spp,
                "max_frames": frames,
                "filename_prefix": name,
            },
            "camera": {"fov": 43.0, "orbit_rate": 0.00035 if not args.probe else 0.0},
            "controller": {"pos": [0.0, 0.12, -3.2], "yaw": 0.0, "pitch": -0.055},
        },
        actions=["pause"],
        label="prepare mycelial render",
    )
    time.sleep(1.0)
    started_at = time.time() - 1.0
    command(actions=["record_start"], label="arm mycelial render")
    time.sleep(0.5)
    command(actions=["resume"], label="render mycelial network")
    source = wait_for_recording(name, started_at, timeout=420.0)

    destination_dir = args.output
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / ("mycelial-network-probe.mp4" if args.probe else "mycelial-network-1080p60.mp4")
    shutil.copy2(source, destination)
    if args.probe:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(destination), "-frames:v", "1", str(destination.with_suffix(".png"))],
            check=True,
        )
    print(destination, flush=True)
    command(actions=["pause"], label="mycelial render complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
