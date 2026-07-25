#!/usr/bin/env python3
"""Audit the networked.art/everything artifact against canonical source contracts.

This is deliberately a *source-contract* audit. It checks load-bearing layouts,
constants, mappings, pass ordering, and browser-sandbox constraints in the
checked-in sources. It does not execute WebGPU, compare buffers, or claim
numeric/pixel parity.

By default the audit writes:

* ``artifacts/webgpu/source-contract-audit.json``
* ``artifacts/webgpu/source-contract-audit.md``

Use ``--require-complete`` to return a non-zero exit status when any required
source contract is missing. Deliberately documented product-boundary omissions
are reported separately and do not make the bounded artifact kernel incomplete.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable, Sequence


AUDIT_SCHEMA = "networked.art.everything.webgpu-source-contract-audit.v1"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON_OUTPUT = Path("artifacts/webgpu/source-contract-audit.json")
DEFAULT_MARKDOWN_OUTPUT = Path("artifacts/webgpu/source-contract-audit.md")

PHYSICS_SETTINGS: tuple[tuple[str, str, str], ...] = (
    ("axial_force", "Axial Force", "AXIAL_FORCE"),
    ("lateral_force", "Lateral Force", "LATERAL_FORCE"),
    ("sensor_gain", "Sensor Gain", "SENSOR_GAIN"),
    ("mutation_scale", "Mutation Scale", "MUTATION_SCALE"),
    ("drag", "Drag", "DRAG"),
    ("strafe_power", "Strafe Power", "STRAFE_POWER"),
    ("sensor_angle", "Sensor Angle", "SENSOR_ANGLE"),
    ("global_force_mult", "Global Force Mult", "GLOBAL_FORCE_MULT"),
    ("sensor_distance", "Sensor Distance", "SENSOR_DISTANCE"),
    ("hazard_rate", "Hazard Rate", "HAZARD_RATE"),
    ("trail_persistence", "Trail Persistence", "TRAIL_PERSISTENCE"),
    ("trail_diffusion", "Trail Diffusion", "TRAIL_DIFFUSION"),
)

SETTING_KEYS = {
    "disable_symmetry",
    "absolute_orientation",
    "boundary_conditions",
    "initial_conditions",
    "num_cohorts",
    "rule_seed",
    "orientation_mix",
}
MAPPED_APPEARANCE_KEYS = {
    "ink_weight",
    "hue_sensitivity",
    "color_by_cohort",
    "watercolor_mode",
}
OMITTED_APPEARANCE_KEYS = {
    "emboss_mode",
    "emboss_intensity",
    "emboss_smoothness",
}
TOP_LEVEL_FIELDS = {
    "version",
    "physics",
    "slider_ranges",
    "sweeps",
    "parameter_sweeps_enabled",
    "jitters",
    "settings",
    "appearance",
    "rule",
    "notes",
}


@dataclass(frozen=True)
class Evidence:
    path: str
    line_start: int
    line_end: int
    marker: str
    excerpt: str


@dataclass
class AssertionResult:
    id: str
    label: str
    passed: bool
    role: str
    evidence: list[Evidence] = field(default_factory=list)
    detail: str | None = None


@dataclass
class CheckResult:
    id: str
    title: str
    claim: str
    required: bool
    status: str
    assertions: list[AssertionResult]
    notes: list[str] = field(default_factory=list)


class SourceStore:
    """Read sources lazily and retain enough data for exact evidence."""

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._texts: dict[str, str | None] = {}

    def path(self, relative_path: str) -> Path:
        return self.repo_root / Path(relative_path)

    def text(self, relative_path: str) -> str | None:
        if relative_path not in self._texts:
            path = self.path(relative_path)
            try:
                self._texts[relative_path] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._texts[relative_path] = None
        return self._texts[relative_path]

    def inputs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for relative_path in sorted(self._texts):
            text = self._texts[relative_path]
            if text is None:
                result.append({"path": relative_path, "exists": False})
                continue
            data = text.encode("utf-8")
            result.append(
                {
                    "path": relative_path,
                    "exists": True,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        return result

    def find(
        self,
        relative_path: str,
        pattern: str,
        *,
        marker: str,
        flags: int = re.MULTILINE,
    ) -> Evidence | None:
        text = self.text(relative_path)
        if text is None:
            return None
        match = re.search(pattern, text, flags)
        if match is None:
            return None
        line_start = text.count("\n", 0, match.start()) + 1
        line_end = text.count("\n", 0, match.end()) + 1
        lines = text.splitlines()
        excerpt_lines = lines[line_start - 1 : min(line_end, line_start + 5)]
        excerpt = " ".join(line.strip() for line in excerpt_lines if line.strip())
        if len(excerpt) > 360:
            excerpt = excerpt[:357] + "..."
        return Evidence(
            path=relative_path,
            line_start=line_start,
            line_end=line_end,
            marker=marker,
            excerpt=excerpt,
        )


class Audit:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.sources = SourceStore(self.repo_root)
        self.checks: list[CheckResult] = []

    def marker(
        self,
        assertion_id: str,
        label: str,
        role: str,
        path: str,
        pattern: str,
        *,
        marker: str,
        flags: int = re.MULTILINE,
    ) -> AssertionResult:
        evidence = self.sources.find(
            path,
            pattern,
            marker=marker,
            flags=flags,
        )
        if evidence is not None:
            return AssertionResult(
                id=assertion_id,
                label=label,
                passed=True,
                role=role,
                evidence=[evidence],
            )
        missing = self.sources.text(path) is None
        detail = (
            f"Source file is missing or unreadable: {path}"
            if missing
            else f"Required marker was not found: {marker}"
        )
        return AssertionResult(
            id=assertion_id,
            label=label,
            passed=False,
            role=role,
            detail=detail,
        )

    def ordered(
        self,
        assertion_id: str,
        label: str,
        role: str,
        path: str,
        patterns: Sequence[tuple[str, str]],
    ) -> AssertionResult:
        text = self.sources.text(path)
        if text is None:
            return AssertionResult(
                id=assertion_id,
                label=label,
                passed=False,
                role=role,
                detail=f"Source file is missing or unreadable: {path}",
            )
        evidence: list[Evidence] = []
        positions: list[int] = []
        missing: list[str] = []
        for marker, pattern in patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match is None:
                missing.append(marker)
                continue
            positions.append(match.start())
            found = self.sources.find(path, pattern, marker=marker)
            if found is not None:
                evidence.append(found)
        in_order = not missing and positions == sorted(positions)
        detail = None
        if missing:
            detail = "Missing ordered marker(s): " + ", ".join(missing)
        elif not in_order:
            detail = "Markers exist but are not in the required order."
        return AssertionResult(
            id=assertion_id,
            label=label,
            passed=in_order,
            role=role,
            evidence=evidence,
            detail=detail,
        )

    def value(
        self,
        assertion_id: str,
        label: str,
        role: str,
        passed: bool,
        *,
        detail: str | None = None,
        evidence: Iterable[Evidence] = (),
    ) -> AssertionResult:
        return AssertionResult(
            id=assertion_id,
            label=label,
            passed=passed,
            role=role,
            evidence=list(evidence),
            detail=detail,
        )

    def add_check(
        self,
        check_id: str,
        title: str,
        claim: str,
        assertions: Sequence[AssertionResult],
        *,
        required: bool = True,
        notes: Sequence[str] = (),
    ) -> None:
        passed = all(assertion.passed for assertion in assertions)
        self.checks.append(
            CheckResult(
                id=check_id,
                title=title,
                claim=claim,
                required=required,
                status="pass" if passed else "fail",
                assertions=list(assertions),
                notes=list(notes),
            )
        )


def _entity_layout_pattern(language: str) -> str:
    if language == "glsl":
        return (
            r"struct\s+Entity\s*\{\s*"
            r"vec2\s+pos\s*;\s*"
            r"vec2\s+vel\s*;\s*"
            r"float\s+size\s*;\s*"
            r"float\s+cohort\s*;[\s\S]*?"
            r"float\s+padding\s*\[\s*2\s*\]\s*;[\s\S]*?"
            r"vec4\s+color\s*;\s*"
            r"\}"
        )
    return (
        r"struct\s+Entity\s*\{\s*"
        r"pos\s*:\s*vec2<f32>\s*,\s*"
        r"vel\s*:\s*vec2<f32>\s*,\s*"
        r"size\s*:\s*f32\s*,\s*"
        r"cohort\s*:\s*f32\s*,\s*"
        r"padding\s*:\s*vec2<f32>\s*,\s*"
        r"color\s*:\s*vec4<f32>\s*,\s*"
        r"\}"
    )


def _setting_definitions(text: str | None) -> list[tuple[str, str, str]]:
    if text is None:
        return []
    block = re.search(
        r"const\s+settingDefinitions\s*=\s*\[(?P<body>[\s\S]*?)\]\s*;",
        text,
    )
    if block is None:
        return []
    return [
        (match.group(1), match.group(2), match.group(3))
        for match in re.finditer(
            r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]',
            block.group("body"),
        )
    ]


def _scan_v7_presets(repo_root: Path) -> dict[str, Any]:
    root = repo_root / "physics_configs"
    files: list[Path] = []
    invalid: list[dict[str, str]] = []
    observed: set[str] = set()
    invalid_rules: list[str] = []
    for path in sorted(root.rglob("*.json")) if root.exists() else []:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            invalid.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(document, dict) or document.get("version") != 7:
            continue
        files.append(path)
        for top_key, value in document.items():
            observed.add(top_key)
            if top_key in {"physics", "slider_ranges", "settings", "appearance", "jitters"}:
                if isinstance(value, dict):
                    observed.update(f"{top_key}.{key}" for key in value)
            elif top_key == "sweeps" and isinstance(value, dict):
                for axis, axis_values in value.items():
                    observed.add(f"sweeps.{axis}")
                    if isinstance(axis_values, dict):
                        observed.update(
                            f"sweeps.{axis}.{key}" for key in axis_values
                        )
        rule = document.get("rule")
        if (
            not isinstance(rule, list)
            or len(rule) != 80
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in rule
            )
        ):
            invalid_rules.append(path.relative_to(repo_root).as_posix())
    return {
        "files": [path.relative_to(repo_root).as_posix() for path in files],
        "invalid_json": invalid,
        "invalid_rules": invalid_rules,
        "observed_fields": sorted(observed),
    }


def _preset_field_policy(field_path: str) -> tuple[str, str]:
    physics_keys = {item[0] for item in PHYSICS_SETTINGS}
    range_keys = {item[1] for item in PHYSICS_SETTINGS}
    sweep_keys = {item[2] for item in PHYSICS_SETTINGS}

    if field_path in {
        "version",
        "rule",
        "parameter_sweeps_enabled",
        "physics",
        "slider_ranges",
        "sweeps",
        "jitters",
        "settings",
        "appearance",
    }:
        return "mapped", "Runtime or build-time container."
    if field_path == "notes":
        return "metadata", "Human-authored preset notes do not affect simulation."
    if field_path.startswith("physics."):
        key = field_path.split(".", 1)[1]
        return (
            ("mapped", "Uploaded through the 12-entry physics setting table.")
            if key in physics_keys
            else ("unclassified", "Unknown physics key.")
        )
    if field_path.startswith("slider_ranges."):
        key = field_path.split(".", 1)[1]
        return (
            ("mapped", "Uploaded as the setting minimum and maximum.")
            if key in range_keys
            else ("unclassified", "Unknown slider-range key.")
        )
    if field_path.startswith("jitters."):
        key = field_path.split(".", 1)[1]
        return (
            ("mapped", "Uploaded as PhysicsSetting jitter.")
            if key in sweep_keys
            else ("unclassified", "Unknown jitter key.")
        )
    if field_path.startswith("sweeps."):
        parts = field_path.split(".")
        if len(parts) == 2 and parts[1] in {"x", "y", "cohort"}:
            return "mapped", "Runtime sweep-axis container."
        if len(parts) == 3 and parts[1] in {"x", "y", "cohort"}:
            if parts[2] in sweep_keys:
                return "mapped", "Uploaded as a PhysicsSetting axis sweep."
            if parts[2] == parts[1]:
                return (
                    "metadata",
                    "Axis-name sentinel is not a physics parameter.",
                )
        return "unclassified", "Unknown sweep field."
    if field_path.startswith("settings."):
        key = field_path.split(".", 1)[1]
        return (
            ("mapped", "Uploaded into WebGPU globals.")
            if key in SETTING_KEYS
            else ("unclassified", "Unknown simulation setting.")
        )
    if field_path.startswith("appearance."):
        key = field_path.split(".", 1)[1]
        if key in MAPPED_APPEARANCE_KEYS:
            return "mapped", "Uploaded into WebGPU globals."
        if key in OMITTED_APPEARANCE_KEYS:
            return (
                "deliberate_omission",
                "Emboss is outside the first artifact-kernel boundary.",
            )
        return "unclassified", "Unknown appearance setting."
    return "unclassified", "No mapping policy exists."


def _field_mapping_evidence(
    audit: Audit,
    field_path: str,
    classification: str,
) -> list[Evidence]:
    template = "runtime/webgpu/artifact.template.html"
    builder = "scripts/build_webgpu_artifact.py"
    readme = "runtime/webgpu/README.md"
    evidence: list[Evidence] = []

    if field_path == "version":
        found = audit.sources.find(
            builder,
            r'config\.get\("version"\)\s*!=\s*7',
            marker='builder requires config version 7',
        )
    elif field_path == "rule":
        found = audit.sources.find(
            template,
            r"new\s+Float32Array\(CONFIG\.rule\)",
            marker="CONFIG.rule is uploaded as Float32Array",
        )
    elif field_path == "parameter_sweeps_enabled":
        found = audit.sources.find(
            template,
            r"if\s*\(!CONFIG\.parameter_sweeps_enabled\)\s*return\s+0",
            marker="parameter_sweeps_enabled gates sweep upload",
        )
    elif field_path.startswith("physics."):
        key = field_path.split(".", 1)[1]
        found = audit.sources.find(
            template,
            rf'\[\s*"{re.escape(key)}"\s*,',
            marker=f'settingDefinitions physics key "{key}"',
        )
    elif field_path.startswith("slider_ranges."):
        key = field_path.split(".", 1)[1]
        found = audit.sources.find(
            template,
            rf',\s*"{re.escape(key)}"\s*,',
            marker=f'settingDefinitions range key "{key}"',
        )
    elif field_path.startswith("jitters."):
        found = audit.sources.find(
            template,
            r"CONFIG\.jitters\s*&&\s*CONFIG\.jitters\[sweepKey\]",
            marker="jitter is uploaded by sweep key",
        )
    elif field_path.startswith("sweeps."):
        parts = field_path.split(".")
        if len(parts) >= 2 and parts[1] in {"x", "y", "cohort"}:
            axis = parts[1]
            found = audit.sources.find(
                template,
                rf'sweepValue\("{axis}"\s*,\s*sweepKey\)',
                marker=f'{axis} sweep upload',
            )
        else:
            found = None
    elif field_path.startswith("settings."):
        key = field_path.split(".", 1)[1]
        found = audit.sources.find(
            template,
            rf"CONFIG\.settings\s*&&\s*CONFIG\.settings\.{re.escape(key)}",
            marker=f"CONFIG.settings.{key}",
        )
    elif field_path.startswith("appearance."):
        key = field_path.split(".", 1)[1]
        if classification == "deliberate_omission":
            found = audit.sources.find(
                readme,
                r"\bemboss\b",
                marker="README deliberate boundary includes emboss",
                flags=re.MULTILINE | re.IGNORECASE,
            )
        else:
            found = audit.sources.find(
                template,
                rf"CONFIG\.appearance\.{re.escape(key)}",
                marker=f"CONFIG.appearance.{key}",
            )
    elif field_path in {
        "physics",
        "slider_ranges",
        "sweeps",
        "jitters",
        "settings",
        "appearance",
    }:
        found = audit.sources.find(
            template,
            rf"CONFIG\.{re.escape(field_path)}",
            marker=f"CONFIG.{field_path} runtime access",
        )
    else:
        found = None
    if found is not None:
        evidence.append(found)
    return evidence


def _build_checks(audit: Audit) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    canonical_entity = "shaders/entity_update.glsl"
    canonical_fourier = "shaders/fourier4_4.glsl"
    canonical_brush_vertex = "shaders/brush.vert"
    canonical_brush_fragment = "shaders/brush.frag"
    canonical_canvas = "shaders/canvas.frag"
    canonical_particles = "shaders/cam_brush.frag"
    canonical_assembly = "shaders/frame_assembly.frag"
    canonical_sim = "sim.py"
    template = "runtime/webgpu/artifact.template.html"
    entity = "runtime/webgpu/shaders/entity.wgsl"
    brush = "runtime/webgpu/shaders/brush.wgsl"
    trail = "runtime/webgpu/shaders/trail.wgsl"
    particles = "runtime/webgpu/shaders/particles.wgsl"
    accumulate = "runtime/webgpu/shaders/accumulate.wgsl"
    present = "runtime/webgpu/shaders/present.wgsl"
    readme = "runtime/webgpu/README.md"
    builder = "scripts/build_webgpu_artifact.py"

    # 48-byte Entity storage layout.
    entity_assertions = [
        audit.marker(
            "entity.canonical.compute",
            "Canonical compute Entity fields are in storage order",
            "canonical",
            canonical_entity,
            _entity_layout_pattern("glsl"),
            marker="Entity { vec2 pos; vec2 vel; float size; float cohort; float padding[2]; vec4 color; }",
        ),
        audit.marker(
            "entity.canonical.brush",
            "Canonical brush vertex shader shares the Entity order",
            "canonical",
            canonical_brush_vertex,
            _entity_layout_pattern("glsl"),
            marker="brush.vert Entity storage layout",
        ),
    ]
    for shader_path, suffix in (
        (entity, "compute"),
        (brush, "brush"),
        (particles, "particles"),
    ):
        entity_assertions.append(
            audit.marker(
                f"entity.webgpu.{suffix}",
                f"WebGPU {suffix} shader shares the Entity order",
                "webgpu",
                shader_path,
                _entity_layout_pattern("wgsl"),
                marker="Entity { pos vec2, vel vec2, size, cohort, padding vec2, color vec4 }",
            )
        )
    entity_assertions.extend(
        [
            audit.marker(
                "entity.runtime.stride",
                "HTML runtime declares a 48-byte stride",
                "webgpu",
                template,
                r"const\s+ENTITY_STRIDE\s*=\s*48\s*;",
                marker="const ENTITY_STRIDE = 48",
            ),
            audit.marker(
                "entity.runtime.allocation",
                "Entity allocation uses the declared stride",
                "webgpu",
                template,
                r"size\s*:\s*particleCount\s*\*\s*ENTITY_STRIDE",
                marker="entity buffer size = particleCount * ENTITY_STRIDE",
            ),
        ]
    )
    audit.add_check(
        "entity-layout",
        "48-byte Entity layout",
        "The storage record remains 12 floats (48 bytes) in canonical field order across every shader that reads it.",
        entity_assertions,
    )

    # Fourier rule shape, basis, hash, and generated-rule constants.
    fourier_assertions = [
        audit.marker(
            "fourier.canonical.center",
            "Canonical center is two vec4 values",
            "canonical",
            canonical_fourier,
            r"struct\s+FourierCenter\s*\{\s*vec4\s+frequency\s*;[\s\S]*?vec4\s+amplitude\s*;",
            marker="FourierCenter = frequency vec4 + amplitude vec4",
        ),
        audit.marker(
            "fourier.canonical.count",
            "Canonical rule uses ten centers",
            "canonical",
            canonical_entity,
            r"FourierCenter\s+centers\s*\[\s*10\s*\]\s*;",
            marker="FourierCenter centers[10]",
        ),
        audit.marker(
            "fourier.webgpu.center",
            "WebGPU center is two vec4<f32> values",
            "webgpu",
            entity,
            r"struct\s+FourierCenter\s*\{\s*frequency\s*:\s*vec4<f32>\s*,\s*amplitude\s*:\s*vec4<f32>",
            marker="FourierCenter = frequency vec4<f32> + amplitude vec4<f32>",
        ),
        audit.marker(
            "fourier.webgpu.count",
            "WebGPU rule uses ten centers",
            "webgpu",
            entity,
            r"centers\s*:\s*array<FourierCenter\s*,\s*10>",
            marker="array<FourierCenter, 10>",
        ),
        audit.marker(
            "fourier.runtime.bytes",
            "Runtime allocates 320 rule bytes",
            "webgpu",
            template,
            r"const\s+RULE_BYTES\s*=\s*320\s*;",
            marker="const RULE_BYTES = 320",
        ),
        audit.marker(
            "fourier.runtime.upload",
            "Runtime requires an 80-float rule upload",
            "webgpu",
            template,
            r"new\s+Float32Array\(CONFIG\.rule\)[\s\S]*?rule\.byteLength\s*!==\s*RULE_BYTES",
            marker="80 floats are uploaded and checked against RULE_BYTES",
        ),
    ]
    for source_path, role, prefix in (
        (canonical_fourier, "canonical", "fourier.canonical"),
        (entity, "webgpu", "fourier.webgpu"),
    ):
        fourier_assertions.extend(
            [
                audit.marker(
                    f"{prefix}.pcg",
                    f"{role.title()} PCG hash constants match",
                    role,
                    source_path,
                    r"747796405u[\s\S]*?2891336453u[\s\S]*?277803737u[\s\S]*?22u",
                    marker="PCG constants 747796405, 2891336453, 277803737 and shift 22",
                ),
                audit.marker(
                    f"{prefix}.hash4",
                    f"{role.title()} four-lane hash transforms match",
                    role,
                    source_path,
                    r"(?:hash|hash2)\s*\([\s\S]*?(?:5(?:\.0)?)[\s\S]*?(?:100(?:\.0)?)[\s\S]*?(?:25(?:\.0)?)",
                    marker="hash4 lanes use +5, -100, and +25 transforms",
                ),
                audit.marker(
                    f"{prefix}.basis",
                    f"{role.title()} Fourier basis constants match",
                    role,
                    source_path,
                    r"0\.6283[\s\S]*?3\.14159[\s\S]*?0\.7[\s\S]*?1\.3[\s\S]*?0\.5",
                    marker="phase offset and sin/cos basis constants",
                ),
                audit.marker(
                    f"{prefix}.generation",
                    f"{role.title()} generated-rule frequency/amplitude contract matches",
                    role,
                    source_path,
                    r"for\s*\([\s\S]*?<\s*10u?[\s\S]*?(?:freq_scale|frequency_scale)[\s\S]*?(?:i\s*\*\s*8\s*\+\s*7|base\s*\+\s*7u)",
                    marker="ten centers consume eight deterministic hash lanes each",
                ),
            ]
        )
    audit.add_check(
        "fourier-rule",
        "Ten-center Fourier rule and hash",
        "The browser retains the 320-byte saved-rule shape, Fourier basis, PCG constants, hash lanes, and generated-rule constants.",
        fourier_assertions,
    )

    # Physics setting table and version-7 field coverage.
    definitions = _setting_definitions(audit.sources.text(template))
    definitions_evidence = audit.sources.find(
        template,
        r"const\s+settingDefinitions\s*=\s*\[[\s\S]*?\]\s*;",
        marker="settingDefinitions ordered table",
    )
    setting_assertions = [
        audit.value(
            "settings.definition-order",
            "The JavaScript table has the exact 12-entry order",
            "webgpu",
            definitions == list(PHYSICS_SETTINGS),
            detail=(
                None
                if definitions == list(PHYSICS_SETTINGS)
                else f"Expected {list(PHYSICS_SETTINGS)!r}; found {definitions!r}"
            ),
            evidence=[definitions_evidence] if definitions_evidence else (),
        ),
        audit.marker(
            "settings.wgsl.shape",
            "WGSL stores twelve padded 32-byte settings",
            "webgpu",
            entity,
            r"struct\s+PhysicsSetting\s*\{\s*first\s*:\s*vec4<f32>\s*,\s*second\s*:\s*vec4<f32>[\s\S]*?array<PhysicsSetting\s*,\s*12>",
            marker="PhysicsSetting has two vec4<f32>; SettingsBuffer has 12 entries",
        ),
        audit.marker(
            "settings.runtime.bytes",
            "Runtime setting buffer size is 12 x 32 bytes",
            "webgpu",
            template,
            r"const\s+SETTINGS_BYTES\s*=\s*12\s*\*\s*32\s*;",
            marker="const SETTINGS_BYTES = 12 * 32",
        ),
        audit.marker(
            "settings.runtime.pack",
            "Runtime packs value, range, sweeps, and jitter",
            "webgpu",
            template,
            r"data\[base\]\s*=[\s\S]*?data\[base\s*\+\s*1\][\s\S]*?data\[base\s*\+\s*2\][\s\S]*?data\[base\s*\+\s*3\][\s\S]*?data\[base\s*\+\s*4\][\s\S]*?data\[base\s*\+\s*5\][\s\S]*?data\[base\s*\+\s*6\]",
            marker="setting upload writes value, min, max, x/y/cohort sweep, jitter",
        ),
        audit.ordered(
            "settings.canonical.assignment-order",
            "Canonical Python assigns the ten entity settings in matching order",
            "canonical",
            canonical_sim,
            [
                (name, rf"'(?:{re.escape(name)})_SETTING'")
                for name in (
                    "AXIAL_FORCE",
                    "LATERAL_FORCE",
                    "SENSOR_GAIN",
                    "MUTATION_SCALE",
                    "DRAG",
                    "STRAFE_POWER",
                    "SENSOR_ANGLE",
                    "GLOBAL_FORCE_MULT",
                    "SENSOR_DISTANCE",
                    "HAZARD_RATE",
                )
            ],
        ),
    ]
    preset_scan = _scan_v7_presets(audit.repo_root)
    field_coverage: list[dict[str, Any]] = []
    unclassified: list[str] = []
    mapped_without_evidence: list[str] = []
    for field_path in preset_scan["observed_fields"]:
        classification, rationale = _preset_field_policy(field_path)
        mapping_evidence = _field_mapping_evidence(
            audit,
            field_path,
            classification,
        )
        if classification == "unclassified":
            unclassified.append(field_path)
        if classification == "mapped" and not mapping_evidence:
            mapped_without_evidence.append(field_path)
        field_coverage.append(
            {
                "field": field_path,
                "classification": classification,
                "rationale": rationale,
                "evidence": [asdict(item) for item in mapping_evidence],
            }
        )
    setting_assertions.extend(
        [
            audit.value(
                "presets.present",
                "At least one version-7 preset was inspected",
                "canonical",
                bool(preset_scan["files"]),
                detail=(
                    None
                    if preset_scan["files"]
                    else "No version-7 JSON presets were found under physics_configs."
                ),
            ),
            audit.value(
                "presets.rules",
                "Every inspected version-7 preset has an 80-number rule",
                "canonical",
                not preset_scan["invalid_rules"],
                detail=(
                    None
                    if not preset_scan["invalid_rules"]
                    else "Invalid rule payloads: "
                    + ", ".join(preset_scan["invalid_rules"])
                ),
            ),
            audit.value(
                "presets.classified",
                "Every observed version-7 field is mapped, metadata, or deliberately omitted",
                "contract",
                not unclassified,
                detail=(
                    None
                    if not unclassified
                    else "Unclassified preset field(s): " + ", ".join(unclassified)
                ),
            ),
            audit.value(
                "presets.mapping-evidence",
                "Every field classified as mapped has source evidence",
                "contract",
                not mapped_without_evidence,
                detail=(
                    None
                    if not mapped_without_evidence
                    else "Mapped fields without source evidence: "
                    + ", ".join(mapped_without_evidence)
                ),
            ),
            audit.marker(
                "presets.builder.version",
                "Builder rejects non-version-7 configs",
                "webgpu",
                builder,
                r'config\.get\("version"\)\s*!=\s*7',
                marker="config version must equal 7",
            ),
            audit.marker(
                "presets.builder.rule",
                "Builder rejects rules that are not exactly 80 floats",
                "webgpu",
                builder,
                r"not\s+isinstance\(rule,\s*list\)\s+or\s+len\(rule\)\s*!=\s*80",
                marker="builder validates an 80-value rule",
            ),
        ]
    )
    audit.add_check(
        "physics-settings-and-presets",
        "Physics table and version-7 preset coverage",
        "The ordered 12-setting upload matches shader indices, and every field observed across version-7 presets is explicitly mapped, metadata, or a documented omission.",
        setting_assertions,
        notes=[
            f"Inspected {len(preset_scan['files'])} version-7 presets.",
            "Per-field coverage is recorded in preset_inventory.field_coverage.",
        ],
    )

    # Sensor and force scale constants.
    sensor_assertions = []
    for source_path, role, prefix in (
        (canonical_entity, "canonical", "sensor.canonical"),
        (entity, "webgpu", "sensor.webgpu"),
    ):
        sensor_assertions.extend(
            [
                audit.marker(
                    f"{prefix}.distance",
                    f"{role.title()} sensor distance uses 0.005 / sqrt(world size)",
                    role,
                    source_path,
                    r"(?:1\.\s*/\s*SQRT_WORLD_SIZE\s*\*\s*\.005|0\.005\s*/\s*sqrt_world_size)[\s\S]*?(?:sensor_distance|get_particle_sensor_distance|calculate_setting\(8u)",
                    marker="sample distance = 0.005 / sqrt(world size) * sensor distance",
                ),
                audit.marker(
                    f"{prefix}.gain",
                    f"{role.title()} sensor gain uses sqrt(world size) * 38.855",
                    role,
                    source_path,
                    r"(?:SQRT_WORLD_SIZE|sqrt_world_size)\s*\*\s*38\.855[\s\S]*?(?:sensor_gain|get_particle_sensor_gain|calculate_setting\(2u)",
                    marker="sensor scaling = sqrt(world size) * 38.855 * sensor gain",
                ),
                audit.marker(
                    f"{prefix}.force",
                    f"{role.title()} force output uses /400",
                    role,
                    source_path,
                    r"(?:force\s*\*=|behavior\.force)[\s\S]*?(?:/\s*400\.|400\.0\s*\*\s*sqrt_world_size)",
                    marker="force scale includes 1 / (400 * sqrt world size)",
                ),
                audit.marker(
                    f"{prefix}.strafe",
                    f"{role.title()} strafe output uses /20",
                    role,
                    source_path,
                    r"(?:strafe\s*\*=|behavior\.strafe)[\s\S]*?(?:/\s*20\.|20\.0\s*\*\s*sqrt_world_size)",
                    marker="strafe scale includes 1 / (20 * sqrt world size)",
                ),
            ]
        )
    audit.add_check(
        "sensor-and-force-scaling",
        "Sensor and motion scaling",
        "Sensor distance, sensor gain, force, and strafe retain the canonical world-size constants.",
        sensor_assertions,
    )

    # Saved-rule mutation.
    mutation_assertions = []
    for source_path, role, prefix in (
        (canonical_entity, "canonical", "mutation.canonical"),
        (entity, "webgpu", "mutation.webgpu"),
    ):
        mutation_assertions.extend(
            [
                audit.marker(
                    f"{prefix}.seed",
                    f"{role.title()} mutation seed uses centers 4, 7, and 1 plus cohort",
                    role,
                    source_path,
                    r"centers\s*\[\s*4\s*\]\.frequency\.xy[\s\S]*?centers\s*\[\s*7\s*\]\.amplitude\.yx[\s\S]*?centers\s*\[\s*1\s*\]\.frequency\.zw[\s\S]*?\+\s*cohort",
                    marker="mutation seed from centers[4], centers[7], centers[1], and cohort",
                ),
                audit.marker(
                    f"{prefix}.amplitude",
                    f"{role.title()} mutation adds signed hash4 amplitude noise",
                    role,
                    source_path,
                    r"(?:amp_mutation|amplitude_mutation)[\s\S]*?(?:hash4)[\s\S]*?amplitude\s*\+=",
                    marker="amplitude += amount * signed hash4 noise",
                ),
                audit.marker(
                    f"{prefix}.frequency",
                    f"{role.title()} mutation scales frequency by amount * 0.5",
                    role,
                    source_path,
                    r"frequency\s*\*=[\s\S]*?amount\s*\*\s*0\.5[\s\S]*?(?:hash|hash2)",
                    marker="frequency *= 1 + amount * 0.5 * hash delta",
                ),
            ]
        )
    mutation_assertions.append(
        audit.marker(
            "mutation.webgpu.setting",
            "WebGPU applies setting index 3 to the saved rule",
            "webgpu",
            entity,
            r"current_rule\s*=\s*mutate_rule\([\s\S]*?calculate_setting\(3u[\s\S]*?globals\.rule_params\.x\s*\+\s*floor\(cohort\)",
            marker="mutate_rule uses mutation setting index 3 and rule seed + cohort",
        )
    )
    audit.add_check(
        "saved-rule-mutation",
        "Saved-rule mutation",
        "Per-cohort rule mutation preserves the canonical seed sources and amplitude/frequency formulas.",
        mutation_assertions,
    )

    # Mirror symmetry and absolute-orientation modes.
    symmetry_assertions = [
        audit.marker(
            "symmetry.canonical.mirror",
            "Canonical behavior evaluates mirrored sensor inputs",
            "canonical",
            canonical_entity,
            r"mirrorterm\s*=\s*black_box\(y_reflect\(R\)\s*,\s*y_reflect\(L\)",
            marker="mirrored black-box evaluation",
        ),
        audit.marker(
            "symmetry.webgpu.mirror",
            "WebGPU behavior evaluates mirrored sensor inputs",
            "webgpu",
            entity,
            r"mirror_term\s*=\s*fourier_noise\([\s\S]*?y_reflect\(right_sample\)[\s\S]*?y_reflect\(left_sample\)",
            marker="mirrored Fourier evaluation",
        ),
        audit.marker(
            "symmetry.canonical.disable",
            "Canonical disable-symmetry mode zeroes the mirror term",
            "canonical",
            canonical_entity,
            r"if\s*\(\s*DISABLE_SYMMETRY\s*\)\s*\{\s*mirrorterm\s*=\s*vec4\(0\)",
            marker="DISABLE_SYMMETRY zeroes mirrorterm",
        ),
        audit.marker(
            "symmetry.webgpu.disable",
            "WebGPU disable-symmetry mode zeroes the mirror term",
            "webgpu",
            entity,
            r"if\s*\(\s*globals\.modes\.z\s*!=\s*0u\s*\)\s*\{\s*mirror_term\s*=\s*vec4<f32>\(0\.0\)",
            marker="globals.modes.z zeroes mirror_term",
        ),
        audit.marker(
            "orientation.canonical",
            "Canonical orientation supports velocity, Y-axis, and radial modes with mix",
            "canonical",
            canonical_entity,
            r"ORIENTATION_MODE[\s\S]*?ORIENTATION_MIX[\s\S]*?ORIENTATION_MODE\s*==\s*1[\s\S]*?vec2\(0\s*,\s*1\)[\s\S]*?ORIENTATION_MODE\s*==\s*2[\s\S]*?-normalize\(e\.pos\)",
            marker="orientation modes 0/1/2 and ORIENTATION_MIX",
        ),
        audit.marker(
            "orientation.webgpu",
            "WebGPU orientation supports velocity, Y-axis, and radial modes with mix",
            "webgpu",
            entity,
            r"orientation_mode[\s\S]*?globals\.appearance\.y[\s\S]*?orientation_mode\s*==\s*1u[\s\S]*?vec2<f32>\(0\.0\s*,\s*1\.0\)[\s\S]*?orientation_mode\s*==\s*2u[\s\S]*?-safe_normalize\(entity\.pos\)",
            marker="orientation modes 0/1/2 and uploaded orientation mix",
        ),
        audit.marker(
            "orientation.runtime",
            "HTML maps orientation and symmetry preset fields into globals",
            "webgpu",
            template,
            r"CONFIG\.settings\.orientation_mix[\s\S]*?CONFIG\.settings\.absolute_orientation[\s\S]*?CONFIG\.settings\.disable_symmetry",
            marker="orientation_mix, absolute_orientation, disable_symmetry globals mapping",
        ),
    ]
    audit.add_check(
        "symmetry-and-orientation",
        "Symmetry and absolute orientation",
        "Mirrored behavior, symmetry disabling, orientation modes, and orientation mixing remain mapped.",
        symmetry_assertions,
    )

    # Sweeps and jitter in entity and trail code.
    sweep_assertions = [
        audit.marker(
            "sweeps.canonical.entity",
            "Canonical entity settings average x/y/cohort sweeps and apply proportional jitter",
            "canonical",
            canonical_entity,
            r"setting\.x_sweep[\s\S]*?setting\.y_sweep[\s\S]*?setting\.cohort_sweep[\s\S]*?active_sweeps[\s\S]*?result\s*\+?=\s*setting\.jitter\s*\*\s*result\s*\*\s*random",
            marker="entity calculate_setting x/y/cohort sweeps, average, jitter",
        ),
        audit.marker(
            "sweeps.canonical.trail",
            "Canonical trail settings also implement sweeps and jitter",
            "canonical",
            canonical_canvas,
            r"setting\.x_sweep[\s\S]*?setting\.y_sweep[\s\S]*?setting\.cohort_sweep[\s\S]*?active_sweeps[\s\S]*?setting\.jitter\s*\*\s*result\s*\*\s*random",
            marker="canvas calculate_setting x/y/cohort sweeps, average, jitter",
        ),
        audit.marker(
            "sweeps.webgpu.entity",
            "WebGPU entity settings implement x/y/cohort sweeps and proportional jitter",
            "webgpu",
            entity,
            r"x_sweep[\s\S]*?y_sweep[\s\S]*?cohort_sweep[\s\S]*?active_sweeps[\s\S]*?result\s*\+=\s*jitter\s*\*\s*result\s*\*\s*random_value",
            marker="WGSL entity calculate_setting sweeps, average, jitter",
        ),
        audit.marker(
            "sweeps.webgpu.trail",
            "WebGPU trail settings implement x/y/cohort sweeps and proportional jitter",
            "webgpu",
            trail,
            r"x_sweep[\s\S]*?y_sweep[\s\S]*?cohort_sweep[\s\S]*?active_sweeps[\s\S]*?result\s*\+=\s*jitter\s*\*\s*result\s*\*\s*random_value",
            marker="WGSL trail calculate_setting sweeps, average, jitter",
        ),
        audit.marker(
            "sweeps.runtime.gate",
            "Runtime honors the parameter-sweep enable flag",
            "webgpu",
            template,
            r"if\s*\(!CONFIG\.parameter_sweeps_enabled\)\s*return\s+0",
            marker="disabled parameter sweeps upload zero",
        ),
        audit.marker(
            "sweeps.runtime.pack",
            "Runtime uploads all three sweep axes and jitter",
            "webgpu",
            template,
            r'sweepValue\("x"[\s\S]*?sweepValue\("y"[\s\S]*?sweepValue\("cohort"[\s\S]*?CONFIG\.jitters',
            marker="x/y/cohort sweeps and jitter are packed",
        ),
    ]
    audit.add_check(
        "sweeps-and-jitter",
        "Parameter sweeps and jitter",
        "Entity and trail settings retain positive/inverse x, y, and cohort sweeps, averaging, and proportional temporal jitter.",
        sweep_assertions,
    )

    # Initialization, hazard resets, and boundary handling.
    init_assertions = [
        audit.marker(
            "init.canonical.modes",
            "Canonical reset supports grid, random, and ring modes",
            "canonical",
            canonical_entity,
            r"reset_mode\s*==\s*0[\s\S]*?reset_mode\s*==\s*1[\s\S]*?reset_mode\s*==\s*2",
            marker="RESET_MODE 0 grid, 1 random, 2 ring",
        ),
        audit.marker(
            "init.webgpu.modes",
            "WebGPU reset supports grid, random, and ring modes",
            "webgpu",
            entity,
            r"globals\.modes\.x\s*==\s*0u[\s\S]*?globals\.modes\.x\s*==\s*1u[\s\S]*?else[\s\S]*?cos\(angle\)[\s\S]*?sin\(angle\)",
            marker="globals.modes.x 0 grid, 1 random, otherwise ring",
        ),
        audit.marker(
            "init.canonical.frame-hazard",
            "Canonical reset triggers on frame zero or hazard",
            "canonical",
            canonical_entity,
            r"frame_count\s*==\s*0\s*\|\|[\s\S]*?hazard_rate",
            marker="frame zero or hazard causes reset",
            flags=re.MULTILINE | re.IGNORECASE,
        ),
        audit.marker(
            "init.webgpu.frame-hazard",
            "WebGPU reset triggers on frame zero or hazard",
            "webgpu",
            entity,
            r"globals\.sim\.x\s*==\s*0u\s*\|\|\s*hazard_rate\s*>\s*hazard_sample",
            marker="frame zero or hazard causes reset",
        ),
        audit.marker(
            "boundary.canonical",
            "Canonical boundary modes are bounce, reset, and wrap",
            "canonical",
            canonical_entity,
            r"boundary_mode\s*==\s*0[\s\S]*?boundary_mode\s*==\s*1[\s\S]*?boundary_mode\s*==\s*2",
            marker="boundary modes 0 bounce, 1 reset, 2 wrap",
        ),
        audit.marker(
            "boundary.webgpu",
            "WebGPU boundary modes are bounce, reset, and wrap",
            "webgpu",
            entity,
            r"boundary_mode\s*==\s*0u[\s\S]*?boundary_mode\s*==\s*1u[\s\S]*?else[\s\S]*?fract\(entity\.pos",
            marker="boundary modes 0 bounce, 1 reset, otherwise wrap",
        ),
        audit.marker(
            "init.runtime.mapping",
            "Runtime maps initial and boundary preset modes",
            "webgpu",
            template,
            r"CONFIG\.settings\.boundary_conditions[\s\S]*?CONFIG\.settings\.initial_conditions",
            marker="boundary_conditions and initial_conditions globals mapping",
        ),
    ]
    audit.add_check(
        "initialization-and-boundaries",
        "Initialization, hazard, and boundary modes",
        "Grid/random/ring initialization, frame-zero and hazard reset, and bounce/reset/wrap boundaries remain mapped.",
        init_assertions,
    )

    # Brush occurs before entity update and retains the unusual blend semantics.
    brush_assertions = [
        audit.ordered(
            "brush.canonical.order",
            "Canonical frame order is brush, entity update, then trail resolve",
            "canonical",
            canonical_sim,
            [
                ("self.brush_update(ctx)", r"self\.brush_update\(ctx\)"),
                ("self.entity_update(ctx", r"self\.entity_update\(ctx"),
                ("self.can_update(ctx", r"self\.can_update\(ctx"),
            ],
        ),
        audit.ordered(
            "brush.webgpu.order",
            "WebGPU frame order is pre-update brush, entity update, then trail resolve",
            "webgpu",
            template,
            [
                ("Pre-update particle brush", r'"Pre-update particle brush"'),
                ("Entity update", r'"Entity update"'),
                ("Trail resolve", r'"Trail resolve"'),
            ],
        ),
        audit.marker(
            "brush.canonical.payload",
            "Canonical brush deposits velocity, 0.01 density, and alpha through a Gaussian",
            "canonical",
            canonical_brush_fragment,
            r"vec4\(vel\s*,\s*\.01\s*,\s*1\)\s*\*\s*kernel_func",
            marker="vec4(velocity, .01, 1) * Gaussian",
        ),
        audit.marker(
            "brush.webgpu.payload",
            "WebGPU brush deposits velocity, 0.01 density, and alpha through a Gaussian",
            "webgpu",
            brush,
            r"vec4<f32>\(input\.velocity\s*,\s*0\.01\s*,\s*1\.0\)\s*\*\s*kernel",
            marker="vec4<f32>(velocity, 0.01, 1.0) * Gaussian",
        ),
        audit.marker(
            "brush.canonical.blend",
            "Canonical brush blend is SRC_ALPHA plus ONE",
            "canonical",
            canonical_sim,
            r"ctx\.blend_func\s*=\s*moderngl\.SRC_ALPHA\s*,\s*moderngl\.ONE",
            marker="blend_func = SRC_ALPHA, ONE",
        ),
        audit.marker(
            "brush.webgpu.blend",
            "WebGPU brush blend is src-alpha plus one",
            "webgpu",
            template,
            r'srcFactor\s*:\s*"src-alpha"[\s\S]*?dstFactor\s*:\s*"one"[\s\S]*?operation\s*:\s*"add"',
            marker='srcFactor "src-alpha", dstFactor "one", operation "add"',
        ),
        audit.marker(
            "brush.webgpu.clear",
            "The particle brush target is cleared before every deposition pass",
            "webgpu",
            template,
            r'"Pre-update particle brush"[\s\S]*?textureResource\(textures\.brush\)[\s\S]*?true',
            marker="brush pass uses clear=true each frame",
        ),
    ]
    audit.add_check(
        "pre-update-brush",
        "Pre-update brush and blend contract",
        "Particles deposit their pre-update velocity/density before compute, with the canonical Gaussian payload and SRC_ALPHA/ONE blend.",
        brush_assertions,
    )

    # Five-tap diffusion and persistence.
    diffusion_assertions = [
        audit.marker(
            "trail.canonical.five-tap",
            "Canonical trail blur is center plus four cardinal taps",
            "canonical",
            canonical_canvas,
            r"getCan\(pos\s*,\s*sam\)\s*\*\s*K\s*\+\s*nc\s*\+\s*sc\s*\+\s*wc\s*\+\s*ec[\s\S]*?4\.\s*\+\s*K",
            marker="(center*K + north + south + west + east) / (4 + K)",
        ),
        audit.marker(
            "trail.webgpu.five-tap",
            "WebGPU trail blur is center plus four cardinal taps",
            "webgpu",
            trail,
            r"center\s*\*\s*diffusion_constant\s*\+\s*north\s*\+\s*south\s*\+\s*west\s*\+\s*east[\s\S]*?4\.0\s*\+\s*diffusion_constant",
            marker="(center*K + north + south + west + east) / (4 + K)",
        ),
        audit.marker(
            "trail.canonical.diffusion-map",
            "Canonical diffusion squares the slider then maps through 4/(5^d-1)",
            "canonical",
            canonical_canvas,
            r"TRAIL_DIFFUSION\s*=\s*TRAIL_DIFFUSION\s*\*\s*TRAIL_DIFFUSION[\s\S]*?4\s*/\s*\(\s*pow\(5\s*,\s*\(TRAIL_DIFFUSION\)\)\s*-\s*1",
            marker="diffusion^2 then K = 4 / (pow(5, diffusion) - 1)",
        ),
        audit.marker(
            "trail.webgpu.diffusion-map",
            "WebGPU diffusion squares the slider then maps through 4/(5^d-1)",
            "webgpu",
            trail,
            r"diffusion\s*\*=\s*diffusion[\s\S]*?4\.0\s*/\s*\(\s*pow\(5\.0\s*,\s*diffusion\)\s*-\s*1\.0",
            marker="diffusion^2 then K = 4 / (pow(5, diffusion) - 1)",
        ),
        audit.marker(
            "trail.canonical.persistence",
            "Canonical resolve mixes blurred trail and brush by persistence",
            "canonical",
            canonical_canvas,
            r"can_color\s*\*\s*trail_persistence\s*\+\s*\(\s*1\s*-\s*trail_persistence\s*\)\s*\*\s*brush_color",
            marker="blurred trail * persistence + brush * (1 - persistence)",
        ),
        audit.marker(
            "trail.webgpu.persistence",
            "WebGPU resolve mixes blurred trail and brush by persistence",
            "webgpu",
            trail,
            r"blurred_trail\s*\*\s*persistence\s*\+\s*particle_brush\s*\*\s*\(\s*1\.0\s*-\s*persistence\s*\)",
            marker="blurred trail * persistence + brush * (1 - persistence)",
        ),
    ]
    audit.add_check(
        "trail-resolve",
        "Five-tap diffusion and persistence",
        "Trail feedback retains the five-tap cross kernel, nonlinear diffusion control, and persistence mix.",
        diffusion_assertions,
    )

    # Explicit legal WebGPU feedback.
    pingpong_assertions = [
        audit.marker(
            "pingpong.trail.resources",
            "Runtime allocates two trail textures",
            "webgpu",
            template,
            r"trails\s*:\s*\[\s*createFloatTexture\(\"everything trail A\"\)\s*,\s*createFloatTexture\(\"everything trail B\"\)",
            marker="trail A and trail B textures",
        ),
        audit.marker(
            "pingpong.trail.swap",
            "Trail source and destination indices are explicitly swapped",
            "webgpu",
            template,
            r"nextTrailIndex\s*=\s*1\s*-\s*trailIndex[\s\S]*?textures\.trails\[nextTrailIndex\][\s\S]*?bindGroups\.trail\[trailIndex\][\s\S]*?trailIndex\s*=\s*nextTrailIndex",
            marker="read trailIndex, write 1-trailIndex, then swap",
        ),
        audit.marker(
            "pingpong.accum.resources",
            "Runtime allocates two accumulation textures",
            "webgpu",
            template,
            r"accumulations\s*:\s*\[\s*createFloatTexture\(\"everything accumulation A\"\)\s*,\s*createFloatTexture\(\"everything accumulation B\"\)",
            marker="accumulation A and accumulation B textures",
        ),
        audit.marker(
            "pingpong.accum.swap",
            "Accumulation source and destination indices are explicitly swapped",
            "webgpu",
            template,
            r"nextAccumulationIndex\s*=\s*1\s*-\s*accumulationIndex[\s\S]*?textures\.accumulations\[nextAccumulationIndex\][\s\S]*?bindGroups\.accumulate\[accumulationIndex\][\s\S]*?accumulationIndex\s*=\s*nextAccumulationIndex",
            marker="read accumulationIndex, write 1-accumulationIndex, then swap",
        ),
        audit.marker(
            "pingpong.trail.readonly",
            "Trail shader declares its previous trail as sampled read-only input",
            "webgpu",
            trail,
            r"var\s+previous_trail\s*:\s*texture_2d<f32>",
            marker="previous_trail sampled texture",
        ),
        audit.marker(
            "pingpong.accum.readonly",
            "Accumulation shader declares previous accumulation as sampled read-only input",
            "webgpu",
            accumulate,
            r"var\s+previous_accumulation\s*:\s*texture_2d<f32>",
            marker="previous_accumulation sampled texture",
        ),
    ]
    audit.add_check(
        "explicit-ping-pong",
        "Explicit trail and accumulation ping-pong",
        "Every feedback pass samples one texture and renders into the other, then swaps roles.",
        pingpong_assertions,
    )

    # Pointer drawing and erasing.
    pointer_assertions = [
        audit.marker(
            "pointer.events",
            "Runtime handles pointer down, move, up, and cancel",
            "webgpu",
            template,
            r'addEventListener\("pointerdown"[\s\S]*?addEventListener\("pointermove"[\s\S]*?addEventListener\("pointerup"[\s\S]*?addEventListener\("pointercancel"',
            marker="pointerdown/move/up/cancel handlers",
        ),
        audit.marker(
            "pointer.erase-ui",
            "Right-drag activates erase and the context menu is suppressed",
            "webgpu",
            template,
            r'addEventListener\("contextmenu"[\s\S]*?pointer\.erase\s*=\s*event\.button\s*===\s*2\s*\|\|\s*event\.buttons\s*===\s*2',
            marker="contextmenu suppressed; button 2 maps to erase",
        ),
        audit.marker(
            "pointer.globals",
            "Runtime uploads current/previous pointer positions and draw/erase flags",
            "webgpu",
            template,
            r"floats\[4\]\s*=\s*pointer\.currentX[\s\S]*?floats\[7\]\s*=\s*pointer\.previousY[\s\S]*?uints\[28\]\s*=\s*pointer\.down[\s\S]*?uints\[29\]\s*=\s*pointer\.erase",
            marker="pointer positions and draw/erase flags are uploaded",
        ),
        audit.marker(
            "pointer.draw",
            "Trail shader adds a Gaussian pointer velocity field",
            "webgpu",
            trail,
            r"globals\.flags\.x\s*!=\s*0u[\s\S]*?globals\.flags\.y\s*==\s*0u[\s\S]*?draw_vector[\s\S]*?draw_kernel[\s\S]*?1\.0\s*-\s*persistence",
            marker="active non-erase pointer adds draw vector through Gaussian kernel",
        ),
        audit.marker(
            "pointer.erase",
            "Trail shader hard-erases within twice the draw radius",
            "webgpu",
            trail,
            r"globals\.flags\.x\s*!=\s*0u\s*&&\s*globals\.flags\.y\s*!=\s*0u[\s\S]*?erase_distance\s*<\s*draw_size\s*\*\s*2\.0[\s\S]*?result\s*=\s*vec4<f32>\(0\.0\s*,\s*0\.0\s*,\s*0\.0\s*,\s*1\.0\)",
            marker="erase mode clears a hard circle of radius draw_size*2",
        ),
        audit.marker(
            "pointer.canonical.draw",
            "Canonical trail shader applies pointer drawing and erasing",
            "canonical",
            canonical_canvas,
            r"draw_mode[\s\S]*?draw_vector[\s\S]*?kernel_weight[\s\S]*?erase_mode[\s\S]*?erase_distance\s*<\s*draw_size\s*\*\s*2",
            marker="canonical draw mode plus right-click eraser",
        ),
    ]
    audit.add_check(
        "pointer-interaction",
        "Pointer draw and erase interactions",
        "Pointer/touch drag bends the trail field and right-drag erases it without privileged browser APIs.",
        pointer_assertions,
    )

    # Color behavior and watercolor path.
    color_assertions = [
        audit.marker(
            "color.canonical.entity",
            "Canonical entity color uses hue sensitivity or cohort hue",
            "canonical",
            canonical_entity,
            r"e\.color\.x\s*=\s*get_particle_hue_sensitivity\(\)\s*\*\s*col_params\.x[\s\S]*?get_particle_color_by_cohort\(\)[\s\S]*?hash\(vec2\(floor\(cohort\)\)\)",
            marker="hue sensitivity and color-by-cohort",
        ),
        audit.marker(
            "color.webgpu.entity",
            "WebGPU entity color uses hue sensitivity or cohort hue",
            "webgpu",
            entity,
            r"entity\.color\.x\s*=\s*globals\.appearance\.x\s*\*\s*behavior\.color\.x[\s\S]*?globals\.modes\.w[\s\S]*?hash2\(vec2<f32>\(floor\(cohort\)\)\)",
            marker="uploaded hue sensitivity and color-by-cohort",
        ),
        audit.marker(
            "color.runtime.mapping",
            "Runtime maps hue sensitivity, color-by-cohort, ink weight, and watercolor",
            "webgpu",
            template,
            r"CONFIG\.appearance\.hue_sensitivity[\s\S]*?CONFIG\.appearance\.ink_weight[\s\S]*?CONFIG\.appearance\.color_by_cohort[\s\S]*?CONFIG\.appearance\.watercolor_mode",
            marker="appearance color and watercolor fields map into globals",
        ),
        audit.marker(
            "watercolor.canonical.particles",
            "Canonical particles use log-space optical density in watercolor mode",
            "canonical",
            canonical_particles,
            r"WATERCOLOR_MODE[\s\S]*?log\(particle_chroma\)\s*\*\s*view_col\.z[\s\S]*?hsv2rgb\(view_col\.xyz\)",
            marker="watercolor log(chroma) path and normal HSV path",
        ),
        audit.marker(
            "watercolor.webgpu.particles",
            "WebGPU particles use log-space optical density in watercolor mode",
            "webgpu",
            particles,
            r"globals\.flags\.w\s*!=\s*0u[\s\S]*?log\(particle_chroma\)\s*\*\s*input\.color\.z[\s\S]*?hsv_to_rgb\(input\.color\.xyz\)",
            marker="watercolor log(chroma) path and normal HSV path",
        ),
        audit.marker(
            "watercolor.canonical.transmission",
            "Canonical assembly converts watercolor density through exp(ink*10*density)",
            "canonical",
            canonical_assembly,
            r"WATERCOLOR_MODE[\s\S]*?exp\(INK_WEIGHT\s*\*\s*INK_CONSTANT\s*\*\s*current_color\)",
            marker="exp(INK_WEIGHT * 10 * current_color)",
        ),
        audit.marker(
            "watercolor.webgpu.transmission",
            "WebGPU accumulation converts watercolor density through exp(ink*10*density)",
            "webgpu",
            accumulate,
            r"globals\.flags\.w\s*!=\s*0u[\s\S]*?exp\([\s\S]*?globals\.render\.x\s*\*\s*10\.0",
            marker="exp(current_color * ink_weight * 10)",
        ),
    ]
    audit.add_check(
        "color-and-watercolor",
        "Color and watercolor rendering",
        "Hue behavior, cohort coloring, log-space watercolor deposition, and optical transmission remain mapped.",
        color_assertions,
    )

    # Tone mapping. Accumulation feedback intentionally differs and is reported below.
    tone_assertions = [
        audit.marker(
            "tone.canonical",
            "Canonical final pass applies brightness then asinh softness",
            "canonical",
            canonical_assembly,
            r"fragColor\.xyz\s*\*=\s*BRIGHTNESS_CONSTANT[\s\S]*?asinh\(len\s*\*\s*TONEMAP_SOFTNESS\)\s*/\s*\(len\s*\*\s*TONEMAP_SOFTNESS\)",
            marker="brightness then asinh(length*softness)/(length*softness)",
        ),
        audit.marker(
            "tone.webgpu",
            "WebGPU final pass applies brightness then asinh softness",
            "webgpu",
            present,
            r"color\s*\*=\s*3\.0\s*\*\s*max\(globals\.appearance\.z[\s\S]*?inverse_hyperbolic_sine\(color_length\s*\*\s*softness\)[\s\S]*?color_length\s*\*\s*softness",
            marker="3*brightness then asinh(length*softness)/(length*softness)",
        ),
        audit.marker(
            "tone.runtime.controls",
            "Runtime uploads brightness and tone-map softness",
            "webgpu",
            template,
            r"floats\[14\]\s*=\s*controls\.brightness[\s\S]*?floats\[15\]\s*=\s*controls\.tonemapSoftness",
            marker="brightness and tonemapSoftness globals",
        ),
        audit.marker(
            "tone.accumulation",
            "WebGPU temporal accumulation remains in linear space before presentation",
            "webgpu",
            accumulate,
            r"mix\(current_color\s*,\s*previous_color\s*,\s*exposure\)",
            marker="linear mix(current, previous, exposure)",
        ),
    ]
    audit.add_check(
        "tone-mapping",
        "Tone mapping and temporal accumulation",
        "The final brightness/asinh display map is retained; the intentional raw-linear accumulation variant is explicitly bounded.",
        tone_assertions,
        notes=[
            "This check does not claim equality with the desktop tone-map/undo-tone-map feedback loop.",
        ],
    )

    # Self-containment and opaque-origin sandbox safety.
    forbidden_patterns = {
        "remote URL": r"(?:https?|wss?)://",
        "external script": r"<script\b[^>]*\bsrc\s*=",
        "external stylesheet": r"<link\b[^>]*\bhref\s*=",
        "fetch": r"\bfetch\s*\(",
        "XMLHttpRequest": r"\bXMLHttpRequest\b",
        "WebSocket": r"\bWebSocket\s*\(",
        "EventSource": r"\bEventSource\s*\(",
        "sendBeacon": r"\bsendBeacon\s*\(",
        "localStorage": r"\blocalStorage\b",
        "sessionStorage": r"\bsessionStorage\b",
        "IndexedDB": r"\bindexedDB\b",
        "Cache Storage": r"\bcaches\s*\.",
        "service worker": r"\bserviceWorker\b",
        "cookies": r"\bdocument\.cookie\b",
    }
    template_text = audit.sources.text(template)
    forbidden_hits: list[str] = []
    if template_text is None:
        forbidden_hits.append("template missing")
    else:
        for label, pattern in forbidden_patterns.items():
            if re.search(pattern, template_text, re.IGNORECASE | re.MULTILINE):
                forbidden_hits.append(label)
    sandbox_assertions = [
        audit.marker(
            "sandbox.csp",
            "Inline CSP blocks network connections, objects, bases, and form actions",
            "webgpu",
            template,
            r"default-src\s+'none'[\s\S]*?connect-src\s+'none'[\s\S]*?object-src\s+'none'[\s\S]*?base-uri\s+'none'[\s\S]*?form-action\s+'none'",
            marker="restrictive self-contained Content-Security-Policy",
        ),
        audit.value(
            "sandbox.forbidden-apis",
            "Template contains no network or persistent-storage primitives",
            "webgpu",
            not forbidden_hits,
            detail=(
                None
                if not forbidden_hits
                else "Forbidden self-containment marker(s): "
                + ", ".join(forbidden_hits)
            ),
        ),
        audit.marker(
            "sandbox.inline-shaders",
            "WGSL is embedded through inline template placeholders",
            "webgpu",
            template,
            r"const\s+SHADERS\s*=\s*Object\.freeze\(\{[\s\S]*?@@EVERYTHING_WGSL_ENTITY@@[\s\S]*?@@EVERYTHING_WGSL_PRESENT@@",
            marker="all WGSL sources are inline template values",
        ),
        audit.marker(
            "sandbox.builder.inline",
            "Builder replaces shader placeholders with JavaScript-safe JSON strings",
            "webgpu",
            builder,
            r"for\s+_path\s*,\s*placeholder\s*,\s*source\s+in\s+shaders[\s\S]*?_json_for_script\(source\)",
            marker="shader sources are JSON-escaped and inlined",
        ),
        audit.marker(
            "sandbox.harness",
            "Repository sandbox harness uses only allow-scripts",
            "contract",
            "runtime/webgpu/sandbox-harness.html",
            r'sandbox\s*=\s*"allow-scripts"',
            marker='sandbox="allow-scripts"',
        ),
    ]
    audit.add_check(
        "sandbox-self-containment",
        "Sandbox and self-containment",
        "The artifact is inline-only, blocks network access, avoids persistent browser state, and is designed for an opaque-origin allow-scripts iframe.",
        sandbox_assertions,
    )

    omission_specs = [
        (
            "intermediate-precision",
            "RGBA16F intermediate targets replace canonical RGBA32F targets for portable WebGPU filtering/blending.",
            r"rgba16float",
            "runtime/webgpu/README.md",
        ),
        (
            "per-particle-rule-readback",
            "The desktop per-particle 320-byte rule readback/output buffer is not allocated.",
            r"per-particle rule readback buffer",
            "runtime/webgpu/README.md",
        ),
        (
            "multi-load-editor",
            "Multi-load editing is outside the first artifact-kernel boundary.",
            r"omits multi-load editing",
            "runtime/webgpu/README.md",
        ),
        (
            "advanced-field-layers",
            "Advanced force/strafe field layers are outside the first artifact-kernel boundary.",
            r"advanced force/strafe field layers",
            "runtime/webgpu/README.md",
        ),
        (
            "camera-and-tiling",
            "Desktop camera pan/zoom and tiling are outside the first artifact-kernel boundary.",
            r"camera\s+pan\s+and\s+zoom\s*,\s*tiling",
            "runtime/webgpu/README.md",
        ),
        (
            "emboss-and-bloom",
            "Emboss and bloom are outside the first artifact-kernel boundary.",
            r"emboss\s*,\s*bloom",
            "runtime/webgpu/README.md",
        ),
        (
            "desktop-tooling",
            "Recording, shader hot reload, and filesystem operations are outside the HTML artifact.",
            r"desktop recording\s*,\s*shader hot reload\s*,[\s\S]*?filesystem operations",
            "runtime/webgpu/README.md",
        ),
        (
            "trial-dish",
            "Trial Dish game systems are outside the first artifact-kernel boundary.",
            r"Trial Dish game systems",
            "runtime/webgpu/README.md",
        ),
        (
            "accumulation-feedback",
            "The browser accumulates raw linear color before final tone mapping instead of reproducing the desktop tone-map/undo-tone-map feedback loop.",
            r"Raw-linear temporal[\s\S]*?tone-map/undo-tone-map feedback loop",
            "runtime/webgpu/README.md",
        ),
    ]
    deliberate_omissions: list[dict[str, Any]] = []
    omission_assertions: list[AssertionResult] = []
    for omission_id, description, pattern, path in omission_specs:
        evidence = audit.sources.find(
            path,
            pattern,
            marker=description,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        documented = evidence is not None
        omission_assertions.append(
            audit.value(
                f"omission.{omission_id}",
                description,
                "boundary",
                documented,
                detail=None if documented else "The omission is not documented.",
                evidence=[evidence] if evidence else (),
            )
        )
        deliberate_omissions.append(
            {
                "id": omission_id,
                "description": description,
                "status": "documented" if documented else "undocumented",
                "evidence": [asdict(evidence)] if evidence else [],
            }
        )
    audit.add_check(
        "documented-boundary",
        "Deliberate first-release boundary",
        "Known fidelity and product-scope exclusions are visible rather than hidden behind a broad parity claim.",
        omission_assertions,
        notes=[
            "These documented exclusions are reported separately and are not required-kernel failures.",
        ],
    )

    preset_inventory = {
        "version": 7,
        "preset_count": len(preset_scan["files"]),
        "files": preset_scan["files"],
        "invalid_json": preset_scan["invalid_json"],
        "invalid_rules": preset_scan["invalid_rules"],
        "observed_fields": preset_scan["observed_fields"],
        "field_coverage": field_coverage,
        "classification_counts": {
            classification: sum(
                1
                for item in field_coverage
                if item["classification"] == classification
            )
            for classification in (
                "mapped",
                "metadata",
                "deliberate_omission",
                "unclassified",
            )
        },
    }
    return preset_inventory, deliberate_omissions


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


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# networked.art/everything source-contract audit",
        "",
        f"Verdict: **{summary['verdict']}**",
        "",
        (
            f"Required checks: {summary['required_passed']}/"
            f"{summary['required_total']} passed. "
            f"All checks: {summary['passed']}/{summary['total']} passed."
        ),
        "",
        "> Scope: static source-contract coverage only. This report does not execute "
        "WebGPU and does not establish numeric, deterministic-buffer, screenshot, "
        "or pixel parity.",
        "",
        "## Required contracts",
        "",
        "| Status | Contract | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        status = "PASS" if check["status"] == "pass" else "FAIL"
        evidence_count = sum(
            len(assertion["evidence"]) for assertion in check["assertions"]
        )
        required = "required" if check["required"] else "informational"
        lines.append(
            f"| {status} | `{check['id']}` — {check['title']} ({required}) | "
            f"{evidence_count} source marker(s) |"
        )

    for check in report["checks"]:
        lines.extend(["", f"### {check['title']}", "", check["claim"], ""])
        for assertion in check["assertions"]:
            status = "PASS" if assertion["passed"] else "FAIL"
            lines.append(f"- **{status}** `{assertion['id']}` — {assertion['label']}")
            if assertion.get("detail"):
                lines.append(f"  - {assertion['detail']}")
            for evidence in assertion["evidence"]:
                location = (
                    f"{evidence['path']}:{evidence['line_start']}"
                    if evidence["line_start"] == evidence["line_end"]
                    else (
                        f"{evidence['path']}:{evidence['line_start']}-"
                        f"{evidence['line_end']}"
                    )
                )
                lines.append(
                    f"  - `{location}` — {evidence['marker']}: "
                    f"`{evidence['excerpt'].replace('`', chr(39))}`"
                )
        for note in check["notes"]:
            lines.append(f"- Note: {note}")

    inventory = report["preset_inventory"]
    lines.extend(
        [
            "",
            "## Version-7 preset field accounting",
            "",
            f"Inspected {inventory['preset_count']} version-7 preset files.",
            "",
            "| Classification | Count |",
            "| --- | ---: |",
        ]
    )
    for classification, count in inventory["classification_counts"].items():
        lines.append(f"| {classification} | {count} |")
    lines.extend(
        [
            "",
            "Every observed field path and its exact mapping evidence is available in "
            "the JSON report under `preset_inventory.field_coverage`.",
            "",
            "## Deliberate omissions",
            "",
        ]
    )
    for omission in report["deliberate_omissions"]:
        status = omission["status"].upper()
        lines.append(f"- **{status}** `{omission['id']}` — {omission['description']}")
        for evidence in omission["evidence"]:
            lines.append(
                f"  - `{evidence['path']}:{evidence['line_start']}` — "
                f"{evidence['marker']}"
            )
    lines.extend(
        [
            "",
            "## What this report does not prove",
            "",
            "- It does not compile WGSL or create a GPU device.",
            "- It does not compare particle buffers or trail textures.",
            "- It does not compare rendered images or establish a pixel tolerance.",
            "- It does not replace the browser smoke test or sandboxed-iframe test.",
            "",
        ]
    )
    return "\n".join(lines)


def run_audit(repo_root: Path) -> dict[str, Any]:
    audit = Audit(repo_root)
    preset_inventory, deliberate_omissions = _build_checks(audit)
    required_checks = [check for check in audit.checks if check.required]
    required_failures = [
        check.id for check in required_checks if check.status != "pass"
    ]
    all_failures = [check.id for check in audit.checks if check.status != "pass"]
    summary = {
        "verdict": (
            "complete_source_contract_coverage"
            if not required_failures
            else "required_source_contract_gaps"
        ),
        "total": len(audit.checks),
        "passed": len(audit.checks) - len(all_failures),
        "failed": len(all_failures),
        "required_total": len(required_checks),
        "required_passed": len(required_checks) - len(required_failures),
        "required_failed": len(required_failures),
        "required_failure_ids": required_failures,
        "all_failure_ids": all_failures,
        "numeric_or_pixel_parity_validated": False,
        "browser_runtime_validated": False,
    }
    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root.resolve()),
        "scope": {
            "kind": "static_source_contract_coverage",
            "claims_numeric_parity": False,
            "claims_pixel_parity": False,
            "claims_browser_execution": False,
            "description": (
                "Checks source layouts, constants, mappings, pass order, "
                "self-containment, and documented artifact-kernel boundaries."
            ),
        },
        "summary": summary,
        "checks": [asdict(check) for check in audit.checks],
        "preset_inventory": preset_inventory,
        "deliberate_omissions": deliberate_omissions,
        "inputs": audit.sources.inputs(),
    }


def _resolve_output(repo_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else repo_root / path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit the WebGPU artifact's static source contracts against "
            "the canonical GLSL/Python engine."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help="Repository root (default: inferred from this script).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help="JSON report path, relative to the repository by default.",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_MARKDOWN_OUTPUT,
        help="Markdown report path, relative to the repository by default.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit 1 when any required source contract fails.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    json_output = _resolve_output(repo_root, args.json_output)
    markdown_output = _resolve_output(repo_root, args.markdown_output)
    if json_output.resolve() == markdown_output.resolve():
        raise SystemExit("error: JSON and Markdown output paths must differ")

    report = run_audit(repo_root)
    json_data = (
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")
    markdown_data = _render_markdown(report).encode("utf-8")
    _atomic_write(json_output, json_data)
    _atomic_write(markdown_output, markdown_data)

    summary = report["summary"]
    print(
        "WebGPU source-contract audit: "
        f"{summary['required_passed']}/{summary['required_total']} required checks "
        f"passed ({summary['verdict']})."
    )
    print(f"JSON: {_display_path(json_output, repo_root)}")
    print(f"Markdown: {_display_path(markdown_output, repo_root)}")
    print(
        "Scope: static source contracts only; numeric/pixel parity was not tested."
    )

    if args.require_complete and summary["required_failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
