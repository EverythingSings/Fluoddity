"""Smoke-check the Steam Deck hardware packet generator."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.game_identity import ENGINE_NAME, GAME_TITLE

EXPECTED_REPORTS = {
    ROOT / "artifacts" / "steam_deck_packet_index.md": "# Steam Deck Hardware Packet",
    ROOT / "artifacts" / "steam_input_handoff.md": "# Steam Input Handoff",
    ROOT / "artifacts" / "steam_input_handoff_summary.md": "# Steam Input Handoff Summary",
    ROOT / "artifacts" / "trial_dish_playtest.md": "# Trial Dish Manual Playtest Report",
    ROOT / "artifacts" / "trial_dish_playtest_summary.md": "# Trial Dish Playtest Summary",
    ROOT / "artifacts" / "trial_dish_tuning_reference.md": "# Trial Dish Tuning Reference",
    ROOT / "artifacts" / "trial_dish_tuning_plan.md": "# Trial Dish Post-Playtest Tuning Plan",
    ROOT / "artifacts" / "package_validation.md": "# Package Runtime Validation Report",
    ROOT / "artifacts" / "package_validation_summary.md": "# Package Runtime Validation Summary",
    ROOT / "artifacts" / "native_wgpu_runtime.md": "# Native wgpu Runtime Handoff",
    ROOT / "artifacts" / "native_validation_suite.md": "# Native Validation Suite",
    ROOT / "artifacts" / "native_rust_quality.md": "# Native Rust Quality",
    ROOT / "artifacts" / "native_rust_tests.md": "# Native Rust Tests",
    ROOT / "artifacts" / "native_shader_parity.md": "# Native Shader Parity Audit",
    ROOT / "artifacts" / "native_config_contract.md": "# Native Config Contract Check",
    ROOT / "artifacts" / "native_input_contract.md": "# Native Input Contract",
    ROOT / "artifacts" / "native_input_runtime.md": "# Native Input Runtime Smoke",
    ROOT / "artifacts" / "native_steam_input_alignment.md": "# Native Steam Input Alignment",
    ROOT / "artifacts" / "native_visual_metrics.md": "# Native Visual Metrics",
    ROOT / "artifacts" / "native_python_visual_parity.md": "# Native Python Visual Parity",
    ROOT / "artifacts" / "native_replay_determinism.md": "# Native Replay Determinism",
    ROOT / "artifacts" / "native_video_export_smoke.md": "# Native Video Export Smoke",
    ROOT / "artifacts" / "native_trial_matrix.md": "# Native Trial Matrix",
    ROOT / "artifacts" / "native_preset_matrix.md": "# Native Preset Matrix",
    ROOT / "artifacts" / "native_rule_sensitivity.md": "# Native Rule Sensitivity",
    ROOT / "artifacts" / "native_parameter_sensitivity.md": "# Native Parameter Sensitivity",
    ROOT / "artifacts" / "native_package_smoke.md": "# Native Package Smoke",
    ROOT / "artifacts" / "native_package_manifest.md": "# Native Package Manifest",
    ROOT / "artifacts" / "native_timing_budget.md": "# Native Timing Budget",
    ROOT / "artifacts" / "native_steam_launch_contract.md": "# Native Steam Launch Contract",
    ROOT / "artifacts" / "steam_deck_preflight.md": "# Steam Deck Preflight Report",
    ROOT / "artifacts" / "steam_deck_preflight_summary.md": "# Steam Deck Preflight Summary",
    ROOT / "artifacts" / "steam_deck_visual_evidence.md": "# Steam Deck Visual Evidence",
    ROOT / "artifacts" / "release_readiness_summary.md": "# Release Readiness Summary",
}
EXPECTED_JSON_REPORTS = {
    ROOT / "artifacts" / "steam_deck_packet_manifest.json": "xenoculture.steam_deck_packet_manifest.v1",
    ROOT / "artifacts" / "trial_definitions.json": "fluoddity.trial_definitions.v1",
    ROOT / "artifacts" / "native_shader_parity.json": "fluoddity.native_shader_parity.v1",
    ROOT / "artifacts" / "native_config_contract.json": "fluoddity.native_config_contract_report.v1",
    ROOT / "artifacts" / "native_input_contract.json": "fluoddity.native_input_contract.v1",
    ROOT / "artifacts" / "native_input_runtime.json": "fluoddity.native_input_runtime_smoke.v1",
    ROOT / "artifacts" / "native_steam_input_alignment.json": "fluoddity.native_steam_input_alignment.v1",
    ROOT / "artifacts" / "native_visual_metrics.json": "fluoddity.native_visual_metrics.v1",
    ROOT / "artifacts" / "native_python_visual_parity.json": "fluoddity.native_python_visual_parity.v1",
    ROOT / "artifacts" / "native_replay_determinism.json": "fluoddity.native_replay_determinism.v1",
    ROOT / "artifacts" / "native_video_export_smoke.json": "fluoddity.native_video_export_smoke.v1",
    ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.metadata.json": "fluoddity.native_video_export.v1",
    ROOT / "artifacts" / "native_trial_matrix.json": "fluoddity.native_trial_matrix.v1",
    ROOT / "artifacts" / "native_preset_matrix.json": "fluoddity.native_preset_matrix.v1",
    ROOT / "artifacts" / "native_rule_sensitivity.json": "fluoddity.native_rule_sensitivity.v1",
    ROOT / "artifacts" / "native_parameter_sensitivity.json": "fluoddity.native_parameter_sensitivity.v1",
    ROOT / "artifacts" / "native_package_smoke.json": "fluoddity.native_package_smoke.v1",
    ROOT / "artifacts" / "native_package_manifest.json": "fluoddity.native_package_manifest.v1",
    ROOT / "artifacts" / "native_timing_budget.json": "fluoddity.native_timing_budget.v1",
    ROOT / "artifacts" / "native_steam_launch_contract.json": "fluoddity.native_steam_launch_contract.v1",
    ROOT / "artifacts" / "native_validation_suite.json": "fluoddity.native_validation_suite.v1",
    ROOT / "artifacts" / "native_rust_quality.json": "fluoddity.native_rust_quality.v1",
    ROOT / "artifacts" / "native_rust_tests.json": "fluoddity.native_rust_tests.v1",
    ROOT / "artifacts" / "release_readiness_summary.json": "xenoculture.release_readiness.v1",
}
EXPECTED_JSON_SCHEMA_REPORTS = {
    ROOT / "artifacts" / "steam_deck_packet_manifest.schema.json": "xenoculture.steam_deck_packet_manifest.v1",
    ROOT / "artifacts" / "trial_definitions.schema.json": "fluoddity.trial_definitions.v1",
    ROOT / "artifacts" / "release_readiness.schema.json": "xenoculture.release_readiness.v1",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_packet(python: str) -> None:
    manual_snapshots = {
        path: path.read_bytes()
        for path in (
            ROOT / "artifacts" / "trial_dish_playtest.md",
            ROOT / "artifacts" / "package_validation.md",
        )
        if path.exists()
    }
    proc = subprocess.run(
        [
            python,
            "scripts/prepare_steam_deck_packet.py",
            "--tester",
            "Smoke",
            "--device",
            "Local",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode == 0, f"packet command failed: {proc.stdout}\n{proc.stderr}")
    require("steam_deck_packet_reports=" in proc.stdout, "packet command should print report paths")
    require("steam_deck_packet_build=" in proc.stdout, "packet command should print build metadata")
    require("steam_deck_packet_index=artifacts/steam_deck_packet_index.md" in proc.stdout, "packet command should print index path")
    require("steam_deck_packet_manifest=artifacts/steam_deck_packet_manifest.json" in proc.stdout, "packet command should print manifest path")
    require(
        "steam_deck_packet_manifest_status=valid" in proc.stdout,
        "packet command should validate the manifest before reporting success",
    )
    require(
        proc.stdout.count("[packet] native validation suite") == 1,
        "packet command should invoke the consolidated native validation suite once",
    )
    require(
        "[packet] native shader parity audit" not in proc.stdout
        and "[packet] native visual metrics" not in proc.stdout,
        "packet command should not rerun native checks already owned by the suite",
    )
    for path, before in manual_snapshots.items():
        require(path.read_bytes() == before, f"packet refresh must preserve manual evidence: {path}")

    for path, heading in EXPECTED_REPORTS.items():
        require(path.exists(), f"missing generated report: {path}")
        text = path.read_text(encoding="utf-8")
        require(heading in text, f"report should contain heading {heading!r}: {path}")
    for path, schema in EXPECTED_JSON_REPORTS.items():
        require(path.exists(), f"missing generated JSON report: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("schema") == schema, f"JSON report should contain schema {schema!r}: {path}")
    for path, schema_id in EXPECTED_JSON_SCHEMA_REPORTS.items():
        require(path.exists(), f"missing generated JSON schema report: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        require(payload.get("$id") == schema_id, f"JSON schema report should contain $id {schema_id!r}: {path}")
        if path.name == "trial_definitions.schema.json":
            require(payload.get("properties", {}).get("trials"), f"JSON schema report should describe trial records: {path}")
        if path.name == "release_readiness.schema.json":
            require(
                payload.get("properties", {}).get("gates")
                and payload.get("properties", {}).get("blocking_next_steps"),
                f"JSON schema report should describe release readiness gates: {path}",
            )
        if path.name == "steam_deck_packet_manifest.schema.json":
            require(
                payload.get("properties", {}).get("artifacts")
                and payload.get("properties", {}).get("release_readiness")
                and payload.get("properties", {}).get("native_video"),
                f"JSON schema report should describe packet artifacts, readiness, and video evidence: {path}",
            )

    handoff = (ROOT / "artifacts" / "steam_input_handoff.md").read_text(encoding="utf-8")
    playtest = (ROOT / "artifacts" / "trial_dish_playtest.md").read_text(encoding="utf-8")
    summary = (ROOT / "artifacts" / "trial_dish_playtest_summary.md").read_text(encoding="utf-8")
    index = (ROOT / "artifacts" / "steam_deck_packet_index.md").read_text(encoding="utf-8")
    for report_name, text in {
        "packet index": index,
        "Steam Input handoff": handoff,
        "playtest report": playtest,
    }.items():
        require(f"- Game: {GAME_TITLE}" in text, f"{report_name} should be stamped with game title")
        require(f"- Engine/package: {ENGINE_NAME}" in text, f"{report_name} should be stamped with engine/package name")
    for report in [
        "artifacts/steam_input_handoff.md",
        "artifacts/steam_input_handoff_summary.md",
        "artifacts/steam_deck_packet_manifest.json",
        "artifacts/steam_deck_packet_manifest.schema.json",
        "artifacts/trial_definitions.json",
        "artifacts/trial_definitions.schema.json",
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
    ]:
        require(report in index, f"packet index should reference {report}")
    require("## Hardware Pass Order" in index, "packet index should include hardware pass order")
    require("trial_dish_tuning_reference.md" in index, "packet index should reference the tuning reference")
    require("Controller-only Trial Dish playtest summary is tuning-ready" in index, "packet index should list tuning-ready external gate")
    require("Rust/wgpu native runtime 60-second timing" in index, "packet index should list native runtime external gate")
    require("Native validation suite reviewed" in index, "packet index should list native validation suite external gate")
    require("Native shader parity audit reviewed" in index, "packet index should list shader parity external gate")
    require("Native input contract reviewed" in index, "packet index should list native input external gate")
    require("Native input runtime smoke reviewed" in index, "packet index should list native input runtime external gate")
    require("Native Steam Input alignment reviewed" in index, "packet index should list native Steam Input alignment external gate")
    require("Native-vs-Python visual parity measurement reviewed" in index, "packet index should list native-vs-Python parity external gate")
    require("Native replay determinism reviewed" in index, "packet index should list native replay determinism external gate")
    require("Native 4K/60 video export reviewed" in index, "packet index should list native video export external gate")
    require("Deck/Linux package video wrappers reviewed" in index, "packet index should preserve Deck/Linux video hardware scope")
    require("Native saved-preset matrix reviewed" in index, "packet index should list native saved-preset external gate")
    require("Native saved-rule sensitivity reviewed" in index, "packet index should list native saved-rule external gate")
    require("Native parameter sensitivity reviewed" in index, "packet index should list native parameter sensitivity external gate")
    require("native_timing_budget.md" in index, "packet index should list native timing budget external gate")
    require("Native Steam launch contract reviewed" in index, "packet index should list native Steam launch external gate")
    require("- Build:" in handoff, "Steam Input handoff should be stamped with build metadata")
    handoff_summary = (ROOT / "artifacts" / "steam_input_handoff_summary.md").read_text(encoding="utf-8")
    require("- Status: not-ready" in handoff_summary, "fresh Steam Input handoff summary should reject the blank handoff")
    require("Steamworks manifest import" in handoff_summary, "fresh Steam Input handoff summary should list missing Steamworks import evidence")
    require("- Build / commit:" in playtest, "playtest report should be stamped with build metadata")
    require("Action-feedback loop" in playtest, "playtest report should include action-feedback loop rating")
    require("Meaningful choice" in playtest, "playtest report should include meaningful-choice rating")
    require("Flow balance" in playtest, "playtest report should include flow-balance rating")
    require(
        "- Status: not-ready" in summary or "- Status: tuning-ready" in summary,
        "playtest summary should report an explicit readiness status",
    )
    require("Missing Evidence" in summary, "fresh packet summary should list missing playtest evidence")
    tuning = (ROOT / "artifacts" / "trial_dish_tuning_reference.md").read_text(encoding="utf-8")
    require("Trial 1: Bloom" in tuning, "tuning reference should include Trial 1")
    require("Activity threshold (`activity_threshold`)" in tuning, "tuning reference should include activity threshold")
    require("Rival growth (`rival_growth`)" in tuning, "tuning reference should include rival growth")
    plan = (ROOT / "artifacts" / "trial_dish_tuning_plan.md").read_text(encoding="utf-8")
    require(
        "- Status: blocked" in plan or "- Status: actionable" in plan,
        "tuning plan should reflect the preserved playtest evidence",
    )
    if "- Status: blocked" in plan:
        require("## Blocker" in plan, "blocked tuning plan should explain the evidence blocker")
    package_validation = (ROOT / "artifacts" / "package_validation.md").read_text(encoding="utf-8")
    require(f"- Game: {GAME_TITLE}" in package_validation, "package validation report should be stamped with game title")
    require(f"- Engine/package: {ENGINE_NAME}" in package_validation, "package validation report should be stamped with engine/package name")
    require("- Build / commit:" in package_validation, "package validation report should be stamped with build metadata")
    require("## Native wgpu Package" in package_validation, "package validation report should include native wgpu package section")
    require("## Native Video Export" in package_validation, "package validation report should include native video section")
    require("`dist/FluoddityNative/`" in package_validation, "package validation report should reference native package output")
    require("Actual Steam Deck hardware used (yes/no)" in package_validation, "package validation should require an explicit hardware scope")
    package_summary = (ROOT / "artifacts" / "package_validation_summary.md").read_text(encoding="utf-8")
    require(
        "- Status: not-ready" in package_summary or "- Status: ready" in package_summary,
        "package validation summary should report an explicit readiness status",
    )
    require("Package Build" in package_summary, "fresh package validation summary should include package coverage")
    require("Native wgpu Package" in package_summary, "fresh package validation summary should include native package coverage")
    require("Native Video Export" in package_summary, "fresh package validation summary should include native video coverage")
    if "- Status: not-ready" in package_summary:
        require("Missing Evidence" in package_summary, "not-ready package summary should list its blockers")
    native_wgpu = (ROOT / "artifacts" / "native_wgpu_runtime.md").read_text(encoding="utf-8")
    require(f"- Game: {GAME_TITLE}" in native_wgpu, "native wgpu report should be stamped with game title")
    require(f"- Engine/package: {ENGINE_NAME}" in native_wgpu, "native wgpu report should be stamped with engine/package name")
    require("runtime/rust-wgpu-spike/scripts/smoke-deck.sh" in native_wgpu, "native wgpu report should include Deck smoke command")
    require("Rust + wgpu" in native_wgpu, "native wgpu report should name runtime candidate")
    require("## Steam Deck Hardware Pass" in native_wgpu, "native wgpu report should include hardware checklist")
    native_validation_suite = (ROOT / "artifacts" / "native_validation_suite.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_validation_suite, "native validation suite should pass")
    require("Gates passed:" in native_validation_suite, "native validation suite should report local gate coverage")
    require("rust_quality" in native_validation_suite, "native validation suite should include Rust quality gate")
    require("rust_unit_tests" in native_validation_suite, "native validation suite should include Rust unit tests")
    require("shader_parity" in native_validation_suite, "native validation suite should include shader parity gate")
    require("python_visual_parity" in native_validation_suite, "native validation suite should include Python visual parity gate")
    require("timing_budget" in native_validation_suite, "native validation suite should include native timing budget gate")
    require("video_export" in native_validation_suite, "native validation suite should include native video export gate")
    native_validation_suite_payload = json.loads((ROOT / "artifacts" / "native_validation_suite.json").read_text(encoding="utf-8"))
    require(native_validation_suite_payload.get("status") == "pass", "native validation suite JSON should pass")
    require(native_validation_suite_payload.get("passed_gate_count") == native_validation_suite_payload.get("gate_count"), "native validation suite JSON should pass all gates")
    suite_gates = {gate.get("id"): gate for gate in native_validation_suite_payload.get("gates", [])}
    require(suite_gates.get("rust_quality", {}).get("observed_status") == "pass", "native validation suite should pass Rust quality")
    require(suite_gates.get("rust_unit_tests", {}).get("observed_status") == "pass", "native validation suite should pass Rust unit tests")
    require(
        suite_gates.get("shader_parity", {}).get("observed_status")
        in {"incomplete", "complete"},
        "native validation suite should accept honest incomplete or completed shader parity",
    )
    require(suite_gates.get("python_visual_parity", {}).get("observed_status") in {"measured-drift", "within-threshold"}, "native validation suite should preserve visual parity status")
    require(suite_gates.get("timing_budget", {}).get("observed_status") == "pass", "native validation suite should pass native timing budget")
    require(suite_gates.get("video_export", {}).get("observed_status") == "pass", "native validation suite should pass native video export")
    native_video_smoke = json.loads((ROOT / "artifacts" / "native_video_export_smoke.json").read_text(encoding="utf-8"))
    require(native_video_smoke.get("status") == "pass", "native video export smoke JSON should pass")
    native_video = native_video_smoke.get("video", {})
    require(
        native_video.get("width") == 3840
        and native_video.get("height") == 2160
        and native_video.get("fps") == 60,
        "native video export smoke should prove 4K/60 output",
    )
    require(native_video.get("bytes", 0) > 0, "native video export smoke should record output bytes")
    require(len(native_video.get("sha256", "")) == 64, "native video export smoke should record MP4 SHA-256")
    require(
        all(native_video_smoke.get("probe", {}).get("stream_checks", {}).values()),
        "native video export smoke should pass all ffprobe checks",
    )
    require(
        native_video_smoke.get("probe", {}).get("complete_decode_returncode") == 0,
        "native video export smoke should fully decode the MP4",
    )
    require(
        native_video_smoke.get("repeat_export", {}).get("status") == "pass",
        "native video export smoke should prove repeat determinism",
    )
    video_metadata = json.loads(
        (ROOT / "artifacts" / "native-wgpu" / "native_video_export_smoke.metadata.json").read_text(
            encoding="utf-8"
        )
    )
    require(video_metadata.get("schema") == "fluoddity.native_video_export.v1", "native video metadata schema should match")
    require(video_metadata.get("timeline", {}).get("mode") == "offline-fixed-step", "native video metadata should identify fixed-step export")
    require(video_metadata.get("timeline", {}).get("deterministic_frame_rate") is True, "native video metadata should identify deterministic frame rate")
    native_rust_quality = (ROOT / "artifacts" / "native_rust_quality.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_rust_quality, "native Rust quality report should pass")
    native_rust_quality_payload = json.loads((ROOT / "artifacts" / "native_rust_quality.json").read_text(encoding="utf-8"))
    require(native_rust_quality_payload.get("status") == "pass", "native Rust quality JSON should pass")
    require(native_rust_quality_payload.get("passed_check_count") == native_rust_quality_payload.get("check_count"), "native Rust quality JSON should pass all checks")
    native_rust_tests = (ROOT / "artifacts" / "native_rust_tests.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_rust_tests, "native Rust tests report should pass")
    native_rust_tests_payload = json.loads((ROOT / "artifacts" / "native_rust_tests.json").read_text(encoding="utf-8"))
    require(native_rust_tests_payload.get("status") == "pass", "native Rust tests JSON should pass")
    native_parity = (ROOT / "artifacts" / "native_shader_parity.md").read_text(encoding="utf-8")
    require(
        any(f"- Status: {status}" in native_parity for status in ("incomplete", "complete")),
        "native shader parity report should mark incomplete or complete",
    )
    require("Rust/WGSL Params layout match: yes" in native_parity, "native shader parity report should verify layout")
    require("ABSOLUTE_ORIENTATION" in native_parity, "native shader parity report should list orientation coverage")
    native_parity_payload = json.loads((ROOT / "artifacts" / "native_shader_parity.json").read_text(encoding="utf-8"))
    require(
        native_parity_payload.get("status") in {"incomplete", "complete"},
        "native shader parity JSON should mark incomplete or complete",
    )
    require(native_parity_payload.get("params_layout_match") is True, "native shader parity JSON should confirm layout match")
    require(
        native_parity_payload.get("covered_gpu_param_count") == native_parity_payload.get("gpu_param_count"),
        "native shader parity JSON should cover every replacement-critical GPU parameter path",
    )
    gpu_param_coverage = {
        item.get("field"): item for item in native_parity_payload.get("gpu_param_coverage", [])
    }
    for field in [
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
        "DISABLE_SYMMETRY",
        "ABSOLUTE_ORIENTATION",
        "ORIENTATION_MIX",
        "boundary_conditions",
        "initial_conditions",
        "num_cohorts",
        "rule_seed",
        "hue_sensitivity",
        "color_by_cohort",
        "ink_weight",
        "watercolor_mode",
        "emboss_mode",
        "emboss_intensity",
        "emboss_smoothness",
        "slider_ranges",
        "x_sweeps",
        "y_sweeps",
        "cohort_sweeps",
        "jitters",
    ]:
        require(
            gpu_param_coverage.get(field, {}).get("status") == "covered",
            f"native shader parity JSON should prove GPU parameter coverage for {field}",
        )
    feature_groups = {group.get("id"): group for group in native_parity_payload.get("feature_groups", [])}
    for group_id in [
        "core_saved_config_params",
        "saved_fourier_rule",
        "orientation_symmetry",
        "parameter_sweeps_jitter",
        "reset_boundary_initialization",
    ]:
        require(
            feature_groups.get(group_id, {}).get("status") == "covered",
            f"native shader parity JSON should cover replacement-required group {group_id}",
        )
        require(
            feature_groups.get(group_id, {}).get("replacement_required") is True,
            f"native shader parity JSON should mark {group_id} replacement-required",
        )
    for group_id in [
        "multi_load_rule_selection",
        "external_force_strafe_fields",
        "rule_readback_mutation_history",
        "canvas_brush_editor_tools",
    ]:
        require(
            feature_groups.get(group_id, {}).get("status") == "missing",
            f"native shader parity JSON should honestly mark deferred gap {group_id} missing",
        )
        require(
            feature_groups.get(group_id, {}).get("replacement_required") is False,
            f"native shader parity JSON should mark {group_id} deferred for player scope",
        )
    native_config_contract = (ROOT / "artifacts" / "native_config_contract.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_config_contract, "native config contract report should pass")
    require("Configs checked: 26" in native_config_contract, "native config contract report should check Core presets")
    native_config_contract_payload = json.loads((ROOT / "artifacts" / "native_config_contract.json").read_text(encoding="utf-8"))
    require(native_config_contract_payload.get("status") == "pass", "native config contract JSON should pass")
    require(
        native_config_contract_payload.get("checked_config_count") == 26,
        "native config contract JSON should check Core presets",
    )
    native_input_contract = (ROOT / "artifacts" / "native_input_contract.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_input_contract, "native input contract report should pass")
    require("RightStickX" in native_input_contract, "native input contract should include right stick X")
    require("ApplyNutrientGel" in native_input_contract, "native input contract should include apply action")
    native_input_contract_payload = json.loads((ROOT / "artifacts" / "native_input_contract.json").read_text(encoding="utf-8"))
    require(native_input_contract_payload.get("input_backend") == "gilrs", "native input contract JSON should name gilrs")
    actions = {action.get("action"): action for action in native_input_contract_payload.get("actions", [])}
    require("South" in actions.get("StartOrResume", {}).get("buttons", []), "native input JSON should include A/South start")
    require("RightTrigger2" in actions.get("ApplyNutrientGel", {}).get("buttons", []), "native input JSON should include R2 apply")
    native_input_runtime = (ROOT / "artifacts" / "native_input_runtime.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_input_runtime, "native input runtime report should pass")
    require("pause_suppresses_apply" in native_input_runtime, "native input runtime should cover pause apply suppression")
    native_input_runtime_payload = json.loads((ROOT / "artifacts" / "native_input_runtime.json").read_text(encoding="utf-8"))
    require(native_input_runtime_payload.get("status") == "pass", "native input runtime JSON should pass")
    input_checks = native_input_runtime_payload.get("checks", {})
    for check in [
        "briefing_starts_paused",
        "south_starts_running",
        "r2_applies_when_running",
        "pause_suppresses_apply",
        "resume_restores_running",
        "right_stick_moves_cursor",
        "result_state_reached",
        "south_next_returns_to_briefing",
        "south_next_advances_trial",
        "final_result_state_reached",
        "final_next_restarts_sequence",
        "result_overlay_names_next_assay",
        "final_overlay_names_sequence_complete",
        "result_overlay_uses_view_exit",
        "prompt_actions_are_structured",
    ]:
        require(input_checks.get(check) is True, f"native input runtime JSON should pass {check}")
    input_snapshots = {snapshot.get("label"): snapshot for snapshot in native_input_runtime_payload.get("snapshots", [])}
    require(
        "Next assay unlocked" in input_snapshots.get("result_won", {}).get("overlay", {}).get("status", ""),
        "native input runtime should capture next-assay result copy",
    )
    require(
        "Sequence complete" in input_snapshots.get("final_result_won", {}).get("overlay", {}).get("status", ""),
        "native input runtime should capture final sequence-complete copy",
    )
    require(
        "VIEW EXIT" in input_snapshots.get("result_won", {}).get("overlay", {}).get("prompt", ""),
        "native input runtime should capture View exit prompt",
    )
    result_actions = {
        action.get("steam_action")
        for action in input_snapshots.get("result_won", {}).get("overlay", {}).get("prompt_actions", [])
    }
    require(
        {"StartExperiment", "ExitExperiment"}.issubset(result_actions),
        "native input runtime should expose structured result prompt actions",
    )
    native_steam_input_alignment = (ROOT / "artifacts" / "native_steam_input_alignment.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_steam_input_alignment, "native Steam Input alignment report should pass")
    require("ApplyNutrientGel" in native_steam_input_alignment, "native Steam Input alignment should include apply action")
    require("StartExperiment" in native_steam_input_alignment, "native Steam Input alignment should include start action")
    require("run_input_runtime.sh" in native_steam_input_alignment, "native Steam Input alignment should include package runtime wrapper")
    native_steam_input_alignment_payload = json.loads((ROOT / "artifacts" / "native_steam_input_alignment.json").read_text(encoding="utf-8"))
    require(native_steam_input_alignment_payload.get("status") == "pass", "native Steam Input alignment JSON should pass")
    aligned_actions = {action.get("steam_action"): action for action in native_steam_input_alignment_payload.get("actions", [])}
    for action in ["AimNutrientGel", "ApplyNutrientGel", "StartExperiment", "PauseExperiment", "ExitExperiment"]:
        require(aligned_actions.get(action, {}).get("valid") is True, f"native Steam Input alignment JSON should pass {action}")
    for wrapper in ["run_input_contract.ps1", "run_input_contract.sh", "run_input_runtime.ps1", "run_input_runtime.sh"]:
        require(
            wrapper in native_steam_input_alignment_payload.get("package_wrappers", []),
            f"native Steam Input alignment JSON should include {wrapper}",
        )
    native_visual_metrics = (ROOT / "artifacts" / "native_visual_metrics.md").read_text(encoding="utf-8")
    require("Scope: coarse image metrics" in native_visual_metrics, "native visual metrics should describe its scope")
    native_visual_metrics_payload = json.loads((ROOT / "artifacts" / "native_visual_metrics.json").read_text(encoding="utf-8"))
    require(
        native_visual_metrics_payload.get("status") in {"compared", "reference-missing"},
        "native visual metrics JSON should report compared or reference-missing",
    )
    require(native_visual_metrics_payload.get("native"), "native visual metrics JSON should include native metrics")
    native_python_visual_parity = (ROOT / "artifacts" / "native_python_visual_parity.md").read_text(encoding="utf-8")
    require(
        "Exact parity claimed: no" in native_python_visual_parity,
        "native-vs-Python parity report should not claim exact parity",
    )
    require(
        "Pixel Difference" in native_python_visual_parity,
        "native-vs-Python parity report should include image delta evidence",
    )
    native_python_visual_parity_payload = json.loads((ROOT / "artifacts" / "native_python_visual_parity.json").read_text(encoding="utf-8"))
    require(
        native_python_visual_parity_payload.get("status") in {"within-threshold", "measured-drift"},
        "native-vs-Python parity JSON should measure current drift without failing the packet",
    )
    require(
        native_python_visual_parity_payload.get("exact_parity_claimed") is False,
        "native-vs-Python parity JSON should explicitly reject exact parity claims",
    )
    require(
        native_python_visual_parity_payload.get("native") and native_python_visual_parity_payload.get("python"),
        "native-vs-Python parity JSON should include both image metrics",
    )
    require(
        native_python_visual_parity_payload.get("pixel_difference", {}).get("same_size") is True,
        "native-vs-Python parity JSON should compare same-size captures",
    )
    native_replay_determinism = (ROOT / "artifacts" / "native_replay_determinism.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_replay_determinism, "native replay determinism report should pass")
    require("Bit exact: yes" in native_replay_determinism, "native replay determinism should be bit-exact")
    native_replay_determinism_payload = json.loads((ROOT / "artifacts" / "native_replay_determinism.json").read_text(encoding="utf-8"))
    require(native_replay_determinism_payload.get("status") == "pass", "native replay determinism JSON should pass")
    require(native_replay_determinism_payload.get("bit_exact") is True, "native replay determinism JSON should be bit-exact")
    require(
        native_replay_determinism_payload.get("pixel_difference", {}).get("mean_abs_channel_delta") == 0.0,
        "native replay determinism JSON should record zero pixel delta",
    )
    native_trial_matrix = (ROOT / "artifacts" / "native_trial_matrix.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_trial_matrix, "native trial matrix report should pass")
    require("Trials checked: 3" in native_trial_matrix, "native trial matrix should check all exported trials")
    native_trial_matrix_payload = json.loads((ROOT / "artifacts" / "native_trial_matrix.json").read_text(encoding="utf-8"))
    require(native_trial_matrix_payload.get("status") == "pass", "native trial matrix JSON should pass")
    require(native_trial_matrix_payload.get("trial_count") == 3, "native trial matrix JSON should check all exported trials")
    require(native_trial_matrix_payload.get("passed_trial_count") == 3, "native trial matrix JSON should pass all exported trials")
    native_preset_matrix = (ROOT / "artifacts" / "native_preset_matrix.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_preset_matrix, "native preset matrix report should pass")
    require("Scope: saved-preset response" in native_preset_matrix, "native preset matrix should describe its scope")
    native_preset_matrix_payload = json.loads((ROOT / "artifacts" / "native_preset_matrix.json").read_text(encoding="utf-8"))
    require(native_preset_matrix_payload.get("status") == "pass", "native preset matrix JSON should pass")
    require(native_preset_matrix_payload.get("preset_count", 0) >= 5, "native preset matrix JSON should check representative presets")
    require(
        native_preset_matrix_payload.get("passed_preset_count") == native_preset_matrix_payload.get("preset_count"),
        "native preset matrix JSON should pass all checked presets",
    )
    native_rule_sensitivity = (ROOT / "artifacts" / "native_rule_sensitivity.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_rule_sensitivity, "native rule sensitivity report should pass")
    require("Scope: saved Fourier rule influence" in native_rule_sensitivity, "native rule sensitivity should describe its scope")
    native_rule_sensitivity_payload = json.loads((ROOT / "artifacts" / "native_rule_sensitivity.json").read_text(encoding="utf-8"))
    require(native_rule_sensitivity_payload.get("status") == "pass", "native rule sensitivity JSON should pass")
    require(
        native_rule_sensitivity_payload.get("saved_rule", {}).get("contract", {}).get("has_saved_rule") is True,
        "native rule sensitivity JSON should confirm saved-rule contract",
    )
    require(
        native_rule_sensitivity_payload.get("zero_rule", {}).get("contract", {}).get("has_saved_rule") is False,
        "native rule sensitivity JSON should confirm zero-rule contract",
    )
    require(
        float(native_rule_sensitivity_payload.get("pixel_delta", {}).get("changed_channel_ratio", 0.0)) >= 0.05,
        "native rule sensitivity JSON should record pixel-level rule influence",
    )
    native_parameter_sensitivity = (ROOT / "artifacts" / "native_parameter_sensitivity.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_parameter_sensitivity, "native parameter sensitivity report should pass")
    require("sensor_gain_low" in native_parameter_sensitivity, "native parameter sensitivity should include sensor gain")
    require("orientation_radial" in native_parameter_sensitivity, "native parameter sensitivity should include orientation")
    native_parameter_sensitivity_payload = json.loads((ROOT / "artifacts" / "native_parameter_sensitivity.json").read_text(encoding="utf-8"))
    require(native_parameter_sensitivity_payload.get("status") == "pass", "native parameter sensitivity JSON should pass")
    require(
        native_parameter_sensitivity_payload.get("passed_variant_count") == len(native_parameter_sensitivity_payload.get("variants", [])),
        "native parameter sensitivity JSON should pass every checked variant",
    )
    checked_fields = {variant.get("field") for variant in native_parameter_sensitivity_payload.get("variants", [])}
    for field in [
        "physics.sensor_gain",
        "physics.sensor_distance",
        "physics.sensor_angle",
        "physics.drag",
        "physics.trail_persistence",
        "settings.disable_symmetry",
        "settings.absolute_orientation",
    ]:
        require(field in checked_fields, f"native parameter sensitivity JSON should check {field}")
    native_package_smoke = (ROOT / "artifacts" / "native_package_smoke.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_package_smoke, "native package smoke report should pass")
    require("Package: `dist/FluoddityNative`" in native_package_smoke, "native package smoke should name package dir")
    native_package_smoke_payload = json.loads((ROOT / "artifacts" / "native_package_smoke.json").read_text(encoding="utf-8"))
    require(native_package_smoke_payload.get("status") == "pass", "native package smoke JSON should pass")
    require(native_package_smoke_payload.get("headless", {}).get("valid") is True, "native package smoke JSON should validate headless launch")
    require(native_package_smoke_payload.get("window", {}).get("valid") is True, "native package smoke JSON should validate window timing")
    require(native_package_smoke_payload.get("steam_launch_wrappers", {}).get("valid") is True, "native package smoke JSON should validate Steam launch wrappers")
    require(
        native_package_smoke_payload.get("steam_launch_wrappers", {})
        .get("steam_facing_executable", {})
        .get("exists")
        is True,
        "native package smoke JSON should validate Steam-facing executable alias",
    )
    require(native_package_smoke_payload.get("input_contract", {}).get("valid") is True, "native package smoke JSON should validate input contract wrapper")
    require(native_package_smoke_payload.get("input_runtime", {}).get("valid") is True, "native package smoke JSON should validate input runtime wrapper")
    require(native_package_smoke_payload.get("steam_input", {}).get("valid") is True, "native package smoke JSON should validate bundled Steam Input handoff")
    require(native_package_smoke_payload.get("ffmpeg_bundle", {}).get("valid") is True, "native package smoke JSON should validate bundled FFmpeg")
    require(native_package_smoke_payload.get("video_export", {}).get("valid") is True, "native package smoke JSON should validate the packaged 4K/60 export wrapper")
    require(
        native_package_smoke_payload.get("video_export", {}).get("steam_deck_hardware_verified") is False,
        "local Windows package video smoke must not claim Steam Deck hardware validation",
    )
    require(
        native_package_smoke_payload.get("environment", {}).get("package_target") == "windows",
        "native package smoke should identify the Windows package target",
    )
    native_package_manifest = (ROOT / "artifacts" / "native_package_manifest.md").read_text(encoding="utf-8")
    require("XenocultureTrialDish.exe" in native_package_manifest, "native package manifest should include Steam-facing executable")
    require("fluoddity-wgpu-spike.exe" in native_package_manifest, "native package manifest should include the executable")
    require("run_steam_deck.ps1" in native_package_manifest, "native package manifest should include Windows Steam launch wrapper")
    require("run_steam_deck.sh" in native_package_manifest, "native package manifest should include Deck/Linux Steam launch wrapper")
    require("run_deck_profile.ps1" in native_package_manifest, "native package manifest should include Windows Deck-profile launcher")
    require("run_input_contract.ps1" in native_package_manifest, "native package manifest should include Windows input contract launcher")
    require("run_input_runtime.sh" in native_package_manifest, "native package manifest should include Deck/Linux input runtime launcher")
    require("run_export_video.ps1" in native_package_manifest, "native package manifest should include Windows video export wrapper")
    require("run_export_video.sh" in native_package_manifest, "native package manifest should include Deck/Linux video export wrapper")
    require("run_record_video.ps1" in native_package_manifest, "native package manifest should include Windows frame-capture wrapper")
    require("run_record_video.sh" in native_package_manifest, "native package manifest should include Deck/Linux frame-capture wrapper")
    require("ffmpeg.exe" in native_package_manifest, "native package manifest should include bundled Windows FFmpeg")
    require("third_party/ffmpeg/LICENSE" in native_package_manifest, "native package manifest should include FFmpeg license")
    require("third_party/ffmpeg/PROVENANCE.txt" in native_package_manifest, "native package manifest should include FFmpeg provenance")
    require("steam_input/steam_input_manifest.vdf" in native_package_manifest, "native package manifest should include Steam Input manifest")
    require("steam_input/trial_prompt_glyph_map.json" in native_package_manifest, "native package manifest should include Steam Input glyph map")
    require("steam_input/steam_input_handoff.md" in native_package_manifest, "native package manifest should include package-local Steam Input handoff")
    native_package_manifest_payload = json.loads((ROOT / "artifacts" / "native_package_manifest.json").read_text(encoding="utf-8"))
    require(native_package_manifest_payload.get("file_count", 0) >= 8, "native package manifest JSON should include package files")
    manifest_paths = {artifact.get("path") for artifact in native_package_manifest_payload.get("artifacts", [])}
    require("XenocultureTrialDish.exe" in manifest_paths, "native package manifest JSON should include Steam-facing executable")
    require("fluoddity-wgpu-spike.exe" in manifest_paths, "native package manifest JSON should include executable")
    require("artifacts/trial_definitions.json" in manifest_paths, "native package manifest JSON should include trial definitions")
    require("run_steam_deck.ps1" in manifest_paths, "native package manifest JSON should include Windows Steam launch wrapper")
    require("run_steam_deck.sh" in manifest_paths, "native package manifest JSON should include Deck/Linux Steam launch wrapper")
    require("run_input_contract.ps1" in manifest_paths, "native package manifest JSON should include input contract wrapper")
    require("run_input_runtime.sh" in manifest_paths, "native package manifest JSON should include input runtime wrapper")
    require("run_export_video.ps1" in manifest_paths, "native package manifest JSON should include Windows video export wrapper")
    require("run_export_video.sh" in manifest_paths, "native package manifest JSON should include Deck/Linux video export wrapper")
    require("run_record_video.ps1" in manifest_paths, "native package manifest JSON should include Windows frame-capture wrapper")
    require("run_record_video.sh" in manifest_paths, "native package manifest JSON should include Deck/Linux frame-capture wrapper")
    require("ffmpeg.exe" in manifest_paths, "native package manifest JSON should include bundled Windows FFmpeg")
    require("third_party/ffmpeg/LICENSE" in manifest_paths, "native package manifest JSON should include FFmpeg license")
    require("third_party/ffmpeg/PROVENANCE.txt" in manifest_paths, "native package manifest JSON should include FFmpeg provenance")
    require("steam_input/steam_input_manifest.vdf" in manifest_paths, "native package manifest JSON should include Steam Input manifest")
    require("steam_input/trial_prompt_glyph_map.json" in manifest_paths, "native package manifest JSON should include Steam Input glyph map")
    require("steam_input/steam_input_handoff.md" in manifest_paths, "native package manifest JSON should include package-local Steam Input handoff")
    for artifact in native_package_manifest_payload.get("artifacts", []):
        require(artifact.get("bytes", 0) > 0, f"native package manifest artifact should record byte size: {artifact}")
        require(len(artifact.get("sha256", "")) == 64, f"native package manifest artifact should record SHA-256: {artifact}")
    native_timing_budget = (ROOT / "artifacts" / "native_timing_budget.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_timing_budget, "native timing budget report should pass")
    require("bounded local Deck-profile smoke" in native_timing_budget, "native timing budget should describe bounded local scope")
    native_timing_budget_payload = json.loads((ROOT / "artifacts" / "native_timing_budget.json").read_text(encoding="utf-8"))
    require(native_timing_budget_payload.get("status") == "pass", "native timing budget JSON should pass")
    require(native_timing_budget_payload.get("profile") == "deck", "native timing budget JSON should check deck profile")
    require(native_timing_budget_payload.get("width") == 1280 and native_timing_budget_payload.get("height") == 800, "native timing budget JSON should check Deck-sized resolution")
    require(float(native_timing_budget_payload.get("avg_frame_ms", 999.0)) <= float(native_timing_budget_payload.get("max_avg_frame_ms", 0.0)), "native timing budget JSON should enforce average frame budget")
    require(float(native_timing_budget_payload.get("worst_frame_ms", 999.0)) <= float(native_timing_budget_payload.get("max_worst_frame_ms", 0.0)), "native timing budget JSON should enforce worst-frame tolerance")
    native_steam_launch_contract = (ROOT / "artifacts" / "native_steam_launch_contract.md").read_text(encoding="utf-8")
    require("- Status: pass" in native_steam_launch_contract, "native Steam launch contract report should pass")
    require("XenocultureTrialDish.exe" in native_steam_launch_contract, "native Steam launch contract should name Windows executable")
    require("./XenocultureTrialDish" in native_steam_launch_contract, "native Steam launch contract should name Deck/Linux executable")
    native_steam_launch_payload = json.loads((ROOT / "artifacts" / "native_steam_launch_contract.json").read_text(encoding="utf-8"))
    require(native_steam_launch_payload.get("status") == "pass", "native Steam launch contract JSON should pass")
    launch_targets = {target.get("platform"): target for target in native_steam_launch_payload.get("targets", [])}
    for platform in ["windows_or_proton", "steam_deck_linux"]:
        target = launch_targets.get(platform, {})
        require(target.get("python_free") is True, f"native Steam launch target should be Python-free: {platform}")
        require(target.get("bounded_smoke") is False, f"native Steam launch target should not be a bounded smoke: {platform}")
        require(target.get("wrapper_uses_target") is True, f"native Steam launch wrapper should use target: {platform}")
    deck_target = launch_targets.get("steam_deck_linux", {})
    require(deck_target.get("compatibility_fallback") is False, "Deck/Linux Steam launch wrapper should not fall back to compatibility binary")
    require(deck_target.get("package_script_creates_target") is True, "Deck package script should create product-named target")
    require(deck_target.get("package_script_marks_executable") is True, "Deck package script should mark product target executable")

    preflight = (ROOT / "artifacts" / "steam_deck_preflight.md").read_text(encoding="utf-8")
    require(f"- Game: {GAME_TITLE}" in preflight, "preflight report should be stamped with game title")
    require(f"- Engine/package: {ENGINE_NAME}" in preflight, "preflight report should be stamped with engine/package name")
    require("- Build:" in preflight, "preflight report should be stamped with build metadata")
    require(
        "Packet index: artifacts/steam_deck_packet_index.md" in preflight,
        "preflight packet should reference the packet index",
    )
    require(
        "## Companion Manual Reports" in preflight,
        "preflight packet should list companion reports",
    )
    require(
        "artifacts/trial_dish_playtest.md" in preflight,
        "preflight packet should reference playtest report",
    )
    require(
        "action-feedback loop, meaningful choice, flow balance" in preflight,
        "preflight packet should name the design-contract playtest ratings",
    )
    require(
        "artifacts/steam_input_handoff_summary.md" in preflight,
        "preflight packet should reference Steam Input handoff summary",
    )
    require(
        "artifacts/trial_dish_playtest_summary.md" in preflight,
        "preflight packet should reference playtest summary",
    )
    require(
        "artifacts/trial_dish_tuning_reference.md" in preflight,
        "preflight packet should reference tuning reference",
    )
    require(
        "artifacts/trial_dish_tuning_plan.md" in preflight,
        "preflight packet should reference tuning plan",
    )
    require(
        "artifacts/package_validation.md" in preflight,
        "preflight packet should reference package validation report",
    )
    require(
        "artifacts/package_validation_summary.md" in preflight,
        "preflight packet should reference package validation summary",
    )
    require(
        "artifacts/native_wgpu_runtime.md" in preflight,
        "preflight packet should reference native wgpu runtime report",
    )
    require(
        "artifacts/steam_deck_preflight_summary.md" in preflight,
        "preflight packet should reference preflight summary",
    )
    preflight_summary = (ROOT / "artifacts" / "steam_deck_preflight_summary.md").read_text(encoding="utf-8")
    require("- Status: not-ready" in preflight_summary, "fresh preflight summary should reject the blank preflight")
    require("Actual Steam Deck hardware performance" in preflight_summary, "fresh preflight summary should list missing hardware evidence")
    visual_evidence = (ROOT / "artifacts" / "steam_deck_visual_evidence.md").read_text(encoding="utf-8")
    require("- Automated visual capture status: skipped" in visual_evidence, "fresh packet should record skipped visual capture status")
    require("No visual smoke images were captured" in visual_evidence, "fresh packet should explain missing visual captures")
    require("## Capture Review" in visual_evidence, "fresh packet should include visual evidence review section")
    readiness_summary = (ROOT / "artifacts" / "release_readiness_summary.md").read_text(encoding="utf-8")
    require("- Status: not-ready" in readiness_summary, "fresh release readiness summary should reject incomplete evidence")
    require("Steam Input handoff" in readiness_summary, "release readiness summary should include Steam Input gate")
    require("Steam Deck preflight" in readiness_summary, "release readiness summary should include Deck preflight gate")
    require("Package runtime validation" in readiness_summary, "release readiness summary should include package runtime gate")
    readiness_payload = json.loads((ROOT / "artifacts" / "release_readiness_summary.json").read_text(encoding="utf-8"))
    require(readiness_payload.get("status") == "not-ready", "fresh release readiness JSON should mark not-ready")
    require(readiness_payload.get("ready") is False, "fresh release readiness JSON should not be ready")
    require(len(readiness_payload.get("gates", [])) == 5, "release readiness JSON should contain five gates")
    manifest_payload = json.loads((ROOT / "artifacts" / "steam_deck_packet_manifest.json").read_text(encoding="utf-8"))
    artifact_paths = {artifact.get("path") for artifact in manifest_payload.get("artifacts", [])}
    require(manifest_payload.get("game") == GAME_TITLE, "packet manifest should include game title")
    require(manifest_payload.get("engine_package") == ENGINE_NAME, "packet manifest should include engine/package name")
    require(
        manifest_payload.get("options", {}).get("preflight_automated_gates") == "skipped",
        "default packet should label only preflight automation as skipped",
    )
    require(
        manifest_payload.get("options", {}).get("native_validation_suite") == "run",
        "packet manifest should record that the native suite ran",
    )
    require(manifest_payload.get("release_readiness", {}).get("status") == "not-ready", "packet manifest should carry readiness status")
    require(manifest_payload.get("release_readiness", {}).get("gate_count") == 5, "packet manifest should carry gate count")
    require("artifacts/steam_deck_packet_index.md" in artifact_paths, "packet manifest should include packet index")
    require("artifacts/release_readiness_summary.json" in artifact_paths, "packet manifest should include release readiness JSON")
    require("artifacts/package_validation_summary.md" in artifact_paths, "packet manifest should include package validation summary")
    require("artifacts/native_wgpu_runtime.md" in artifact_paths, "packet manifest should include native wgpu runtime report")
    require("artifacts/native_validation_suite.md" in artifact_paths, "packet manifest should include native validation suite report")
    require("artifacts/native_validation_suite.json" in artifact_paths, "packet manifest should include native validation suite JSON")
    require("artifacts/native_rust_quality.md" in artifact_paths, "packet manifest should include native Rust quality report")
    require("artifacts/native_rust_quality.json" in artifact_paths, "packet manifest should include native Rust quality JSON")
    require("artifacts/native_rust_tests.md" in artifact_paths, "packet manifest should include native Rust tests report")
    require("artifacts/native_rust_tests.json" in artifact_paths, "packet manifest should include native Rust tests JSON")
    require("artifacts/native_shader_parity.md" in artifact_paths, "packet manifest should include native shader parity report")
    require("artifacts/native_shader_parity.json" in artifact_paths, "packet manifest should include native shader parity JSON")
    require("artifacts/native_config_contract.md" in artifact_paths, "packet manifest should include native config contract report")
    require("artifacts/native_config_contract.json" in artifact_paths, "packet manifest should include native config contract JSON")
    require("artifacts/native_input_contract.md" in artifact_paths, "packet manifest should include native input contract report")
    require("artifacts/native_input_contract.json" in artifact_paths, "packet manifest should include native input contract JSON")
    require("artifacts/native_input_runtime.md" in artifact_paths, "packet manifest should include native input runtime report")
    require("artifacts/native_input_runtime.json" in artifact_paths, "packet manifest should include native input runtime JSON")
    require("artifacts/native_steam_input_alignment.md" in artifact_paths, "packet manifest should include native Steam Input alignment report")
    require("artifacts/native_steam_input_alignment.json" in artifact_paths, "packet manifest should include native Steam Input alignment JSON")
    require("artifacts/native_visual_metrics.md" in artifact_paths, "packet manifest should include native visual metrics report")
    require("artifacts/native_visual_metrics.json" in artifact_paths, "packet manifest should include native visual metrics JSON")
    require("artifacts/native_python_visual_parity.md" in artifact_paths, "packet manifest should include native-vs-Python visual parity report")
    require("artifacts/native_python_visual_parity.json" in artifact_paths, "packet manifest should include native-vs-Python visual parity JSON")
    require("artifacts/native_replay_determinism.md" in artifact_paths, "packet manifest should include native replay determinism report")
    require("artifacts/native_replay_determinism.json" in artifact_paths, "packet manifest should include native replay determinism JSON")
    require("artifacts/native_video_export_smoke.md" in artifact_paths, "packet manifest should include native video export report")
    require("artifacts/native_video_export_smoke.json" in artifact_paths, "packet manifest should include native video export JSON")
    require("artifacts/native-wgpu/native_video_export_smoke.mp4" in artifact_paths, "packet manifest should include native video MP4 evidence")
    require("artifacts/native-wgpu/native_video_export_smoke.ppm" in artifact_paths, "packet manifest should include native video poster evidence")
    require("artifacts/native-wgpu/native_video_export_smoke.metadata.json" in artifact_paths, "packet manifest should include native video metadata")
    require("artifacts/native_trial_matrix.md" in artifact_paths, "packet manifest should include native trial matrix report")
    require("artifacts/native_trial_matrix.json" in artifact_paths, "packet manifest should include native trial matrix JSON")
    require("artifacts/native_preset_matrix.md" in artifact_paths, "packet manifest should include native preset matrix report")
    require("artifacts/native_preset_matrix.json" in artifact_paths, "packet manifest should include native preset matrix JSON")
    require("artifacts/native_rule_sensitivity.md" in artifact_paths, "packet manifest should include native rule sensitivity report")
    require("artifacts/native_rule_sensitivity.json" in artifact_paths, "packet manifest should include native rule sensitivity JSON")
    require("artifacts/native_parameter_sensitivity.md" in artifact_paths, "packet manifest should include native parameter sensitivity report")
    require("artifacts/native_parameter_sensitivity.json" in artifact_paths, "packet manifest should include native parameter sensitivity JSON")
    require("artifacts/native_package_smoke.md" in artifact_paths, "packet manifest should include native package smoke report")
    require("artifacts/native_package_smoke.json" in artifact_paths, "packet manifest should include native package smoke JSON")
    require("artifacts/native_package_manifest.md" in artifact_paths, "packet manifest should include native package manifest report")
    require("artifacts/native_package_manifest.json" in artifact_paths, "packet manifest should include native package manifest JSON")
    require("artifacts/native_timing_budget.md" in artifact_paths, "packet manifest should include native timing budget report")
    require("artifacts/native_timing_budget.json" in artifact_paths, "packet manifest should include native timing budget JSON")
    require("artifacts/native_steam_launch_contract.md" in artifact_paths, "packet manifest should include native Steam launch contract report")
    require("artifacts/native_steam_launch_contract.json" in artifact_paths, "packet manifest should include native Steam launch contract JSON")
    require("artifacts/steam_deck_visual_evidence.md" in artifact_paths, "packet manifest should include visual evidence index")
    require("artifacts/steam_deck_packet_manifest.schema.json" in artifact_paths, "packet manifest should include its checked schema")
    native_video_snapshot = manifest_payload.get("native_video", {})
    require(native_video_snapshot.get("status") == "pass", "packet manifest should snapshot passing native video evidence")
    require(native_video_snapshot.get("evidence_scope") == "local-host-offscreen-export", "packet manifest should scope native video evidence to the local host")
    require(native_video_snapshot.get("steam_deck_hardware_verified") is False, "packet manifest must not relabel local video evidence as Deck hardware evidence")
    require(
        native_video_snapshot.get("width") == 3840
        and native_video_snapshot.get("height") == 2160
        and native_video_snapshot.get("fps") == 60,
        "packet manifest should snapshot 4K/60 video evidence",
    )
    for artifact in manifest_payload.get("artifacts", []):
        require(artifact.get("bytes", 0) > 0, f"manifest artifact should record byte size: {artifact}")
        require(len(artifact.get("sha256", "")) == 64, f"manifest artifact should record SHA-256: {artifact}")

    validator = subprocess.run(
        [python, "scripts/validate_steam_deck_packet_manifest.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(validator.returncode == 0, f"manifest validator failed: {validator.stdout}\n{validator.stderr}")
    require(
        "steam_deck_packet_manifest_status=valid" in validator.stdout,
        "manifest validator should report a valid packet",
    )


def expect_failure(python: str, args: list[str], expected_text: str) -> None:
    proc = subprocess.run(
        [python, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    require(proc.returncode != 0, f"expected command to fail: {' '.join(args)}")
    combined = proc.stdout + proc.stderr
    require(expected_text in combined, f"expected {expected_text!r} in failure output")


def main() -> int:
    python = sys.executable
    run_packet(python)
    expect_failure(
        python,
        ["scripts/steam_deck_preflight.py", "--with-fed-results", "--no-run"],
        "--with-fed-results requires --with-visual",
    )
    expect_failure(
        python,
        ["scripts/prepare_steam_deck_packet.py", "--with-visual"],
        "--with-visual and --with-fed-results require --run-automated",
    )
    print("steam_deck_packet_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
