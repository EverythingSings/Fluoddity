"""Fine-search the strongest Optix-Redo families with calibrated lighting."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import time

from search_optix_redo import command, make_contact_sheet, wait_for_screenshot


@dataclass(frozen=True)
class FineCandidate:
    label: str
    config: str
    cohorts: int
    mutation: float
    seed: float
    initialization: int
    gravity_force: float
    gravity_strafe: float
    curve_length: float
    curve_r0: float
    curve_r1: float
    dish: bool


CANDIDATES = (
    FineCandidate("worm-bloom-soft", "00Worms2", 16, 0.010, 0.23, 0, 0.08, 0.10, 1.8, 0.38, 0.040, True),
    FineCandidate("worm-bloom-orbit", "00Worms2", 24, 0.016, 0.47, 2, 0.12, 0.14, 2.4, 0.28, 0.025, False),
    FineCandidate("dragon-grove", "00Dragon", 12, 0.006, 0.73, 0, 0.00, 0.00, 1.3, 0.50, 0.070, True),
    FineCandidate("dragon-orbit", "00Dragon", 20, 0.012, 0.31, 2, 0.10, -0.08, 2.0, 0.32, 0.030, False),
    FineCandidate("shroom-cathedral", "00Shroom2", 12, 0.006, 0.37, 3, -0.05, 0.04, 1.0, 0.55, 0.100, True),
    FineCandidate("shroom-nebula", "00Shroom2", 18, 0.012, 0.61, 1, -0.08, 0.08, 1.4, 0.42, 0.060, False),
    FineCandidate("coral-crown-lit", "00Coral4", 20, 0.010, 0.83, 2, 0.07, 0.05, 1.6, 0.44, 0.050, True),
    FineCandidate("web-orchid", "00Web", 20, 0.010, 0.29, 3, -0.03, 0.12, 2.2, 0.26, 0.020, False),
    FineCandidate("mitosis-orb", "00Mitosis", 16, 0.010, 0.43, 2, 0.04, 0.08, 1.0, 0.58, 0.090, False),
    FineCandidate("jelly-canopy", "00JellySeaweed", 20, 0.010, 0.19, 3, -0.04, 0.10, 2.0, 0.30, 0.030, True),
    FineCandidate("tendril-cage", "00Tenta", 20, 0.009, 0.59, 2, 0.05, -0.11, 2.2, 0.30, 0.026, False),
    FineCandidate("sunflower-filament", "00SunflowerBowl", 14, 0.007, 0.53, 0, 0.07, -0.04, 1.5, 0.46, 0.055, True),
)


CALIBRATED_STYLE = {
    "rendering": {
        "brightness": 0.75,
        "tonemap_softness": 1.7,
    },
    "optix": {
        "ambient": 0.22,
        "albedo_saturation": 1.05,
        "albedo_brightness": 1.05,
        "ao_enabled": True,
        "ao_num_rays": 1,
        "ao_radius": 0.35,
    },
    "lighting": {
        "light_direction": [-0.35, 0.8, -0.45],
        "light_intensity": 6.5,
        "sky_color_top": [0.08, 0.12, 0.20],
        "sky_color_bottom": [0.01, 0.015, 0.025],
        "sky_intensity": 0.45,
    },
    "bloom": {
        "enabled": True,
        "threshold": 0.65,
        "intensity": 0.06,
        "radius": 1.0,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settle", type=float, default=6.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    command(settings={"preferences": CALIBRATED_STYLE}, label="apply calibrated lighting")
    results: list[dict] = []
    for index, candidate in enumerate(CANDIDATES, 1):
        print(f"\n[{index}/{len(CANDIDATES)}] {candidate.label}", flush=True)
        command(
            actions=[
                {"name": "load_config", "filename": candidate.config,
                 "category": "Advanced"},
                "pause",
            ],
            label=f"load fine {candidate.label}",
        )
        time.sleep(0.25)
        command(
            settings={
                "sim": {
                    "num_cohorts": candidate.cohorts,
                    "MUTATION_SCALE": candidate.mutation,
                    "rule_seed": candidate.seed,
                    "initial_conditions": candidate.initialization,
                    "GRAVITY_FORCE": candidate.gravity_force,
                    "GRAVITY_STRAFE": candidate.gravity_strafe,
                },
                "preferences": {
                    "optix": {
                        "use_curves": True,
                        "curve_length": candidate.curve_length,
                        "curve_r0": candidate.curve_r0,
                        "curve_r1": candidate.curve_r1,
                        "sdf_enabled": candidate.dish,
                    }
                },
                "camera": {"fov": 42.0, "orbit_rate": 0.0},
                "controller": {"pos": [0.0, 0.10, -3.4], "yaw": 0.0, "pitch": -0.045},
            },
            actions=["reset", "resume"],
            label=f"evolve fine {candidate.label}",
        )
        time.sleep(args.settle)
        command(actions=["pause"], label=f"pause fine {candidate.label}")
        time.sleep(0.2)
        started_at = time.time() - 0.1
        command(
            actions=[{"name": "screenshot", "label": candidate.label,
                      "note": "Optix-Redo fine parameter search"}],
            label=f"capture fine {candidate.label}",
        )
        source = wait_for_screenshot(candidate.label, started_at)
        destination = args.output / f"{candidate.label}.png"
        shutil.copy2(source, destination)
        results.append({"candidate": asdict(candidate), "image": str(destination),
                        "source": str(source)})
        print(destination, flush=True)

    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    contact_sheet = args.output / "contact-sheet.png"
    make_contact_sheet(results, contact_sheet)
    print(f"\nIndex: {index_path}")
    print(f"Contact sheet: {contact_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
