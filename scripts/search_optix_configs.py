"""Probe saved physics configs through the headless stream operator.

Each config evolves using the fast OptiX renderer, then records one offline
path-traced frame and extracts it as a PNG for visual comparison.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from stream_operator import operator_root, queue_command


DEFAULT_CONFIGS = (
    "LavaLamp2",
    "Ooze",
    "Cilia",
    "Strings",
    "Plasma",
    "Reef",
    "Waterbear",
    "Whirlpools",
)


def safe_name(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")


def command(*, settings: dict | None = None, actions: list | None = None, label: str = "") -> None:
    payload: dict = {"version": 1}
    if settings:
        payload["set"] = settings
    if actions:
        payload["actions"] = actions
    if label:
        payload["label"] = label
    receipt = queue_command(payload, wait_seconds=20)
    if not receipt or receipt.get("status") != "applied":
        raise RuntimeError(f"operator rejected {label or payload}: {receipt}")


def wait_for_recording(prefix: str, started_at: float, timeout: float = 45.0) -> Path:
    videos = Path.home() / "Documents" / "Fluoddity" / "Videos"
    status_path = operator_root() / "status.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        matches = [
            path for path in videos.glob(f"{prefix}-*.mp4")
            if path.stat().st_mtime >= started_at
        ]
        if matches:
            latest = max(matches, key=lambda path: path.stat().st_mtime)
            if not status.get("recording") and latest.stat().st_size > 0:
                # One-frame probes can begin and end between one-second status
                # heartbeats. ffprobe is the authoritative test that the MP4's
                # closing moov atom has been written.
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(latest)],
                    capture_output=True,
                    text=True,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    return latest
        time.sleep(0.25)
    raise TimeoutError(f"recording for {prefix!r} did not finish")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="*", default=DEFAULT_CONFIGS)
    parser.add_argument("--category", default="Advanced", choices=("Core", "Advanced", "Custom"))
    parser.add_argument("--settle", type=float, default=6.0, help="seconds to evolve each config")
    parser.add_argument("--spp", type=int, default=4, help="samples per path-traced probe")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Documents" / "Fluoddity" / "Review" / "Candidates",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    results = []
    for config_name in args.configs:
        slug = safe_name(config_name)
        prefix = f"candidate-{slug}"
        print(f"\n=== {config_name}: evolving for {args.settle:g}s ===", flush=True)
        command(
            settings={
                "preferences": {
                    "three_d_rt_mode": 0,
                    "three_d_optix_sdf_enabled": True,
                    "three_d_optix_use_curves": True,
                    "three_d_optix_curve_length": 0.8,
                    "three_d_optix_curve_r0": 1.6,
                    "three_d_optix_curve_r1": 0.2,
                    "three_d_optix_sky_color_top": [0.08, 0.1, 0.16],
                    "three_d_optix_sky_color_bottom": [0.015, 0.02, 0.03],
                    "three_d_optix_light_intensity": 3.5,
                    "three_d_optix_albedo_saturation": 0.95,
                    "three_d_optix_albedo_brightness": 1.15,
                }
            },
            actions=[
                {"name": "window_size", "width": 1280, "height": 720, "hidden": True},
                {"name": "load_config", "filename": config_name, "category": args.category},
                "reset",
                "resume",
            ],
            label=f"search settle {config_name}",
        )
        time.sleep(args.settle)

        # Mode switching and recording activation are intentionally split across
        # frames. Starting both in one operator command can capture the last
        # raster frame before the path-tracing branch becomes active.
        command(
            settings={
                "preferences": {
                    "three_d_rt_mode": 1,
                    "three_d_rt_preview_spp": args.spp,
                    "max_frames": 1,
                    "filename_prefix": prefix,
                },
                "controller": {"pos": [0.0, 0.15, -3.4], "yaw": 0.0, "pitch": -0.06},
            },
            actions=["pause"],
            label=f"search probe {config_name}",
        )
        time.sleep(1.0)
        started_at = time.time() - 1.0
        command(actions=["record_start"], label=f"arm probe {config_name}")
        time.sleep(0.5)
        command(actions=["resume"], label=f"run probe {config_name}")
        video = wait_for_recording(prefix, started_at)
        image = args.output / f"{slug}.png"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-frames:v", "1", str(image)],
            check=True,
        )
        print(f"{config_name}: {image}", flush=True)
        results.append({"config": config_name, "video": str(video), "image": str(image)})

    index = args.output / "index.json"
    index.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nIndex: {index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
