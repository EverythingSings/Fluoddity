"""Render the strongest organism-like Reef colony variants at native 1080p."""

from __future__ import annotations

from pathlib import Path
import shutil
import time

from search_optix_configs import command, wait_for_recording


COLONIES = (
    ("reef-colony-jellies", 0.42),
    ("reef-colony-tendrils", 0.73),
)


STYLE = {
    "three_d_optix_sdf_enabled": True,
    "three_d_optix_resolution_scale": 1.0,
    "three_d_optix_capture_width": 1920,
    "three_d_optix_capture_height": 1080,
    "three_d_optix_use_curves": True,
    "three_d_optix_curve_length": 0.95,
    "three_d_optix_curve_r0": 2.3,
    "three_d_optix_curve_r1": 0.18,
    "three_d_optix_sky_color_top": [0.08, 0.1, 0.16],
    "three_d_optix_sky_color_bottom": [0.015, 0.02, 0.03],
    "three_d_optix_light_direction": [0.35, 0.8, -0.45],
    "three_d_optix_light_color": [1.0, 0.94, 0.86],
    "three_d_optix_light_intensity": 3.5,
    "three_d_pt_denoise_enabled": True,
    "three_d_pt_max_bounces": 4,
    "three_d_pt_global_material": 1,
    "three_d_optix_albedo_saturation": 1.05,
    "three_d_optix_albedo_brightness": 1.2,
    "recording_motion_blur": False,
    "motion_blur_samples": 1,
    "supersample_k": 1,
    "brightness": 0.9,
    "tonemap_softness": 2.1,
}


def main() -> int:
    output = Path.home() / "Documents" / "Fluoddity" / "Review" / "Final"
    output.mkdir(parents=True, exist_ok=True)

    for name, seed in COLONIES:
        command(
            settings={"preferences": {**STYLE, "three_d_rt_mode": 0}},
            actions=[
                {"name": "window_size", "width": 1920, "height": 1080, "hidden": True},
                {"name": "load_config", "filename": "Reef", "category": "Advanced"},
                "pause",
            ],
            label=f"load {name}",
        )
        command(
            settings={
                "sim": {
                    "initial_conditions": 0,
                    "num_cohorts": 16,
                    "MUTATION_SCALE": 0.02,
                    "rule_seed": seed,
                }
            },
            actions=["reset", "resume"],
            label=f"settle {name}",
        )
        time.sleep(15.0)

        command(
            settings={
                "preferences": {
                    **STYLE,
                    "three_d_rt_mode": 1,
                    "three_d_rt_preview_spp": 16,
                    "max_frames": 300,
                    "filename_prefix": name,
                },
                "camera": {"fov": 45.0, "orbit_rate": 0.0},
                "controller": {"pos": [0.0, 0.12, -3.2], "yaw": 0.0, "pitch": -0.055},
            },
            actions=["pause"],
            label=f"prepare {name}",
        )
        time.sleep(1.0)
        started_at = time.time() - 1.0
        command(actions=["record_start"], label=f"arm {name}")
        time.sleep(0.5)
        command(actions=["resume"], label=f"record {name}")
        source = wait_for_recording(name, started_at, timeout=300.0)
        destination = output / f"{name}-1920x1080-60fps.mp4"
        shutil.copy2(source, destination)
        print(destination, flush=True)

    command(actions=["pause"], label="reef colony renders complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
