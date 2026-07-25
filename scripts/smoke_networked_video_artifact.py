"""Smoke-check the self-contained prerecorded-video HTML exporter."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fluoddity-networked-video-") as temp:
        work = Path(temp)
        video = work / "probe.mp4"
        poster = work / "probe.png"
        output = work / "probe.html"
        manifest = work / "probe.json"
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        poster.write_bytes(b"\x89PNG\r\n\x1a\n")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/export_networked_html.py",
                "--video",
                str(video),
                "--poster",
                str(poster),
                "--output",
                str(output),
                "--manifest",
                str(manifest),
                "--title",
                "Contract Probe",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        require(proc.returncode == 0, f"export failed: {proc.stdout}\n{proc.stderr}")

        document = output.read_text(encoding="utf-8")
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        require(
            'content="fluoddity.networked-html-artifact.v1"' in document,
            "standalone artifact should declare its schema",
        )
        require("fetch(" not in document and "http://" not in document and "https://" not in document, "artifact should not make network requests")
        require("data-video" not in document, "standalone artifact should use its namespaced video-data element")
        require(payload.get("schema") == "fluoddity.networked-html-artifact.v1", "manifest schema should match")
        require(payload.get("self_contained") is True, "manifest should declare self-containment")
        require(payload.get("external_requests") == 0, "manifest should declare zero external requests")
        require(payload.get("artifact", {}).get("bytes") == output.stat().st_size, "manifest should record output bytes")
        require(len(payload.get("artifact", {}).get("sha256", "")) == 64, "manifest should record output hash")
        require(
            "video.pause();\n    applyPointer(event);" not in document,
            "a tap must not scrub or change speed before toggling playback",
        )
        require(
            "resumeAfterVisibility=!video.paused" in document
            and "else if(resumeAfterVisibility)" in document,
            "visibility resume should snapshot the actual playback state",
        )
        require(
            "if(!Number.isFinite(video.duration)||video.duration<=0)return;" in document,
            "standalone arrow stepping should wait for finite video metadata",
        )

        fragment = work / "fragment.html"
        fragment_manifest = work / "fragment.json"
        fragment_proc = subprocess.run(
            [
                sys.executable,
                "scripts/export_networked_html.py",
                "--video",
                str(video),
                "--poster",
                str(poster),
                "--output",
                str(fragment),
                "--manifest",
                str(fragment_manifest),
                "--fragment",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        require(
            fragment_proc.returncode == 0,
            f"fragment export failed: {fragment_proc.stdout}\n{fragment_proc.stderr}",
        )
        fragment_text = fragment.read_text(encoding="utf-8")
        require('tabindex="0"' in fragment_text, "fragment should expose a keyboard focus target")
        require(
            'root.addEventListener("keydown"' in fragment_text,
            "fragment should implement the advertised keyboard controls",
        )
        require(
            "if(!Number.isFinite(video.duration)||video.duration<=0)return;" in fragment_text,
            "fragment arrow stepping should wait for finite video metadata",
        )

        original_video = video.read_bytes()
        original_poster = poster.read_bytes()
        collision_commands = [
            ("output-video", ["--output", str(video), "--manifest", str(manifest)]),
            ("output-poster", ["--output", str(poster), "--manifest", str(manifest)]),
            ("manifest-output", ["--output", str(output), "--manifest", str(output)]),
            ("manifest-video", ["--output", str(output), "--manifest", str(video)]),
            ("manifest-poster", ["--output", str(output), "--manifest", str(poster)]),
        ]
        for label, path_args in collision_commands:
            collision = subprocess.run(
                [
                    sys.executable,
                    "scripts/export_networked_html.py",
                    "--video",
                    str(video),
                    "--poster",
                    str(poster),
                    *path_args,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            require(collision.returncode != 0, f"{label} collision should be rejected")
            require("paths must be distinct" in collision.stderr, f"{label} should explain collision")
            require(video.read_bytes() == original_video, f"{label} must not overwrite source video")
            require(poster.read_bytes() == original_poster, f"{label} must not overwrite source poster")

    print("networked_video_artifact_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
