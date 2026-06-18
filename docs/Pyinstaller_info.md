# Specification: Portable PyInstaller Bundle with CUDA & OptiX Support

## 1. Objective
Create a standalone, portable application folder using PyInstaller (`--onedir` mode) that includes all core requirements (`ModernGL`, `GLFW`, `ImGui Bundle`) alongside the necessary NVIDIA CUDA and OptiX runtime binaries. 

The goal is zero-footprint deployment on a borrowed PC. When the folder is deleted, no trace of the SDKs should remain on the host system.

---

## 2. System Assumptions & Prerequisites
* **Host PC Requirement:** The borrowed PC must have an NVIDIA RTX GPU and up-to-date NVIDIA display drivers installed.
* **Architecture:** Target and development OS must match (e.g., Windows 10/11 64-bit to Windows 10/11 64-bit).
* **Mode:** Strict `--onedir` bundle directory (do not use `--onefile` to avoid multi-gigabyte unpack delays in `TEMP`).

---

## 3. Step 1: Code Modifications (Entry Point Initialization)
The AI agent must place this exact logic at the absolute top of the main entry point file (before importing `cupy`, `cuda`, `pyoptix`, `moderngl`, or `glfw`). 

This forces the runtime environment to prioritize DLLs bundled inside the application folder rather than searching system environment paths.

```python
import os
import sys

def initialize_portable_environment():
    """Forces Python and the OS to look into the PyInstaller directory for CUDA/OptiX binaries."""
    if getattr(sys, 'frozen', False):
        # Path to the root of the extracted PyInstaller bundle folder
        bundle_dir = sys._MEIPASS
        
        # 1. Update system path environment variable
        os.environ["PATH"] = bundle_dir + os.pathsep + os.environ.get("PATH", "")
        
        # 2. Force Windows to resolve DLL dependencies from the bundle folder
        if sys.platform == 'win32':
            try:
                os.add_dll_directory(bundle_dir)
            except AttributeError:
                # Fallback for very old Python configurations if applicable
                pass
                
        print(f"[PORTABLE INIT] Runtime path isolated to: {bundle_dir}")

# Execute immediately upon module loading
initialize_portable_environment()
```

---

## 4. Step 2: Binary Dependency Extraction
Before building, the agent or developer must harvest the required NVIDIA runtime binaries from the development machine and place them into a staging directory: `./nvidia_libs/`.

### Windows DLL Harvest Checklist
Copy the following `.dll` binaries from your CUDA Toolkit install path (typically `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\vX.X\bin`) into `./nvidia_libs/`:
* `cudart64_*.dll` (CUDA Runtime)
* `cublas64_*.dll` & `cublasLt64_*.dll` (BLAS)
* `cufft64_*.dll` (FFT)
* `curand64_*.dll` (Random number generation)
* `cusolver64_*.dll` & `cusolverMg64_*.dll` (Solvers)
* `cusparse64_*.dll` (Sparse matrices)
* `nvrtc64_*.dll` (Runtime Compilation - critical for CuPy)

### OptiX Dynamic Libraries
* Locate and copy `nvoptix.dll` (usually found inside the NVIDIA Driver/System32 directory or OptiX SDK installation) into `./nvidia_libs/`.

---

## 5. Step 3: PyInstaller Specification Configuration
The application must be compiled using a custom `.spec` file to handle deep graphical imports (`glcontext`) and map the collected binaries.

The agent should generate or modify the project's `.spec` file to structure the `Analysis` container exactly as follows:

```python
# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None
project_root = os.path.abspath(os.getcwd())
nvidia_libs_dir = os.path.join(project_root, 'nvidia_libs')

# Build list of tuples dynamically for all harvested NVIDIA binaries
nvidia_binaries = []
if os.path.exists(nvidia_libs_dir):
    for f in os.listdir(nvidia_libs_dir):
        if f.endswith('.dll') or f.endswith('.so'):
            nvidia_binaries.append((os.path.join(nvidia_libs_dir, f), '.'))

a = Analysis(
    ['main.py'],  # Replace with actual entry point filename
    pathex=[project_root],
    binaries=nvidia_binaries,
    datas=[],
    hiddenimports=[
        'glcontext',
        'moderngl',
        'cupy',
        'cuda',
        'pyoptix',
        'imgui_bundle',
        'scipy.special.cython_special'  # Often needed for scipy subpackages
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='StandaloneApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Keep UPX disabled to prevent compression corruption on large CUDA binaries
    console=True, # Leave True during testing to catch missing DLL errors on stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='StandaloneAppFolder',
)
```

---

## 6. Execution Instructions for Agent
1. Verify all required `.dll` files are successfully copied into `./nvidia_libs/`.
2. Apply the initialization patch to the application entry script.
3. Save the specification above as `app_build.spec`.
4. Run the compilation pipeline using the terminal payload:
   ```bash
   pyinstaller app_build.spec
   ```
5. Deliver the resultant directory located in `./dist/StandaloneAppFolder/`.
