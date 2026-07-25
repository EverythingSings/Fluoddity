"""Check Rust/wgpu native input against the Steam Input handoff artifacts."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "artifacts" / "native_steam_input_alignment.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_steam_input_alignment.md"
DEFAULT_NATIVE_CONTRACT = ROOT / "artifacts" / "native_input_contract.json"
DEFAULT_NATIVE_RUNTIME = ROOT / "artifacts" / "native_input_runtime.json"
DEFAULT_STEAM_MANIFEST = ROOT / "steam_input" / "steam_input_manifest.vdf"
DEFAULT_GLYPH_MAP = ROOT / "steam_input" / "trial_prompt_glyph_map.json"
DEFAULT_PACKAGE_DIR = ROOT / "dist" / "FluoddityNative"

EXPECTED_ACTIONS = {
    "AimNutrientGel": {
        "native_kind": "cursor",
        "required_native": ["RightStickX", "RightStickY"],
        "glyph": "Right Stick",
    },
    "ApplyNutrientGel": {
        "native_kind": "action",
        "native_action": "ApplyNutrientGel",
        "required_native": ["RightTrigger2", "RightTrigger"],
        "glyph": "R2",
    },
    "StartExperiment": {
        "native_kind": "action",
        "native_action": "StartOrResume",
        "required_native": ["South"],
        "glyph": "A",
    },
    "PauseExperiment": {
        "native_kind": "action",
        "native_action": "PauseToggle",
        "required_native": ["Start", "Mode"],
        "glyph": "Menu",
    },
    "ExitExperiment": {
        "native_kind": "action",
        "native_action": "ExitExperiment",
        "required_native": ["Select"],
        "glyph": "View",
    },
}
EXPECTED_WRAPPERS = [
    "run_input_contract.ps1",
    "run_input_contract.sh",
    "run_input_runtime.ps1",
    "run_input_runtime.sh",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke native controller alignment with Steam Input artifacts.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="Machine-readable report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--native-contract", type=Path, default=DEFAULT_NATIVE_CONTRACT, help="Native input contract JSON.")
    parser.add_argument("--native-runtime", type=Path, default=DEFAULT_NATIVE_RUNTIME, help="Native input runtime smoke JSON.")
    parser.add_argument("--steam-manifest", type=Path, default=DEFAULT_STEAM_MANIFEST, help="Steam Input VDF manifest.")
    parser.add_argument("--glyph-map", type=Path, default=DEFAULT_GLYPH_MAP, help="Trial prompt glyph map JSON.")
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE_DIR, help="Native package directory.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def vdf_tokens(text: str) -> set[str]:
    return set(re.findall(r'"([^"]+)"', text))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(
    native_contract: dict,
    native_runtime: dict,
    steam_manifest_text: str,
    glyph_map: dict,
    package_dir: Path,
) -> tuple[list[dict], list[str], list[str]]:
    failures: list[str] = []
    action_results: list[dict] = []
    wrapper_results: list[str] = []
    tokens = vdf_tokens(steam_manifest_text)
    glyph_actions = glyph_map.get("actions", {})
    native_actions = {action.get("action"): action for action in native_contract.get("actions", [])}
    cursor = native_contract.get("cursor", {})
    prompt_states = native_contract.get("prompt_states", [])
    prompt_state_actions = {
        state.get("status"): set(state.get("prompt_actions", []))
        for state in prompt_states
        if isinstance(state, dict)
    }
    runtime_prompt_actions = []
    for snapshot in native_runtime.get("snapshots", []):
        for action in snapshot.get("overlay", {}).get("prompt_actions", []):
            runtime_prompt_actions.append(
                {
                    "snapshot": snapshot.get("label", ""),
                    "steam_action": action.get("steam_action", ""),
                    "fallback_label": action.get("fallback_label", ""),
                }
            )

    require(native_contract.get("schema") == "fluoddity.native_input_contract.v1", "native input contract schema mismatch", failures)
    require(native_runtime.get("schema") == "fluoddity.native_input_runtime_smoke.v1", "native input runtime schema mismatch", failures)
    require(native_contract.get("input_backend") == "gilrs", "native input contract should use gilrs", failures)
    require("TrialDish" in tokens, "Steam Input manifest missing TrialDish action set", failures)
    require(
        prompt_state_actions.get("briefing") == {"StartExperiment", "ApplyNutrientGel", "PauseExperiment"},
        "native input contract briefing prompts should expose Steam Input action ids",
        failures,
    )
    require(
        prompt_state_actions.get("running") == {"AimNutrientGel", "ApplyNutrientGel", "PauseExperiment"},
        "native input contract running prompts should expose Steam Input action ids",
        failures,
    )
    require(
        prompt_state_actions.get("result") == {"StartExperiment", "ExitExperiment"},
        "native input contract result prompts should expose Steam Input action ids",
        failures,
    )

    for steam_action, expected in EXPECTED_ACTIONS.items():
        action_failures: list[str] = []
        require(steam_action in tokens, f"Steam Input manifest missing {steam_action}", action_failures)
        glyph = glyph_actions.get(steam_action, {})
        require(glyph.get("fallback_label") == expected["glyph"], f"{steam_action} glyph fallback should be {expected['glyph']}", action_failures)
        glyph_path = glyph.get("glyph_asset", "")
        require(bool(glyph_path), f"{steam_action} glyph asset missing", action_failures)
        if glyph_path:
            require((ROOT / glyph_path).exists(), f"{steam_action} glyph asset not found: {glyph_path}", action_failures)

        if expected["native_kind"] == "cursor":
            native_values = [cursor.get("axis_x"), cursor.get("axis_y")]
        else:
            native = native_actions.get(expected["native_action"], {})
            native_values = native.get("buttons", [])
            require(bool(native), f"native action missing: {expected['native_action']}", action_failures)
        for value in expected["required_native"]:
            require(value in native_values, f"{steam_action} native binding missing {value}", action_failures)

        action_results.append(
            {
                "steam_action": steam_action,
                "native_binding": expected.get("native_action", "RightStick cursor"),
                "required_native": expected["required_native"],
                "glyph": expected["glyph"],
                "valid": not action_failures,
                "failures": action_failures,
            }
        )
        failures.extend(action_failures)

    for prompt_action in runtime_prompt_actions:
        action = prompt_action["steam_action"]
        fallback = prompt_action["fallback_label"]
        require(action in tokens, f"runtime prompt action missing from Steam Input manifest: {action}", failures)
        glyph = glyph_actions.get(action, {})
        require(bool(glyph), f"runtime prompt action missing from glyph map: {action}", failures)
        if glyph:
            require(
                glyph.get("fallback_label") == fallback,
                f"runtime prompt fallback mismatch for {action} in {prompt_action['snapshot']}: {fallback}",
                failures,
            )

    for wrapper in EXPECTED_WRAPPERS:
        path = package_dir / wrapper
        if path.exists() and path.stat().st_size > 0:
            wrapper_results.append(wrapper)
        else:
            failures.append(f"native package missing input wrapper: {wrapper}")

    return action_results, wrapper_results, failures


def write_markdown(payload: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Native Steam Input Alignment",
        "",
        f"- Status: {payload['status']}",
        f"- Native contract: `{payload['inputs']['native_contract']}`",
        f"- Native runtime: `{payload['inputs']['native_runtime']}`",
        f"- Steam Input manifest: `{payload['inputs']['steam_manifest']}`",
        f"- Glyph map: `{payload['inputs']['glyph_map']}`",
        f"- Package: `{payload['inputs']['package_dir']}`",
        "",
        "## Checked Actions",
        "",
        "| Steam Input action | Native binding | Required native controls | Glyph fallback | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for action in payload["actions"]:
        status = "pass" if action["valid"] else "fail"
        lines.append(
            f"| `{action['steam_action']}` | `{action['native_binding']}` | "
            f"{', '.join(action['required_native'])} | {action['glyph']} | {status} |"
        )
    lines.extend(["", "## Package Wrappers", ""])
    for wrapper in payload["package_wrappers"]:
        lines.append(f"- `{wrapper}`")
    if payload["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in payload["failures"])
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    native_contract_path = resolve(args.native_contract)
    native_runtime_path = resolve(args.native_runtime)
    steam_manifest_path = resolve(args.steam_manifest)
    glyph_map_path = resolve(args.glyph_map)
    package_dir = resolve(args.package_dir)
    json_output = resolve(args.json_output)
    markdown_output = resolve(args.markdown)

    failures: list[str] = []
    for path, label in [
        (native_contract_path, "native input contract"),
        (native_runtime_path, "native input runtime"),
        (steam_manifest_path, "Steam Input manifest"),
        (glyph_map_path, "glyph map"),
    ]:
        require(path.exists(), f"missing {label}: {path}", failures)
    require(package_dir.exists(), f"missing native package directory: {package_dir}", failures)
    if failures:
        actions: list[dict] = []
        wrappers: list[str] = []
    else:
        actions, wrappers, failures = validate(
            load_json(native_contract_path),
            load_json(native_runtime_path),
            steam_manifest_path.read_text(encoding="utf-8"),
            load_json(glyph_map_path),
            package_dir,
        )

    payload = {
        "schema": "fluoddity.native_steam_input_alignment.v1",
        "status": "pass" if not failures else "fail",
        "inputs": {
            "native_contract": native_contract_path.relative_to(ROOT).as_posix(),
            "native_runtime": native_runtime_path.relative_to(ROOT).as_posix(),
            "steam_manifest": steam_manifest_path.relative_to(ROOT).as_posix(),
            "glyph_map": glyph_map_path.relative_to(ROOT).as_posix(),
            "package_dir": package_dir.relative_to(ROOT).as_posix(),
        },
        "actions": actions,
        "package_wrappers": wrappers,
        "failures": failures,
    }
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    write_markdown(payload, markdown_output)
    print(f"native_steam_input_alignment_status={payload['status']}")
    print(f"native_steam_input_alignment_markdown={markdown_output}")
    print(f"native_steam_input_alignment_json={json_output}")
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
