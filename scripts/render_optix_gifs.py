"""Render the selected OptiX material studies to MP4 masters and review GIFs."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import time

from search_optix_configs import command, wait_for_recording


STUDIES = (
    {
        "name": "reef-folded-matter",
        "config": "Reef",
        "settle": 15.0,
        "style": {
            "three_d_optix_use_curves": True,
            "three_d_optix_curve_length": 0.95,
            "three_d_optix_curve_r0": 2.3,
            "three_d_optix_curve_r1": 0.18,
            "three_d_pt_global_material": 1,
            "three_d_optix_albedo_saturation": 1.05,
            "three_d_optix_albedo_brightness": 1.2,
        },
    },
    {
        "name": "plasma-turbulent-volume",
        "config": "Plasma",
        "settle": 15.0,
        "style": {
            "three_d_optix_use_curves": True,
            "three_d_optix_curve_length": 1.25,
            "three_d_optix_curve_r0": 1.7,
            "three_d_optix_curve_r1": 0.08,
            "three_d_pt_global_material": 0,
            "three_d_optix_albedo_saturation": 1.15,
            "three_d_optix_albedo_brightness": 1.15,
        },
    },
    {
        "name": "whirlpools-purple-granules",
        "config": "Whirlpools",
        "settle": 15.0,
        "style": {
            "three_d_optix_use_curves": False,
            "three_d_optix_sphere_radius_scale": 4.8,
            "three_d_optix_sphere_size_jitter": 0.12,
            "three_d_pt_global_material": 1,
            "three_d_optix_albedo_saturation": 1.25,
            "three_d_optix_albedo_brightness": 1.15,
        },
    },
)

MAX_X_GIF_BYTES = 14_500_000
X_GIF_PROFILES = (
    # Descending quality. The encoder stops at the first profile below the
    # conservative 14.5 MB ceiling, leaving margin under X's 15 MB limit.
    (960, 540, 20, 192),
    (854, 480, 18, 160),
    (720, 405, 15, 128),
)


BASE_STYLE = {
    "three_d_optix_sdf_enabled": True,
    "three_d_optix_resolution_scale": 1.0,
    "three_d_optix_sky_color_top": [0.08, 0.1, 0.16],
    "three_d_optix_sky_color_bottom": [0.015, 0.02, 0.03],
    "three_d_optix_light_direction": [0.35, 0.8, -0.45],
    "three_d_optix_light_color": [1.0, 0.94, 0.86],
    "three_d_optix_light_intensity": 3.5,
    "three_d_optix_ambient": 0.12,
    "three_d_optix_shadows_enabled": True,
    "three_d_pt_denoise_enabled": True,
    "three_d_pt_max_bounces": 4,
    "recording_motion_blur": False,
    "motion_blur_samples": 1,
    "supersample_k": 1,
    "brightness": 0.9,
    "tonemap_softness": 2.1,
}


def encode_x_gif(video: Path, gif: Path) -> tuple[int, int, int, int]:
    for width, height, fps, colors in X_GIF_PROFILES:
        graph = (
            f"fps={fps},scale={width}:{height}:flags=lanczos,split[a][b];"
            f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
            "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle"
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-lavfi", graph, str(gif)],
            check=True,
        )
        if gif.stat().st_size <= MAX_X_GIF_BYTES:
            return width, height, fps, colors
    raise RuntimeError(f"could not encode {video.name} below the X GIF limit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--spp", type=int, default=16)
    parser.add_argument("--encode-only", action="store_true", help="rebuild X-ready GIFs from existing MP4 masters")
    parser.add_argument("--video-only", action="store_true", help="render MP4 masters without GIF encoding")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Documents" / "Fluoddity" / "Review" / "Final",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, round(args.seconds * 60))

    for study in STUDIES:
        name = study["name"]
        if (args.width, args.height) == (1280, 720):
            master = args.output / f"{name}-60fps.mp4"
        else:
            master = args.output / f"{name}-{args.width}x{args.height}-60fps.mp4"
        gif = args.output / f"{name}-x-ready.gif"
        if args.encode_only:
            if not master.exists():
                raise FileNotFoundError(master)
            profile = encode_x_gif(master, gif)
            print(f"GIF: {gif} ({profile[0]}x{profile[1]}, {profile[2]} fps, {profile[3]} colors)", flush=True)
            continue

        print(f"\n=== {name}: settle ===", flush=True)
        style = BASE_STYLE | study["style"] | {"three_d_rt_mode": 0}
        style["three_d_optix_capture_width"] = args.width
        style["three_d_optix_capture_height"] = args.height
        command(
            settings={"preferences": style},
            actions=[
                {"name": "window_size", "width": args.width, "height": args.height, "hidden": True},
                {"name": "load_config", "filename": study["config"], "category": "Advanced"},
                "reset",
                "resume",
            ],
            label=f"final settle {name}",
        )
        time.sleep(study["settle"])

        print(f"=== {name}: record {frame_count} frames ===", flush=True)
        command(
            settings={
                "preferences": {
                    **style,
                    "three_d_rt_mode": 1,
                    "three_d_rt_preview_spp": args.spp,
                    "max_frames": frame_count,
                    "filename_prefix": name,
                },
                "camera": {"fov": 48.0, "orbit_rate": 0.0},
                "controller": {"pos": [0.0, 0.15, -3.4], "yaw": 0.0, "pitch": -0.06},
            },
            actions=["pause"],
            label=f"final prepare {name}",
        )
        time.sleep(1.0)
        started_at = time.time() - 1.0
        command(actions=["record_start"], label=f"final arm {name}")
        time.sleep(0.5)
        command(actions=["resume"], label=f"final run {name}")
        video = wait_for_recording(name, started_at, timeout=300.0)

        master.write_bytes(video.read_bytes())
        print(f"MP4: {master}", flush=True)
        if not args.video_only:
            profile = encode_x_gif(master, gif)
            print(f"GIF:  {gif} ({profile[0]}x{profile[1]}, {profile[2]} fps, {profile[3]} colors)", flush=True)

    if not args.encode_only:
        command(actions=["pause"], label="final renders complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
