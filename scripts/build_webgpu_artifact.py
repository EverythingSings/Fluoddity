#!/usr/bin/env python3
"""Build networked.art/everything's self-contained WebGPU HTML artifact.

Template contract
-----------------
``runtime/webgpu/artifact.template.html`` must contain each of these exactly
once:

* ``@@EVERYTHING_TITLE_JSON@@``
* ``@@EVERYTHING_PARTICLE_COUNT@@``
* ``@@EVERYTHING_RESOLUTION@@``
* ``@@EVERYTHING_CONFIG_JSON@@``

Every ``runtime/webgpu/shaders/*.wgsl`` file also has exactly one placeholder.
The placeholder is derived from its filename stem by replacing non-alphanumeric
characters with underscores and uppercasing it. For example, ``entity.wgsl``
maps to ``@@EVERYTHING_WGSL_ENTITY@@``.

Title, config, and shader replacements are JavaScript-safe JSON values. This
keeps the template readable while producing one HTML file with no runtime file
or network dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any


NETWORKED_ART_LIMIT_BYTES = 95_000_000
ARTIFACT_SCHEMA = "networked.art.everything.webgpu-artifact.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE = REPO_ROOT / "runtime" / "webgpu" / "artifact.template.html"
DEFAULT_SHADER_DIR = REPO_ROOT / "runtime" / "webgpu" / "shaders"
DEFAULT_CONFIG = REPO_ROOT / "physics_configs" / "Core" / "Curls.json"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "networked-art" / "everything.html"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "artifacts"
    / "networked-art"
    / "everything.manifest.json"
)

FIXED_PLACEHOLDERS = {
    "@@EVERYTHING_TITLE_JSON@@",
    "@@EVERYTHING_PARTICLE_COUNT@@",
    "@@EVERYTHING_RESOLUTION@@",
    "@@EVERYTHING_CONFIG_JSON@@",
}
PLACEHOLDER_RE = re.compile(r"@@EVERYTHING_[A-Z0-9_]+@@")


class BuildError(ValueError):
    """Raised for an invalid artifact source or package."""


def _resolve_from_repo(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_for_script(value: Any, *, compact: bool = True) -> str:
    separators = (",", ":") if compact else None
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=separators,
    )
    # JSON values are embedded inside an inline script. Escaping these
    # characters prevents a user-supplied title from closing that script.
    return (
        encoded.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _load_config(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"Could not read config {path}: {exc}") from exc

    try:
        config = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"Config is not valid UTF-8 JSON: {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise BuildError("Config root must be a JSON object")
    if config.get("version") != 7:
        raise BuildError(
            f"Config version must be exactly 7, got {config.get('version')!r}"
        )

    rule = config.get("rule")
    if not isinstance(rule, list) or len(rule) != 80:
        actual = len(rule) if isinstance(rule, list) else type(rule).__name__
        raise BuildError(f"Config rule must contain exactly 80 floats, got {actual}")
    for index, value in enumerate(rule):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BuildError(f"Config rule[{index}] is not numeric: {value!r}")
        if not math.isfinite(float(value)):
            raise BuildError(f"Config rule[{index}] is not finite: {value!r}")

    return config, raw


def _shader_placeholder(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", path.stem).strip("_").upper()
    if not stem:
        raise BuildError(f"Cannot derive a placeholder from shader name {path.name!r}")
    return f"@@EVERYTHING_WGSL_{stem}@@"


def _replace_once(document: str, placeholder: str, value: str) -> str:
    count = document.count(placeholder)
    if count != 1:
        raise BuildError(
            f"Template must contain {placeholder} exactly once; found {count}"
        )
    return document.replace(placeholder, value, 1)


def _read_shaders(shader_dir: Path) -> list[tuple[Path, str, str]]:
    try:
        paths = sorted(shader_dir.glob("*.wgsl"), key=lambda path: path.name.casefold())
    except OSError as exc:
        raise BuildError(f"Could not enumerate shader directory {shader_dir}: {exc}") from exc
    if not paths:
        raise BuildError(f"No .wgsl shaders found in {shader_dir}")

    shaders: list[tuple[Path, str, str]] = []
    placeholders: set[str] = set()
    for path in paths:
        placeholder = _shader_placeholder(path)
        if placeholder in placeholders:
            raise BuildError(
                f"Shader names collide on generated placeholder {placeholder}"
            )
        placeholders.add(placeholder)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BuildError(f"Could not read shader {path}: {exc}") from exc
        if not source.strip():
            raise BuildError(f"Shader is empty: {path}")
        shaders.append((path, placeholder, source))
    return shaders


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_artifact(
    *,
    template_path: Path,
    shader_dir: Path,
    config_path: Path,
    output_path: Path,
    manifest_path: Path,
    title: str,
    particle_count: int,
    resolution: int,
) -> dict[str, Any]:
    if not title.strip():
        raise BuildError("Title must not be blank")
    if len(title) > 100:
        raise BuildError("Title must be at most 100 characters for networked.art")
    if particle_count <= 0:
        raise BuildError("Particle count must be a positive integer")
    if resolution < 256 or resolution > 1024:
        raise BuildError(
            "Resolution must be between 256 and 1024, matching the artifact runtime"
        )
    if output_path.resolve() == manifest_path.resolve():
        raise BuildError("Artifact and manifest paths must be different")

    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BuildError(f"Could not read template {template_path}: {exc}") from exc
    config, config_raw = _load_config(config_path)
    shaders = _read_shaders(shader_dir)
    protected_sources = {
        template_path.resolve(),
        config_path.resolve(),
        *(path.resolve() for path, _placeholder, _source in shaders),
    }
    for label, target in (
        ("Artifact", output_path),
        ("Manifest", manifest_path),
    ):
        if target.resolve() in protected_sources:
            raise BuildError(f"{label} path would overwrite an artifact source: {target}")

    document = template
    replacements = {
        "@@EVERYTHING_TITLE_JSON@@": _json_for_script(title),
        "@@EVERYTHING_PARTICLE_COUNT@@": str(particle_count),
        "@@EVERYTHING_RESOLUTION@@": str(resolution),
        "@@EVERYTHING_CONFIG_JSON@@": _json_for_script(config),
    }
    for placeholder in FIXED_PLACEHOLDERS:
        document = _replace_once(document, placeholder, replacements[placeholder])
    for _path, placeholder, source in shaders:
        document = _replace_once(document, placeholder, _json_for_script(source))

    unmatched = sorted(set(PLACEHOLDER_RE.findall(document)))
    if unmatched:
        raise BuildError(
            "Unmatched artifact template placeholder(s): " + ", ".join(unmatched)
        )

    shader_names = ",".join(path.name for path, _placeholder, _source in shaders)
    banner = (
        f"<!-- {ARTIFACT_SCHEMA}; config-version=7; "
        f"config-sha256={_sha256(config_raw)}; shaders={shader_names} -->"
    )
    doctype_match = re.match(r"(?i)(\s*<!doctype\s+html\s*>)", document)
    if doctype_match:
        document = (
            document[: doctype_match.end()]
            + "\n"
            + banner
            + document[doctype_match.end() :]
        )
    else:
        document = banner + "\n" + document

    artifact_bytes = document.encode("utf-8")
    byte_size = len(artifact_bytes)
    if byte_size > NETWORKED_ART_LIMIT_BYTES:
        raise BuildError(
            f"Artifact is {byte_size:,} bytes, exceeding networked.art's "
            f"{NETWORKED_ART_LIMIT_BYTES:,}-byte limit"
        )

    artifact_sha256 = _sha256(artifact_bytes)
    manifest: dict[str, Any] = {
        "schema": ARTIFACT_SCHEMA,
        "artifact": {
            "file": output_path.name,
            "bytes": byte_size,
            "sha256": artifact_sha256,
            "limit_bytes": NETWORKED_ART_LIMIT_BYTES,
        },
        "source": {
            "template": _display_path(template_path),
            "config": _display_path(config_path),
            "config_sha256": _sha256(config_raw),
            "shaders": [
                {
                    "file": _display_path(path),
                    "sha256": _sha256(source.encode("utf-8")),
                }
                for path, _placeholder, source in shaders
            ],
        },
        "settings": {
            "title": title,
            "particle_count": particle_count,
            "resolution": resolution,
        },
    }

    manifest_bytes = (
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    _atomic_write(output_path, artifact_bytes)
    _atomic_write(manifest_path, manifest_bytes)
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one self-contained networked.art/everything HTML artifact."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--title", default="networked.art/everything")
    parser.add_argument("--particle-count", type=int, default=120_000)
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--shader-dir",
        type=Path,
        default=DEFAULT_SHADER_DIR,
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        manifest = build_artifact(
            template_path=_resolve_from_repo(args.template),
            shader_dir=_resolve_from_repo(args.shader_dir),
            config_path=_resolve_from_repo(args.config),
            output_path=_resolve_from_repo(args.output),
            manifest_path=_resolve_from_repo(args.manifest),
            title=args.title,
            particle_count=args.particle_count,
            resolution=args.resolution,
        )
    except BuildError as exc:
        raise SystemExit(f"error: {exc}") from exc

    artifact = manifest["artifact"]
    print(
        f"Built {_display_path(_resolve_from_repo(args.output))}: "
        f"{artifact['bytes']:,} bytes, sha256 {artifact['sha256']}"
    )
    print(f"Manifest: {_display_path(_resolve_from_repo(args.manifest))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
