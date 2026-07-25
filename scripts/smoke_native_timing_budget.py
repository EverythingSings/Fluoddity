"""Validate the native package's bounded Deck-profile timing report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMING = ROOT / "dist" / "FluoddityNative" / "artifacts" / "wgpu_deck_timing.json"
DEFAULT_JSON = ROOT / "artifacts" / "native_timing_budget.json"
DEFAULT_MARKDOWN = ROOT / "artifacts" / "native_timing_budget.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check native bounded Deck-profile frame-time budget.")
    parser.add_argument("--timing-report", type=Path, default=DEFAULT_TIMING, help="Timing JSON from the native Deck-profile run.")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON, help="JSON report path.")
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN, help="Markdown report path.")
    parser.add_argument("--min-frames", type=int, default=5, help="Minimum bounded timing frames expected.")
    parser.add_argument("--max-avg-frame-ms", type=float, default=16.67, help="Average frame-time budget for 60 FPS.")
    parser.add_argument("--max-worst-frame-ms", type=float, default=50.0, help="Worst-frame tolerance for short local smoke runs.")
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def write_reports(payload: dict, json_path: Path, markdown_path: Path) -> None:
    json_path = resolve(json_path)
    markdown_path = resolve(markdown_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Native Timing Budget",
        "",
        f"- Status: {payload['status']}",
        f"- Timing report: `{payload['timing_report']}`",
        f"- Scope: bounded local Deck-profile smoke, not actual Steam Deck hardware certification",
        f"- Frames: {payload.get('frames', 'missing')}",
        f"- Average frame time: {payload.get('avg_frame_ms', 'missing')} ms",
        f"- Worst frame time: {payload.get('worst_frame_ms', 'missing')} ms",
        f"- Average frame-time budget: <= {payload['max_avg_frame_ms']:.2f} ms",
        f"- Worst-frame tolerance: <= {payload['max_worst_frame_ms']:.2f} ms",
        "",
        "## Checks",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"- `{check['id']}`: {'pass' if check['passed'] else 'fail'} - {check['detail']}")
    if payload["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in payload["failures"])
    lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")


def check(checks: list[dict], failures: list[str], check_id: str, passed: bool, detail: str) -> None:
    checks.append({"id": check_id, "passed": passed, "detail": detail})
    if not passed:
        failures.append(detail)


def main() -> int:
    args = parse_args()
    timing_path = resolve(args.timing_report)
    checks: list[dict] = []
    failures: list[str] = []
    payload: dict[str, object] = {
        "schema": "fluoddity.native_timing_budget.v1",
        "timing_report": repo_path(timing_path),
        "min_frames": args.min_frames,
        "max_avg_frame_ms": args.max_avg_frame_ms,
        "max_worst_frame_ms": args.max_worst_frame_ms,
        "checks": checks,
        "failures": failures,
    }

    check(checks, failures, "timing_report_exists", timing_path.exists(), f"timing report exists at {repo_path(timing_path)}")
    report = {}
    if timing_path.exists():
        report = json.loads(timing_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "profile": report.get("profile"),
                "width": report.get("width"),
                "height": report.get("height"),
                "frames": report.get("frames"),
                "elapsed_seconds": report.get("elapsed_seconds"),
                "avg_fps": report.get("avg_fps"),
                "avg_frame_ms": report.get("avg_frame_ms"),
                "worst_frame_ms": report.get("worst_frame_ms"),
                "trial_id": report.get("trial_id"),
                "trial_runtime": report.get("trial_runtime"),
            }
        )

    check(checks, failures, "deck_profile", report.get("profile") == "deck", "timing profile should be deck")
    check(checks, failures, "deck_resolution", report.get("width") == 1280 and report.get("height") == 800, "timing run should use 1280x800")
    check(
        checks,
        failures,
        "minimum_frames",
        isinstance(report.get("frames"), int) and report.get("frames", 0) >= args.min_frames,
        f"timing report should contain at least {args.min_frames} frames",
    )
    check(
        checks,
        failures,
        "average_frame_budget",
        isinstance(report.get("avg_frame_ms"), (int, float)) and float(report.get("avg_frame_ms")) <= args.max_avg_frame_ms,
        f"average frame time should be <= {args.max_avg_frame_ms:.2f} ms",
    )
    check(
        checks,
        failures,
        "worst_frame_tolerance",
        isinstance(report.get("worst_frame_ms"), (int, float)) and float(report.get("worst_frame_ms")) <= args.max_worst_frame_ms,
        f"worst frame time should be <= {args.max_worst_frame_ms:.2f} ms",
    )
    trial_runtime = report.get("trial_runtime")
    check(checks, failures, "trial_runtime_present", isinstance(trial_runtime, dict), "timing report should include trial_runtime")
    if isinstance(trial_runtime, dict):
        check(
            checks,
            failures,
            "trial_runtime_running_or_finished",
            trial_runtime.get("status_code") in {1, 2, 3},
            "trial runtime should be running or finished during Deck-profile timing",
        )

    payload["status"] = "pass" if not failures else "fail"
    write_reports(payload, args.json_output, args.markdown)
    print(f"native_timing_budget_status={payload['status']}")
    print(f"native_timing_budget_markdown={resolve(args.markdown)}")
    print(f"native_timing_budget_json={resolve(args.json_output)}")
    return 0 if payload["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
