#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
TRIAL_PATH="${TRIAL_PATH:-artifacts/trial_definitions.json}"
TRIAL_ID="${TRIAL_ID:-rival_bloom}"
CONFIG_PATH="${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
ARTIFACTS_DIR="${ARTIFACTS_DIR:-artifacts/native-wgpu}"
MAX_WINDOW_FRAMES="${MAX_WINDOW_FRAMES:-3600}"

cd "$REPO_ROOT"

if [[ ! -f "$TRIAL_PATH" ]]; then
    echo "missing $TRIAL_PATH; run python scripts/export_trial_definitions.py before copying to Deck" >&2
    exit 1
fi

mkdir -p "$ARTIFACTS_DIR"
cargo build --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release

window_output="$(runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike \
    --trial "$TRIAL_PATH" \
    --trial-id "$TRIAL_ID" \
    --config "$CONFIG_PATH" \
    --deck-profile \
    --max-window-frames "$MAX_WINDOW_FRAMES" \
    --timing-report "$ARTIFACTS_DIR/wgpu_deck_timing.json")"
echo "$window_output"
if ! grep -q "wgpu_window_timing" <<<"$window_output"; then
    echo "native Deck smoke did not report window timing" >&2
    exit 1
fi
if ! grep -q "trial_runtime_state status=1" <<<"$window_output"; then
    echo "native Deck smoke did not report running trial state" >&2
    exit 1
fi
if ! grep -q "hazard_rate=0.0000 boundary_conditions=2 initial_conditions=0 num_cohorts=64 disable_symmetry=false absolute_orientation=0 orientation_mix=1.000 hue_sensitivity=0.073 color_by_cohort=false parameter_sweeps_enabled=false" <<<"$window_output"; then
    echo "native Deck smoke did not load saved boundary/reset/cohort/orientation/appearance settings" >&2
    exit 1
fi

echo "native_wgpu_deck_smoke=ok"
echo "native_wgpu_timing=$ARTIFACTS_DIR/wgpu_deck_timing.json"
