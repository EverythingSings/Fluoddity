#!/usr/bin/env python3
"""
Minimal proof of concept: ModernGL buffer -> CUDA/OpenGL interop -> OptiX.

Data flow per the design:

  1. ModernGL owns a GL buffer of 1,000,000 float4 = (x, y, z, radius) beads.
  2. The GL buffer is registered with CUDA (cudaGraphicsGLRegisterBuffer) and
     mapped to get a raw device pointer. No copies -- OptiX reads the GL
     buffer's memory directly.
  3. A CuPy kernel derives AABBs from the mapped pointer; an OptiX GAS
     (custom primitives) is built over them using the RT cores.
  4. Each frame OptiX raytraces the beads (primary ray + one shadow ray to a
     directional light) directly into a GL pixel-unpack buffer (PBO), also
     registered with CUDA.
  5. The PBO is unmapped and blitted to a texture / fullscreen triangle by
     ModernGL.

Note on "RTX cores": the pyoptix 9.1.0 bindings only expose
BuildInputCustomPrimitiveArray (no BuildInputSphereArray), so the spheres are
custom AABB primitives with a tiny __intersection__ program. BVH build and
traversal -- the expensive part for 1M primitives -- still runs on the RT
cores; only the analytic sphere test runs on the SMs.

Requirements:
  * OptiX SDK 9.1 installed (for headers). Set OPTIX_PATH if not in the
    default Windows location.
  * Driver new enough for OptiX 9.1 (R570+).

Controls: ESC quits. The light orbits so you can watch the shadows sweep.
"""

import os
import sys
import glob
import time
import ctypes

import numpy as np
import cupy as cp
import glfw
import moderngl
import optix
from cuda.bindings import runtime as cudart
from cuda.bindings import nvrtc

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 720
GRID = 1000                      # GRID*GRID beads = 1,000,000
NUM_BEADS = GRID * GRID
BEAD_RADIUS = 0.0003             # "tiny"


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def check_cuda(result):
    err = result[0]
    if err != cudart.cudaError_t.cudaSuccess:
        raise RuntimeError(f"CUDA error: {err}")
    return result[1] if len(result) == 2 else result[1:] if len(result) > 2 else None


def check_nvrtc(result, prog=None):
    if result[0].value:
        msg = nvrtc.nvrtcGetErrorString(result[0])[1]
        if prog is not None:
            _, logsize = nvrtc.nvrtcGetProgramLogSize(prog)
            log = b" " * logsize
            nvrtc.nvrtcGetProgramLog(prog, log)
            msg = f"{msg}\n{log.decode()}"
        raise RuntimeError(f"NVRTC error: {msg}")
    return result[1] if len(result) == 2 else result[1:] if len(result) > 2 else None


def find_optix_include():
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
    raise RuntimeError("OptiX headers not found. Set OPTIX_PATH to the SDK root.")


def find_cuda_include():
    p = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME") or "/usr/local/cuda"
    return os.path.join(p, "include")


def aligned_dtype(names, formats, alignment):
    dt = np.dtype({"names": names, "formats": formats, "align": True})
    size = (dt.itemsize + alignment - 1) // alignment * alignment
    return np.dtype({"names": names, "formats": formats,
                     "itemsize": size, "align": True})


def to_device(np_array):
    """Copy a host numpy array into freshly allocated device memory."""
    nbytes = np_array.nbytes
    d_mem = cp.cuda.alloc(nbytes)
    d_mem.copy_from(ctypes.c_void_p(np_array.ctypes.data).value, nbytes)
    return d_mem


# ----------------------------------------------------------------------------
# OptiX device code (compiled at runtime with NVRTC)
# ----------------------------------------------------------------------------
CUDA_SRC = r"""
#include <optix.h>

extern "C" {
struct Params
{
    uchar4*            image;     // mapped GL PBO
    float4*            spheres;   // mapped GL vertex buffer: xyz = center, w = radius
    unsigned long long handle;    // traversable
    unsigned int       width;
    unsigned int       height;
    float3 eye; float3 U; float3 V; float3 W;   // pinhole camera basis
    float3 light_dir;                           // unit vector TOWARD the light
};
__constant__ Params params;
}

// --- minimal float3 math ----------------------------------------------------
static __forceinline__ __device__ float3 mk3(float x, float y, float z){ return make_float3(x,y,z); }
static __forceinline__ __device__ float3 operator+(float3 a, float3 b){ return mk3(a.x+b.x, a.y+b.y, a.z+b.z); }
static __forceinline__ __device__ float3 operator-(float3 a, float3 b){ return mk3(a.x-b.x, a.y-b.y, a.z-b.z); }
static __forceinline__ __device__ float3 operator*(float s, float3 a){ return mk3(s*a.x, s*a.y, s*a.z); }
static __forceinline__ __device__ float3 operator*(float3 a, float s){ return mk3(a.x*s, a.y*s, a.z*s); }
static __forceinline__ __device__ float3 operator*(float3 a, float3 b){ return mk3(a.x*b.x, a.y*b.y, a.z*b.z); }
static __forceinline__ __device__ float  dot(float3 a, float3 b){ return a.x*b.x + a.y*b.y + a.z*b.z; }
static __forceinline__ __device__ float3 normalize(float3 a){ float s = rsqrtf(dot(a,a)); return s*a; }

static __forceinline__ __device__ unsigned char to_byte(float x)
{
    x = sqrtf(fminf(fmaxf(x, 0.0f), 1.0f));      // cheap gamma
    return (unsigned char)(x * 255.99f);
}

// --- ray generation ----------------------------------------------------------
extern "C" __global__ void __raygen__rg()
{
    const uint3 idx = optixGetLaunchIndex();
    const float2 d = make_float2(
        2.0f * ((float)idx.x + 0.5f) / (float)params.width  - 1.0f,
        2.0f * ((float)idx.y + 0.5f) / (float)params.height - 1.0f);
    const float3 dir = normalize(d.x * params.U + d.y * params.V + params.W);

    unsigned int p0, p1, p2;                     // RGB payload
    optixTrace(
        (OptixTraversableHandle)params.handle,
        params.eye, dir,
        0.0f, 1e16f, 0.0f,                       // tmin, tmax, time
        OptixVisibilityMask(255),
        OPTIX_RAY_FLAG_DISABLE_ANYHIT,
        0, 0,                                    // SBT offset, stride
        0,                                       // miss index: radiance
        p0, p1, p2);

    params.image[idx.y * params.width + idx.x] = make_uchar4(
        to_byte(__uint_as_float(p0)),
        to_byte(__uint_as_float(p1)),
        to_byte(__uint_as_float(p2)),
        255);
}

// --- miss programs -----------------------------------------------------------
extern "C" __global__ void __miss__radiance()
{
    const float3 dir = optixGetWorldRayDirection();
    const float t = 0.5f * (dir.y + 1.0f);       // sky gradient
    const float3 c = (1.0f - t) * mk3(0.08f, 0.08f, 0.10f) + t * mk3(0.45f, 0.62f, 0.85f);
    optixSetPayload_0(__float_as_uint(c.x));
    optixSetPayload_1(__float_as_uint(c.y));
    optixSetPayload_2(__float_as_uint(c.z));
}

extern "C" __global__ void __miss__occlusion()
{
    optixSetPayload_0(0u);                       // reached the light: not occluded
}

// --- sphere intersection (custom primitive) ----------------------------------
extern "C" __global__ void __intersection__sphere()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float4 s = params.spheres[prim];

    const float3 O = optixGetObjectRayOrigin() - mk3(s.x, s.y, s.z);
    const float3 D = optixGetObjectRayDirection();

    const float a = dot(D, D);
    const float b = dot(O, D);
    const float c = dot(O, O) - s.w * s.w;
    const float disc = b * b - a * c;
    if (disc < 0.0f) return;

    const float sq = sqrtf(disc);
    const float t0 = (-b - sq) / a;
    const float t1 = (-b + sq) / a;
    const float tmin = optixGetRayTmin();
    const float tmax = optixGetRayTmax();
    if (t0 > tmin && t0 < tmax)       optixReportIntersection(t0, 0);
    else if (t1 > tmin && t1 < tmax)  optixReportIntersection(t1, 0);
}

// --- closest hit: Lambert + shadow ray ---------------------------------------
extern "C" __global__ void __closesthit__ch()
{
    const unsigned int prim = optixGetPrimitiveIndex();
    const float4 s = params.spheres[prim];

    const float  t = optixGetRayTmax();
    const float3 P = optixGetWorldRayOrigin() + t * optixGetWorldRayDirection();
    const float3 N = normalize(P - mk3(s.x, s.y, s.z));
    const float3 L = params.light_dir;

    // shadow ray toward the light; only the occlusion miss program can run
    unsigned int occluded = 1u;
    optixTrace(
        (OptixTraversableHandle)params.handle,
        P + 1e-4f * N, L,
        0.0f, 1e16f, 0.0f,
        OptixVisibilityMask(255),
        OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT
        | OPTIX_RAY_FLAG_DISABLE_ANYHIT
        | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
        0, 0,
        1,                                       // miss index: occlusion
        occluded);

    // per-bead albedo from a cheap index hash
    unsigned int h = prim * 2654435761u;
    const float3 albedo = mk3(0.45f + 0.45f * ((h       & 255u) / 255.0f),
                              0.45f + 0.45f * ((h >>  8 & 255u) / 255.0f),
                              0.45f + 0.45f * ((h >> 16 & 255u) / 255.0f));

    const float ndl = fmaxf(dot(N, L), 0.0f);
    const float vis = occluded ? 0.0f : 1.0f;
    const float3 c = albedo * (0.12f + 0.95f * ndl * vis) * mk3(1.0f, 0.97f, 0.92f);

    optixSetPayload_0(__float_as_uint(c.x));
    optixSetPayload_1(__float_as_uint(c.y));
    optixSetPayload_2(__float_as_uint(c.z));
}
"""


def compile_ptx(src):
    opts = [b"-use_fast_math", b"-default-device", b"-std=c++17",
            b"-rdc", b"true",
            f"-I{find_optix_include()}".encode(),
            f"-I{find_cuda_include()}".encode()]
    prog = check_nvrtc(nvrtc.nvrtcCreateProgram(
        src.encode(), b"beads.cu", 0, [], []))
    check_nvrtc(nvrtc.nvrtcCompileProgram(prog, len(opts), opts), prog)
    size = check_nvrtc(nvrtc.nvrtcGetPTXSize(prog))
    ptx = b" " * size
    check_nvrtc(nvrtc.nvrtcGetPTX(prog, ptx))
    return ptx


# ----------------------------------------------------------------------------
# OpenGL side (ModernGL): the bead buffer, the display PBO/texture, the quad
# ----------------------------------------------------------------------------
def init_gl():
    if not glfw.init():
        raise RuntimeError("glfw init failed")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    window = glfw.create_window(WIDTH, HEIGHT, "OptiX beads (GL interop)", None, None)
    glfw.make_context_current(window)
    glfw.swap_interval(0)
    ctx = moderngl.create_context()
    return window, ctx


def make_bead_buffer(ctx):
    """The 'simulation' buffer: 1M beads on a wavy carpet, owned by OpenGL."""
    xs = np.linspace(-1.0, 1.0, GRID, dtype=np.float32)
    X, Z = np.meshgrid(xs, xs)
    Y = 0.10 * np.sin(X * 700.1) * np.cos(Z * 500.3) \
      + 0.03 * np.sin(X * 23.0 + Z * 17.0)

    beads = np.empty((NUM_BEADS, 4), dtype=np.float32)
    beads[:, 0] = X.ravel()
    beads[:, 1] = Y.ravel()
    beads[:, 2] = Z.ravel()
    beads[:, 3] = BEAD_RADIUS
    return ctx.buffer(beads.tobytes())      # <- positions+radii live in a GL buffer


def make_display(ctx):
    pbo = ctx.buffer(reserve=WIDTH * HEIGHT * 4, dynamic=True)
    tex = ctx.texture((WIDTH, HEIGHT), 4)
    tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
    prog = ctx.program(
        vertex_shader="""
            #version 330
            out vec2 uv;
            void main() {
                vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
                uv = p;
                gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
            }""",
        fragment_shader="""
            #version 330
            uniform sampler2D tex;
            in vec2 uv;
            out vec4 fragColor;
            void main() { fragColor = texture(tex, uv); }""")
    vao = ctx.vertex_array(prog, [])
    return pbo, tex, vao


# ----------------------------------------------------------------------------
# Compute shader for bead animation
# ----------------------------------------------------------------------------
COMPUTE_SRC = """
#version 430
layout(local_size_x = 256) in;
layout(std430, binding = 0) buffer BeadBuffer { vec4 beads[]; };
uniform float u_time;
uniform int   u_grid;
void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx >= uint(u_grid * u_grid)) return;
    float x = beads[idx].x;
    float z = beads[idx].z;
    float y = 0.10 * sin(x * 700.1) * cos(z * 500.3)
            + 0.03 * sin(x * 23.0 + z * 17.0)
            + 0.04 * sin(x * 50.0 + u_time * 2.0)
            + 0.03 * cos(z * 40.0 - u_time * 1.5);
    beads[idx].y = y;
}
"""


def make_compute_shader(ctx):
    cs = ctx.compute_shader(COMPUTE_SRC)
    cs['u_grid'].value = GRID
    return cs


# ----------------------------------------------------------------------------
# CUDA <-> GL interop
# ----------------------------------------------------------------------------
def register_buffer(gl_buffer, flags):
    return check_cuda(cudart.cudaGraphicsGLRegisterBuffer(int(gl_buffer.glo), flags))


def map_pointer(resource):
    check_cuda(cudart.cudaGraphicsMapResources(1, resource, 0))
    ptr, size = check_cuda(cudart.cudaGraphicsResourceGetMappedPointer(resource))
    return int(ptr), int(size)


def unmap(resource):
    check_cuda(cudart.cudaGraphicsUnmapResources(1, resource, 0))


# ----------------------------------------------------------------------------
# OptiX setup
# ----------------------------------------------------------------------------
def create_context():
    def log(level, tag, msg):
        print(f"[{level:>2}][{tag:>12}]: {msg}")
    opts = optix.DeviceContextOptions(logCallbackFunction=log, logCallbackLevel=3)
    return optix.deviceContextCreate(0, opts)


def build_gas(octx, d_spheres_ptr):
    """Compute AABBs from the mapped GL pointer with CuPy, build the GAS.
    Returns (handle, d_gas, d_temp, d_aabbs, temp_size, gas_size)."""
    # zero-copy view of the GL buffer's memory
    mem = cp.cuda.UnownedMemory(d_spheres_ptr, NUM_BEADS * 16, owner=None)
    spheres = cp.ndarray((NUM_BEADS, 4), dtype=cp.float32,
                         memptr=cp.cuda.MemoryPointer(mem, 0))

    d_aabbs = cp.empty((NUM_BEADS, 6), dtype=cp.float32)
    d_aabbs[:, 0:3] = spheres[:, 0:3] - spheres[:, 3:4]
    d_aabbs[:, 3:6] = spheres[:, 0:3] + spheres[:, 3:4]
    cp.cuda.Device().synchronize()

    build_input = optix.BuildInputCustomPrimitiveArray(
        aabbBuffers=[d_aabbs.data.ptr],
        numPrimitives=NUM_BEADS,
        flags=[optix.GEOMETRY_FLAG_DISABLE_ANYHIT],
        numSbtRecords=1)
    accel_opts = optix.AccelBuildOptions(
        buildFlags=int(optix.BUILD_FLAG_PREFER_FAST_TRACE
                       | optix.BUILD_FLAG_ALLOW_UPDATE),
        operation=optix.BUILD_OPERATION_BUILD)

    sizes = octx.accelComputeMemoryUsage([accel_opts], [build_input])
    d_temp = cp.cuda.alloc(sizes.tempSizeInBytes)
    d_gas = cp.cuda.alloc(sizes.outputSizeInBytes)
    handle = octx.accelBuild(0, [accel_opts], [build_input],
                             d_temp.ptr, sizes.tempSizeInBytes,
                             d_gas.ptr, sizes.outputSizeInBytes, [])
    cp.cuda.Device().synchronize()
    return handle, d_gas, d_temp, d_aabbs, sizes.tempSizeInBytes, sizes.outputSizeInBytes


def refit_gas(octx, d_spheres_ptr, d_gas, d_temp, d_aabbs, temp_size, gas_size):
    """Recompute AABBs and refit the GAS in-place. Returns updated handle."""
    mem = cp.cuda.UnownedMemory(d_spheres_ptr, NUM_BEADS * 16, owner=None)
    spheres = cp.ndarray((NUM_BEADS, 4), dtype=cp.float32,
                         memptr=cp.cuda.MemoryPointer(mem, 0))

    d_aabbs[:, 0:3] = spheres[:, 0:3] - spheres[:, 3:4]
    d_aabbs[:, 3:6] = spheres[:, 0:3] + spheres[:, 3:4]
    cp.cuda.Device().synchronize()

    build_input = optix.BuildInputCustomPrimitiveArray(
        aabbBuffers=[d_aabbs.data.ptr],
        numPrimitives=NUM_BEADS,
        flags=[optix.GEOMETRY_FLAG_DISABLE_ANYHIT],
        numSbtRecords=1)
    accel_opts = optix.AccelBuildOptions(
        buildFlags=int(optix.BUILD_FLAG_PREFER_FAST_TRACE
                       | optix.BUILD_FLAG_ALLOW_UPDATE),
        operation=optix.BUILD_OPERATION_UPDATE)

    handle = octx.accelBuild(0, [accel_opts], [build_input],
                             d_temp.ptr, temp_size,
                             d_gas.ptr, gas_size, [])
    cp.cuda.Device().synchronize()
    return handle


def build_pipeline(octx, ptx):
    pco = optix.PipelineCompileOptions(
        usesMotionBlur=False,
        traversableGraphFlags=int(optix.TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_GAS),
        numPayloadValues=3,
        numAttributeValues=2,
        exceptionFlags=int(optix.EXCEPTION_FLAG_NONE),
        pipelineLaunchParamsVariableName="params",
        usesPrimitiveTypeFlags=optix.PRIMITIVE_TYPE_FLAGS_CUSTOM)

    mco = optix.ModuleCompileOptions(
        maxRegisterCount=optix.COMPILE_DEFAULT_MAX_REGISTER_COUNT,
        optLevel=optix.COMPILE_OPTIMIZATION_DEFAULT,
        debugLevel=optix.COMPILE_DEBUG_LEVEL_DEFAULT)
    module, log = octx.moduleCreate(mco, pco, ptx)

    rg_desc = optix.ProgramGroupDesc()
    rg_desc.raygenModule = module
    rg_desc.raygenEntryFunctionName = "__raygen__rg"
    (rg,), _ = octx.programGroupCreate([rg_desc])

    ms_desc = optix.ProgramGroupDesc()
    ms_desc.missModule = module
    ms_desc.missEntryFunctionName = "__miss__radiance"
    (ms_rad,), _ = octx.programGroupCreate([ms_desc])

    ms2_desc = optix.ProgramGroupDesc()
    ms2_desc.missModule = module
    ms2_desc.missEntryFunctionName = "__miss__occlusion"
    (ms_occ,), _ = octx.programGroupCreate([ms2_desc])

    hg_desc = optix.ProgramGroupDesc()
    hg_desc.hitgroupModuleCH = module
    hg_desc.hitgroupEntryFunctionNameCH = "__closesthit__ch"
    hg_desc.hitgroupModuleIS = module
    hg_desc.hitgroupEntryFunctionNameIS = "__intersection__sphere"
    (hg,), _ = octx.programGroupCreate([hg_desc])

    groups = [rg, ms_rad, ms_occ, hg]
    max_trace_depth = 2                              # primary + shadow
    plo = optix.PipelineLinkOptions()
    plo.maxTraceDepth = max_trace_depth
    pipeline = octx.pipelineCreate(pco, plo, groups, "")

    stack = optix.StackSizes()
    for g in groups:
        optix.util.accumulateStackSizes(g, stack, pipeline)
    dc_trav, dc_state, cc = optix.util.computeStackSizes(stack, max_trace_depth, 0, 0)
    pipeline.setStackSize(dc_trav, dc_state, cc, 1)
    return pipeline, groups


def build_sbt(groups):
    rg, ms_rad, ms_occ, hg = groups
    hdr = f"{optix.SBT_RECORD_HEADER_SIZE}B"
    dtype = aligned_dtype(["header"], [hdr], optix.SBT_RECORD_ALIGNMENT)

    h_rg = np.zeros(1, dtype=dtype)
    optix.sbtRecordPackHeader(rg, h_rg)

    h_ms0 = np.zeros(1, dtype=dtype)
    h_ms1 = np.zeros(1, dtype=dtype)
    optix.sbtRecordPackHeader(ms_rad, h_ms0)
    optix.sbtRecordPackHeader(ms_occ, h_ms1)
    h_ms = np.concatenate([h_ms0, h_ms1])            # miss index 0, 1

    h_hg = np.zeros(1, dtype=dtype)
    optix.sbtRecordPackHeader(hg, h_hg)

    d_rg, d_ms, d_hg = to_device(h_rg), to_device(h_ms), to_device(h_hg)
    sbt = optix.ShaderBindingTable(
        raygenRecord=d_rg.ptr,
        missRecordBase=d_ms.ptr,
        missRecordStrideInBytes=dtype.itemsize,
        missRecordCount=2,
        hitgroupRecordBase=d_hg.ptr,
        hitgroupRecordStrideInBytes=dtype.itemsize,
        hitgroupRecordCount=1)
    return sbt, (d_rg, d_ms, d_hg)                   # keep device memory alive


# Launch-params struct -- field order must match the CUDA `Params` struct.
PARAMS_DTYPE = aligned_dtype(
    ["image", "spheres", "handle", "width", "height",
     "eye_x", "eye_y", "eye_z",
     "u_x", "u_y", "u_z",
     "v_x", "v_y", "v_z",
     "w_x", "w_y", "w_z",
     "l_x", "l_y", "l_z"],
    ["u8", "u8", "u8", "u4", "u4"] + ["f4"] * 15,
    8)


def camera_basis(eye, lookat, up, fov_deg, aspect):
    eye, lookat, up = map(lambda v: np.asarray(v, np.float32), (eye, lookat, up))
    W = lookat - eye
    wlen = np.linalg.norm(W)
    U = np.cross(W, up); U /= np.linalg.norm(U)
    V = np.cross(U, W);  V /= np.linalg.norm(V)
    vlen = wlen * np.tan(0.5 * np.radians(fov_deg))
    return eye, U * vlen * aspect, V * vlen, W


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    window, ctx = init_gl()

    # 1. The GL-owned data: 1M beads + the display PBO + compute shader
    bead_buf = make_bead_buffer(ctx)
    pbo, tex, vao = make_display(ctx)
    compute = make_compute_shader(ctx)
    ctx.finish()                                     # ensure GL uploads are done

    # 2. Register GL buffers with CUDA
    cp.zeros(1)                                      # touch CUDA / primary context
    flags = cudart.cudaGraphicsRegisterFlags
    bead_res = register_buffer(bead_buf, flags.cudaGraphicsRegisterFlagsReadOnly)
    pbo_res = register_buffer(pbo, flags.cudaGraphicsRegisterFlagsWriteDiscard)

    # Map bead buffer for initial GAS build, then unmap so GL can write
    spheres_ptr, _ = map_pointer(bead_res)

    # 3. OptiX: context, GAS over the mapped GL memory, pipeline, SBT
    octx = create_context()
    gas_handle, d_gas, d_temp, d_aabbs, temp_size, gas_size = build_gas(octx, spheres_ptr)
    ptx = compile_ptx(CUDA_SRC)
    pipeline, groups = build_pipeline(octx, ptx)
    sbt, _sbt_mem = build_sbt(groups)

    unmap(bead_res)                                  # release to GL for compute shader

    d_params = cp.empty(PARAMS_DTYPE.itemsize, dtype=cp.uint8)

    eye, U, V, W = camera_basis(
        eye=(0.0, 0.1, .755), lookat=(0.0, 0.0, 0.0), up=(0, 1, 0),
        fov_deg=35.0, aspect=WIDTH / HEIGHT)

    t0 = time.perf_counter()
    frames, last_fps_t = 0, t0
    print(f"Rendering {NUM_BEADS:,} beads...")

    num_groups = (NUM_BEADS + 255) // 256

    while not glfw.window_should_close(window):
        if glfw.get_key(window, glfw.KEY_ESCAPE) == glfw.PRESS:
            break
        t = time.perf_counter() - t0

        # 4. Animate beads with GL compute shader
        compute['u_time'].value = t
        bead_buf.bind_to_storage_buffer(0)
        compute.run(group_x=num_groups)
        ctx.finish()                                 # ensure compute writes are visible

        # 5. Map beads to CUDA and refit GAS
        spheres_ptr, _ = map_pointer(bead_res)
        gas_handle = refit_gas(octx, spheres_ptr, d_gas, d_temp, d_aabbs,
                               temp_size, gas_size)

        # orbiting directional light so the shadows visibly sweep
        a = 0.4 * t
        light = np.array([np.cos(a), 0.55, np.sin(a)], np.float32)
        light /= np.linalg.norm(light)

        # 6. Map PBO, launch OptiX directly into it
        image_ptr, _ = map_pointer(pbo_res)
        h_params = np.array([(
            image_ptr, spheres_ptr, gas_handle, WIDTH, HEIGHT,
            *eye, *U, *V, *W, *light)], dtype=PARAMS_DTYPE)
        d_params.set(np.frombuffer(h_params.tobytes(), dtype=np.uint8))

        optix.launch(pipeline, 0, d_params.data.ptr, PARAMS_DTYPE.itemsize,
                     sbt, WIDTH, HEIGHT, 1)
        check_cuda(cudart.cudaDeviceSynchronize())
        unmap(pbo_res)                               # hand the PBO back to GL

        # 7. Unmap beads so GL can write next frame
        unmap(bead_res)

        # 8. Display: PBO -> texture -> fullscreen triangle
        tex.write(pbo)
        tex.use(0)
        vao.render(moderngl.TRIANGLES, vertices=3)
        glfw.swap_buffers(window)
        glfw.poll_events()

        frames += 1
        now = time.perf_counter()
        if now - last_fps_t > 0.5:
            fps = frames / (now - last_fps_t)
            glfw.set_window_title(
                window, f"OptiX beads (GL interop) - {NUM_BEADS:,} spheres - {fps:5.1f} fps")
            frames, last_fps_t = 0, now

    check_cuda(cudart.cudaGraphicsUnregisterResource(pbo_res))
    check_cuda(cudart.cudaGraphicsUnregisterResource(bead_res))
    glfw.terminate()


if __name__ == "__main__":
    main()