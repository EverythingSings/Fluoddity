"""Render the selected Optix-Redo configuration as a five-minute master."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import time

from probe_optix_redo_candidates import wait_for_recording
from search_optix_redo import command
from search_optix_redo_fine import CALIBRATED_STYLE, CANDIDATES


WINNER = next(candidate for candidate in CANDIDATES if candidate.label == "mitosis-orb")
FRAMES = 18_000
FPS = 60
WIDTH = 1280
HEIGHT = 720


def main() -> int:
    output_dir = Path(__file__).resolve().parents[1] / "artifacts" / "optix-redo-search"
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "mitosis-orb-optix-redo-5min"

    preferences = {
        **CALIBRATED_STYLE,
        "rendering": {
            **CALIBRATED_STYLE["rendering"],
            "renderer": 1,
            "entity_count": 1_000_000,
            "canvas_resolution": 196,
            "rt_mode": 0,
            "speedmult": 1,
            "motion_blur": False,
            "capture_spp": 1,
            "render_resolution_scale": 1.0,
        },
        "recording": {
            "max_frames": FRAMES,
            "motion_blur_samples": 1,
            "recording_motion_blur": False,
            "recording_blur_quality": 1,
            "supersample_k": 1,
            "filename_prefix": prefix,
            "video_end_frame": 0,
        },
    }
    sim_overrides = {
        "num_cohorts": WINNER.cohorts,
        "MUTATION_SCALE": WINNER.mutation,
        "rule_seed": WINNER.seed,
        "initial_conditions": WINNER.initialization,
        "GRAVITY_FORCE": WINNER.gravity_force,
        "GRAVITY_STRAFE": WINNER.gravity_strafe,
    }
    optix_geometry = {
        "use_curves": True,
        "curve_length": WINNER.curve_length,
        "curve_r0": WINNER.curve_r0,
        "curve_r1": WINNER.curve_r1,
        "sdf_enabled": WINNER.dish,
    }
    camera = {"fov": 42.0, "orbit_rate": 2.0 * math.pi / FRAMES}
    controller = {"pos": [0.0, 0.10, -3.55], "yaw": 0.0, "pitch": -0.045}

    command(
        settings={"preferences": preferences},
        actions=[
            {"name": "window_size", "width": WIDTH, "height": HEIGHT, "hidden": True},
            {"name": "load_config", "filename": WINNER.config, "category": "Advanced"},
            "vsync_off",
            "pause",
        ],
        label="load final mitosis orb",
    )
    time.sleep(0.4)
    command(
        settings={
            "sim": sim_overrides,
            "preferences": {"optix": optix_geometry},
            "camera": camera,
            "controller": controller,
        },
        actions=["reset", "resume"],
        label="settle final mitosis orb",
    )
    time.sleep(5.0)
    command(actions=["pause"], label="pause before final render")
    time.sleep(0.25)
    started_at = time.time() - 0.1
    command(actions=["record_start"], label="arm final five minute render")
    time.sleep(0.25)
    command(actions=["resume"], label="render final five minute video")
    source = wait_for_recording(prefix, started_at, timeout=1_200.0)

    destination = output_dir / "mitosis-orb-optix-redo-5min-720p60.mp4"
    shutil.copy2(source, destination)
    base_config = Path(__file__).resolve().parents[1] / "physics_configs" / "Advanced" / f"{WINNER.config}.json"
    shutil.copy2(base_config, output_dir / "mitosis-orb-base-config.json")

    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(destination)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1],
    ).stdout.strip()
    manifest = {
        "name": "Mitosis Orb",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_commit": commit,
        "candidate": asdict(WINNER),
        "base_config": str(base_config),
        "sim_overrides": sim_overrides,
        "preferences": preferences,
        "optix_geometry": optix_geometry,
        "camera": camera,
        "controller": controller,
        "video": {
            "path": str(destination),
            "source": str(source),
            "width": WIDTH,
            "height": HEIGHT,
            "fps": FPS,
            "frames": FRAMES,
            "duration_seconds": float(duration),
        },
    }
    manifest_path = output_dir / "mitosis-orb-config-and-render.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(destination, flush=True)
    print(manifest_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
