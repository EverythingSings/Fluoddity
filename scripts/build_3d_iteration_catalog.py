"""Build or normalize a portable catalog of 3D iteration captures."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_DIR = Path("artifacts/unique_iterations")
DEFAULT_OUTPUT = Path("docs/evidence/3d_gravity_iterations/catalog.json")
DEFAULT_PATH_PREFIX = PurePosixPath("artifacts/unique_iterations")
DEFAULT_GRAVITY_Y = -0.00008
GRAVITY_STEP_Y = -0.00007
GRAVITY_SEQUENCE_LENGTH = 7

NOTES = {
    "Aperture": "settled gravity column with a bright central throat and floor rings",
    "Arterial Traffic": "multiple hanging colored vessels and branching streams",
    "Barrage": "dense luminous impact plume",
    "Crowns": "separate crown-like suspended lobes",
    "Boats": "bright drifting bodies over a dense floor field",
    "Boats2": "rain-like vertical strands and a settled base",
    "Bowties": "thin vertical filaments with a suspended side bloom",
    "Branes": "solid magenta volumetric wall",
    "Branes2": "layered pale column and dense floor accumulation",
    "Bullets": "several narrow projectile-like towers",
    "Caltrops": "bright clustered forms with radial protrusions",
    "Chomp": "multicolor branching mass with floor interaction",
    "Chomp2": "dense striped vertical organism",
    "Cilia": "bright diffuse cap over a settled base",
    "Flowers": "flower-like suspended clusters",
    "Comets": "elongated luminous trails and orbital blobs",
    "Contours": "layered contour-like volume",
    "Darts": "thin hanging darts and isolated bulbs",
    "Diatomic": "paired bulbous forms",
    "DrawOnMe2": "large branching ribbon structures",
    "Ecosystem": "dense mixed-height ecosystem field",
    "EtchSketch": "fine traced filaments",
    "Fans": "fan-like vertical sprays",
    "Fans2": "tighter fan columns",
    "Flowers2": "bright flower canopy",
    "Flowers3": "layered flower canopy with floor glow",
}


def repo_path(path: Path) -> Path:
    """Resolve a CLI path relative to the repository root."""
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def capture_filename(raw_path: str) -> str:
    """Extract a filename from either Windows or POSIX provenance."""
    windows_name = PureWindowsPath(raw_path).name
    return PurePosixPath(windows_name).name


def capture_index(filename: str) -> int:
    match = re.match(r"iteration-(\d+)-", filename, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"capture name does not contain an iteration index: {filename}")
    return int(match.group(1))


def preset_name(filename: str) -> str:
    name = filename[:-4] if filename.lower().endswith(".mp4") else filename
    match = re.match(r"iteration-\d+-(.+)", name, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"capture name does not contain a preset: {filename}")
    return match.group(1)


def gravity_y_for(index: int) -> float:
    return round(
        DEFAULT_GRAVITY_Y
        + ((index - 1) % GRAVITY_SEQUENCE_LENGTH) * GRAVITY_STEP_Y,
        8,
    )


def portable_capture_path(filename: str, prefix: PurePosixPath) -> str:
    return (prefix / filename).as_posix()


def portable_provenance_path(
    raw_path: str,
    fallback_prefix: PurePosixPath,
) -> str:
    """Retain the path below artifacts/ while dropping machine-specific roots."""
    parts = PureWindowsPath(raw_path).parts
    for index, part in enumerate(parts):
        if part.casefold() == "artifacts":
            return PurePosixPath(*parts[index:]).as_posix()
    return portable_capture_path(capture_filename(raw_path), fallback_prefix)


def read_capture_list(
    list_path: Path,
    fallback_prefix: PurePosixPath,
) -> list[str]:
    captures = []
    for line_number, line in enumerate(
        list_path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"file\s+'(.+)'", stripped)
        if not match:
            raise ValueError(
                f"unsupported capture-list line {list_path}:{line_number}: {line}"
            )
        captures.append(portable_provenance_path(match.group(1), fallback_prefix))
    return captures


def build_item(
    *,
    filename: str,
    byte_count: int,
    reject_below_bytes: int,
    path_prefix: PurePosixPath,
) -> dict[str, Any]:
    index = capture_index(filename)
    preset = preset_name(filename)
    return {
        "capture_index": index,
        "preset": preset,
        "path_before_archive": portable_capture_path(filename, path_prefix),
        "bytes": byte_count,
        "gravity_y": gravity_y_for(index),
        "quality_filter": (
            "reviewed_capture"
            if byte_count > reject_below_bytes
            else "reject_near_empty"
        ),
        "interesting_structure": NOTES.get(
            preset,
            "distinct authored 3D gravity evolution; inspect contact sheet",
        ),
    }


def base_payload(branch: str, iterations: list[dict[str, Any]]) -> dict[str, Any]:
    gravity_values = [
        round(DEFAULT_GRAVITY_Y + index * GRAVITY_STEP_Y, 8)
        for index in range(GRAVITY_SEQUENCE_LENGTH)
    ]
    return {
        "schema": "fluoddity.3d_iteration_catalog.v1",
        "branch": branch,
        "physics": {
            "gravity": "downward acceleration applied in entity_update.glsl",
            "default_gravity_uniform": [0.0, DEFAULT_GRAVITY_Y, 0.0],
            "capture_gravity_y_sequence": gravity_values,
        },
        "capture_method": (
            "fresh native launch per saved preset with a unique prefix, "
            "rule seed, and deterministic gravity step"
        ),
        "review_notes": (
            "Near-empty Beholder and Inky captures are retained in the catalog "
            "but marked rejected."
        ),
        "iterations": iterations,
    }


def catalog_from_captures(
    capture_dir: Path,
    branch: str,
    reject_below_bytes: int,
    path_prefix: PurePosixPath,
) -> dict[str, Any]:
    captures = sorted(capture_dir.glob("*.mp4"), key=lambda path: path.name.casefold())
    if not captures:
        raise ValueError(f"no MP4 captures found in {capture_dir}")
    iterations = [
        build_item(
            filename=path.name,
            byte_count=path.stat().st_size,
            reject_below_bytes=reject_below_bytes,
            path_prefix=path_prefix,
        )
        for path in captures
    ]
    return base_payload(branch, iterations)


def normalize_catalog(
    source_path: Path,
    reject_below_bytes: int,
    path_prefix: PurePosixPath,
) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("schema") != "fluoddity.3d_iteration_catalog.v1":
        raise ValueError(f"unsupported catalog schema in {source_path}")
    source_iterations = source.get("iterations")
    if not isinstance(source_iterations, list) or not source_iterations:
        raise ValueError(f"catalog contains no iterations: {source_path}")

    iterations = []
    for source_item in source_iterations:
        filename = capture_filename(str(source_item["path_before_archive"]))
        item = build_item(
            filename=filename,
            byte_count=int(source_item["bytes"]),
            reject_below_bytes=reject_below_bytes,
            path_prefix=path_prefix,
        )
        if source_item.get("quality_filter"):
            item["quality_filter"] = source_item["quality_filter"]
        if source_item.get("interesting_structure"):
            item["interesting_structure"] = source_item["interesting_structure"]
        iterations.append(item)

    payload = base_payload(str(source.get("branch", "unknown")), iterations)
    payload["archive"] = {
        "media_retained": False,
        "cataloged_before_media_cleanup": True,
        "capture_paths_are_provenance_only": True,
    }
    payload["contact_sheet"] = (
        "docs/evidence/3d_gravity_iterations/contact-sheet.png"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument(
        "--capture-dir",
        type=Path,
        help=(
            "directory of MP4 captures; relative paths are resolved from the "
            "repository root"
        ),
    )
    sources.add_argument(
        "--source-catalog",
        type=Path,
        help="existing v1 catalog to sanitize and normalize",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output JSON path (default: {DEFAULT_OUTPUT.as_posix()})",
    )
    parser.add_argument(
        "--path-prefix",
        type=PurePosixPath,
        default=DEFAULT_PATH_PREFIX,
        help="repository-relative provenance prefix stored in the catalog",
    )
    parser.add_argument(
        "--branch",
        default="codex/3d-gravity-iterations",
        help="source branch recorded for a new capture-directory catalog",
    )
    parser.add_argument(
        "--reject-below-bytes",
        type=int,
        default=1_000_000,
        help="mark captures at or below this byte count as near-empty",
    )
    parser.add_argument(
        "--capture-list",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help=(
            "preserve an ffmpeg concat list as a named, sanitized capture set; "
            "may be repeated"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.reject_below_bytes < 0:
        raise ValueError("--reject-below-bytes must be non-negative")
    if args.path_prefix.is_absolute():
        raise ValueError("--path-prefix must be repository-relative")

    output_path = repo_path(args.output)
    if args.source_catalog:
        payload = normalize_catalog(
            repo_path(args.source_catalog),
            args.reject_below_bytes,
            args.path_prefix,
        )
    else:
        capture_dir = repo_path(args.capture_dir or DEFAULT_CAPTURE_DIR)
        payload = catalog_from_captures(
            capture_dir,
            args.branch,
            args.reject_below_bytes,
            args.path_prefix,
        )

    if args.capture_list:
        capture_sets = {}
        for capture_list in args.capture_list:
            name, separator, raw_path = capture_list.partition("=")
            if (
                not separator
                or not re.fullmatch(r"[a-z][a-z0-9_]*", name)
                or not raw_path
            ):
                raise ValueError(
                    "--capture-list must use a lowercase NAME=PATH value"
                )
            if name in capture_sets:
                raise ValueError(f"duplicate capture-list name: {name}")
            capture_sets[name] = read_capture_list(
                repo_path(Path(raw_path)),
                args.path_prefix,
            )
        payload["capture_sets"] = capture_sets

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output_path} ({len(payload['iterations'])} iterations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
