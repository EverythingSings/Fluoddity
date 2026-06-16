"""OptiX sphere renderer: raytrace entities as solid spheres using RT cores.

This module provides the OptiXSphereRenderer class, a self-contained renderer
that reads Fluoddity's entity SSBO via GL-CUDA interop and produces a raytraced
image of solid spheres with Lambert shading and shadow rays.

Adapted from demos/optix_demo.py.
"""

import numpy as np

import optix
import cupy as cp
from cuda.bindings import runtime as cudart

import moderngl

from .interop import (
    check_cuda,
    register_gl_buffer,
    map_resource,
    unmap_resource,
    unregister_resource,
    compile_ptx,
    aligned_dtype,
    to_device,
)
from .cuda_src import SPHERE_CUDA_SRC


# ---------------------------------------------------------------------------
# Launch-params dtype -- must match the CUDA Params struct field-by-field.
#
# CUDA struct layout (with alignment):
#   ushort4*           image;          // offset  0, ptr (8 bytes)
#   float*             entities;       // offset  8, ptr (8 bytes)
#   unsigned int       entity_stride;  // offset 16, u4  (4 bytes)
#   <pad 4 bytes>
#   unsigned long long handle;         // offset 24, u8  (8 bytes)
#   unsigned int       width;          // offset 32, u4
#   unsigned int       height;         // offset 36, u4
#   float3 eye;                        // offset 40, 3×f4
#   float3 U;                          // offset 52, 3×f4
#   float3 V;                          // offset 64, 3×f4
#   float3 W;                          // offset 76, 3×f4
#   float3 light_dir;                  // offset 88, 3×f4
#   float  ambient;                    // offset 100, f4
#   float  radius_scale;               // offset 104, f4
#   int    shadows_enabled;            // offset 108, i4
#   float3 light_color;               // offset 112, 3×f4
#   float  light_intensity;           // offset 124, f4
#   float3 sky_color_top;             // offset 128, 3×f4
#   float3 sky_color_bottom;          // offset 140, 3×f4
#   --- AO ---
#   int    ao_enabled;                // offset 152, i4
#   int    ao_num_rays;               // offset 156, i4
#   float  ao_radius;                 // offset 160, f4
#   unsigned int ao_frame_index;      // offset 164, u4
#   Total: 168 bytes (8-byte aligned)
# ---------------------------------------------------------------------------
PARAMS_DTYPE = np.dtype({
    "names": [
        "image", "entities", "entity_stride", "_pad0", "handle",
        "width", "height",
        "eye_x", "eye_y", "eye_z",
        "u_x", "u_y", "u_z",
        "v_x", "v_y", "v_z",
        "w_x", "w_y", "w_z",
        "l_x", "l_y", "l_z",
        "ambient", "radius_scale", "shadows_enabled",
        "lc_r", "lc_g", "lc_b",
        "light_intensity",
        "sky_top_r", "sky_top_g", "sky_top_b",
        "sky_bot_r", "sky_bot_g", "sky_bot_b",
        # AO
        "ao_enabled", "ao_num_rays", "ao_radius", "ao_frame_index",
        # Albedo controls
        "albedo_saturation", "albedo_brightness",
        # Sphere size jitter
        "sphere_size_jitter",
        # SDF scene
        "sdf_enabled",
        "sdf_aabb_min_x", "sdf_aabb_min_y", "sdf_aabb_min_z",
        "sdf_aabb_max_x", "sdf_aabb_max_y", "sdf_aabb_max_z",
        "sdf_prim_index",
    ],
    "formats": [
        "u8", "u8", "u4", "u4", "u8",
        "u4", "u4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        "f4", "f4", "i4",
        "f4", "f4", "f4",
        "f4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        # AO
        "i4", "i4", "f4", "u4",
        # Albedo controls
        "f4", "f4",
        # Sphere size jitter
        "f4",
        # SDF scene
        "i4",
        "f4", "f4", "f4",
        "f4", "f4", "f4",
        "u4",
    ],
    "offsets": [
        0, 8, 16, 20, 24,
        32, 36,
        40, 44, 48,
        52, 56, 60,
        64, 68, 72,
        76, 80, 84,
        88, 92, 96,
        100, 104, 108,
        112, 116, 120,
        124,
        128, 132, 136,
        140, 144, 148,
        # AO
        152, 156, 160, 164,
        # Albedo controls
        168, 172,
        # Sphere size jitter
        176,
        # SDF scene
        180,
        184, 188, 192,
        196, 200, 204,
        208,
    ],
    "itemsize": 216,
})


def _camera_basis_from_vectors(pos, direction, up, fov_deg, aspect):
    """Convert FPS camera vectors to OptiX pinhole basis (eye, U, V, W).

    Args:
        pos: Camera position (3,).
        direction: Unit look direction (3,).
        up: Unit up vector (3,).
        fov_deg: Vertical field of view in degrees.
        aspect: Width / height.

    Returns:
        (eye, U, V, W) as numpy float32 arrays.
    """
    eye = np.asarray(pos, dtype=np.float32)
    W = np.asarray(direction, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)

    U = np.cross(W, up)
    U = U / max(np.linalg.norm(U), 1e-8)
    V = np.cross(U, W)
    V = V / max(np.linalg.norm(V), 1e-8)

    # Scale by FOV: at distance 1 along W, the half-height is tan(fov/2)
    vlen = np.tan(0.5 * np.radians(fov_deg))
    U = U * vlen * aspect
    V = V * vlen
    # W stays as unit direction (distance 1)

    return eye, U.astype(np.float32), V.astype(np.float32), W.astype(np.float32)


class OptiXSphereRenderer:
    """Raytrace entities as solid spheres using OptiX RT cores.

    Reads a ModernGL entity buffer (SSBO with 8-float stride) via GL-CUDA
    interop, builds a GAS over sphere AABBs, and renders into a GL texture
    via a PBO.

    Usage:
        renderer = OptiXSphereRenderer(ctx, entity_buffer, entity_count)
        renderer.build_accel()
        tex = renderer.render(width, height, eye, U, V, W, light_dir)
        # ... display tex ...
        renderer.cleanup()
    """

    def __init__(self, ctx, entity_buffer, entity_count, entity_stride=8):
        """Initialize OptiX context, compile PTX, build pipeline and SBT.

        Args:
            ctx: ModernGL context (must be current).
            entity_buffer: ModernGL buffer with Entity structs (SSBO binding 0).
            entity_count: Number of entities in the buffer.
            entity_stride: Floats per entity (default 8).
        """
        self._ctx = ctx
        self._entity_count = entity_count
        self._entity_stride = entity_stride

        # Display resources (lazily sized in render())
        self._pbo = None
        self._tex = None
        self._pbo_res = None
        self._render_width = 0
        self._render_height = 0

        # GAS resources (built in build_accel())
        self._gas_handle = None
        self._d_gas = None
        self._d_temp = None
        self._d_aabbs = None
        self._temp_size = 0
        self._gas_size = 0
        self._total_prims = 0

        # Initialize CuPy / CUDA primary context
        cp.zeros(1)

        # Register entity buffer with CUDA (read-only)
        self._entity_buffer = entity_buffer
        flags = cudart.cudaGraphicsRegisterFlags
        self._entity_res = register_gl_buffer(
            entity_buffer, flags.cudaGraphicsRegisterFlagsReadOnly
        )

        # OptiX context
        def _log_cb(level, tag, msg):
            print(f"[OptiX {level:>2}][{tag:>12}]: {msg}")

        opts = optix.DeviceContextOptions(
            logCallbackFunction=_log_cb, logCallbackLevel=3
        )
        self._octx = optix.deviceContextCreate(0, opts)

        # Load pre-compiled PTX if available, otherwise compile via NVRTC
        ptx = self._load_ptx()
        self._pipeline, self._groups = self._build_pipeline(ptx)
        self._sbt, self._sbt_mem = self._build_sbt()

        # Device-side launch params buffer
        self._d_params = cp.empty(PARAMS_DTYPE.itemsize, dtype=cp.uint8)

        # Dedicated CUDA stream for OptiX launches
        self._stream_obj = check_cuda(cudart.cudaStreamCreate())
        self._stream = int(self._stream_obj)  # raw handle for OptiX/CUDA APIs

        # CUDA events for timing instrumentation
        self._evt_gas_start = check_cuda(cudart.cudaEventCreate())
        self._evt_gas_end = check_cuda(cudart.cudaEventCreate())
        self._evt_render_start = check_cuda(cudart.cudaEventCreate())
        self._evt_render_end = check_cuda(cudart.cudaEventCreate())
        self.last_gas_ms = 0.0
        self.last_render_ms = 0.0

        # Log device info
        err, props = cudart.cudaGetDeviceProperties(0)
        if err == cudart.cudaError_t.cudaSuccess:
            name = props.name
            if isinstance(name, bytes):
                name = name.decode().rstrip('\x00')
            print(f"OptiX: CUDA device: {name}")

    # ------------------------------------------------------------------
    # PTX loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_ptx():
        """Load pre-compiled PTX if available, otherwise compile via NVRTC."""
        import os
        ptx_path = os.path.join(
            os.path.dirname(__file__), "spheres.ptx"
        )
        if os.path.isfile(ptx_path):
            with open(ptx_path, "rb") as f:
                ptx = f.read()
            print(f"OptiX: loaded pre-compiled PTX ({len(ptx)} bytes)")
            return ptx

        print("OptiX: compiling PTX via NVRTC (no pre-compiled PTX found)...")
        return compile_ptx(SPHERE_CUDA_SRC)

    # ------------------------------------------------------------------
    # Pipeline / SBT construction
    # ------------------------------------------------------------------

    def _build_pipeline(self, ptx):
        """Create OptiX pipeline with raygen, miss, and hitgroup programs."""
        pco = optix.PipelineCompileOptions(
            usesMotionBlur=False,
            traversableGraphFlags=int(
                optix.TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_GAS
            ),
            numPayloadValues=3,
            numAttributeValues=2,
            exceptionFlags=int(optix.EXCEPTION_FLAG_NONE),
            pipelineLaunchParamsVariableName="params",
            usesPrimitiveTypeFlags=optix.PRIMITIVE_TYPE_FLAGS_CUSTOM,
        )

        mco = optix.ModuleCompileOptions(
            maxRegisterCount=optix.COMPILE_DEFAULT_MAX_REGISTER_COUNT,
            optLevel=optix.COMPILE_OPTIMIZATION_DEFAULT,
            debugLevel=optix.COMPILE_DEBUG_LEVEL_DEFAULT,
        )
        module, _log = self._octx.moduleCreate(mco, pco, ptx)

        # Raygen
        rg_desc = optix.ProgramGroupDesc()
        rg_desc.raygenModule = module
        rg_desc.raygenEntryFunctionName = "__raygen__rg"
        (rg,), _ = self._octx.programGroupCreate([rg_desc])

        # Miss: radiance (index 0)
        ms_desc = optix.ProgramGroupDesc()
        ms_desc.missModule = module
        ms_desc.missEntryFunctionName = "__miss__radiance"
        (ms_rad,), _ = self._octx.programGroupCreate([ms_desc])

        # Miss: occlusion (index 1)
        ms2_desc = optix.ProgramGroupDesc()
        ms2_desc.missModule = module
        ms2_desc.missEntryFunctionName = "__miss__occlusion"
        (ms_occ,), _ = self._octx.programGroupCreate([ms2_desc])

        # Hit group: closest-hit + custom intersection
        hg_desc = optix.ProgramGroupDesc()
        hg_desc.hitgroupModuleCH = module
        hg_desc.hitgroupEntryFunctionNameCH = "__closesthit__ch"
        hg_desc.hitgroupModuleIS = module
        hg_desc.hitgroupEntryFunctionNameIS = "__intersection__sphere"
        (hg,), _ = self._octx.programGroupCreate([hg_desc])

        groups = [rg, ms_rad, ms_occ, hg]

        max_trace_depth = 2  # primary + shadow
        plo = optix.PipelineLinkOptions()
        plo.maxTraceDepth = max_trace_depth
        pipeline = self._octx.pipelineCreate(pco, plo, groups, "")

        # Configure stack sizes
        stack = optix.StackSizes()
        for g in groups:
            optix.util.accumulateStackSizes(g, stack, pipeline)
        dc_trav, dc_state, cc = optix.util.computeStackSizes(
            stack, max_trace_depth, 0, 0
        )
        pipeline.setStackSize(dc_trav, dc_state, cc, 1)

        return pipeline, groups

    def _build_sbt(self):
        """Build the Shader Binding Table."""
        rg, ms_rad, ms_occ, hg = self._groups
        hdr = f"{optix.SBT_RECORD_HEADER_SIZE}B"
        dtype = aligned_dtype(["header"], [hdr], optix.SBT_RECORD_ALIGNMENT)

        h_rg = np.zeros(1, dtype=dtype)
        optix.sbtRecordPackHeader(rg, h_rg)

        h_ms0 = np.zeros(1, dtype=dtype)
        h_ms1 = np.zeros(1, dtype=dtype)
        optix.sbtRecordPackHeader(ms_rad, h_ms0)
        optix.sbtRecordPackHeader(ms_occ, h_ms1)
        h_ms = np.concatenate([h_ms0, h_ms1])

        h_hg = np.zeros(1, dtype=dtype)
        optix.sbtRecordPackHeader(hg, h_hg)

        d_rg = to_device(h_rg)
        d_ms = to_device(h_ms)
        d_hg = to_device(h_hg)

        sbt = optix.ShaderBindingTable(
            raygenRecord=d_rg.ptr,
            missRecordBase=d_ms.ptr,
            missRecordStrideInBytes=dtype.itemsize,
            missRecordCount=2,
            hitgroupRecordBase=d_hg.ptr,
            hitgroupRecordStrideInBytes=dtype.itemsize,
            hitgroupRecordCount=1,
        )
        return sbt, (d_rg, d_ms, d_hg)  # prevent GC

    # ------------------------------------------------------------------
    # Display resources (PBO + texture)
    # ------------------------------------------------------------------

    def _ensure_display(self, width, height):
        """Create or resize the PBO and output texture."""
        if self._render_width == width and self._render_height == height:
            return

        # Clean up old PBO registration
        if self._pbo_res is not None:
            unregister_resource(self._pbo_res)
            self._pbo_res = None

        # Create new PBO and texture (rgba16f for linear HDR output)
        self._pbo = self._ctx.buffer(
            reserve=width * height * 8, dynamic=True  # 4 x fp16 per pixel
        )
        self._tex = self._ctx.texture((width, height), 4, dtype='f2')
        self._tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

        # Register PBO with CUDA (write-discard)
        flags = cudart.cudaGraphicsRegisterFlags
        self._pbo_res = register_gl_buffer(
            self._pbo, flags.cudaGraphicsRegisterFlagsWriteDiscard
        )

        self._render_width = width
        self._render_height = height

    # ------------------------------------------------------------------
    # Acceleration structure (GAS)
    # ------------------------------------------------------------------

    def _compute_aabbs(self, d_entities_ptr, radius_scale=1.0,
                       sphere_size_jitter=0.0,
                       sdf_enabled=False, sdf_aabb_min=None, sdf_aabb_max=None):
        """Compute float6 AABBs from the mapped entity buffer via CuPy.

        Handles Fluoddity's 8-float stride by reshaping and indexing columns.
        radius_scale and sphere_size_jitter are applied so AABBs match the
        intersection shader. When sdf_enabled, appends one extra AABB for the
        SDF scene.
        """
        nbytes = self._entity_count * self._entity_stride * 4
        mem = cp.cuda.UnownedMemory(d_entities_ptr, nbytes, owner=None)
        entities_flat = cp.ndarray(
            self._entity_count * self._entity_stride,
            dtype=cp.float32,
            memptr=cp.cuda.MemoryPointer(mem, 0),
        )
        entities = entities_flat.reshape(self._entity_count, self._entity_stride)

        # Extract position (cols 0,1,2) and radius (col 7)
        pos = entities[:, 0:3]  # (N, 3)
        rad = entities[:, 7:8] * radius_scale  # (N, 1)

        # Apply per-sphere jitter matching the CUDA intersection shader
        if sphere_size_jitter > 0.0:
            h = (cp.arange(self._entity_count, dtype=cp.uint32) * 2654435761) & 0xFFFF
            jitter = h.astype(cp.float32) / 32767.5 - 1.0
            rad = rad * (1.0 + sphere_size_jitter * jitter.reshape(-1, 1))

        total_prims = self._entity_count + (1 if sdf_enabled else 0)
        if self._d_aabbs is None or self._d_aabbs.shape[0] != total_prims:
            self._d_aabbs = cp.empty(
                (total_prims, 6), dtype=cp.float32
            )

        self._d_aabbs[:self._entity_count, 0:3] = pos - rad
        self._d_aabbs[:self._entity_count, 3:6] = pos + rad

        # Append SDF AABB as the last primitive
        if sdf_enabled and sdf_aabb_min is not None:
            sdf_row = cp.array([[
                sdf_aabb_min[0], sdf_aabb_min[1], sdf_aabb_min[2],
                sdf_aabb_max[0], sdf_aabb_max[1], sdf_aabb_max[2],
            ]], dtype=cp.float32)
            self._d_aabbs[self._entity_count:self._entity_count + 1, :] = sdf_row

        self._total_prims = total_prims
        cp.cuda.Device().synchronize()  # sync CuPy's default stream

    def build_accel(self, radius_scale=1.0, sphere_size_jitter=0.0,
                    sdf_enabled=False, sdf_aabb_min=None, sdf_aabb_max=None):
        """Full GAS build. Maps entity buffer, computes AABBs, builds BVH.

        Must be called at least once before render(). Call again periodically
        to maintain BVH quality as entities move.

        Args:
            radius_scale: Multiplier on entity size for AABB computation.
            sphere_size_jitter: Per-sphere radius jitter magnitude (0-1).
            sdf_enabled: If True, append SDF AABB as an extra primitive.
            sdf_aabb_min: SDF bounding box min (3-tuple).
            sdf_aabb_max: SDF bounding box max (3-tuple).
        """
        self._ctx.finish()  # ensure GL writes are complete
        entities_ptr, _ = map_resource(self._entity_res)

        try:
            self._compute_aabbs(entities_ptr, radius_scale, sphere_size_jitter,
                                sdf_enabled, sdf_aabb_min, sdf_aabb_max)

            build_input = optix.BuildInputCustomPrimitiveArray(
                aabbBuffers=[self._d_aabbs.data.ptr],
                numPrimitives=self._total_prims,
                flags=[optix.GEOMETRY_FLAG_DISABLE_ANYHIT],
                numSbtRecords=1,
            )
            accel_opts = optix.AccelBuildOptions(
                buildFlags=int(
                    optix.BUILD_FLAG_PREFER_FAST_TRACE
                    | optix.BUILD_FLAG_ALLOW_UPDATE
                ),
                operation=optix.BUILD_OPERATION_BUILD,
            )

            sizes = self._octx.accelComputeMemoryUsage(
                [accel_opts], [build_input]
            )
            self._d_temp = cp.cuda.alloc(sizes.tempSizeInBytes)
            self._d_gas = cp.cuda.alloc(sizes.outputSizeInBytes)
            self._temp_size = sizes.tempSizeInBytes
            self._gas_size = sizes.outputSizeInBytes

            check_cuda(cudart.cudaEventRecord(self._evt_gas_start, self._stream_obj))
            self._gas_handle = self._octx.accelBuild(
                self._stream,
                [accel_opts],
                [build_input],
                self._d_temp.ptr,
                self._temp_size,
                self._d_gas.ptr,
                self._gas_size,
                [],
            )
            check_cuda(cudart.cudaEventRecord(self._evt_gas_end, self._stream_obj))
            check_cuda(cudart.cudaStreamSynchronize(self._stream_obj))
            self.last_gas_ms = check_cuda(
                cudart.cudaEventElapsedTime(self._evt_gas_start, self._evt_gas_end)
            )
        finally:
            unmap_resource(self._entity_res)

    def refit_accel(self, radius_scale=1.0, sphere_size_jitter=0.0,
                    sdf_enabled=False, sdf_aabb_min=None, sdf_aabb_max=None):
        """Refit existing GAS with updated AABBs (faster, lower BVH quality).

        Requires a prior build_accel() call. The GAS is updated in-place
        without reallocation.

        Args:
            radius_scale: Multiplier on entity size for AABB computation.
            sphere_size_jitter: Per-sphere radius jitter magnitude (0-1).
            sdf_enabled: If True, append SDF AABB as an extra primitive.
            sdf_aabb_min: SDF bounding box min (3-tuple).
            sdf_aabb_max: SDF bounding box max (3-tuple).
        """
        if self._gas_handle is None:
            self.build_accel(radius_scale, sphere_size_jitter,
                             sdf_enabled, sdf_aabb_min, sdf_aabb_max)
            return

        self._ctx.finish()
        entities_ptr, _ = map_resource(self._entity_res)

        try:
            self._compute_aabbs(entities_ptr, radius_scale, sphere_size_jitter,
                                sdf_enabled, sdf_aabb_min, sdf_aabb_max)

            build_input = optix.BuildInputCustomPrimitiveArray(
                aabbBuffers=[self._d_aabbs.data.ptr],
                numPrimitives=self._total_prims,
                flags=[optix.GEOMETRY_FLAG_DISABLE_ANYHIT],
                numSbtRecords=1,
            )
            accel_opts = optix.AccelBuildOptions(
                buildFlags=int(
                    optix.BUILD_FLAG_PREFER_FAST_TRACE
                    | optix.BUILD_FLAG_ALLOW_UPDATE
                ),
                operation=optix.BUILD_OPERATION_UPDATE,
            )

            check_cuda(cudart.cudaEventRecord(self._evt_gas_start, self._stream_obj))
            self._gas_handle = self._octx.accelBuild(
                self._stream,
                [accel_opts],
                [build_input],
                self._d_temp.ptr,
                self._temp_size,
                self._d_gas.ptr,
                self._gas_size,
                [],
            )
            check_cuda(cudart.cudaEventRecord(self._evt_gas_end, self._stream_obj))
            check_cuda(cudart.cudaStreamSynchronize(self._stream_obj))
            self.last_gas_ms = check_cuda(
                cudart.cudaEventElapsedTime(self._evt_gas_start, self._evt_gas_end)
            )
        finally:
            unmap_resource(self._entity_res)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, width, height, eye, U, V, W, light_dir,
               ambient=0.12, radius_scale=1.0, shadows_enabled=True,
               light_color=(1.0, 1.0, 1.0), light_intensity=1.0,
               sky_color_top=(0.45, 0.62, 0.85),
               sky_color_bottom=(0.08, 0.08, 0.10),
               ao_enabled=False, ao_num_rays=2, ao_radius=0.5,
               ao_frame_index=0,
               albedo_saturation=0.8, albedo_brightness=1.0,
               sphere_size_jitter=0.0,
               sdf_enabled=False, sdf_aabb_min=None, sdf_aabb_max=None):
        """Render one frame of raytraced spheres.

        The entity buffer must NOT be mapped by the caller. This method
        maps it internally for the OptiX launch, then unmaps it.

        Args:
            width, height: Output image dimensions.
            eye: Camera position (3-tuple or array).
            U: Camera horizontal extent vector (3-tuple or array).
            V: Camera vertical extent vector (3-tuple or array).
            W: Camera center ray direction (3-tuple or array).
            light_dir: Directional light direction toward the light (3-tuple).
            ambient: Ambient light intensity (0-1).
            radius_scale: Multiplier on entity size field.
            shadows_enabled: Whether to cast shadow rays.
            light_color: RGB light color (3-tuple, default white).
            light_intensity: Light intensity multiplier.
            sky_color_top: Sky gradient top color (3-tuple).
            sky_color_bottom: Sky gradient bottom color (3-tuple).

        Returns:
            moderngl.Texture (rgba8) with the rendered image.
        """
        if self._gas_handle is None:
            raise RuntimeError(
                "GAS not built. Call build_accel() before render()."
            )

        self._ensure_display(width, height)

        # Map entity buffer for the OptiX launch (intersection reads it)
        self._ctx.finish()
        entities_ptr, _ = map_resource(self._entity_res)

        try:
            # Map PBO for OptiX to write into
            image_ptr, _ = map_resource(self._pbo_res)

            try:
                # Fill launch params
                eye = np.asarray(eye, dtype=np.float32)
                U = np.asarray(U, dtype=np.float32)
                V = np.asarray(V, dtype=np.float32)
                W = np.asarray(W, dtype=np.float32)
                light_dir = np.asarray(light_dir, dtype=np.float32)

                h_params = np.zeros(1, dtype=PARAMS_DTYPE)
                h_params["image"] = image_ptr
                h_params["entities"] = entities_ptr
                h_params["entity_stride"] = self._entity_stride
                h_params["_pad0"] = 0
                h_params["handle"] = self._gas_handle
                h_params["width"] = width
                h_params["height"] = height
                h_params["eye_x"] = eye[0]
                h_params["eye_y"] = eye[1]
                h_params["eye_z"] = eye[2]
                h_params["u_x"] = U[0]
                h_params["u_y"] = U[1]
                h_params["u_z"] = U[2]
                h_params["v_x"] = V[0]
                h_params["v_y"] = V[1]
                h_params["v_z"] = V[2]
                h_params["w_x"] = W[0]
                h_params["w_y"] = W[1]
                h_params["w_z"] = W[2]
                h_params["l_x"] = light_dir[0]
                h_params["l_y"] = light_dir[1]
                h_params["l_z"] = light_dir[2]
                h_params["ambient"] = ambient
                h_params["radius_scale"] = radius_scale
                h_params["shadows_enabled"] = 1 if shadows_enabled else 0

                light_color = np.asarray(light_color, dtype=np.float32)
                sky_color_top = np.asarray(sky_color_top, dtype=np.float32)
                sky_color_bottom = np.asarray(sky_color_bottom, dtype=np.float32)
                h_params["lc_r"] = light_color[0]
                h_params["lc_g"] = light_color[1]
                h_params["lc_b"] = light_color[2]
                h_params["light_intensity"] = light_intensity
                h_params["sky_top_r"] = sky_color_top[0]
                h_params["sky_top_g"] = sky_color_top[1]
                h_params["sky_top_b"] = sky_color_top[2]
                h_params["sky_bot_r"] = sky_color_bottom[0]
                h_params["sky_bot_g"] = sky_color_bottom[1]
                h_params["sky_bot_b"] = sky_color_bottom[2]

                h_params["ao_enabled"] = 1 if ao_enabled else 0
                h_params["ao_num_rays"] = ao_num_rays
                h_params["ao_radius"] = ao_radius
                h_params["ao_frame_index"] = ao_frame_index
                h_params["albedo_saturation"] = albedo_saturation
                h_params["albedo_brightness"] = albedo_brightness
                h_params["sphere_size_jitter"] = sphere_size_jitter

                # SDF scene
                h_params["sdf_enabled"] = 1 if sdf_enabled else 0
                if sdf_enabled and sdf_aabb_min is not None:
                    h_params["sdf_aabb_min_x"] = sdf_aabb_min[0]
                    h_params["sdf_aabb_min_y"] = sdf_aabb_min[1]
                    h_params["sdf_aabb_min_z"] = sdf_aabb_min[2]
                    h_params["sdf_aabb_max_x"] = sdf_aabb_max[0]
                    h_params["sdf_aabb_max_y"] = sdf_aabb_max[1]
                    h_params["sdf_aabb_max_z"] = sdf_aabb_max[2]
                    h_params["sdf_prim_index"] = self._entity_count

                self._d_params.set(
                    np.frombuffer(h_params.tobytes(), dtype=np.uint8)
                )

                check_cuda(cudart.cudaEventRecord(self._evt_render_start, self._stream_obj))
                optix.launch(
                    self._pipeline,
                    self._stream,
                    self._d_params.data.ptr,
                    PARAMS_DTYPE.itemsize,
                    self._sbt,
                    width,
                    height,
                    1,  # depth
                )
                check_cuda(cudart.cudaEventRecord(self._evt_render_end, self._stream_obj))
                check_cuda(cudart.cudaStreamSynchronize(self._stream_obj))
                self.last_render_ms = check_cuda(
                    cudart.cudaEventElapsedTime(
                        self._evt_render_start, self._evt_render_end
                    )
                )
            finally:
                unmap_resource(self._pbo_res)
        finally:
            unmap_resource(self._entity_res)

        # Blit PBO to texture (fast GPU-to-GPU copy)
        self._tex.write(self._pbo)
        return self._tex

    def render_from_camera(self, width, height, cam_pos, cam_dir, cam_up,
                           fov_deg, light_dir=(0.577, 0.577, 0.577),
                           ambient=0.12, radius_scale=1.0,
                           shadows_enabled=True,
                           light_color=(1.0, 1.0, 1.0),
                           light_intensity=1.0,
                           sky_color_top=(0.45, 0.62, 0.85),
                           sky_color_bottom=(0.08, 0.08, 0.10),
                           ao_enabled=False, ao_num_rays=2,
                           ao_radius=0.5, ao_frame_index=0,
                           albedo_saturation=0.8, albedo_brightness=1.0,
                           sphere_size_jitter=0.0,
                           sdf_enabled=False, sdf_aabb_min=None,
                           sdf_aabb_max=None):
        """Convenience: render from FPS camera vectors.

        Converts Fluoddity's ControllerCam-style vectors to OptiX pinhole
        basis and calls render().

        Args:
            cam_pos: Camera position (3,).
            cam_dir: Unit look direction (3,).
            cam_up: Unit up vector (3,).
            fov_deg: Vertical FOV in degrees.
            light_dir: Unit vector toward the light.
            ambient: Ambient light intensity.
            radius_scale: Multiplier on entity size field.
            shadows_enabled: Whether to cast shadow rays.
            light_color: RGB light color (3-tuple, default white).
            light_intensity: Light intensity multiplier.
            sky_color_top: Sky gradient top color (3-tuple).
            sky_color_bottom: Sky gradient bottom color (3-tuple).

        Returns:
            moderngl.Texture (rgba8).
        """
        aspect = width / max(height, 1)
        eye, U, V, W = _camera_basis_from_vectors(
            cam_pos, cam_dir, cam_up, fov_deg, aspect
        )
        return self.render(
            width, height, eye, U, V, W, light_dir,
            ambient=ambient,
            radius_scale=radius_scale,
            shadows_enabled=shadows_enabled,
            light_color=light_color,
            light_intensity=light_intensity,
            sky_color_top=sky_color_top,
            sky_color_bottom=sky_color_bottom,
            ao_enabled=ao_enabled,
            ao_num_rays=ao_num_rays,
            ao_radius=ao_radius,
            ao_frame_index=ao_frame_index,
            albedo_saturation=albedo_saturation,
            albedo_brightness=albedo_brightness,
            sphere_size_jitter=sphere_size_jitter,
            sdf_enabled=sdf_enabled,
            sdf_aabb_min=sdf_aabb_min,
            sdf_aabb_max=sdf_aabb_max,
        )

    # ------------------------------------------------------------------
    # Buffer management
    # ------------------------------------------------------------------

    def update_entity_buffer(self, entity_buffer, entity_count):
        """Re-register a new entity buffer (after world_size change / reset).

        Args:
            entity_buffer: New ModernGL buffer.
            entity_count: New entity count.
        """
        # Unregister old buffer
        if self._entity_res is not None:
            unregister_resource(self._entity_res)

        self._entity_buffer = entity_buffer
        self._entity_count = entity_count

        flags = cudart.cudaGraphicsRegisterFlags
        self._entity_res = register_gl_buffer(
            entity_buffer, flags.cudaGraphicsRegisterFlagsReadOnly
        )

        # Invalidate GAS (must be rebuilt)
        self._gas_handle = None
        self._d_gas = None
        self._d_temp = None
        self._d_aabbs = None

    def resize(self, width, height):
        """Force recreation of PBO and output texture for a new resolution."""
        self._render_width = 0  # force _ensure_display to recreate
        self._render_height = 0

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self):
        """Release all CUDA and OptiX resources."""
        if self._pbo_res is not None:
            try:
                unregister_resource(self._pbo_res)
            except RuntimeError:
                pass
            self._pbo_res = None

        if self._entity_res is not None:
            try:
                unregister_resource(self._entity_res)
            except RuntimeError:
                pass
            self._entity_res = None

        # Destroy CUDA stream and events
        if hasattr(self, '_stream_obj') and self._stream_obj is not None:
            try:
                cudart.cudaStreamDestroy(self._stream_obj)
            except RuntimeError:
                pass
            self._stream_obj = None
            self._stream = None
        for attr in ('_evt_gas_start', '_evt_gas_end',
                     '_evt_render_start', '_evt_render_end'):
            evt = getattr(self, attr, None)
            if evt is not None:
                try:
                    cudart.cudaEventDestroy(evt)
                except RuntimeError:
                    pass
                setattr(self, attr, None)

        self._gas_handle = None
        self._d_gas = None
        self._d_temp = None
        self._d_aabbs = None
        self._d_params = None
        self._sbt_mem = None

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    @staticmethod
    def is_available():
        """Check if OptiX/CUDA/RTX hardware is available.

        Returns False gracefully on machines without the required
        packages or hardware. Logs the specific reason on failure.
        """
        try:
            import optix as _optix  # noqa: F811
        except ImportError:
            print("OptiX unavailable: 'optix' package not installed")
            return False
        try:
            import cupy as _cp  # noqa: F811
        except ImportError:
            print("OptiX unavailable: 'cupy' package not installed")
            return False
        try:
            from cuda.bindings import runtime as _cudart  # noqa: F811
        except ImportError:
            print("OptiX unavailable: 'cuda-python' package not installed")
            return False
        try:
            err, count = _cudart.cudaGetDeviceCount()
            if err != _cudart.cudaError_t.cudaSuccess or count == 0:
                print("OptiX unavailable: no CUDA-capable GPU detected")
                return False
            return True
        except Exception as e:
            print(f"OptiX unavailable: {e}")
            return False
