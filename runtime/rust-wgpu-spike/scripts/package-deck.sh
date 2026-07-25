#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PYTHON="${PYTHON:-python}"
OUTPUT_DIR="${OUTPUT_DIR:-dist/FluoddityNative}"
TRIAL_ID="${TRIAL_ID:-rival_bloom}"
CONFIG_PATH="${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
FFMPEG_BUNDLE="${FLUODDITY_FFMPEG_BUNDLE:-}"
FFMPEG_LICENSE="${FLUODDITY_FFMPEG_LICENSE:-}"

cd "$REPO_ROOT"
DIST_ROOT="$(realpath -m "$REPO_ROOT/dist")"
if [[ "$OUTPUT_DIR" = /* ]]; then
    PACKAGE_ROOT="$(realpath -m "$OUTPUT_DIR")"
else
    PACKAGE_ROOT="$(realpath -m "$REPO_ROOT/$OUTPUT_DIR")"
fi
case "$PACKAGE_ROOT" in
    "$DIST_ROOT"/*) ;;
    *)
        echo "OUTPUT_DIR must resolve to a child of $DIST_ROOT; got $PACKAGE_ROOT" >&2
        exit 2
        ;;
esac
if [[ -z "$FFMPEG_BUNDLE" || ! -x "$FFMPEG_BUNDLE" ]]; then
    echo "Set FLUODDITY_FFMPEG_BUNDLE to an executable redistributable static FFmpeg build." >&2
    exit 2
fi
if [[ -z "$FFMPEG_LICENSE" || ! -s "$FFMPEG_LICENSE" ]]; then
    echo "Set FLUODDITY_FFMPEG_LICENSE to the license file shipped with that FFmpeg build." >&2
    exit 2
fi
if ! file "$FFMPEG_BUNDLE" | grep -Eqi "statically linked|static-pie linked"; then
    echo "FLUODDITY_FFMPEG_BUNDLE must be statically linked; a copied system launcher is not self-contained." >&2
    exit 2
fi
if ! "$FFMPEG_BUNDLE" -hide_banner -encoders 2>/dev/null | grep -q "libx264"; then
    echo "The supplied FFmpeg bundle does not expose the required libx264 encoder." >&2
    exit 2
fi
"$PYTHON" scripts/export_trial_definitions.py --output artifacts/trial_definitions.json
cargo build --manifest-path runtime/rust-wgpu-spike/Cargo.toml --release

rm -rf "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT/artifacts" "$PACKAGE_ROOT/physics_configs/Core" "$PACKAGE_ROOT/steam_input/glyphs" "$PACKAGE_ROOT/third_party/ffmpeg"
cp runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike "$PACKAGE_ROOT/XenocultureTrialDish"
cp runtime/rust-wgpu-spike/target/release/fluoddity-wgpu-spike "$PACKAGE_ROOT/fluoddity-wgpu-spike"
cp artifacts/trial_definitions.json "$PACKAGE_ROOT/artifacts/trial_definitions.json"
cp physics_configs/Core/*.json "$PACKAGE_ROOT/physics_configs/Core/"
cp "$FFMPEG_BUNDLE" "$PACKAGE_ROOT/ffmpeg"
cp "$FFMPEG_LICENSE" "$PACKAGE_ROOT/third_party/ffmpeg/LICENSE"
{
    echo "Component: FFmpeg"
    echo "Packaged executable: ffmpeg"
    echo "Source executable: $FFMPEG_BUNDLE"
    echo "Version: $("$FFMPEG_BUNDLE" -version | head -n 1)"
    echo "Required encoder: libx264"
    echo "License file: third_party/ffmpeg/LICENSE"
    echo "Packaged by: runtime/rust-wgpu-spike/scripts/package-deck.sh"
} > "$PACKAGE_ROOT/third_party/ffmpeg/PROVENANCE.txt"
cp runtime/rust-wgpu-spike/README.md "$PACKAGE_ROOT/README.md"
cp runtime/rust-wgpu-spike/scripts/smoke-deck.sh "$PACKAGE_ROOT/smoke-deck.source.sh"
cp steam_input/README.md "$PACKAGE_ROOT/steam_input/README.md"
cp steam_input/steam_input_manifest.vdf "$PACKAGE_ROOT/steam_input/steam_input_manifest.vdf"
cp steam_input/trial_prompt_glyph_map.json "$PACKAGE_ROOT/steam_input/trial_prompt_glyph_map.json"
cp steam_input/glyphs/* "$PACKAGE_ROOT/steam_input/glyphs/"
"$PYTHON" scripts/write_steam_input_handoff.py --output "$PACKAGE_ROOT/steam_input/steam_input_handoff.md"

cat > "$PACKAGE_ROOT/run_steam_deck.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\$0")"
TRIAL_ID="\${TRIAL_ID:-$TRIAL_ID}"
exec ./XenocultureTrialDish --trial artifacts/trial_definitions.json --trial-id "\$TRIAL_ID" --config physics_configs/Core/Bubbles.json --window
EOF

cat > "$PACKAGE_ROOT/run_deck_profile.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\$0")"
MAX_WINDOW_FRAMES="\${MAX_WINDOW_FRAMES:-3600}"
TRIAL_ID="\${TRIAL_ID:-$TRIAL_ID}"
exec ./fluoddity-wgpu-spike --trial artifacts/trial_definitions.json --trial-id "\$TRIAL_ID" --config physics_configs/Core/Bubbles.json --deck-profile --max-window-frames "\$MAX_WINDOW_FRAMES" --timing-report artifacts/wgpu_deck_timing.json
EOF

cat > "$PACKAGE_ROOT/run_input_contract.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec ./fluoddity-wgpu-spike --dump-input-contract artifacts/native_input_contract.json
EOF

cat > "$PACKAGE_ROOT/run_input_runtime.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\$0")"
TRIAL_ID="\${TRIAL_ID:-$TRIAL_ID}"
exec ./fluoddity-wgpu-spike --trial artifacts/trial_definitions.json --trial-id "\$TRIAL_ID" --config physics_configs/Core/Bubbles.json --dump-input-smoke artifacts/native_input_runtime.json
EOF

cat > "$PACKAGE_ROOT/run_export_video.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PACKAGE_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
CALLER_DIR="\$PWD"
TRIAL_ID="\${TRIAL_ID:-$TRIAL_ID}"
CONFIG_PATH="\${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
VIDEO_SECONDS="\${VIDEO_SECONDS:-10}"
WIDTH="\${WIDTH:-3840}"
HEIGHT="\${HEIGHT:-2160}"
FPS="\${FPS:-60}"
CRF="\${CRF:-15}"
PRESET="\${PRESET:-slow}"

if [[ "\$CONFIG_PATH" != /* ]]; then
    CONFIG_PATH="\$PACKAGE_DIR/\$CONFIG_PATH"
fi
if [[ -z "\${OUTPUT_PATH:-}" ]]; then
    if [[ -z "\${XDG_VIDEOS_DIR:-}" && -z "\${HOME:-}" ]]; then
        echo "Set OUTPUT_PATH, XDG_VIDEOS_DIR, or HOME before exporting video." >&2
        exit 2
    fi
    VIDEO_DIR="\${XDG_VIDEOS_DIR:-\$HOME/Videos}/Fluoddity"
    OUTPUT_PATH="\$VIDEO_DIR/Xenoculture-\$TRIAL_ID-\$(date +%Y-%m-%d_%H-%M-%S).mp4"
elif [[ "\$OUTPUT_PATH" != /* ]]; then
    OUTPUT_PATH="\$CALLER_DIR/\$OUTPUT_PATH"
fi
OUTPUT_PATH="\$(realpath -m "\$OUTPUT_PATH")"
if [[ -z "\${REPORT_PATH:-}" ]]; then
    REPORT_PATH="\${OUTPUT_PATH%.*}.json"
elif [[ "\$REPORT_PATH" != /* ]]; then
    REPORT_PATH="\$CALLER_DIR/\$REPORT_PATH"
fi
REPORT_PATH="\$(realpath -m "\$REPORT_PATH")"
mkdir -p "\$(dirname "\$OUTPUT_PATH")" "\$(dirname "\$REPORT_PATH")"

FRAME_ARGS=(--video-seconds "\$VIDEO_SECONDS")
if [[ -n "\${FRAMES:-}" ]]; then
    FRAME_ARGS=(--frames "\$FRAMES")
fi

"\$PACKAGE_DIR/XenocultureTrialDish" \
    --trial "\$PACKAGE_DIR/artifacts/trial_definitions.json" \
    --trial-id "\$TRIAL_ID" \
    --config "\$CONFIG_PATH" \
    "\${FRAME_ARGS[@]}" \
    --video-out "\$OUTPUT_PATH" \
    --video-report "\$REPORT_PATH" \
    --render-width "\$WIDTH" \
    --render-height "\$HEIGHT" \
    --video-fps "\$FPS" \
    --video-crf "\$CRF" \
    --video-preset "\$PRESET" \
    --ffmpeg "\$PACKAGE_DIR/ffmpeg"
echo "native_video_export=\$OUTPUT_PATH"
echo "native_video_report=\$REPORT_PATH"
EOF

cat > "$PACKAGE_ROOT/run_record_video.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PACKAGE_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
CALLER_DIR="\$PWD"
TRIAL_ID="\${TRIAL_ID:-$TRIAL_ID}"
CONFIG_PATH="\${CONFIG_PATH:-physics_configs/Core/Bubbles.json}"
WIDTH="\${WIDTH:-3840}"
HEIGHT="\${HEIGHT:-2160}"
FPS="\${FPS:-60}"
CRF="\${CRF:-15}"
PRESET="\${PRESET:-fast}"
if [[ "\$FPS" != "60" ]]; then
    echo "run_record_video.sh supports only 60 FPS window frame capture. Use run_export_video.sh for other frame rates." >&2
    exit 2
fi

if [[ "\$CONFIG_PATH" != /* ]]; then
    CONFIG_PATH="\$PACKAGE_DIR/\$CONFIG_PATH"
fi
if [[ -z "\${OUTPUT_PATH:-}" ]]; then
    if [[ -z "\${XDG_VIDEOS_DIR:-}" && -z "\${HOME:-}" ]]; then
        echo "Set OUTPUT_PATH, XDG_VIDEOS_DIR, or HOME before recording frames." >&2
        exit 2
    fi
    VIDEO_DIR="\${XDG_VIDEOS_DIR:-\$HOME/Videos}/Fluoddity"
    OUTPUT_PATH="\$VIDEO_DIR/Xenoculture-frame-capture-\$TRIAL_ID-\$(date +%Y-%m-%d_%H-%M-%S).mp4"
elif [[ "\$OUTPUT_PATH" != /* ]]; then
    OUTPUT_PATH="\$CALLER_DIR/\$OUTPUT_PATH"
fi
OUTPUT_PATH="\$(realpath -m "\$OUTPUT_PATH")"
if [[ -z "\${REPORT_PATH:-}" ]]; then
    REPORT_PATH="\${OUTPUT_PATH%.*}.json"
elif [[ "\$REPORT_PATH" != /* ]]; then
    REPORT_PATH="\$CALLER_DIR/\$REPORT_PATH"
fi
REPORT_PATH="\$(realpath -m "\$REPORT_PATH")"
mkdir -p "\$(dirname "\$OUTPUT_PATH")" "\$(dirname "\$REPORT_PATH")"

BOUND_ARGS=()
if [[ -n "\${FRAMES:-}" ]]; then
    BOUND_ARGS=(--frames "\$FRAMES")
elif [[ -n "\${VIDEO_SECONDS:-}" ]]; then
    BOUND_ARGS=(--video-seconds "\$VIDEO_SECONDS")
fi

"\$PACKAGE_DIR/XenocultureTrialDish" \
    --trial "\$PACKAGE_DIR/artifacts/trial_definitions.json" \
    --trial-id "\$TRIAL_ID" \
    --config "\$CONFIG_PATH" \
    --window \
    "\${BOUND_ARGS[@]}" \
    --video-out "\$OUTPUT_PATH" \
    --video-report "\$REPORT_PATH" \
    --render-width "\$WIDTH" \
    --render-height "\$HEIGHT" \
    --video-fps "\$FPS" \
    --video-crf "\$CRF" \
    --video-preset "\$PRESET" \
    --ffmpeg "\$PACKAGE_DIR/ffmpeg"
echo "native_window_frame_capture=\$OUTPUT_PATH"
echo "native_video_report=\$REPORT_PATH"
EOF

chmod +x \
    "$PACKAGE_ROOT/XenocultureTrialDish" \
    "$PACKAGE_ROOT/fluoddity-wgpu-spike" \
    "$PACKAGE_ROOT/ffmpeg" \
    "$PACKAGE_ROOT/run_steam_deck.sh" \
    "$PACKAGE_ROOT/run_deck_profile.sh" \
    "$PACKAGE_ROOT/run_input_contract.sh" \
    "$PACKAGE_ROOT/run_input_runtime.sh" \
    "$PACKAGE_ROOT/run_export_video.sh" \
    "$PACKAGE_ROOT/run_record_video.sh"

cat > "$PACKAGE_ROOT/PACKAGE_README.md" <<'EOF'
# Fluoddity Native Runtime Package

This is the Rust/wgpu native runtime candidate package.

Steam-facing executable: `XenocultureTrialDish`

Steam Input handoff files are bundled under `steam_input/`.

Run the player-facing native Steam/Deck launch:

```bash
bash run_steam_deck.sh
```

Run the Deck/Linux timing pass:

```bash
bash run_deck_profile.sh
```

Dump native input mapping/runtime reports:

```bash
bash run_input_contract.sh
bash run_input_runtime.sh
```

Export a deterministic silent 4K/60 H.264 MP4 master:

```bash
bash run_export_video.sh
```

The export wrapper uses the package-local static `ffmpeg`, advances the simulation
on a fixed 60 Hz timeline, and writes a JSON report beside the MP4. Set
`OUTPUT_PATH`, `VIDEO_SECONDS` or `FRAMES`, `WIDTH`, `HEIGHT`, `FPS`, `CRF`, and
`PRESET` to override its defaults. A relative `OUTPUT_PATH` is resolved against
the directory from which you launched the wrapper, including paths with spaces.

Capture presented native window frames until the window closes:

```bash
bash run_record_video.sh
```

`run_record_video.sh` is 60 FPS frame-sequence capture, not wall-clock screen
recording. It advances one 60 Hz trial-time step per redraw. If rendering or
encoding cannot sustain 60 FPS, playback duration is based on captured frame
count. Set `FRAMES` or `VIDEO_SECONDS` for a bounded validation capture. Use
`run_export_video.sh` for deterministic masters or other output frame rates.

The bundled encoder is `ffmpeg`; its license and provenance are recorded under
`third_party/ffmpeg/`. The Deck package requires a redistributable static FFmpeg
build with `libx264`; it never falls back to a host FFmpeg installation.

The default timing report is `artifacts/wgpu_deck_timing.json`.
EOF

echo "native_wgpu_package=ok"
echo "native_wgpu_package_dir=$PACKAGE_ROOT"
echo "native_wgpu_package_ffmpeg=$PACKAGE_ROOT/ffmpeg"
