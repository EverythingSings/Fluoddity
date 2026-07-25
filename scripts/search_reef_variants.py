"""Search Reef-derived colony layouts for distinct organism-like bodies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from search_optix_configs import command, operator_root, wait_for_recording


COARSE_VARIANTS = (
    ("reef-grid-9-subtle", 0, 9, 0.002, 0.42),
    ("reef-grid-16-subtle", 0, 16, 0.002, 0.42),
    ("reef-grid-16-varied", 0, 16, 0.02, 0.42),
    ("reef-grid-25-varied", 0, 25, 0.02, 0.42),
    ("reef-grid-36-varied", 0, 36, 0.02, 0.42),
    ("reef-grid-16-wild", 0, 16, 0.05, 0.42),
    ("reef-random-16", 1, 16, 0.02, 0.42),
    ("reef-sphere-16", 2, 16, 0.02, 0.42),
)

FINE_VARIANTS = (
    ("reef-colony-12-m010", 0, 12, 0.010, 0.42),
    ("reef-colony-12-m020", 0, 12, 0.020, 0.42),
    ("reef-colony-16-m010", 0, 16, 0.010, 0.42),
    ("reef-colony-16-m015", 0, 16, 0.015, 0.42),
    ("reef-colony-16-m025", 0, 16, 0.025, 0.42),
    ("reef-colony-20-m015", 0, 20, 0.015, 0.42),
    ("reef-colony-20-m025", 0, 20, 0.025, 0.42),
    ("reef-colony-16-seed73", 0, 16, 0.020, 0.73),
)


STYLE = {
    "three_d_rt_mode": 0,
    "three_d_optix_sdf_enabled": True,
    "three_d_optix_use_curves": True,
    "three_d_optix_curve_length": 0.95,
    "three_d_optix_curve_r0": 2.3,
    "three_d_optix_curve_r1": 0.18,
    "three_d_optix_sky_color_top": [0.08, 0.1, 0.16],
    "three_d_optix_sky_color_bottom": [0.015, 0.02, 0.03],
    "three_d_optix_light_intensity": 3.5,
    "three_d_optix_albedo_saturation": 1.05,
    "three_d_optix_albedo_brightness": 1.2,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", choices=("coarse", "fine"), default="coarse")
    args = parser.parse_args()
    variants = COARSE_VARIANTS if args.round == "coarse" else FINE_VARIANTS
    folder = "ReefVariants" if args.round == "coarse" else "ReefVariantsFine"
    output = Path.home() / "Documents" / "Fluoddity" / "Review" / folder
    output.mkdir(parents=True, exist_ok=True)
    results = []

    for name, initial_conditions, cohorts, mutation, seed in variants:
        print(f"\n=== {name} ===", flush=True)
        command(
            settings={"preferences": STYLE},
            actions=[
                {"name": "window_size", "width": 1280, "height": 720, "hidden": True},
                {"name": "load_config", "filename": "Reef", "category": "Advanced"},
                "pause",
            ],
            label=f"load {name}",
        )
        command(
            settings={
                "sim": {
                    "initial_conditions": initial_conditions,
                    "num_cohorts": cohorts,
                    "MUTATION_SCALE": mutation,
                    "rule_seed": seed,
                }
            },
            actions=["reset", "resume"],
            label=f"evolve {name}",
        )
        time.sleep(15.0)

        command(
            settings={
                "preferences": {
                    **STYLE,
                    "three_d_rt_mode": 1,
                    "three_d_rt_preview_spp": 12,
                    "max_frames": 1,
                    "filename_prefix": name,
                },
                "controller": {"pos": [0.0, 0.15, -3.4], "yaw": 0.0, "pitch": -0.06},
            },
            actions=["pause"],
            label=f"prepare {name}",
        )
        time.sleep(1.0)
        started_at = time.time() - 1.0
        command(actions=["record_start"], label=f"arm {name}")
        time.sleep(0.5)
        command(actions=["resume"], label=f"capture {name}")
        video = wait_for_recording(name, started_at)
        image = output / f"{name}.png"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-frames:v", "1", str(image)],
            check=True,
        )
        results.append({"name": name, "image": str(image), "video": str(video)})

    (output / "index.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    command(actions=["pause"], label="reef variant search complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
