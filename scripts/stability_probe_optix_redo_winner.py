"""Fast-forward the selected config through a five-minute simulation horizon."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import time

from optix_redo_operator import operator_root
from search_optix_redo import command, make_contact_sheet, wait_for_screenshot
from search_optix_redo_fine import CALIBRATED_STYLE, CANDIDATES


STABILITY_CANDIDATES = {
    candidate.label: candidate for candidate in CANDIDATES
    if candidate.label in {
        "worm-bloom-orbit", "shroom-nebula", "mitosis-orb", "dragon-orbit"
    }
}


def current_frame() -> int:
    status = json.loads((operator_root() / "status.json").read_text(encoding="utf-8"))
    return int(status["frame_count"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--speedmult", type=int, default=20)
    parser.add_argument("--candidate", choices=sorted(STABILITY_CANDIDATES),
                        default="worm-bloom-orbit")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    winner = STABILITY_CANDIDATES[args.candidate]

    command(
        settings={"preferences": {
            **CALIBRATED_STYLE,
            "rendering": {
                **CALIBRATED_STYLE["rendering"],
                "renderer": 1,
                "rt_mode": 0,
                "speedmult": args.speedmult,
                "motion_blur": False,
                "capture_spp": 1,
                "render_resolution_scale": 1.0,
            },
            "recording": {
                "max_frames": 1,
                "motion_blur_samples": 1,
                "recording_motion_blur": False,
                "supersample_k": 1,
            },
        }},
        actions=[
            {"name": "window_size", "width": 1280, "height": 720, "hidden": True},
            {"name": "load_config", "filename": winner.config, "category": "Advanced"},
            "pause",
        ],
        label="load winner stability probe",
    )
    time.sleep(0.3)
    command(
        settings={
            "sim": {
                "num_cohorts": winner.cohorts,
                "MUTATION_SCALE": winner.mutation,
                "rule_seed": winner.seed,
                "initial_conditions": winner.initialization,
                "GRAVITY_FORCE": winner.gravity_force,
                "GRAVITY_STRAFE": winner.gravity_strafe,
            },
            "preferences": {"optix": {
                "use_curves": True,
                "curve_length": winner.curve_length,
                "curve_r0": winner.curve_r0,
                "curve_r1": winner.curve_r1,
                "sdf_enabled": winner.dish,
            }},
            "camera": {"fov": 42.0, "orbit_rate": 0.00035},
            "controller": {"pos": [0.0, 0.10, -3.4], "yaw": 0.0, "pitch": -0.045},
        },
        actions=["reset", "resume"],
        label="run winner stability probe",
    )

    results = []
    for target in (1000, 4500, 9000, 13500, 18000):
        while current_frame() < target:
            time.sleep(0.1)
        command(actions=["pause"], label=f"pause stability {target}")
        time.sleep(0.2)
        actual = current_frame()
        label = f"{winner.label}-step-{actual:05d}"
        started_at = time.time() - 0.1
        command(actions=[{"name": "screenshot", "label": label}],
                label=f"capture stability {actual}")
        source = wait_for_screenshot(label, started_at)
        destination = args.output / f"{label}.png"
        shutil.copy2(source, destination)
        results.append({"candidate": {**asdict(winner), "target": target,
                                       "actual": actual},
                        "image": str(destination), "source": str(source)})
        if target < 18000:
            command(actions=["resume"], label=f"resume stability {target}")

    index = args.output / "index.json"
    index.write_text(json.dumps(results, indent=2), encoding="utf-8")
    sheet = args.output / "stability-contact-sheet.png"
    make_contact_sheet(results, sheet, columns=5)
    print(f"Index: {index}")
    print(f"Stability sheet: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
