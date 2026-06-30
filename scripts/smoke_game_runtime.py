"""Timed runtime smoke for the game-mode OpenGL path.

This launches the app, waits long enough to catch startup/import/shader errors,
then terminates it. It is not a visual QA pass; it proves that game mode starts
and remains alive briefly.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test game-mode startup.")
    parser.add_argument("--seconds", type=float, default=5.0, help="Seconds to keep the app alive.")
    parser.add_argument("--width", type=int, default=640, help="Launch window width.")
    parser.add_argument("--height", type=int, default=480, help="Launch window height.")
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
        *args.extra_arg,
    ]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags,
    )

    deadline = time.monotonic() + max(0.1, args.seconds)
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=1)
            print(f"runtime_smoke=exited_{proc.returncode}")
            if stdout:
                print("stdout:")
                print(stdout.rstrip())
            if stderr:
                print("stderr:")
                print(stderr.rstrip())
            return 1
        time.sleep(0.1)

    proc.terminate()
    try:
        stdout, stderr = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate(timeout=3)

    print("runtime_smoke=started_and_terminated")
    if stdout:
        print("stdout:")
        print(stdout.rstrip())
    if stderr:
        print("stderr:")
        print(stderr.rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
