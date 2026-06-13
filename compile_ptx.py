"""Pre-compile OptiX PTX for distribution builds.

Usage:
    python compile_ptx.py

Compiles the OptiX CUDA source (from optix_renderer/cuda_src.py) to PTX
via NVRTC and writes it to optix_renderer/spheres.ptx. The renderer loads
this file at startup to skip runtime compilation.

Called by build.ps1 before PyInstaller. Exits with code 1 on failure.
"""

import sys
import os

def main():
    try:
        from optix_renderer.cuda_src import SPHERE_CUDA_SRC
        from optix_renderer.interop import compile_ptx
    except ImportError as e:
        print(f"PTX compilation skipped: {e}")
        sys.exit(1)

    try:
        print("Compiling OptiX PTX via NVRTC...")
        ptx = compile_ptx(SPHERE_CUDA_SRC)

        out_path = os.path.join(
            os.path.dirname(__file__), "optix_renderer", "spheres.ptx"
        )
        with open(out_path, "wb") as f:
            f.write(ptx)

        print(f"PTX written to {out_path} ({len(ptx)} bytes)")
    except Exception as e:
        print(f"PTX compilation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
