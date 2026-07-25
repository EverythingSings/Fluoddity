"""Aggregate V1 release-readiness summaries into one blocking report."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts" / "release_readiness_summary.md"

DEFAULT_STEAM_INPUT_SUMMARY = ROOT / "artifacts" / "steam_input_handoff_summary.md"
DEFAULT_DECK_PREFLIGHT_SUMMARY = ROOT / "artifacts" / "steam_deck_preflight_summary.md"
DEFAULT_PACKAGE_SUMMARY = ROOT / "artifacts" / "package_validation_summary.md"
DEFAULT_PLAYTEST_SUMMARY = ROOT / "artifacts" / "trial_dish_playtest_summary.md"
DEFAULT_TUNING_PLAN = ROOT / "artifacts" / "trial_dish_tuning_plan.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate release-readiness evidence.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Summary output path.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional machine-readable JSON summary path.")
    parser.add_argument("--steam-input-summary", type=Path, default=DEFAULT_STEAM_INPUT_SUMMARY, help="Steam Input handoff summary path.")
    parser.add_argument("--deck-preflight-summary", type=Path, default=DEFAULT_DECK_PREFLIGHT_SUMMARY, help="Steam Deck preflight summary path.")
    parser.add_argument("--package-summary", type=Path, default=DEFAULT_PACKAGE_SUMMARY, help="Package/runtime validation summary path.")
    parser.add_argument("--playtest-summary", type=Path, default=DEFAULT_PLAYTEST_SUMMARY, help="Trial Dish playtest summary path.")
    parser.add_argument("--tuning-plan", type=Path, default=DEFAULT_TUNING_PLAN, help="Post-playtest tuning plan path.")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Exit 2 unless every release-readiness gate is ready.",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def gates_from_args(args: argparse.Namespace) -> list[tuple[str, Path, set[str], str]]:
    return [
        (
            "Steam Input handoff",
            resolve_path(args.steam_input_summary),
            {"ready"},
            "Run `python scripts/summarize_steam_input_handoff.py --require-ready` after Steamworks import/default config.",
        ),
        (
            "Steam Deck preflight",
            resolve_path(args.deck_preflight_summary),
            {"ready"},
            "Run `python scripts/summarize_steam_deck_preflight.py --require-ready` after the hardware pass.",
        ),
        (
            "Package runtime validation",
            resolve_path(args.package_summary),
            {"ready"},
            "Run `python scripts/summarize_package_validation.py --require-ready` after native Linux or Proton launch validation, including the Rust/wgpu `dist/FluoddityNative/` package candidate.",
        ),
        (
            "Trial Dish playtest",
            resolve_path(args.playtest_summary),
            {"tuning-ready"},
            "Run `python scripts/summarize_trial_dish_playtest.py --require-ready` after filling the playtest report.",
        ),
        (
            "Post-playtest tuning plan",
            resolve_path(args.tuning_plan),
            {"actionable"},
            "Run `python scripts/write_trial_dish_tuning_plan.py --require-ready` after the playtest summary is tuning-ready.",
        ),
    ]


def status_from_text(text: str) -> str:
    match = re.search(r"^- Status: (.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "missing"


def read_gate(name: str, path: Path, ready_statuses: set[str], next_step: str) -> dict[str, str | bool]:
    source = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    if not path.exists():
        return {
            "name": name,
            "source": source,
            "status": "missing",
            "ready": False,
            "next_step": next_step,
        }
    status = status_from_text(path.read_text(encoding="utf-8"))
    return {
        "name": name,
        "source": source,
        "status": status,
        "ready": status in ready_statuses,
        "next_step": next_step,
    }


def release_payload(gates_spec: list[tuple[str, Path, set[str], str]]) -> dict:
    gates = [read_gate(*gate) for gate in gates_spec]
    status = "ready" if all(bool(gate["ready"]) for gate in gates) else "not-ready"
    blockers = [gate for gate in gates if not gate["ready"]]
    return {
        "schema": "xenoculture.release_readiness.v1",
        "status": status,
        "ready": status == "ready",
        "gates": gates,
        "blocking_next_steps": [
            {
                "gate": gate["name"],
                "next_step": gate["next_step"],
            }
            for gate in blockers
        ],
    }


def write_summary(output: Path, payload: dict) -> Path:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Release Readiness Summary",
        "",
        f"- Status: {payload['status']}",
        "",
        "## Gates",
        "",
        "| Gate | Status | Source |",
        "| --- | --- | --- |",
    ]
    for gate in payload["gates"]:
        lines.append(f"| {gate['name']} | {gate['status']} | `{gate['source']}` |")

    lines.extend(["", "## Blocking Next Steps", ""])
    if payload["blocking_next_steps"]:
        lines.extend(f"- {item['gate']}: {item['next_step']}" for item in payload["blocking_next_steps"])
    else:
        lines.append("- None. All release-readiness gates are ready.")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def write_json_summary(output: Path, payload: dict) -> Path:
    output = resolve_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main() -> int:
    args = parse_args()
    payload = release_payload(gates_from_args(args))
    output = write_summary(args.output, payload)
    if args.json_output is not None:
        json_output = write_json_summary(args.json_output, payload)
        print(f"release_readiness_json={json_output}")
    print(f"release_readiness_summary={output}")
    status = payload["status"]
    print(f"release_readiness_status={status}")
    if args.require_ready and status != "ready":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
