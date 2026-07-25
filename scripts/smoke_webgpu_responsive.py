#!/usr/bin/env python3
"""Exercise the packaged WebGPU controls in a real headless browser.

The static artifact smoke verifies packaging and sandbox contracts. This smoke
adds the browser-layout boundary that static HTML inspection cannot prove:
every slider must remain rendered and reachable at compact iframe sizes, and
the bound range inputs must still update their outputs.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "artifacts" / "networked-art" / "everything.html"
DEFAULT_HARNESS = ROOT / "runtime" / "webgpu" / "responsive-harness.html"
DEFAULT_JSON = ROOT / "artifacts" / "webgpu" / "responsive-smoke.json"
DEFAULT_VIEWPORTS = (
    (1280, 600),
    (800, 600),
    (680, 620),
    (390, 640),
    (320, 300),
    (320, 180),
)
COMMON_BROWSER_PATHS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate WebGPU controls at compact iframe sizes in Chrome or Edge."
    )
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--harness", type=Path, default=DEFAULT_HARNESS)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Validate the existing packaged artifact without rebuilding it first.",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def find_browser(explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(resolve(explicit))
    configured = os.environ.get("FLUODDITY_BROWSER")
    if configured:
        candidates.append(Path(configured))
    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe", "chromium"):
        executable = shutil.which(name)
        if executable:
            candidates.append(Path(executable))
    candidates.extend(COMMON_BROWSER_PATHS)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Chrome or Edge was not found. Pass --browser or set FLUODDITY_BROWSER."
    )


def attribute(dom: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}=\"([^\"]*)\"", dom)
    return match.group(1) if match else None


def run_viewport(
    browser: Path,
    harness_url: str,
    artifact_url_path: str,
    width: int,
    height: int,
    profile_root: Path,
) -> dict[str, object]:
    profile = profile_root / f"profile-{width}x{height}"
    url = (
        f"{harness_url}?width={width}&height={height}"
        f"&artifact={quote(artifact_url_path, safe='/')}"
    )
    outer_width = max(1400, width + 80)
    outer_height = max(900, height + 80)
    command = [
        str(browser),
        "--headless=new",
        "--enable-unsafe-webgpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-sync",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-default-browser-check",
        "--no-first-run",
        "--no-proxy-server",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=3000",
        f"--user-data-dir={profile}",
        f"--window-size={outer_width},{outer_height}",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    dom = proc.stdout
    observed = {
        "requested_viewport": f"{width}x{height}",
        "observed_viewport": attribute(dom, "data-responsive-viewport"),
        "controls": attribute(dom, "data-responsive-controls"),
        "sliders": attribute(dom, "data-responsive-sliders"),
        "reachable": attribute(dom, "data-responsive-reachable"),
        "obscured": attribute(dom, "data-responsive-obscured"),
        "functional": attribute(dom, "data-responsive-functional"),
        "scrollable": attribute(dom, "data-responsive-scrollable"),
        "returncode": proc.returncode,
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-8:]),
    }
    observed["passed"] = (
        proc.returncode == 0
        and observed["observed_viewport"] == observed["requested_viewport"]
        and observed["controls"] == "pass"
        and observed["sliders"] == "4/4"
        and observed["reachable"] == "4/4"
        and observed["obscured"] == "pass"
        and observed["functional"] == "pass"
    )
    return observed


def main() -> int:
    args = parse_args()
    artifact = resolve(args.artifact)
    harness = resolve(args.harness)
    json_output = resolve(args.json_output)
    browser = find_browser(args.browser)

    if not args.skip_build:
        subprocess.run(
            [sys.executable, "scripts/build_webgpu_artifact.py"],
            cwd=ROOT,
            check=True,
        )
    if not artifact.is_file():
        raise FileNotFoundError(f"Packaged artifact not found: {artifact}")
    if not harness.is_file():
        raise FileNotFoundError(f"Responsive harness not found: {harness}")

    try:
        artifact_relative = artifact.resolve().relative_to(ROOT)
        harness_relative = harness.resolve().relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(
            "The responsive artifact and harness must be inside the repository."
        ) from exc

    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    harness_url = (
        f"http://127.0.0.1:{server.server_port}/"
        f"{quote(harness_relative.as_posix(), safe='/')}"
    )
    artifact_url_path = f"/{artifact_relative.as_posix()}"

    try:
        with tempfile.TemporaryDirectory(prefix="fluoddity-webgpu-responsive-") as temp:
            results = [
                run_viewport(
                    browser,
                    harness_url,
                    artifact_url_path,
                    width,
                    height,
                    Path(temp),
                )
                for width, height in DEFAULT_VIEWPORTS
            ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    payload = {
        "schema": "networked.art.everything.responsive-smoke.v1",
        "status": "pass" if all(result["passed"] for result in results) else "fail",
        "browser": str(browser),
        "artifact": artifact_relative.as_posix(),
        "harness": harness_relative.as_posix(),
        "viewports": results,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for result in results:
        print(
            "webgpu_responsive_viewport="
            f"{result['requested_viewport']} "
            f"observed={result['observed_viewport']} "
            f"sliders={result['sliders']} "
            f"reachable={result['reachable']} "
            f"obscured={result['obscured']} "
            f"functional={result['functional']} "
            f"scrollable={result['scrollable']} "
            f"status={'pass' if result['passed'] else 'fail'}"
        )
    print(f"webgpu_responsive_status={payload['status']}")
    print(f"webgpu_responsive_json={json_output}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
