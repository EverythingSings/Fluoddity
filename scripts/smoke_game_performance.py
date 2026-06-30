"""Timed performance smoke for the game-mode app loop."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record game-mode frame timing metrics.")
    parser.add_argument("--seconds", type=float, default=3.0, help="Seconds to measure.")
    parser.add_argument("--width", type=int, default=1280, help="Launch window width.")
    parser.add_argument("--height", type=int, default=800, help="Launch window height.")
    parser.add_argument(
        "--min-fps",
        type=float,
        default=30.0,
        help="Fail if measured average FPS is below this value.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used to launch main.py.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Additional argument to pass through to main.py. Repeat for multiple args.",
    )
    return parser.parse_args()


def parse_metrics(stdout: str) -> dict[str, float]:
    match = re.search(r"performance_smoke=(.+)", stdout)
    if not match:
        raise AssertionError("missing performance_smoke output")

    metrics: dict[str, float] = {}
    for part in match.group(1).split():
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        metrics[key] = float(value)
    return metrics


def main() -> int:
    args = parse_args()
    cmd = [
        args.python,
        "main.py",
        "--game",
        "--width",
        str(args.width),
        "--height",
        str(args.height),
        "--performance-smoke-seconds",
        str(max(0.1, args.seconds)),
        *args.extra_arg,
    ]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        creationflags=creationflags,
        timeout=max(10.0, args.seconds + 10.0),
    )

    if proc.returncode != 0:
        print(f"performance_smoke=exited_{proc.returncode}")
        if proc.stdout:
            print("stdout:")
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("stderr:")
            print(proc.stderr.rstrip())
        return proc.returncode

    metrics = parse_metrics(proc.stdout)
    avg_fps = metrics.get("avg_fps", 0.0)
    if avg_fps < args.min_fps:
        print(
            "performance_smoke=below_threshold "
            f"avg_fps={avg_fps:.2f} min_fps={args.min_fps:.2f}"
        )
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("stderr:")
            print(proc.stderr.rstrip())
        return 1

    print(
        "performance_smoke=ok "
        f"avg_fps={avg_fps:.2f} "
        f"avg_frame_ms={metrics.get('avg_frame_ms', 0.0):.2f} "
        f"worst_frame_ms={metrics.get('worst_frame_ms', 0.0):.2f}"
    )
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print("stderr:")
        print(proc.stderr.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
