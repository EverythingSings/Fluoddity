"""Attach to and finalize the already-running Optix-Redo master render."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess

from probe_optix_redo_candidates import wait_for_recording
from render_optix_redo_final import FPS, FRAMES, HEIGHT, WIDTH, WINNER
from search_optix_redo_fine import CALIBRATED_STYLE


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    output_dir = repo / "artifacts" / "optix-redo-search"
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "mitosis-orb-optix-redo-5min"
    source = wait_for_recording(prefix, 0.0, timeout=900.0)
    destination = output_dir / "mitosis-orb-optix-redo-5min-720p60.mp4"
    shutil.copy2(source, destination)

    base_config = repo / "physics_configs" / "Advanced" / f"{WINNER.config}.json"
    shutil.copy2(base_config, output_dir / "mitosis-orb-base-config.json")
    sim_overrides = {
        "num_cohorts": WINNER.cohorts,
        "MUTATION_SCALE": WINNER.mutation,
        "rule_seed": WINNER.seed,
        "initial_conditions": WINNER.initialization,
        "GRAVITY_FORCE": WINNER.gravity_force,
        "GRAVITY_STRAFE": WINNER.gravity_strafe,
    }
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
    optix_geometry = {
        "use_curves": True,
        "curve_length": WINNER.curve_length,
        "curve_r0": WINNER.curve_r0,
        "curve_r1": WINNER.curve_r1,
        "sdf_enabled": WINNER.dish,
    }
    camera = {"fov": 42.0, "orbit_rate": 2.0 * math.pi / FRAMES}
    controller = {"pos": [0.0, 0.10, -3.55], "yaw": 0.0, "pitch": -0.045}
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_name,width,height,avg_frame_rate,nb_frames",
         "-of", "json", str(destination)],
        check=True, capture_output=True, text=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
        cwd=repo,
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
            "expected_frames": FRAMES,
            "expected_fps": FPS,
            "expected_width": WIDTH,
            "expected_height": HEIGHT,
            "ffprobe": json.loads(probe.stdout),
        },
    }
    manifest_path = output_dir / "mitosis-orb-config-and-render.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(destination, flush=True)
    print(manifest_path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
