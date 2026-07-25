# Building Fluoddity Deliverables

This repository has three maintained deliverables: the Python/OpenGL
PyInstaller prototype, the Rust/wgpu native shipping candidate, and the
self-contained WebGPU HTML artifact for networked.art/everything. They are
separate surfaces with separate validation boundaries.

## Prerequisites

**IMPORTANT:** PyInstaller must run in the same Python environment where dependencies are installed!

### FFmpeg (Required for Video Recording)

Fluoddity uses FFmpeg for video recording. If you want video recording to work in the built application:

1. **Download FFmpeg:**
   - Windows: Download from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) or [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
   - Extract `ffmpeg.exe` from the archive

2. **Add FFmpeg to PATH:**
   - Copy `ffmpeg.exe` to a folder in your PATH, or
   - Add FFmpeg's `bin` folder to your system PATH environment variable

3. **Verify installation:**
   ```powershell
   ffmpeg -version
   ```

For the Python/PyInstaller build, FFmpeg on `PATH` is bundled when the build
script can resolve it. Otherwise, users need a working FFmpeg installation for
the legacy recorder.

The Rust/wgpu native package has a stricter publication contract: it requires
FFmpeg with the `libx264` encoder, bundles the executable beside the native
runtime, and includes the selected distribution's license and generated
provenance under `third_party/ffmpeg/`. See the native package steps below.

### Option 1: Use Virtual Environment (Recommended)

If you have a virtual environment (like `Scratch.venv`):

```powershell
# PowerShell - Activate virtual environment
.\Scratch.venv\Scripts\Activate.ps1

# Verify you're in the venv
python -c "import imgui_bundle, moderngl, glfw; print('Using venv - all imports OK!')"

# Install PyInstaller in the venv
pip install pyinstaller
```

### Option 2: Use System Python

If not using a venv, install to system Python:

```bash
pip install -r requirements.txt
pip install pyinstaller
python -c "import imgui_bundle, moderngl, glfw; print('All imports OK!')"
```

## Building

### Quick Build (Recommended)

Simply run the build script:

```powershell
.\build.ps1
```

This script will:
1. Activate the virtual environment
2. Run PyInstaller with proper settings
3. Move the shaders folder to the correct location
4. Copy default config files
5. Copy the bundled Core and Advanced physics configs

### Manual Build

If you prefer to build manually:

```powershell
# Activate virtual environment
.\Scratch.venv\Scripts\Activate.ps1

# Run PyInstaller
python -m PyInstaller --clean --noconfirm Fluoddity.spec

# Move shaders folder
Move-Item -Path "dist\Fluoddity\_internal\shaders" -Destination "dist\Fluoddity\shaders"
```

**Note:** The build uses `launcher_debug.py` which will keep the console window open if there's a crash, making it easier to debug startup issues.

This will create a `dist/Fluoddity` folder containing:
- `Fluoddity.exe` (or `Fluoddity` on Unix-like systems) - The main executable
- All required DLLs and dependencies
- `shaders/` directory with all GLSL shader files
- Python runtime and libraries

The Linux/Steam Deck build adds the source `steam_input/` directory and a
generated handoff report; the current Windows `build.ps1` does not.

### Native Rust/wgpu Package

Build the self-contained Windows native candidate from the repo root:

```powershell
.\runtime\rust-wgpu-spike\scripts\package-windows.ps1
```

The script requires an FFmpeg distribution on `PATH` that exposes `libx264`
and has a discoverable license file in its bundle root. It writes
`dist/FluoddityNative/` with the native executables, all shipped Core configs,
`ffmpeg.exe`, license/provenance material, and package-local launch, validation,
and video wrappers.

Export the preferred offline 4K/60 master from that package with:

```powershell
.\dist\FluoddityNative\run_export_video.ps1 -Seconds 10
```

The wrapper writes H.264 `yuv420p` MP4 with BT.709 metadata and faststart
layout, plus a JSON export report beside the video. The offline exporter
advances a fixed 60 Hz simulation timeline independently of render/encode
speed. It does not create a PPM poster unless a source-level export explicitly
adds `--out path/to/poster.ppm`.

`run_record_video.ps1` captures one frame per presented native-window redraw at
60 FPS and advances recorded trial time on the same frame clock. It is
frame-sequence capture, not wall-clock-real-time screen recording when GPU
readback or FFmpeg runs below the requested rate. Use `run_export_video.ps1` for
publishable masters.

Build the equivalent native Linux/Deck package only with an explicitly selected
redistributable static FFmpeg executable and its license:

```bash
FLUODDITY_FFMPEG_BUNDLE=/absolute/path/to/ffmpeg \
FLUODDITY_FFMPEG_LICENSE=/absolute/path/to/LICENSE \
bash runtime/rust-wgpu-spike/scripts/package-deck.sh
```

The Deck package rejects dynamically linked FFmpeg builds and builds without
`libx264`. After packaging, use `run_export_video.sh` for offline masters and
`run_record_video.sh` for presented window-frame capture.

Windows package/export validation does not prove the Deck build. A release
claim for Deck requires building and running the package on Linux/actual Steam
Deck hardware, confirming the Vulkan adapter, probing/decoding the package-local
MP4, and recording device, OS, storage, thermals, and runtime observations.

### Python Linux / Steam Deck Build

Build on Linux or Steam Deck Desktop Mode:

```bash
bash scripts/build_linux.sh
```

The script creates `dist/Fluoddity/run_steam_deck.sh`, which is the intended Steam launch target for Deck testing. It sets `FLUODDITY_STEAM_DECK=1` and runs Fluoddity with `--steam-deck --game`, so the packaged Deck target opens the Trial Dish player shell by default. It also copies `steam_input/` into the distribution so the intended Steam Input action surface, prompt glyph map, and placeholder glyph assets stay beside the Deck build artifacts.

For source validation without packaging:

```bash
python main.py --steam-deck --game
```

The Steam Deck profile launches at `1280x800` fullscreen, increases UI scale, and applies conservative performance defaults. Track release-readiness in [`docs/steam_deck_verified.md`](docs/steam_deck_verified.md).

### Clone on Steam Deck

```bash
git clone https://github.com/EverythingSings/Fluoddity.git
cd Fluoddity
bash scripts/build_linux.sh
./dist/Fluoddity/run_steam_deck.sh
```

### WebGPU networked.art/everything Artifact

Build the self-contained browser artifact from the repository root:

```bash
python scripts/build_webgpu_artifact.py
```

The builder embeds the configured physics data and WGSL sources into
`artifacts/networked-art/everything.html`; the generated file has no runtime
network or persistence dependency. Validate its static package contract,
source-contract coverage, and real compact-viewport behavior with:

```bash
python scripts/smoke_webgpu_artifact.py --require-thumbnail
python scripts/audit_webgpu_artifact_parity.py --require-complete
python scripts/smoke_webgpu_responsive.py --skip-build
```

The responsive smoke uses Chrome or Edge (pass `--browser` or set
`FLUODDITY_BROWSER` when auto-discovery is insufficient). At compact
networked.art embed sizes, the controls must remain scrollable, visible, and
functional at normal browser zoom. Do not publish an artifact that requires
zooming out to expose sliders.

This browser artifact is a bounded generative-art runtime, not a claim of full
Python editor, Trial Dish, or native shader parity.

## Distribution

The entire Python `dist/Fluoddity` folder can be distributed as-is. Users can:
1. Copy the folder to their desired location
2. Run `Fluoddity.exe` directly

The native candidate is a separate `dist/FluoddityNative` package and must be
built on the target platform. Its bundled FFmpeg executable, license, and
provenance files are part of the distributable and must remain together.

The WebGPU deliverable is the generated
`artifacts/networked-art/everything.html` plus its upload thumbnail. It is not
part of either desktop package.

The application will create the following in its working directory:
- `preferences.config` - User preferences (UI settings, parameter sweeps, etc.)
- `physics_configs/` - Saved physics configurations (created when user saves configs)

## Notes

- The build is platform-specific (Windows .exe on Windows, etc.)
- The Python package is typically 50-100 MB; the native package can be
  substantially larger depending on the selected redistributable FFmpeg build
- First run may be slightly slower as Windows/antivirus scans the executable
- The console window can be hidden by changing `console=True` to `console=False` in `Fluoddity.spec`

## Troubleshooting

### Missing DLLs
If the built application fails to start due to missing DLLs, check the PyInstaller output for warnings and add any missing modules to the `hiddenimports` list in `Fluoddity.spec`.

### Shader Loading Issues
If shaders fail to load, verify that the `shaders/` directory is present in the `dist/Fluoddity` folder with all `.vert`, `.frag`, and `.glsl` files.

### ModernGL/OpenGL Issues
ModernGL requires OpenGL support. The user's system must have:
- OpenGL 3.3 or higher
- Up-to-date graphics drivers

### Video Recording Issues
If video recording fails with "FFmpeg not found":
1. **If building:** Install FFmpeg, add it to PATH, and rebuild
2. **If distributing:** Either bundle FFmpeg with the build (see above), or instruct users to:
   - Download FFmpeg from [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
   - Place `ffmpeg.exe` in the same folder as `Fluoddity.exe`, or
   - Install FFmpeg and add it to their system PATH

The application will show a helpful error message if FFmpeg is not found.

For the native runtime, pass an explicit executable with `--ffmpeg`, set
`FLUODDITY_FFMPEG`, or keep the packaged `ffmpeg.exe` / `ffmpeg` beside the
native executable. Confirm the selected binary exposes `libx264`:

```bash
ffmpeg -hide_banner -encoders
```

If a native export stops early, do not publish a `.partial.mp4`; a successful
run transactionally publishes the completed MP4, optional poster, and
`fluoddity.native_video_export.v1` JSON report with backup-and-restore
protection for existing regular-file artifacts.

## Clean Build

To clean previous build artifacts:

```bash
# Remove build artifacts
rm -rf build/ dist/

# Clean PyInstaller cache (if needed)
pyinstaller --clean Fluoddity.spec
```
