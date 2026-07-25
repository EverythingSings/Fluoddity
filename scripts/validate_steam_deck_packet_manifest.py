"""Validate the generated Steam Deck packet manifest against local artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "artifacts" / "steam_deck_packet_manifest.json"
DEFAULT_READINESS = ROOT / "artifacts" / "release_readiness_summary.json"

EXPECTED_ARTIFACTS = {
    "artifacts/steam_deck_packet_index.md",
    "artifacts/steam_deck_packet_manifest.schema.json",
    "artifacts/trial_definitions.json",
    "artifacts/trial_definitions.schema.json",
    "artifacts/steam_input_handoff.md",
    "artifacts/steam_input_handoff_summary.md",
    "artifacts/trial_dish_playtest.md",
    "artifacts/trial_dish_playtest_summary.md",
    "artifacts/trial_dish_tuning_reference.md",
    "artifacts/trial_dish_tuning_plan.md",
    "artifacts/package_validation.md",
    "artifacts/package_validation_summary.md",
    "artifacts/native_wgpu_runtime.md",
    "artifacts/native_validation_suite.md",
    "artifacts/native_validation_suite.json",
    "artifacts/native_rust_quality.md",
    "artifacts/native_rust_quality.json",
    "artifacts/native_rust_tests.md",
    "artifacts/native_rust_tests.json",
    "artifacts/native_shader_parity.md",
    "artifacts/native_shader_parity.json",
    "artifacts/native_config_contract.md",
    "artifacts/native_config_contract.json",
    "artifacts/native_input_contract.md",
    "artifacts/native_input_contract.json",
    "artifacts/native_input_runtime.md",
    "artifacts/native_input_runtime.json",
    "artifacts/native_steam_input_alignment.md",
    "artifacts/native_steam_input_alignment.json",
    "artifacts/native_visual_metrics.md",
    "artifacts/native_visual_metrics.json",
    "artifacts/native_python_visual_parity.md",
    "artifacts/native_python_visual_parity.json",
    "artifacts/native_replay_determinism.md",
    "artifacts/native_replay_determinism.json",
    "artifacts/native_video_export_smoke.md",
    "artifacts/native_video_export_smoke.json",
    "artifacts/native-wgpu/native_video_export_smoke.mp4",
    "artifacts/native-wgpu/native_video_export_smoke.ppm",
    "artifacts/native-wgpu/native_video_export_smoke.metadata.json",
    "artifacts/native_trial_matrix.md",
    "artifacts/native_trial_matrix.json",
    "artifacts/native_preset_matrix.md",
    "artifacts/native_preset_matrix.json",
    "artifacts/native_rule_sensitivity.md",
    "artifacts/native_rule_sensitivity.json",
    "artifacts/native_parameter_sensitivity.md",
    "artifacts/native_parameter_sensitivity.json",
    "artifacts/native_package_smoke.md",
    "artifacts/native_package_smoke.json",
    "artifacts/native_package_manifest.md",
    "artifacts/native_package_manifest.json",
    "artifacts/native_timing_budget.md",
    "artifacts/native_timing_budget.json",
    "artifacts/native_steam_launch_contract.md",
    "artifacts/native_steam_launch_contract.json",
    "artifacts/steam_deck_preflight.md",
    "artifacts/steam_deck_preflight_summary.md",
    "artifacts/steam_deck_visual_evidence.md",
    "artifacts/release_readiness_summary.md",
    "artifacts/release_readiness_summary.json",
    "artifacts/release_readiness.schema.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Steam Deck packet manifest hashes and readiness snapshot.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Generated packet manifest JSON.")
    parser.add_argument(
        "--readiness-json",
        type=Path,
        default=DEFAULT_READINESS,
        help="Generated release readiness JSON referenced by the manifest.",
    )
    return parser.parse_args()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    require(path.exists(), f"missing JSON file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(payload, dict), f"JSON root should be object: {path}")
    return payload


def validate_manifest(manifest_path: Path, readiness_path: Path) -> None:
    manifest_path = resolve_repo_path(manifest_path)
    readiness_path = resolve_repo_path(readiness_path)
    manifest = load_json(manifest_path)
    require(
        manifest.get("schema") == "xenoculture.steam_deck_packet_manifest.v1",
        "manifest schema id mismatch",
    )
    artifacts = manifest.get("artifacts")
    require(isinstance(artifacts, list) and artifacts, "manifest artifacts should be a non-empty list")
    seen: set[str] = set()

    for entry in artifacts:
        require(isinstance(entry, dict), f"manifest artifact entry should be object: {entry!r}")
        artifact_path = entry.get("path")
        require(isinstance(artifact_path, str) and artifact_path, f"artifact path missing: {entry!r}")
        require(artifact_path not in seen, f"duplicate manifest artifact: {artifact_path}")
        seen.add(artifact_path)

        path = ROOT / artifact_path
        require(path.exists(), f"manifest artifact missing on disk: {artifact_path}")
        require(path.is_file(), f"manifest artifact should be a file: {artifact_path}")
        require(path.stat().st_size == entry.get("bytes"), f"byte count mismatch for {artifact_path}")
        require(sha256_file(path) == entry.get("sha256"), f"sha256 mismatch for {artifact_path}")

    missing = sorted(EXPECTED_ARTIFACTS - seen)
    extra = sorted(seen - EXPECTED_ARTIFACTS)
    require(not missing, f"manifest missing expected artifacts: {', '.join(missing)}")
    require(not extra, f"manifest lists unexpected artifacts: {', '.join(extra)}")

    readiness = load_json(readiness_path)
    snapshot = manifest.get("release_readiness")
    require(isinstance(snapshot, dict), "manifest release_readiness should be an object")
    require(snapshot.get("status") == readiness.get("status"), "release readiness status mismatch")
    require(snapshot.get("ready") is readiness.get("ready"), "release readiness ready flag mismatch")
    require(snapshot.get("gate_count") == len(readiness.get("gates", [])), "release readiness gate count mismatch")
    require(
        snapshot.get("blocking_count") == len(readiness.get("blocking_next_steps", [])),
        "release readiness blocking count mismatch",
    )

    native_video = manifest.get("native_video")
    require(isinstance(native_video, dict), "manifest native_video should be an object")
    video_report = load_json(ROOT / "artifacts" / "native_video_export_smoke.json")
    export_report = load_json(
        ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.metadata.json"
    )
    video_path = ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.mp4"
    require(native_video.get("status") == "pass", "native video snapshot should pass")
    require(
        native_video.get("evidence_scope") == "local-host-offscreen-export",
        "native video snapshot should identify local-host scope",
    )
    require(
        native_video.get("steam_deck_hardware_verified") is False,
        "local packet generation must not claim Steam Deck hardware video validation",
    )
    require(
        native_video.get("width") == 3840
        and native_video.get("height") == 2160
        and native_video.get("fps") == 60,
        "native video snapshot should record 4K/60 evidence",
    )
    require(
        native_video.get("frames") == video_report.get("video", {}).get("frames"),
        "native video frame count mismatch",
    )
    require(
        native_video.get("codec") == "h264"
        and native_video.get("pixel_format") == "yuv420p",
        "native video snapshot should record H.264/yuv420p",
    )
    require(
        native_video.get("timeline_mode")
        == export_report.get("timeline", {}).get("mode")
        == "offline-fixed-step",
        "native video snapshot should record offline fixed-step export",
    )
    require(
        native_video.get("video_sha256") == sha256_file(video_path),
        "native video snapshot hash mismatch",
    )


def main() -> int:
    args = parse_args()
    try:
        validate_manifest(args.manifest, args.readiness_json)
    except (AssertionError, json.JSONDecodeError) as exc:
        print("steam_deck_packet_manifest_status=invalid")
        print(f"steam_deck_packet_manifest_error={exc}")
        return 2
    print("steam_deck_packet_manifest_status=valid")
    print(f"steam_deck_packet_manifest={resolve_repo_path(args.manifest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
