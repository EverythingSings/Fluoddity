"""Audit native Rust/wgpu coverage against the Python/GLSL fluid engine surface."""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_shader_parity.md"
DEFAULT_JSON = ROOT / "artifacts" / "native_shader_parity.json"

PARAM_MAPPING = {
    "AXIAL_FORCE": "axial_force",
    "LATERAL_FORCE": "lateral_force",
    "SENSOR_GAIN": "sensor_gain",
    "MUTATION_SCALE": "mutation_scale",
    "DRAG": "drag",
    "STRAFE_POWER": "strafe_power",
    "SENSOR_ANGLE": "sensor_angle",
    "GLOBAL_FORCE_MULT": "global_force_mult",
    "SENSOR_DISTANCE": "sensor_distance",
    "TRAIL_PERSISTENCE": "trail_persistence",
    "TRAIL_DIFFUSION": "trail_diffusion",
    "HAZARD_RATE": "hazard_rate",
    "DISABLE_SYMMETRY": "disable_symmetry",
    "ABSOLUTE_ORIENTATION": "absolute_orientation",
    "ORIENTATION_MIX": "orientation_mix",
    "hue_sensitivity": "hue_sensitivity",
    "color_by_cohort": "color_by_cohort",
    "ink_weight": "ink_weight",
    "watercolor_mode": "watercolor_mode",
    "emboss_mode": "emboss_mode",
    "emboss_intensity": "emboss_intensity",
    "emboss_smoothness": "emboss_smoothness",
    "slider_ranges": "physics_settings",
    "parameter_sweeps_enabled": "parameter_sweeps_enabled",
    "x_sweeps": "physics_settings",
    "y_sweeps": "physics_settings",
    "cohort_sweeps": "physics_settings",
    "jitters": "physics_settings",
    "rule_seed": "rule_seed",
    "boundary_conditions": "boundary_conditions",
    "initial_conditions": "initial_conditions",
    "num_cohorts": "num_cohorts",
    "notes": "notes",
}

GPU_PARAM_MAPPING = {
    "AXIAL_FORCE": {"kind": "params", "target": "axial_force"},
    "LATERAL_FORCE": {"kind": "params", "target": "lateral_force"},
    "SENSOR_GAIN": {"kind": "params", "target": "sensor_gain"},
    "MUTATION_SCALE": {"kind": "params", "target": "mutation_scale"},
    "DRAG": {"kind": "params", "target": "drag"},
    "STRAFE_POWER": {"kind": "params", "target": "strafe_power"},
    "SENSOR_ANGLE": {"kind": "params", "target": "sensor_angle"},
    "GLOBAL_FORCE_MULT": {"kind": "params", "target": "global_force_mult"},
    "SENSOR_DISTANCE": {"kind": "params", "target": "sensor_distance"},
    "TRAIL_PERSISTENCE": {"kind": "params", "target": "trail_persistence"},
    "TRAIL_DIFFUSION": {"kind": "params", "target": "trail_diffusion"},
    "HAZARD_RATE": {"kind": "params", "target": "hazard_rate"},
    "DISABLE_SYMMETRY": {"kind": "params", "target": "disable_symmetry"},
    "ABSOLUTE_ORIENTATION": {"kind": "params", "target": "absolute_orientation"},
    "ORIENTATION_MIX": {"kind": "params", "target": "orientation_mix"},
    "boundary_conditions": {"kind": "params", "target": "boundary_conditions"},
    "initial_conditions": {"kind": "params", "target": "initial_conditions"},
    "num_cohorts": {"kind": "params", "target": "num_cohorts"},
    "rule_seed": {"kind": "params", "target": "rule_seed"},
    "hue_sensitivity": {"kind": "params", "target": "hue_sensitivity"},
    "color_by_cohort": {"kind": "params", "target": "color_by_cohort"},
    "ink_weight": {"kind": "params", "target": "ink_weight"},
    "watercolor_mode": {"kind": "params", "target": "watercolor_mode"},
    "emboss_mode": {"kind": "params", "target": "emboss_mode"},
    "emboss_intensity": {"kind": "params", "target": "emboss_intensity"},
    "emboss_smoothness": {"kind": "params", "target": "emboss_smoothness"},
    "slider_ranges": {"kind": "native_setting", "target": "physics_settings"},
    "x_sweeps": {"kind": "native_setting", "target": "physics_settings"},
    "y_sweeps": {"kind": "native_setting", "target": "physics_settings"},
    "cohort_sweeps": {"kind": "native_setting", "target": "physics_settings"},
    "jitters": {"kind": "native_setting", "target": "physics_settings"},
}

EXPECTED_MISSING_FEATURES = set()

FEATURE_GROUPS = [
    {
        "id": "core_saved_config_params",
        "title": "Core Saved Config Parameters",
        "glsl_uniforms": [
            "AXIAL_FORCE_SETTING",
            "LATERAL_FORCE_SETTING",
            "SENSOR_GAIN_SETTING",
            "MUTATION_SCALE_SETTING",
            "DRAG_SETTING",
            "STRAFE_POWER_SETTING",
            "SENSOR_ANGLE_SETTING",
            "GLOBAL_FORCE_MULT_SETTING",
            "SENSOR_DISTANCE_SETTING",
            "HAZARD_RATE_SETTING",
        ],
        "native_needles": [
            "axial_force",
            "lateral_force",
            "sensor_gain",
            "mutation_scale",
            "drag",
            "strafe_power",
            "sensor_angle",
            "global_force_mult",
            "sensor_distance",
            "trail_persistence",
            "trail_diffusion",
            "hazard_rate",
        ],
        "replacement_required": True,
        "note": "Scalar saved config values loaded into the native RuntimeConfig/Params contract.",
    },
    {
        "id": "saved_fourier_rule",
        "title": "Saved Fourier Rule",
        "glsl_uniforms": ["target_rule"],
        "native_needles": ["rule_coefficients", "native_rule", "has_saved_rule"],
        "replacement_required": True,
        "note": "Saved 80-float rule coefficients are loaded and evaluated by native WGSL.",
    },
    {
        "id": "orientation_symmetry",
        "title": "Orientation And Symmetry",
        "glsl_uniforms": ["DISABLE_SYMMETRY", "ABSOLUTE_ORIENTATION", "ORIENTATION_MIX"],
        "native_needles": ["disable_symmetry", "absolute_orientation", "orientation_mix", "sensor_orientation"],
        "replacement_required": True,
        "note": "Native path has explicit orientation and symmetry parameters plus effect sensitivity evidence.",
    },
    {
        "id": "parameter_sweeps_jitter",
        "title": "Parameter Sweeps And Jitter",
        "glsl_uniforms": [],
        "native_needles": ["x_sweep", "y_sweep", "cohort_sweep", "jitter", "parameter_sweeps_enabled"],
        "replacement_required": True,
        "note": "Native path loads saved sweep/jitter settings and uses them through NativeSetting.",
    },
    {
        "id": "reset_boundary_initialization",
        "title": "Reset Boundary Initialization",
        "glsl_uniforms": ["RESET_MODE", "BOUNDARY_CONDITIONS_MODE", "COHORTS"],
        "native_needles": ["initial_conditions", "boundary_conditions", "num_cohorts", "reset_position"],
        "replacement_required": True,
        "note": "Native initialization covers saved reset, boundary, and cohort settings.",
    },
    {
        "id": "multi_load_rule_selection",
        "title": "Multi-Load Rule Selection",
        "glsl_uniforms": [
            "MULTILOAD_COUNT",
            "MULTI_LOAD_CURRENT_PROGRESS",
            "MULTI_LOAD_SIMULTANEOUS_CONFIGS",
            "MULTI_LOAD_ASSIGNMENT_MODE",
            "MULTI_LOAD_PER_CONFIG_INITIAL_CONDITIONS",
            "MULTI_LOAD_PER_CONFIG_COHORTS",
            "MULTI_LOAD_PER_CONFIG_HAZARD_RATE",
        ],
        "native_needles": ["multi_load", "target_rules"],
        "replacement_required": False,
        "note": "Editor/gallery multi-config rule blending is not implemented in the native player spike.",
    },
    {
        "id": "external_force_strafe_fields",
        "title": "External Force And Strafe Fields",
        "glsl_uniforms": ["field_texture", "force_field_strength", "strafe_field_strength"],
        "native_needles": ["field_texture", "force_field_strength", "strafe_field_strength"],
        "replacement_required": False,
        "note": "Painted/imported force and strafe fields are editor-facing and absent from the native spike.",
    },
    {
        "id": "rule_readback_mutation_history",
        "title": "Rule Readback And Mutation History",
        "glsl_uniforms": ["WRITE_RULES"],
        "native_needles": ["WRITE_RULES", "write_rules", "rule_readback"],
        "replacement_required": False,
        "note": "Python editor readback/mutation-history plumbing is not part of the native player shell yet.",
    },
    {
        "id": "presentation_view_modes",
        "title": "Presentation View Modes",
        "glsl_uniforms": [
            "view_mode",
            "view_min",
            "view_max",
            "BRIGHTNESS",
            "EXPOSURE",
            "TONEMAP_SOFTNESS",
            "PARAMETER_SWEEP_MODE",
            "TRAIL_DRAW_RADIUS",
        ],
        "native_needles": ["present.wgsl", "watercolor_mode", "emboss_mode", "ink_weight"],
        "replacement_required": False,
        "note": "Native presentation has its own minimal player-oriented path, not the full Python editor view stack.",
    },
    {
        "id": "canvas_brush_editor_tools",
        "title": "Canvas Brush Editor Tools",
        "glsl_uniforms": ["canvas", "brush_mode", "mouse_screen_coords", "fixed_direction_heading"],
        "native_needles": ["brush_mode", "mouse_screen_coords", "fixed_direction_heading"],
        "replacement_required": False,
        "note": "Mouse brush/canvas editing is intentionally outside the current native Deck player spike.",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Rust/wgpu native shader parity.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Exit 2 unless native coverage is complete. Layout mismatches always fail.",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sim_state_fields() -> list[str]:
    tree = ast.parse((ROOT / "state" / "sim_state.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SimState":
            return [stmt.target.id for stmt in node.body if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)]
    raise RuntimeError("SimState class not found")


def glsl_uniforms() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in [
        ROOT / "shaders" / "entity_update.glsl",
        ROOT / "shaders" / "fourier4_4.glsl",
        ROOT / "shaders" / "frame_assembly.frag",
    ]:
        uniforms = sorted(set(re.findall(r"^\s*uniform\s+(?:\w+\s+)+(\w+)\s*;", path.read_text(encoding="utf-8"), re.MULTILINE)))
        result[path.relative_to(ROOT).as_posix()] = uniforms
    return result


def rust_struct_fields(source: str, struct_name: str) -> list[str]:
    match = re.search(rf"struct\s+{re.escape(struct_name)}\s*\{{(?P<body>.*?)\n\}}", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"{struct_name} struct not found")
    fields: list[str] = []
    for line in match.group("body").splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        field_match = re.match(r"(?:pub\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if field_match:
            fields.append(field_match.group(1))
    return fields


def wgsl_struct_fields(path: Path, struct_name: str) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"struct\s+{re.escape(struct_name)}\s*\{{(?P<body>.*?)\n\}};", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"{struct_name} struct not found in {path}")
    fields: list[str] = []
    for line in match.group("body").splitlines():
        field_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
        if field_match:
            fields.append(field_match.group(1))
    return fields


def wgsl_params_fields(path: Path) -> list[str]:
    return wgsl_struct_fields(path, "Params")


def gpu_param_coverage(
    sim_fields: list[str],
    rust_params: list[str],
    wgsl_params: dict[str, list[str]],
    rust_native_setting: list[str],
    wgsl_native_settings: dict[str, list[str]],
    native_text: str,
) -> list[dict[str, object]]:
    coverage: list[dict[str, object]] = []
    for field, mapping in GPU_PARAM_MAPPING.items():
        if field not in sim_fields:
            continue
        target = mapping["target"]
        kind = mapping["kind"]
        missing: list[str] = []
        evidence: list[str] = []
        if kind == "params":
            if target in rust_params:
                evidence.append("rust Params")
            else:
                missing.append("rust Params")
            for shader, fields in wgsl_params.items():
                if target in fields:
                    evidence.append(f"{shader} Params")
                else:
                    missing.append(f"{shader} Params")
        elif kind == "native_setting":
            required_fields = ["slider_value", "min_value", "max_value", "x_sweep", "y_sweep", "cohort_sweep", "jitter"]
            missing_rust_fields = [name for name in required_fields if name not in rust_native_setting]
            if missing_rust_fields:
                missing.append(f"rust NativeSetting fields: {', '.join(missing_rust_fields)}")
            else:
                evidence.append("rust NativeSetting")
            for shader, fields in wgsl_native_settings.items():
                missing_wgsl_fields = [name for name in required_fields if name not in fields]
                if missing_wgsl_fields:
                    missing.append(f"{shader} NativeSetting fields: {', '.join(missing_wgsl_fields)}")
                else:
                    evidence.append(f"{shader} NativeSetting")
            if target not in native_text:
                missing.append("physics_settings binding/use")
            else:
                evidence.append("physics_settings binding/use")
        else:
            missing.append(f"unknown mapping kind: {kind}")
        coverage.append(
            {
                "field": field,
                "kind": kind,
                "target": target,
                "status": "covered" if not missing else "missing",
                "evidence": evidence,
                "missing": missing,
            }
        )
    return coverage


def feature_group_coverage(native_text: str, uniforms: dict[str, list[str]]) -> list[dict[str, object]]:
    observed_uniforms = {uniform for shader_uniforms in uniforms.values() for uniform in shader_uniforms}
    groups: list[dict[str, object]] = []
    for group in FEATURE_GROUPS:
        required_uniforms = group["glsl_uniforms"]
        uniform_hits = [uniform for uniform in required_uniforms if uniform in observed_uniforms]
        native_hits = [needle for needle in group["native_needles"] if needle in native_text]
        missing_native_needles = [needle for needle in group["native_needles"] if needle not in native_text]
        if not required_uniforms and native_hits:
            status = "covered"
        elif required_uniforms and len(uniform_hits) == len(required_uniforms) and not missing_native_needles:
            status = "covered"
        elif native_hits:
            status = "partial"
        else:
            status = "missing"
        groups.append(
            {
                "id": group["id"],
                "title": group["title"],
                "status": status,
                "replacement_required": group["replacement_required"],
                "glsl_uniforms": required_uniforms,
                "glsl_uniforms_present": uniform_hits,
                "native_evidence": native_hits,
                "missing_native_evidence": missing_native_needles,
                "note": group["note"],
            }
        )
    return groups


def write_reports(markdown_path: Path, json_path: Path, payload: dict) -> None:
    markdown_path = resolve(markdown_path)
    json_path = resolve(json_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    missing = payload["missing_sim_state_fields"]
    mapped = payload["mapped_sim_state_fields"]
    lines = [
        "# Native Shader Parity Audit",
        "",
        f"- Status: {payload['status']}",
        f"- SimState fields mapped into native runtime: {len(mapped)}/{payload['sim_state_field_count']}",
        f"- GLSL uniform names observed: {payload['glsl_uniform_count']}",
        f"- Rust/WGSL Params layout match: {'yes' if payload['params_layout_match'] else 'no'}",
        "",
        "## Mapped SimState Fields",
        "",
    ]
    lines.extend(f"- `{field}` -> `{target}`" for field, target in mapped.items())
    lines.extend(["", "## Missing Native Fluid Features", ""])
    lines.extend(f"- `{field}`" for field in missing)
    lines.extend(["", "## Native Feature Groups", ""])
    for group in payload["feature_groups"]:
        required = "replacement-required" if group["replacement_required"] else "deferred/player-scope"
        lines.append(f"- `{group['id']}`: {group['status']} ({required}) - {group['note']}")
        if group["missing_native_evidence"]:
            lines.append(f"  - missing native evidence: {', '.join(group['missing_native_evidence'])}")
    lines.extend(["", "## GPU Parameter Coverage", ""])
    lines.append(
        f"- Replacement-critical saved fields reaching native GPU payloads: "
        f"{payload['covered_gpu_param_count']}/{payload['gpu_param_count']}"
    )
    for item in payload["gpu_param_coverage"]:
        lines.append(f"- `{item['field']}` -> `{item['target']}` ({item['kind']}): {item['status']}")
        if item["missing"]:
            lines.append(f"  - missing: {', '.join(item['missing'])}")
    lines.extend(["", "## WGSL Params Layout", ""])
    for shader, fields in payload["wgsl_params_fields"].items():
        mismatch = "" if fields == payload["rust_params_fields"] else " (mismatch)"
        lines.append(f"- `{shader}`: {len(fields)} fields{mismatch}")
    lines.extend(["", "## WGSL NativeSetting Layout", ""])
    for shader, fields in payload["wgsl_native_setting_fields"].items():
        mismatch = "" if fields == payload["rust_native_setting_fields"] else " (mismatch)"
        lines.append(f"- `{shader}`: {len(fields)} fields{mismatch}")
    lines.extend(["", "## GLSL Uniform Sources", ""])
    for shader, uniforms in payload["glsl_uniforms"].items():
        lines.append(f"- `{shader}`: {len(uniforms)} uniforms")
    lines.append("")

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    rust_source = (ROOT / "runtime" / "rust-wgpu-spike" / "src" / "main.rs").read_text(encoding="utf-8")
    sim_fields = sim_state_fields()
    rust_config_fields = set(rust_struct_fields(rust_source, "RuntimeConfig"))
    rust_params = rust_struct_fields(rust_source, "Params")
    rust_native_setting = rust_struct_fields(rust_source, "NativeSetting")
    wgsl_params = {
        path.relative_to(ROOT).as_posix(): wgsl_params_fields(path)
        for path in [
            ROOT / "runtime" / "rust-wgpu-spike" / "src" / "spike.wgsl",
            ROOT / "runtime" / "rust-wgpu-spike" / "src" / "particles.wgsl",
            ROOT / "runtime" / "rust-wgpu-spike" / "src" / "present.wgsl",
        ]
    }
    wgsl_native_settings = {}
    for path in [
        ROOT / "runtime" / "rust-wgpu-spike" / "src" / "spike.wgsl",
        ROOT / "runtime" / "rust-wgpu-spike" / "src" / "particles.wgsl",
    ]:
        wgsl_native_settings[path.relative_to(ROOT).as_posix()] = wgsl_struct_fields(path, "NativeSetting")
    mapped = {
        field: target
        for field, target in PARAM_MAPPING.items()
        if field in sim_fields and target in rust_config_fields
    }
    missing = [field for field in sim_fields if field not in mapped]
    expected_missing_present = sorted(EXPECTED_MISSING_FEATURES & set(missing))
    layout_match = all(fields == rust_params for fields in wgsl_params.values())
    uniforms = glsl_uniforms()
    native_text = "\n".join(
        [
            rust_source,
            (ROOT / "runtime" / "rust-wgpu-spike" / "src" / "spike.wgsl").read_text(encoding="utf-8"),
            (ROOT / "runtime" / "rust-wgpu-spike" / "src" / "particles.wgsl").read_text(encoding="utf-8"),
            (ROOT / "runtime" / "rust-wgpu-spike" / "src" / "present.wgsl").read_text(encoding="utf-8"),
        ]
    )
    feature_groups = feature_group_coverage(native_text, uniforms)
    gpu_coverage = gpu_param_coverage(
        sim_fields,
        rust_params,
        wgsl_params,
        rust_native_setting,
        wgsl_native_settings,
        native_text,
    )
    covered_gpu_params = [item for item in gpu_coverage if item["status"] == "covered"]
    uniform_count = len({uniform for shader_uniforms in uniforms.values() for uniform in shader_uniforms})
    status = "incomplete"
    if not layout_match:
        status = "layout-mismatch"
    elif len(covered_gpu_params) != len(gpu_coverage):
        status = "gpu-param-mismatch"
    elif not missing and all(group["status"] == "covered" for group in feature_groups if group["replacement_required"]):
        status = "complete"

    payload = {
        "schema": "fluoddity.native_shader_parity.v1",
        "status": status,
        "sim_state_field_count": len(sim_fields),
        "mapped_sim_state_fields": mapped,
        "missing_sim_state_fields": missing,
        "expected_missing_features_present": expected_missing_present,
        "rust_runtime_config_fields": sorted(rust_config_fields),
        "rust_params_fields": rust_params,
        "rust_native_setting_fields": rust_native_setting,
        "wgsl_params_fields": wgsl_params,
        "wgsl_native_setting_fields": wgsl_native_settings,
        "params_layout_match": layout_match,
        "gpu_param_count": len(gpu_coverage),
        "covered_gpu_param_count": len(covered_gpu_params),
        "gpu_param_coverage": gpu_coverage,
        "glsl_uniform_count": uniform_count,
        "glsl_uniforms": uniforms,
        "feature_groups": feature_groups,
    }
    write_reports(args.markdown, args.json_output, payload)
    print(f"native_shader_parity_status={status}")
    print(f"native_shader_parity_markdown={resolve(args.markdown)}")
    print(f"native_shader_parity_json={resolve(args.json_output)}")
    if status in {"layout-mismatch", "gpu-param-mismatch"} or (args.require_complete and status != "complete"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
