# Building Fluoddity Distribution

This document explains how to build a distributable version of Fluoddity using PyInstaller.

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

If FFmpeg is in your PATH when you build, it will be automatically bundled with the application. Otherwise, users will need to install FFmpeg separately to use video recording.

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

## Distribution

The entire `dist/Fluoddity` folder can be distributed as-is. Users can:
1. Copy the folder to their desired location
2. Run `Fluoddity.exe` directly

The application will create the following in its working directory:
- `preferences.config` - User preferences (UI settings, parameter sweeps, etc.)
- `physics_configs/` - Saved physics configurations (created when user saves configs)

## Notes

- The build is platform-specific (Windows .exe on Windows, etc.)
- Total folder size will be approximately 50-100 MB depending on dependencies
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

## Clean Build

To clean previous build artifacts:

```bash
# Remove build artifacts
rm -rf build/ dist/

# Clean PyInstaller cache (if needed)
pyinstaller --clean Fluoddity.spec
```
