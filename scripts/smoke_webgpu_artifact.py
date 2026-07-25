#!/usr/bin/env python3
"""Static safety and packaging checks for a networked.art/everything artifact."""

from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
from typing import Any


NETWORKED_ART_LIMIT_BYTES = 95_000_000
ARTIFACT_SCHEMA = "networked.art.everything.webgpu-artifact.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = (
    REPO_ROOT / "artifacts" / "networked-art" / "everything.html"
)
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "artifacts"
    / "networked-art"
    / "everything.manifest.json"
)
DEFAULT_HARNESS = REPO_ROOT / "runtime" / "webgpu" / "sandbox-harness.html"
DEFAULT_THUMBNAIL = (
    REPO_ROOT
    / "artifacts"
    / "networked-art"
    / "everything-thumbnail.jpg"
)

URL_SCHEME_RE = re.compile(r"(?i)\b(?:https?|wss?):(?:/{2}|(?:\\/){2})")
NETWORK_API_PATTERNS = {
    "fetch": re.compile(r"\bfetch\s*\("),
    "XMLHttpRequest": re.compile(r"\bXMLHttpRequest\b"),
    "WebSocket": re.compile(r"\bWebSocket\s*\("),
    "EventSource": re.compile(r"\bEventSource\s*\("),
    "importScripts": re.compile(r"\bimportScripts\s*\("),
    "sendBeacon": re.compile(r"\bsendBeacon\s*\("),
    "dynamic import": re.compile(r"\bimport\s*\("),
}
PERSISTENCE_PATTERNS = {
    "localStorage": re.compile(r"\blocalStorage\b"),
    "sessionStorage": re.compile(r"\bsessionStorage\b"),
    "IndexedDB": re.compile(r"\bindexedDB\b", re.IGNORECASE),
    "Cache Storage": re.compile(r"\bcaches\s*[\.\[]|\bCacheStorage\b"),
    "service worker": re.compile(r"\bserviceWorker\b"),
    "StorageManager": re.compile(r"\bStorageManager\b|\bnavigator\s*\.\s*storage\b"),
    "origin-private filesystem": re.compile(
        r"\bgetDirectory\s*\(|\bshowSaveFilePicker\s*\("
    ),
    "cookies": re.compile(r"\bdocument\s*\.\s*cookie\b"),
}
PLACEHOLDER_RE = re.compile(r"@@EVERYTHING_[A-Z0-9_]+@@")


class ArtifactParser(HTMLParser):
    """Collect dependency-bearing tags without executing the document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_count = 0
        self.script_srcs: list[str] = []
        self.links: list[dict[str, str]] = []
        self.iframes: list[dict[str, str]] = []
        self.external_attributes: list[tuple[str, str, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        lowered = tag.casefold()
        attributes = {
            key.casefold(): value or "" for key, value in attrs if key is not None
        }
        if lowered == "html":
            self.html_count += 1
        if lowered == "script" and attributes.get("src"):
            self.script_srcs.append(attributes["src"])
        if lowered == "link":
            self.links.append(attributes)
        if lowered == "iframe":
            self.iframes.append(attributes)

        dependency_attributes = {
            "script": ("src",),
            "img": ("src", "srcset"),
            "video": ("src", "poster"),
            "audio": ("src",),
            "source": ("src", "srcset"),
            "track": ("src",),
            "iframe": ("src",),
            "embed": ("src",),
            "object": ("data",),
        }
        for attribute in dependency_attributes.get(lowered, ()):
            value = attributes.get(attribute, "").strip()
            if value and not _is_inline_reference(value):
                self.external_attributes.append((lowered, attribute, value))


def _is_inline_reference(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        normalized.startswith(("data:", "blob:", "#"))
        or normalized in {"about:blank", ""}
    )


def _resolve_from_repo(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"could not read manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"manifest is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest root is not an object")
    return value


def validate_artifact(
    artifact_path: Path, manifest_path: Path | None = None
) -> list[str]:
    failures: list[str] = []
    try:
        raw = artifact_path.read_bytes()
    except OSError as exc:
        return [f"could not read artifact {artifact_path}: {exc}"]

    if len(raw) > NETWORKED_ART_LIMIT_BYTES:
        failures.append(
            f"artifact is {len(raw):,} bytes; limit is "
            f"{NETWORKED_ART_LIMIT_BYTES:,}"
        )
    if artifact_path.suffix.casefold() != ".html":
        failures.append("artifact filename does not end in .html")
    try:
        document = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return failures + [f"artifact is not valid UTF-8: {exc}"]

    if len(re.findall(r"(?i)<!doctype\s+html", document)) != 1:
        failures.append("artifact must contain exactly one HTML doctype")

    parser = ArtifactParser()
    try:
        parser.feed(document)
        parser.close()
    except Exception as exc:  # HTMLParser may reject malformed entities/tags.
        failures.append(f"artifact HTML could not be parsed: {exc}")
    if parser.html_count != 1:
        failures.append(
            f"artifact must contain exactly one <html> element; found {parser.html_count}"
        )
    if parser.script_srcs:
        failures.append(
            "external/module script src is not allowed: "
            + ", ".join(parser.script_srcs)
        )
    if parser.links:
        descriptions = [
            f"rel={link.get('rel', '')!r} href={link.get('href', '')!r}"
            for link in parser.links
        ]
        failures.append("<link> dependencies are not allowed: " + ", ".join(descriptions))
    if parser.external_attributes:
        details = [
            f"<{tag}> {attribute}={value!r}"
            for tag, attribute, value in parser.external_attributes
        ]
        failures.append("non-inline asset reference(s): " + ", ".join(details))

    if URL_SCHEME_RE.search(document):
        failures.append("artifact contains an HTTP(S) or WebSocket URL")
    for label, pattern in NETWORK_API_PATTERNS.items():
        if pattern.search(document):
            failures.append(f"artifact contains network-loading API: {label}")
    for label, pattern in PERSISTENCE_PATTERNS.items():
        if pattern.search(document):
            failures.append(f"artifact contains persistent-storage API: {label}")

    placeholders = sorted(set(PLACEHOLDER_RE.findall(document)))
    if placeholders:
        failures.append("unresolved template placeholder(s): " + ", ".join(placeholders))

    required_markers = {
        "artifact schema": ARTIFACT_SCHEMA,
        "v7 config": '"version":7',
        "WGSL compute entry point": "@compute",
        "WGSL fragment entry point": "@fragment",
        "WebGPU feature detection": "navigator.gpu",
        "WebGPU adapter request": "requestAdapter",
        "WebGPU device request": "requestDevice",
        "inline-only CSP": "connect-src 'none'",
        "trail ping-pong": "nextTrailIndex = 1 - trailIndex",
        "accumulation ping-pong":
            "nextAccumulationIndex = 1 - accumulationIndex",
        "responsive layout reporter": "updateResponsiveContract",
        "responsive browser smoke hook": "responsive-smoke",
        "responsive control input smoke":
            'input.dispatchEvent(new Event("input", { bubbles: true }))',
        "responsive control hit testing": "document.elementFromPoint",
        "responsive control focus testing": "document.activeElement === input",
        "responsive reachability probe gating":
            "let reachableCount = visibleCount;\n      if (responsiveSmokeMode)",
    }
    for label, marker in required_markers.items():
        if marker not in document:
            failures.append(f"missing {label} marker: {marker!r}")
    if re.search(r"\.slider\s*\{\s*display\s*:\s*none", document):
        failures.append(
            "compact layout must keep sliders rendered; use a scrollable control panel"
        )

    if manifest_path is not None:
        try:
            manifest = _load_manifest(manifest_path)
        except ValueError as exc:
            failures.append(str(exc))
        else:
            if manifest.get("schema") != ARTIFACT_SCHEMA:
                failures.append(
                    f"manifest schema is not {ARTIFACT_SCHEMA!r}: "
                    f"{manifest.get('schema')!r}"
                )
            artifact = manifest.get("artifact")
            if not isinstance(artifact, dict):
                failures.append("manifest artifact field is not an object")
            else:
                if artifact.get("bytes") != len(raw):
                    failures.append(
                        "manifest artifact byte count does not match the HTML file"
                    )
                if artifact.get("sha256") != _sha256(raw):
                    failures.append(
                        "manifest artifact SHA-256 does not match the HTML file"
                    )
                if artifact.get("limit_bytes") != NETWORKED_ART_LIMIT_BYTES:
                    failures.append("manifest artifact limit_bytes is incorrect")
            source = manifest.get("source")
            if not isinstance(source, dict) or not source.get("config"):
                failures.append("manifest does not identify its source config")
            settings = manifest.get("settings")
            if not isinstance(settings, dict):
                failures.append("manifest settings field is not an object")
            else:
                if not isinstance(settings.get("particle_count"), int):
                    failures.append("manifest particle_count is not an integer")
                if not isinstance(settings.get("resolution"), int):
                    failures.append("manifest resolution is not an integer")

    return failures


def validate_sandbox_harness(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        document = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"could not read sandbox harness {path}: {exc}"]

    parser = ArtifactParser()
    try:
        parser.feed(document)
        parser.close()
    except Exception as exc:
        return [f"sandbox harness HTML could not be parsed: {exc}"]

    if len(parser.iframes) != 1:
        failures.append(
            f"sandbox harness must contain exactly one iframe; found "
            f"{len(parser.iframes)}"
        )
        return failures

    iframe = parser.iframes[0]
    sandbox_tokens = {
        token for token in iframe.get("sandbox", "").split() if token
    }
    if sandbox_tokens != {"allow-scripts"}:
        failures.append(
            "sandbox harness iframe permissions must be exactly allow-scripts; "
            f"got {sorted(sandbox_tokens)}"
        )
    if iframe.get("src") != "../../artifacts/networked-art/everything.html":
        failures.append(
            "sandbox harness iframe does not target the default generated artifact"
        )
    return failures


def _jpeg_dimensions(raw: bytes) -> tuple[int, int] | None:
    if not raw.startswith(b"\xff\xd8"):
        return None
    offset = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 4 <= len(raw):
        if raw[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA:
            break
        if offset + 2 > len(raw):
            break
        segment_length = struct.unpack(">H", raw[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(raw):
            break
        if marker in start_of_frame and segment_length >= 7:
            height, width = struct.unpack(">HH", raw[offset + 3 : offset + 7])
            return width, height
        offset += segment_length
    return None


def validate_thumbnail(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [f"could not read artwork thumbnail {path}: {exc}"]
    if len(raw) > NETWORKED_ART_LIMIT_BYTES:
        failures.append(
            f"thumbnail is {len(raw):,} bytes; limit is "
            f"{NETWORKED_ART_LIMIT_BYTES:,}"
        )

    dimensions: tuple[int, int] | None = None
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        dimensions = struct.unpack(">II", raw[16:24])
        if path.suffix.casefold() != ".png":
            failures.append("PNG thumbnail does not use a .png filename")
    elif raw.startswith(b"\xff\xd8"):
        dimensions = _jpeg_dimensions(raw)
        if path.suffix.casefold() not in {".jpg", ".jpeg"}:
            failures.append("JPEG thumbnail does not use a .jpg or .jpeg filename")
    else:
        failures.append("thumbnail is not a supported PNG or JPEG image")

    if dimensions is None:
        failures.append("thumbnail dimensions could not be decoded")
    else:
        width, height = dimensions
        if width <= 0 or height <= 0:
            failures.append(f"thumbnail has invalid dimensions {width}x{height}")
        if width != height:
            failures.append(
                f"thumbnail must be square for the artwork feed; got {width}x{height}"
            )
    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Statically validate a packaged networked.art/everything artifact."
    )
    parser.add_argument("artifact", nargs="?", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Manifest to cross-check.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Validate only the HTML file.",
    )
    parser.add_argument(
        "--harness",
        type=Path,
        default=DEFAULT_HARNESS,
        help="Script-only iframe harness to validate.",
    )
    parser.add_argument(
        "--no-harness",
        action="store_true",
        help="Skip validation of the networked.art-style iframe harness.",
    )
    parser.add_argument(
        "--thumbnail",
        type=Path,
        default=DEFAULT_THUMBNAIL,
        help="Static artwork thumbnail to validate when present.",
    )
    parser.add_argument(
        "--require-thumbnail",
        action="store_true",
        help="Fail if the static artwork thumbnail is missing.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact_path = _resolve_from_repo(args.artifact)
    manifest_path = None if args.no_manifest else _resolve_from_repo(args.manifest)
    failures = validate_artifact(artifact_path, manifest_path)
    harness_path = None if args.no_harness else _resolve_from_repo(args.harness)
    if harness_path is not None:
        failures.extend(validate_sandbox_harness(harness_path))
    thumbnail_path = _resolve_from_repo(args.thumbnail)
    validate_preview = thumbnail_path.exists() or args.require_thumbnail
    if validate_preview:
        failures.extend(validate_thumbnail(thumbnail_path))
    if failures:
        print(f"FAIL {artifact_path}")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    size = artifact_path.stat().st_size
    print(
        f"PASS {artifact_path} ({size:,} bytes; "
        f"{NETWORKED_ART_LIMIT_BYTES - size:,} bytes headroom)"
    )
    if manifest_path is not None:
        print(f"PASS manifest {manifest_path}")
    if harness_path is not None:
        print(f"PASS sandbox harness {harness_path}")
    if validate_preview:
        print(f"PASS thumbnail {thumbnail_path}")
    else:
        print(
            f"SKIP thumbnail {thumbnail_path} "
            "(capture it before publishing, then use --require-thumbnail)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
