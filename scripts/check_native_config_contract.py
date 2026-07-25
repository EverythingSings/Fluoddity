"""Compare Python config loading with the Rust/wgpu normalized config contract."""
from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from native_runtime_tools import build_native_runtime, native_runtime_binary
from ui.physics_params import PHYSICS_PARAMS


DEFAULT_REPORT = ROOT / "artifacts" / "native_config_contract.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_config_contract.md"
PHYSICS_SCALE = {"SENSOR_DISTANCE": 0.018}
FIELD_TO_CONFIG = {param.name: param.config_attr for param in PHYSICS_PARAMS}
PHYSICS_DEFAULTS = {
    "axial_force": 0.371,
    "lateral_force": -0.707,
    "sensor_gain": 0.116,
    "mutation_scale": 0.0,
    "drag": 0.504,
    "strafe_power": 0.224,
    "sensor_angle": 0.45,
    "global_force_mult": 1.0,
    "sensor_distance": 1.0,
    "trail_persistence": 0.938,
    "trail_diffusion": 1.0,
    "hazard_rate": 0.0,
}
SETTINGS_DEFAULTS = {
    "disable_symmetry": False,
    "absolute_orientation": 0,
    "orientation_mix": 1.0,
    "boundary_conditions": 0,
    "initial_conditions": 0,
    "num_cohorts": 64,
    "rule_seed": 0.42,
}
APPEARANCE_DEFAULTS = {
    "ink_weight": 1.0,
    "hue_sensitivity": 0.5,
    "color_by_cohort": True,
    "watercolor_mode": False,
    "emboss_mode": 0,
    "emboss_intensity": 0.5,
    "emboss_smoothness": 0.1,
}
SETTING_ORDER = [
    "AXIAL_FORCE",
    "LATERAL_FORCE",
    "SENSOR_GAIN",
    "MUTATION_SCALE",
    "DRAG",
    "STRAFE_POWER",
    "SENSOR_ANGLE",
    "GLOBAL_FORCE_MULT",
    "SENSOR_DISTANCE",
    "TRAIL_PERSISTENCE",
    "TRAIL_DIFFUSION",
    "HAZARD_RATE",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check native config contract parity.")
    parser.add_argument(
        "--config-glob",
        default="physics_configs/Core/*.json",
        help="Config glob relative to the repo root.",
    )
    parser.add_argument("--binary", type=Path, default=None, help="Optional Rust runtime binary override.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_REPORT, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--no-build", action="store_true", help="Skip building the Rust runtime first.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def seed_from_float(seed: float) -> int:
    bits = struct.unpack("<I", struct.pack("<f", float(seed)))[0]
    return (bits ^ rotl32(bits, 13) ^ 0x9E37_79B9) & 0xFFFF_FFFF


def rotl32(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (32 - shift))) & 0xFFFF_FFFF


def expected_contract(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    physics = data.get("physics", {})
    settings = data.get("settings", {})
    appearance = data.get("appearance", {})
    rule = data.get("rule", [0.0] * 80)
    if len(rule) != 80:
        raise RuntimeError(f"{path} has {len(rule)} rule floats, expected 80")
    values = {
        key: f32(physics.get(key, default))
        for key, default in PHYSICS_DEFAULTS.items()
    }
    setting_values = {
        key: settings.get(key, default)
        for key, default in SETTINGS_DEFAULTS.items()
    }
    appearance_values = {
        key: appearance.get(key, default)
        for key, default in APPEARANCE_DEFAULTS.items()
    }
    return {
        "schema": "fluoddity.native_config_contract.v1",
        "notes": str(data.get("notes", "")),
        "rule_seed_value": f32(setting_values["rule_seed"]),
        "rule_seed": seed_from_float(setting_values["rule_seed"]),
        "sensor_distance": f32(clamp(values["sensor_distance"] * 0.018, 0.006, 0.08)),
        "sensor_angle": values["sensor_angle"],
        "sensor_gain": f32(clamp(values["sensor_gain"], 0.05, 8.0)),
        "mutation_scale": f32(clamp(values["mutation_scale"], 0.0, 2.0)),
        "drag": f32(clamp(values["drag"], 0.0, 1.0)),
        "strafe_power": f32(clamp(values["strafe_power"], -2.0, 2.0)),
        "axial_force": values["axial_force"],
        "lateral_force": values["lateral_force"],
        "global_force_mult": f32(clamp(values["global_force_mult"], 0.0, 4.0)),
        "trail_persistence": f32(clamp(values["trail_persistence"], 0.0, 0.999)),
        "trail_diffusion": f32(clamp(values["trail_diffusion"], 0.0, 4.0)),
        "hazard_rate": f32(clamp(values["hazard_rate"], 0.0, 0.05)),
        "orientation_mix": f32(clamp(setting_values["orientation_mix"], 0.0, 1.0)),
        "absolute_orientation": min(int(setting_values["absolute_orientation"]), 2),
        "disable_symmetry": bool(setting_values["disable_symmetry"]),
        "hue_sensitivity": f32(clamp(appearance_values["hue_sensitivity"], 0.0, 4.0)),
        "color_by_cohort": bool(appearance_values["color_by_cohort"]),
        "ink_weight": f32(clamp(appearance_values["ink_weight"], 0.0, 8.0)),
        "watercolor_mode": bool(appearance_values["watercolor_mode"]),
        "emboss_mode": min(int(appearance_values["emboss_mode"]), 2),
        "emboss_intensity": f32(clamp(appearance_values["emboss_intensity"], 0.0, 4.0)),
        "emboss_smoothness": f32(clamp(appearance_values["emboss_smoothness"], 0.001, 4.0)),
        "parameter_sweeps_enabled": bool(data.get("parameter_sweeps_enabled", False)),
        "boundary_conditions": min(int(setting_values["boundary_conditions"]), 2),
        "initial_conditions": min(int(setting_values["initial_conditions"]), 2),
        "num_cohorts": max(1, min(int(setting_values["num_cohorts"]), 144)),
        "has_saved_rule": any(abs(float(value)) >= 0.000_001 for value in rule),
        "rule_float_count": len(rule),
        "physics_settings": expected_physics_settings(data, values),
    }


def expected_physics_settings(data: dict, values: dict[str, float]) -> list[dict]:
    params_by_name = {param.name: param for param in PHYSICS_PARAMS}
    slider_ranges = default_slider_ranges()
    slider_ranges.update(data.get("slider_ranges", {}))
    sweeps = data.get("sweeps", {})
    x_sweeps = default_param_map()
    x_sweeps.update(sweeps.get("x", {}))
    y_sweeps = default_param_map()
    y_sweeps.update(sweeps.get("y", {}))
    cohort_sweeps = default_param_map()
    cohort_sweeps.update(sweeps.get("cohort", {}))
    jitters = default_param_map()
    jitters.update(data.get("jitters", {}))
    parameter_sweeps_enabled = bool(data.get("parameter_sweeps_enabled", False))
    settings = []
    for field in SETTING_ORDER:
        param = params_by_name[field]
        scale = PHYSICS_SCALE.get(field, 1.0)
        slider_range = slider_ranges[param.label]
        settings.append(
            {
                "field": field,
                "label": param.label,
                "slider_value": normalized_slider_value(field, values),
                "min_value": f32(float(slider_range[0]) * scale),
                "max_value": f32(float(slider_range[1]) * scale),
                "x_sweep": f32(x_sweeps.get(field, 0.0) if parameter_sweeps_enabled else 0.0),
                "y_sweep": f32(y_sweeps.get(field, 0.0) if parameter_sweeps_enabled else 0.0),
                "cohort_sweep": f32(
                    cohort_sweeps.get(field, 0.0) if parameter_sweeps_enabled else 0.0
                ),
                "jitter": f32(jitters.get(field, 0.0)),
            }
        )
    return settings


def normalized_slider_value(field: str, values: dict[str, float]) -> float:
    attr = FIELD_TO_CONFIG[field]
    raw = values[attr]
    if field == "SENSOR_DISTANCE":
        return f32(clamp(raw * 0.018, 0.006, 0.08))
    if field == "SENSOR_GAIN":
        return f32(clamp(raw, 0.05, 8.0))
    if field == "MUTATION_SCALE":
        return f32(clamp(raw, 0.0, 2.0))
    if field == "DRAG":
        return f32(clamp(raw, 0.0, 1.0))
    if field == "STRAFE_POWER":
        return f32(clamp(raw, -2.0, 2.0))
    if field == "GLOBAL_FORCE_MULT":
        return f32(clamp(raw, 0.0, 4.0))
    if field == "TRAIL_PERSISTENCE":
        return f32(clamp(raw, 0.0, 0.999))
    if field == "TRAIL_DIFFUSION":
        return f32(clamp(raw, 0.0, 4.0))
    if field == "HAZARD_RATE":
        return f32(clamp(raw, 0.0, 0.05))
    return f32(raw)


def default_param_map() -> dict[str, float]:
    return {param.name: 0.0 for param in PHYSICS_PARAMS}


def default_slider_ranges() -> dict[str, list[float]]:
    return {
        param.label: [param.default_min, param.default_max, param.default_min, param.default_max]
        for param in PHYSICS_PARAMS
    }


def f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def native_contract(binary: Path, config_path: Path, index: int) -> dict:
    dump_path = ROOT / "artifacts" / "native-wgpu" / f"config_contract_{index:03d}.json"
    subprocess.run(
        [
            str(binary),
            "--config",
            str(config_path),
            "--dump-config-contract",
            str(dump_path),
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return json.loads(dump_path.read_text(encoding="utf-8"))


def compare(expected: dict, actual: dict, prefix: str = "") -> list[str]:
    failures: list[str] = []
    for key, expected_value in expected.items():
        current = f"{prefix}.{key}" if prefix else key
        if key not in actual:
            failures.append(f"{current}: missing")
            continue
        actual_value = actual[key]
        if isinstance(expected_value, float):
            if not close(expected_value, float(actual_value)):
                failures.append(f"{current}: expected {expected_value!r}, got {actual_value!r}")
        elif isinstance(expected_value, list):
            failures.extend(compare_list(expected_value, actual_value, current))
        else:
            if expected_value != actual_value:
                failures.append(f"{current}: expected {expected_value!r}, got {actual_value!r}")
    return failures


def compare_list(expected: list, actual: object, prefix: str) -> list[str]:
    if not isinstance(actual, list):
        return [f"{prefix}: expected list, got {type(actual).__name__}"]
    failures: list[str] = []
    if len(expected) != len(actual):
        failures.append(f"{prefix}: expected {len(expected)} items, got {len(actual)}")
        return failures
    for index, expected_item in enumerate(expected):
        current = f"{prefix}[{index}]"
        actual_item = actual[index]
        if isinstance(expected_item, dict):
            failures.extend(compare(expected_item, actual_item, current))
        elif expected_item != actual_item:
            failures.append(f"{current}: expected {expected_item!r}, got {actual_item!r}")
    return failures


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=0.000_01)


def write_reports(results: list[dict], json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    passed = [result for result in results if not result["failures"]]
    payload = {
        "schema": "fluoddity.native_config_contract_report.v1",
        "status": "pass" if len(passed) == len(results) else "fail",
        "checked_config_count": len(results),
        "passed_config_count": len(passed),
        "results": results,
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Config Contract Check",
        "",
        f"- Status: {payload['status']}",
        f"- Configs checked: {len(results)}",
        f"- Configs passed: {len(passed)}",
        "",
        "## Results",
        "",
    ]
    for result in results:
        status = "pass" if not result["failures"] else "fail"
        lines.append(f"- `{result['config']}`: {status}")
        for failure in result["failures"][:5]:
            lines.append(f"  - {failure}")
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    if not args.no_build:
        build_native_runtime()
    binary = resolve(args.binary) if args.binary is not None else native_runtime_binary()
    if not binary.exists():
        raise SystemExit(f"native runtime binary not found: {binary}")
    configs = sorted(ROOT.glob(args.config_glob))
    if not configs:
        raise SystemExit(f"no configs matched {args.config_glob!r}")
    results = []
    for index, config_path in enumerate(configs):
        expected = expected_contract(config_path)
        actual = native_contract(binary, config_path, index)
        failures = compare(expected, actual)
        results.append(
            {
                "config": config_path.relative_to(ROOT).as_posix(),
                "failures": failures,
            }
        )
    write_reports(results, args.json_output, args.markdown)
    passed = sum(1 for result in results if not result["failures"])
    print(f"native_config_contract_status={'pass' if passed == len(results) else 'fail'}")
    print(f"native_config_contract_checked={len(results)}")
    print(f"native_config_contract_passed={passed}")
    print(f"native_config_contract_markdown={resolve(args.markdown)}")
    print(f"native_config_contract_json={resolve(args.json_output)}")
    return 0 if passed == len(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
