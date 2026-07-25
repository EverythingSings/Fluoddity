"""Render short motion probes for the strongest fine-search candidates."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import time

from PIL import Image, ImageDraw

from optix_redo_operator import operator_root
from search_optix_redo import command
from search_optix_redo_fine import CALIBRATED_STYLE, CANDIDATES


SHORTLIST = ("worm-bloom-orbit", "dragon-orbit", "shroom-nebula", "mitosis-orb")


def wait_for_recording(prefix: str, started_at: float, timeout: float = 120.0) -> Path:
    status_path = operator_root() / "status.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status_path.exists():
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            latest = status.get("artifacts", {}).get("latest_video", "")
            if latest:
                path = Path(latest)
                if (path.exists() and path.stat().st_mtime >= started_at
                        and path.name.startswith(prefix)
                        and not status.get("recording", False)):
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(path)],
                        capture_output=True, text=True,
                    )
                    if probe.returncode == 0 and probe.stdout.strip():
                        return path
        time.sleep(0.15)
    raise TimeoutError(f"recording for {prefix!r} did not finish")


def make_temporal_sheet(rows: list[tuple[str, Path]], output: Path) -> None:
    row_images = []
    for label, video in rows:
        row_path = output.parent / f"{label}-timeline.png"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video),
            "-vf", "fps=1,scale=480:270:force_original_aspect_ratio=decrease,"
                   "pad=480:270:(ow-iw)/2:(oh-ih)/2:black,tile=6x1",
            "-frames:v", "1", str(row_path),
        ], check=True)
        with Image.open(row_path) as image:
            row_images.append((label, image.convert("RGB").copy()))

    label_h = 32
    width = max(image.width for _, image in row_images)
    height = sum(image.height + label_h for _, image in row_images)
    sheet = Image.new("RGB", (width, height), "#080b12")
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, image in row_images:
        draw.text((8, y + 8), label, fill="#eef4ff")
        y += label_h
        sheet.paste(image, (0, y))
        y += image.height
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=360)
    parser.add_argument("--settle", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    selected = {candidate.label: candidate for candidate in CANDIDATES}
    rows: list[tuple[str, Path]] = []
    results: list[dict] = []
    for index, label in enumerate(SHORTLIST, 1):
        candidate = selected[label]
        print(f"\n[{index}/{len(SHORTLIST)}] {label}", flush=True)
        command(
            settings={"preferences": {
                **CALIBRATED_STYLE,
                "rendering": {
                    **CALIBRATED_STYLE["rendering"],
                    "renderer": 1,
                    "rt_mode": 0,
                    "capture_spp": 1,
                    "render_resolution_scale": 1.0,
                },
                "recording": {
                    "max_frames": args.frames,
                    "motion_blur_samples": 1,
                    "recording_motion_blur": False,
                    "recording_blur_quality": 1,
                    "supersample_k": 1,
                    "filename_prefix": f"probe-{label}",
                },
            }},
            actions=[
                {"name": "window_size", "width": 1280, "height": 720, "hidden": True},
                {"name": "load_config", "filename": candidate.config, "category": "Advanced"},
                "pause",
            ],
            label=f"load probe {label}",
        )
        time.sleep(0.3)
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
                "preferences": {"optix": {
                    "use_curves": True,
                    "curve_length": candidate.curve_length,
                    "curve_r0": candidate.curve_r0,
                    "curve_r1": candidate.curve_r1,
                    "sdf_enabled": candidate.dish,
                }},
                "camera": {"fov": 42.0, "orbit_rate": 0.0007},
                "controller": {"pos": [0.0, 0.10, -3.4], "yaw": 0.0, "pitch": -0.045},
            },
            actions=["reset", "resume"],
            label=f"settle probe {label}",
        )
        time.sleep(args.settle)
        command(actions=["pause"], label=f"pause probe {label}")
        time.sleep(0.2)
        started_at = time.time() - 0.1
        command(actions=["record_start"], label=f"arm probe {label}")
        time.sleep(0.25)
        command(actions=["resume"], label=f"record probe {label}")
        video = wait_for_recording(f"probe-{label}", started_at)
        destination = args.output / f"probe-{label}.mp4"
        shutil.copy2(video, destination)
        rows.append((label, destination))
        results.append({"candidate": asdict(candidate), "video": str(destination),
                        "source": str(video)})
        print(destination, flush=True)

    index = args.output / "index.json"
    index.write_text(json.dumps(results, indent=2), encoding="utf-8")
    sheet = args.output / "temporal-contact-sheet.png"
    make_temporal_sheet(rows, sheet)
    print(f"\nIndex: {index}")
    print(f"Temporal sheet: {sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
