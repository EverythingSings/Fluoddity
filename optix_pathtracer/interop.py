"""GL-CUDA interop helpers for OptiX sphere rendering.

Wraps cudaGraphicsGLRegisterBuffer / Map / Unmap with error checking.
Adapted from demos/optix_demo.py.
"""

import os
import sys
import glob
import ctypes

import numpy as np

from cuda.bindings import runtime as cudart
from cuda.bindings import nvrtc


# ---------------------------------------------------------------------------
# CUDA error checking
# ---------------------------------------------------------------------------

def check_cuda(result):
    """Check a cuda.bindings.runtime call and raise on error."""
    err = result[0]
    if err != cudart.cudaError_t.cudaSuccess:
        raise RuntimeError(f"CUDA error: {err}")
    if len(result) == 2:
        return result[1]
    if len(result) > 2:
        return result[1:]
    return None


def check_nvrtc(result, prog=None):
    """Check an nvrtc call and raise on error (with optional compiler log)."""
    if result[0].value:
        msg = nvrtc.nvrtcGetErrorString(result[0])[1]
        if prog is not None:
            _, logsize = nvrtc.nvrtcGetProgramLogSize(prog)
            log = b" " * logsize
            nvrtc.nvrtcGetProgramLog(prog, log)
            msg = f"{msg}\n{log.decode()}"
        raise RuntimeError(f"NVRTC error: {msg}")
    if len(result) == 2:
        return result[1]
    if len(result) > 2:
        return result[1:]
    return None


# ---------------------------------------------------------------------------
# GL buffer registration / mapping
# ---------------------------------------------------------------------------

def register_gl_buffer(gl_buffer, flags):
    """Register a ModernGL buffer with CUDA for interop.

    Args:
        gl_buffer: moderngl.Buffer instance
        flags: cudaGraphicsRegisterFlags value

    Returns:
        CUDA graphics resource handle.
    """
    return check_cuda(
        cudart.cudaGraphicsGLRegisterBuffer(int(gl_buffer.glo), flags)
    )


def map_resource(resource):
    """Map a registered CUDA graphics resource and return (device_ptr, size)."""
    check_cuda(cudart.cudaGraphicsMapResources(1, resource, 0))
    ptr, size = check_cuda(cudart.cudaGraphicsResourceGetMappedPointer(resource))
    return int(ptr), int(size)


def unmap_resource(resource):
    """Unmap a previously mapped CUDA graphics resource."""
    check_cuda(cudart.cudaGraphicsUnmapResources(1, resource, 0))


def unregister_resource(resource):
    """Unregister a CUDA graphics resource."""
    check_cuda(cudart.cudaGraphicsUnregisterResource(resource))


# ---------------------------------------------------------------------------
# SDK path helpers
# ---------------------------------------------------------------------------

def find_optix_include():
    """Locate the OptiX SDK include directory for NVRTC compilation."""
    p = os.environ.get("OPTIX_PATH")
    if p:
        inc = os.path.join(p, "include")
        return inc if os.path.isdir(inc) else p
    if sys.platform == "win32":
        hits = sorted(glob.glob(
            r"C:\ProgramData\NVIDIA Corporation\OptiX SDK 9*\include"))
        if hits:
            return hits[-1]
    for p in ("/opt/optix/include", "/usr/local/optix/include"):
        if os.path.isdir(p):
            return p
    raise RuntimeError(
        "OptiX headers not found. Set OPTIX_PATH to the SDK root."
    )


def find_cuda_include():
    """Locate the CUDA toolkit include directory for NVRTC compilation."""
    p = (os.environ.get("CUDA_PATH")
         or os.environ.get("CUDA_HOME")
         or "/usr/local/cuda")
    return os.path.join(p, "include")


# ---------------------------------------------------------------------------
# PTX compilation
# ---------------------------------------------------------------------------

def compile_ptx(cuda_source: str) -> bytes:
    """Compile CUDA C++ source to PTX via NVRTC.

    Args:
        cuda_source: CUDA C++ source code string.

    Returns:
        Compiled PTX as bytes.
    """
    opts = [
        b"-use_fast_math",
        b"-default-device",
        b"-std=c++17",
        b"-rdc", b"true",
        f"-I{find_optix_include()}".encode(),
        f"-I{find_cuda_include()}".encode(),
    ]
    prog = check_nvrtc(nvrtc.nvrtcCreateProgram(
        cuda_source.encode(), b"spheres.cu", 0, [], []))
    check_nvrtc(nvrtc.nvrtcCompileProgram(prog, len(opts), opts), prog)
    size = check_nvrtc(nvrtc.nvrtcGetPTXSize(prog))
    ptx = b" " * size
    check_nvrtc(nvrtc.nvrtcGetPTX(prog, ptx))
    return ptx


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def aligned_dtype(names, formats, alignment):
    """Create a numpy structured dtype with a specific alignment/padding."""
    dt = np.dtype({"names": names, "formats": formats, "align": True})
    size = (dt.itemsize + alignment - 1) // alignment * alignment
    return np.dtype({
        "names": names,
        "formats": formats,
        "itemsize": size,
        "align": True,
    })


def to_device(np_array):
    """Copy a host numpy array into freshly allocated CuPy device memory."""
    import cupy as cp
    nbytes = np_array.nbytes
    d_mem = cp.cuda.alloc(nbytes)
    d_mem.copy_from(ctypes.c_void_p(np_array.ctypes.data).value, nbytes)
    return d_mem
