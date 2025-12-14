# SimScratch Architecture Guide

**Quick Onboarding for Claude Code Instances**

This document provides a rapid understanding of the SimScratch particle simulation codebase. Read this first before diving into .py and .glsl files.

---

## Quick Start Guide

**What this project is**: GPU-accelerated abstract art particle simulation with evolved behavioral rules using Fourier basis networks.

**Key Components**:
- **Entry point**: [main.py](main.py) - Main loop and application orchestration
- **Hot path**: [shaders/entity_update.glsl](shaders/entity_update.glsl) - Core particle logic (compute shader processing 1M particles)
- **Key interaction**: cam_brush view mode + left-click particles to capture and mutate rules
- **Tech stack**: ModernGL (OpenGL wrapper), GLSL compute shaders, ImGui for UI, FFmpeg for video export

**First-time orientation**:
1. Start at [main.py](main.py) lines 55-102 to see the main loop
2. Look at [shaders/entity_update.glsl](shaders/entity_update.glsl) to understand particle behavior
3. Check [ui.py](ui.py) lines 68-105 for particle clicking interaction
4. Review this document's Section 8 for file location quick reference

---

## System Architecture

### Data Flow Diagram

```
Main Loop (main.py:55-102)
  │
  ├─> Simulation Update (sim.py)
  │   │
  │   ├─> entity_update.glsl (compute shader)
  │   │   └─> Updates 1,048,576 particles (position, velocity, rules)
  │   │
  │   ├─> brush.vert/frag
  │   │   └─> Renders particles to brush texture (velocity field)
  │   │
  │   └─> canvas.vert/frag
  │       └─> Blends brush into persistent canvas with DRAIN decay
  │
  ├─> Camera Render (camera.py)
  │   │
  │   ├─> Normal mode: View canvas texture (standard 2D visualization)
  │   ├─> cam_brush mode: Interactive particle rendering + clicking
  │   └─> march mode: Volumetric ray marching (DensityRender.py)
  │
  └─> UI Render (ui.py)
      └─> ImGui controls, parameter sliders, rule history
```

### GPU Memory Layout

**Storage Buffers (SSBO)**:
- **Binding 0**: `entities[]` - 1,048,576 × 64 bytes = 64 MB
  - Each entity: pos, vel, status_code, size, depth, cohort, color, lock
- **Binding 1**: `free_list_buffer` - Lock-free concurrent stack for particle allocation
  - 1,048,576 + 64 entries for free list management
- **Binding 2**: `rule_buffer` - 1,048,576 × 320 bytes = 320 MB
  - Each rule: 10 FourierCenter structs (frequency + amplitude vec4s)

**Textures**:
- `can` / `view_can` - 1024×1024×4 floats (canvas velocity field and visualization)
- `brush_tex` / `view_brush_tex` - 1024×1024×4 floats (particle rendering buffers)
- `reference_image` - 1024×1024 colorspace reference (currently neutralized)

**Total GPU Memory**: ~400 MB buffers + ~16 MB textures

---

## Critical Data Structures

### Entity Structure

Defined in [shaders/entity_update.glsl](shaders/entity_update.glsl#L8-L20):

```glsl
struct Entity {
    vec2 pos;           // Position in [-1, 1] normalized space
    vec2 vel;           // Velocity vector
    int status_code;    // 0=kill, >0=alive (age countdown), -1=dead/on free list
    float size;         // Particle size (for rendering)
    float depth;        // Hierarchy depth (currently unused)
    float cohort;       // Group ID (0-63) for mutation diversity
    vec4 color;         // RGBA (HSV hue, saturation, value, alpha)
    uint lock;          // Atomic lock for thread-safe access
    float padding[3];   // Alignment padding for std430 layout
};
```

**Key Constants** ([sim.py](sim.py#L11-L14)):
- `ENTITY_COUNT = 1,048,576` (1M particles maximum)
- `START_COUNT = 600,000` (initial particle spawn count)
- `SIZE_OF_ENTITY_STRUCT = 64` bytes
- `CANVAS_SHAPE = (1024, 1024)`

### Fourier Rule Structure

Defined in [shaders/fourier4_4.glsl](shaders/fourier4_4.glsl):

```glsl
struct FourierCenter {
    vec4 frequency;  // 4D input frequency vector
    vec4 amplitude;  // 4D amplitude/weight vector
};

struct Rule {
    FourierCenter centers[10];  // 10 basis functions per rule
};
```

**How it works**:
- Each rule = 10 FourierCenter structs = 80 floats = 320 bytes
- Evaluation: `sin/cos(dot(input, frequency) + phase_offset) * amplitude`
- Creates harmonic basis functions at fundamental and first harmonic frequencies
- Output: 4D force vector (axial force, lateral force, strafe components)

**Why Fourier?** (replaced RBF in commit d81ef9d):
- Better for learning periodic/cyclic behaviors
- Smoother gradients for evolution/mutation
- Frequency-based (where in input space) vs RBF's radial approach (how far)

---

## The Hot Path - Particle Update Loop

**File**: [shaders/entity_update.glsl](shaders/entity_update.glsl)

**Execution**: Compute shader with (ENTITY_COUNT + 63) / 64 work groups, 64 threads each

### Per-Frame, Per-Particle Processing

**Every frame, for each of 1M particles**:

1. **Acquire atomic lock** (lines ~130-140)
   - Spinlock using `atomicCompSwap(e.lock, 0, 1)`
   - Ensures thread-safe access to particle data

2. **Sample canvas velocity** (lines ~180-200)
   - Left and right sensor positions (±60° rotation)
   - Offset by `TAP_STRETCH` parameter
   - Reads velocity field from canvas texture

3. **Load or create Fourier rule** (lines ~150-160)
   - Read from `rule_buffer[entity_id]`
   - If new particle, initialize random rule

4. **Mutate rule** (lines ~150-160)
   - Based on `floor(e.cohort)` as seed (0-63 groups)
   - Scaled by `sliders.w` (Mutation Scale parameter)
   - Frequency jitter (0.5× scale), amplitude jitter (1× scale)
   - 5% chance of octave jump (×2 or ×0.5 frequency)

5. **Evaluate Fourier network** (lines ~200-220)
   - Input: canvas_samples (left/right velocity)
   - Process through 10 FourierCenters
   - Output: 4D force vector

6. **Apply forces to velocity** (lines ~220-240)
   - Force application with `RULE_OUTPUT_GAIN` multiplier
   - Strafe (lateral) forces scaled by `STRAFE_SCALE`
   - Velocity damping: `vel *= DRAG`

7. **Update position** (lines ~240-260)
   - `pos += vel * dt`
   - Boundary bouncing (reflects off [-1, 1] edges)
   - Optional edge-kill mode

8. **Age particle** (lines ~260-280)
   - Decrement `status_code`
   - status=0 → particle dies (freed on even frames)
   - status>0 → alive, continues aging

9. **Release lock** (line ~290)
   - `atomicExchange(e.lock, 0)`

### Key Uniforms

```glsl
uniform int frame_count;          // Current frame number
uniform float dt;                 // Time delta (slider controlled)
uniform Rule target_rule;         // Global rule from clicked particle
uniform vec2 canvas_resolution;   // (1024, 1024)
uniform sampler2D canvas;         // Velocity field texture
uniform float DRAG;               // Velocity damping (default 0.504)
uniform float STRAFE_SCALE;       // Lateral movement scale (default 0.224)
uniform float TAP_STRETCH;        // Canvas sample offset (default 0.2)
uniform float RULE_OUTPUT_GAIN;   // Force multiplier (default 1.0)
uniform vec4 sliders;             // User-controlled params
    // sliders.x = Axial Force (currently unused in shader)
    // sliders.y = Lateral Force (currently unused in shader)
    // sliders.z = Tap scaling multiplier
    // sliders.w = Mutation amount
```

---

## View Modes & User Interaction

### View Mode Overview

Five view modes accessible via UI dropdown ([ui.py](ui.py#L297-L315)):

1. **Canvas** - Standard 2D canvas visualization (`view_can` texture)
2. **cam_brush** - Interactive particle rendering with clicking
3. **March** - Volumetric ray marching ([DensityRender.py](DensityRender.py))
4. **noise_test** - Fourier basis visualization ([noise_tester.py](noise_tester.py))
5. **Free List tester** - Memory allocation diagnostic ([stack_tester.py](stack_tester.py))

### Primary Interactive Mode: cam_brush

**Activation**: UI dropdown → "cam_brush" ([ui.py](ui.py#L306))

**Two-Stage Rendering Pipeline** ([camera.py](camera.py#L107-L156)):

**Stage 1 - Instanced Particle Rendering**:
- Shader: [shaders/cam_brush.vert](shaders/cam_brush.vert) / [shaders/cam_brush.frag](shaders/cam_brush.frag)
- Renders all 1,048,576 particles as instanced quads
- Per-particle quad generation with frustum culling
- Kernel modes: Gaussian (soft) or Flat (hard) - toggled via `flat_kernel` checkbox
- Blending modes: ADD, MAX, or OFF (UI dropdown)
- Output: High-precision float32 RGBA to `cam_brush_target`

**Stage 2 - Post-Processing**:
- Shader: [shaders/cam_brush_pp.frag](shaders/cam_brush_pp.frag)
- Bloom effect with directional weights
- Blends with main canvas (`can` texture) for color grading
- Tone mapping: `fragColor.xyz /= pow(length(fragColor.xyz), 0.575)`
- Output: Final composited texture to `cam_brush_pp_target`

### Particle Clicking Workflow

**File**: [ui.py](ui.py#L68-L105)

**LEFT-CLICK - Capture Rule**:
1. Convert screen coordinates → texture coordinates
   - `tmouse = self.camera.screen_to_tex(self.mouse_pos)`
2. Read entity buffer from GPU
   - `ent_cache = np.frombuffer(self.sim.entities.read(), dtype=np.float32)`
3. Extract all particle positions
   - X positions: `ent_cache[::16]` (every 16th float)
   - Y positions: `ent_cache[1::16]`
4. Find nearest particle via distance minimization
   - `focused_id = ((xs - tmouse[0])**2 + (ys - tmouse[1])**2).argmin()`
5. Extract particle's Fourier rule from GPU buffer
   - Via `readback_rule()` in [util.py](util.py#L38-L62)
   - Rule structure: 10 FourierCenters × 8 floats = 80 values
6. Push to history stack
   - `self.rule_history.append(targ_rule)`
7. Upload as `target_rule` uniform
   - Affects all particles globally (they mutate from this base)

**RIGHT-CLICK - Undo**:
- Pop from rule history: `self.rule_history.pop()`
- If history empty, reset to blank rule (all zeros)
- Upload previous rule as `target_rule` uniform

**Key Insight**: Clicking a particle extracts its evolved rule and makes it the new "base" for all particles to mutate from. This allows you to capture interesting behaviors and propagate them through the population.

---

## Video Recording System

### Activation

**Key**: Press `P` ([ui.py](ui.py#L140-L144))

**Output**: Auto-timestamped MP4 file in project root: `animation-HH-MM-SS.mp4`

### Recording Pipeline

**Stage 1 - GPU Frame Capture** ([save_frame_gpu.py](save_frame_gpu.py)):
1. Motion blur temporal accumulation
   - Default: 12 samples (`motion_blur_samps`)
   - Multiple render passes averaged
2. Supersampling spatial quality
   - Default: 2× (`supersample_k`)
   - Render at higher resolution, downsample
3. Shader-based tone mapping and downsampling
4. Returns numpy uint8 RGB array

**Stage 2 - FFmpeg Encoding** ([ffmpeg_recorder.py](ffmpeg_recorder.py)):
- Real-time encoding with `preset='fast'`, `crf=23`
- 50 FPS default
- H.264 codec
- Pipes raw RGB24 directly to ffmpeg stdin (no intermediate files)
- Auto-padding to even dimensions for H.264 compliance

### UI Controls

Located in [ui.py](ui.py#L365-L368):

- **Max Frames**: Recording duration limit (default 1800 = 36 seconds @ 50 FPS)
- **Motion Blur Samples**: Temporal accumulation passes (default 12)
- **Supersample Kernel Width**: Spatial downsampling factor (default 2)

**Important**: Recording requires `speedmult == 1` (one simulation step per frame for temporal accuracy)

---

## Key Subsystems

### Fourier Basis Networks

**File**: [shaders/fourier4_4.glsl](shaders/fourier4_4.glsl)

**Purpose**: Evolved behavioral rules that determine particle movement based on canvas velocity samples

**Network Architecture**:
- 10 FourierCenter entries per rule
- Each center: `frequency` (vec4) + `amplitude` (vec4)
- Total: 80 floats = 320 bytes per rule

**Evaluation** (lines ~20-60):
```glsl
vec4 output = vec4(0.0);
for (int i = 0; i < 10; i++) {
    float phase = dot(input, centers[i].frequency);
    // Fundamental frequency
    output += sin(phase) * centers[i].amplitude;
    // First harmonic
    output += cos(phase * 2.0) * centers[i].amplitude * 0.5;
}
return output;
```

**Mutation Strategy** (lines ~80-120):
1. **Frequency perturbation**: Small random ±changes (0.5× scale)
   - High behavioral impact, so careful exploration
2. **Amplitude perturbation**: Random ±changes (1× scale)
   - Scale/strength adjustments
3. **Octave jumps**: 5% chance to ×2 or ×0.5 frequency
   - Helps escape local optima

**Historical Context**:
- Replaced RBF (Radial Basis Functions) in commit `d81ef9d`
- RBF variants still in codebase: [rbf4_4.glsl](shaders/rbf4_4.glsl), [rbf8_4.glsl](shaders/rbf8_4.glsl) (legacy)

### Free List System

**File**: [shaders/free_list.glsl](shaders/free_list.glsl)

**Purpose**: Lock-free concurrent stack for tracking dead particle IDs (enables dynamic allocation/deallocation)

**Design**:
- Single atomic counter `head` (number of items in stack)
- `buffer_data[]` array stores available entity IDs
- Operations use atomic increment/decrement

**Functions**:
- `free_list_pop()` - Atomically decrement head and get ID (for creating new particle)
- `free_list_push(id)` - Atomically increment head and store ID (for recycling dead particle)
- Returns `INVALID_ID` (0xFFFFFFFF) when empty

**Benefits**: Dynamic particle creation without CPU-GPU synchronization

### Temporal Accumulation

**File**: [temporal_accumulator.py](temporal_accumulator.py)

**Purpose**: Motion blur when `speedmult > 1`

**How it works**:
1. When speedmult > 1, main loop runs multiple simulation steps per frame ([main.py](main.py#L66-L76))
2. Each step generates a view texture
3. Textures accumulate in GPU texture: `accumulated_tex`
4. Each frame contribution = `current_frame / speedmult`
5. Final accumulated texture displayed after speedmult frames complete

**Benefits**: Smooth motion blur for high-speed playback without temporal aliasing

---

## File Location Quick Reference

| Component | File(s) | Purpose | Key Lines |
|-----------|---------|---------|-----------|
| **Entry point** | [main.py](main.py) | Application orchestration, main loop | 55-102: main loop |
| **Simulation core** | [sim.py](sim.py) | Entity/canvas update, buffer management | 11-14: constants<br>51-65: buffers |
| **UI system** | [ui.py](ui.py) | ImGui interface, parameter controls, rule history | 68-105: particle clicking<br>297-315: view modes |
| **Camera/rendering** | [camera.py](camera.py) | View modes, coordinate transforms | 107-156: cam_brush pipeline<br>192-242: screen_to_tex |
| **Particle update** | [shaders/entity_update.glsl](shaders/entity_update.glsl) | **HOT PATH** - Compute shader, particle physics | Entire file (~300 lines) |
| **Fourier network** | [shaders/fourier4_4.glsl](shaders/fourier4_4.glsl) | Behavioral rule evaluation | 20-60: evaluation<br>80-120: mutation |
| **Particle rendering** | [shaders/brush.vert](shaders/brush.vert)<br>[shaders/brush.frag](shaders/brush.frag) | Rasterize particles to velocity texture | Instanced rendering |
| **Canvas blending** | [shaders/canvas.vert](shaders/canvas.vert)<br>[shaders/canvas.frag](shaders/canvas.frag) | Persistent canvas with DRAIN decay | Tone mapping, HSV conversion |
| **Interactive view** | [shaders/cam_brush.vert](shaders/cam_brush.vert)<br>[shaders/cam_brush.frag](shaders/cam_brush.frag)<br>[shaders/cam_brush_pp.frag](shaders/cam_brush_pp.frag) | Clickable particle rendering + post-processing | Two-stage pipeline |
| **Free list** | [shaders/free_list.glsl](shaders/free_list.glsl) | Lock-free particle allocation | pop/push functions |
| **Video export** | [vid_saver.py](vid_saver.py)<br>[ffmpeg_recorder.py](ffmpeg_recorder.py)<br>[save_frame_gpu.py](save_frame_gpu.py) | Motion blur + FFmpeg encoding | GPU accumulation + H.264 encoding |
| **Volumetric mode** | [DensityRender.py](DensityRender.py)<br>[shaders/march.frag](shaders/march.frag) | Ray marching renderer | 182-241: VolumetricRenderProgram |
| **Utilities** | [util.py](util.py) | Shader loading, rule I/O | 38-62: readback_rule<br>64-82: set_rule_uniform |

---

## Common Workflows

### Modifying Particle Behavior

**Goal**: Change how particles move and interact

1. Edit [shaders/entity_update.glsl](shaders/entity_update.glsl)
   - Lines 180-250: Force application logic
   - Lines 200-220: Fourier network evaluation
   - Lines 240-260: Position update and boundary handling
2. Press `V` to hot-reload shaders
   - Or enable shader_refresh checkbox (auto-reloads every 300 frames)
3. Observe changes in cam_brush mode
4. Adjust UI sliders to fine-tune behavior:
   - DRAG: Velocity damping
   - STRAFE_SCALE: Lateral movement
   - RULE_OUTPUT_GAIN: Force multiplier

### Tweaking Fourier Network

**Goal**: Modify the rule evolution system

1. Edit [shaders/fourier4_4.glsl](shaders/fourier4_4.glsl)
   - Lines 20-60: Network evaluation (basis functions)
   - Lines 80-120: Mutation logic (frequency/amplitude changes)
2. Adjust `sliders.w` (Mutation Scale) in UI
   - Controls how much rules mutate each frame
3. Click particles to capture evolved behaviors
   - Left-click: Capture rule from particle
   - Right-click: Undo to previous rule
4. Watch population evolve with new mutation characteristics

### Adding UI Parameters

**Goal**: Expose a new shader parameter to UI control

1. Add slider in [ui.py](ui.py) `render_main_window()` method
   - Example: `imgui.slider_float("My Param", self.my_param, 0.0, 1.0)`
2. Pass to shader via uniform in [sim.py](sim.py) or [camera.py](camera.py)
   - `self.sim.program['my_param'] = self.ui.my_param`
3. Declare uniform in relevant .glsl file
   - `uniform float my_param;`
4. Use parameter in shader logic

### Debugging Particle Issues

**Common debugging strategies**:

1. **Visualize Fourier basis**
   - Switch to `noise_test` view mode
   - Shows rule network output in frequency space
   - Located in [noise_tester.py](noise_tester.py)

2. **Check particle allocation**
   - Use Free List tester view mode
   - Shows free list integrity and allocation patterns
   - Located in [stack_tester.py](stack_tester.py)

3. **Inspect entity status codes**
   - Check [shaders/entity_update.glsl](shaders/entity_update.glsl) lines 153+
   - status_code=0: marked for death
   - status_code>0: alive, aging
   - status_code=-1: dead, on free list

4. **Monitor GPU buffer contents**
   - Use `entities.read()` in [ui.py](ui.py) line 72+
   - Readback and inspect particle data on CPU
   - Check for NaN/Inf values (sign of numerical instability)

---

## Performance Characteristics

### GPU Bottlenecks

**Compute Shader** ([entity_update.glsl](shaders/entity_update.glsl)):
- Workload: 1M particles, 64 threads per work group
- Bottleneck: Compute-bound (Fourier network evaluation, rule mutation)
- Potential issue: Atomic lock contention if many particles at same location

**Brush Rendering**:
- Workload: 1M instanced quads rendered per frame
- Bottleneck: Fillrate-bound (overdraw when particles cluster)
- Blending mode affects performance (MAX mode faster than ADD)

**Canvas Update**:
- Workload: 1024×1024 fullscreen quad
- Bottleneck: Texture bandwidth (reading previous canvas state)
- DRAIN parameter affects blend complexity

### Memory Usage

**GPU Buffers**: ~400 MB
- entities[]: 64 MB
- rule_buffer: 320 MB
- free_list_buffer: ~4 MB

**Textures**: ~16 MB
- Canvas textures: 2 × 1024×1024×4 floats = 8 MB
- Brush textures: 2 × 1024×1024×4 floats = 8 MB

**Temporal Accumulation**: Additional memory
- view_texture × speedmult (increases with motion blur samples)

### Optimization Points

**If experiencing performance issues**:

1. **Reduce particle count**
   - Edit `ENTITY_COUNT` in [sim.py](sim.py#L11)
   - Trade visual density for performance

2. **Disable temporal accumulation**
   - Set `speedmult = 1` in UI
   - Eliminates motion blur overhead

3. **Simplify Fourier network**
   - Reduce number of FourierCenters (currently 10)
   - Edit [fourier4_4.glsl](shaders/fourier4_4.glsl) to use fewer centers

4. **Lower canvas resolution**
   - Edit `CANVAS_SHAPE` in [sim.py](sim.py#L14)
   - Reduces texture bandwidth and fillrate pressure

5. **Optimize brush blending**
   - Use MAX blend mode instead of ADD
   - Reduces GPU blend complexity

---

## Git History Context

### Current Branch

**Branch**: `experimental-fourier`

**Main Branch**: Not set (check repository for default branch)

### Recent Commits

**Latest**: `d81ef9d` - "Replace RBF with Fourier basis network for entity rules"
- Major behavioral change: RBF → Fourier basis functions
- Modified: [entity_update.glsl](shaders/entity_update.glsl), [fourier4_4.glsl](shaders/fourier4_4.glsl)
- Legacy RBF code still present in [rbf4_4.glsl](shaders/rbf4_4.glsl), [rbf8_4.glsl](shaders/rbf8_4.glsl)

**Previous**: `ce7c4db` - "Add temporal accumulation for motion blur with speed multiplier"
- Added: [temporal_accumulator.py](temporal_accumulator.py)
- Modified: [main.py](main.py) to support speedmult > 1
- Enables smooth motion blur via GPU texture accumulation

**Initial**: `d564bc2` - "Initial commit: Working simulation project"
- Baseline working simulation
- RBF-based rules (pre-Fourier)

### Uncommitted Changes

**Modified**: [shaders/entity_update.glsl](shaders/entity_update.glsl)
- Current working directory has local changes
- Use `git diff shaders/entity_update.glsl` to see modifications

---

## Additional Resources

### Related Documentation

- [REFACTOR_PLAN.md](REFACTOR_PLAN.md) - Detailed refactoring tasks and code cleanup plan

### Keyboard Shortcuts

Defined in [ui.py](ui.py) keyboard callback:

- **WASD**: Pan camera
- **Q/E**: Zoom in/out
- **R**: Reset simulation (keep rules)
- **Z**: Full reset (clear rules)
- **V**: Reload shaders (hot reload)
- **G**: Play/pause simulation
- **P**: Start/stop video recording

### Gamepad Support

Full analog stick control available for march mode ([ui.py](ui.py#L198-L241)):
- Left stick: Camera position
- Right stick: Camera orientation
- Deadzone: 0.2 (configurable)

---

## Success Checklist for New Claude Instances

After reading this document, you should be able to:

- ✓ Locate the main loop and understand the update cycle
- ✓ Identify the hot path (entity_update.glsl) and how particles are processed
- ✓ Understand the Fourier network rule system and mutation
- ✓ Navigate to any major component using the file location quick reference
- ✓ Modify particle behavior by editing entity_update.glsl
- ✓ Add new UI parameters and connect them to shaders
- ✓ Use cam_brush mode to interact with particles and capture rules
- ✓ Debug common issues using view modes and buffer inspection
- ✓ Understand data flow: Python ↔ GLSL ↔ GPU buffers

**Time to productive understanding**: < 10 minutes

---

*Generated for Claude Code instances - Focus on "what you need to know" to be productive quickly*
