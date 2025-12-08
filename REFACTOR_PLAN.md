# SimScratch Refactoring Plan

## Project Overview
Physarum-like generative artwork with GPU-accelerated particle simulation, evolvable RBF-based rule system, and multiple visualization modes (2D canvas, volumetric ray marching, particle rendering).

---

## Phase 1: Remove Dead Code & Deprecated Files

### 1.1 Delete Unused/Backup Shaders
- [ ] `shaders/entity_update_BACKUP.glsl` - backup file
- [ ] `shaders/entity_update Flower.glsl` - variant backup
- [ ] `shaders/rbf8_4.glsl` - unused 8D RBF implementation
- [ ] `shaders/shadow.glsl` - not referenced anywhere in codebase

### 1.2 Remove Commented Debug Code
**entity_update.glsl:**
- [ ] Line 153-154: Alternative rule mutation using mix()
- [ ] Line 246-259: Experimental velocity field sampling
- [ ] Line 281: Reference image diagnostic (muted refcol)

**camera.frag:**
- [ ] Line 9, 29-34: Kaleidoscopic transform (#ifdef KAL) - either enable properly or remove

**canvas.frag:**
- [ ] Line 61: Commented getBlur() alternative

**save_frame_gpu.py:**
- [ ] Line 76: DEBUG output (if statement always false)

### 1.3 Archive/Remove Test Files
- [ ] `guitest.py` - not integrated, standalone ImGui test
- [ ] `rbf_gen.py` - code generator for extensible RBF (rbf8_4.glsl unused)
- [ ] Decision: Keep `noise_tester.py` and `stack_tester.py` (actively used diagnostics)

---

## Phase 2: Code Organization & Structure

### 2.1 Consolidate Shader Includes
**Current state:** Shaders manually prepended at runtime via util.py
- [ ] Document shader dependency tree clearly
- [ ] Add header comments to free_list.glsl and rbf4_4.glsl explaining they're includes
- [ ] Consider: Create shaders/includes/ subdirectory for clarity

### 2.2 Normalize Naming Conventions
**Texture naming inconsistency:**
- `can_tex` vs `view_can_tex` (velocity field vs visualization)
- `brush_tex` vs `view_brush_tex`

**Action:**
- [ ] Add comments in sim.py explaining texture pairs (simulation vs visualization)
- [ ] Consider renaming: `sim_canvas`/`view_canvas`, `sim_brush`/`view_brush`

### 2.3 Extract Magic Numbers to Constants
**sim.py:**
- [ ] Extract hardcoded values: kernel widths, damage coefficients, cohort count (64)
- [ ] Create CONFIG section at top of file
- [ ] Unify START_COUNT (600k) vs ENTITY_COUNT (1M) - document why different

**Shaders:**
- [ ] Extract TAP_STRETCH, DAMAGE multiplier (15.0), cohort count
- [ ] Use #define for shader constants

### 2.4 Organize File Structure
**Proposed structure:**
```
SimScratch/
├── core/
│   ├── main.py
│   ├── sim.py
│   ├── ui.py
│   ├── camera.py
│   └── DensityRender.py
├── utils/
│   ├── util.py
│   ├── vid_saver.py
│   ├── save_frame_gpu.py
│   └── mp4_builder.py
├── diagnostics/
│   ├── noise_tester.py
│   ├── stack_tester.py
│   └── hist.py
├── shaders/
│   ├── includes/
│   │   ├── free_list.glsl
│   │   └── rbf4_4.glsl
│   ├── compute/
│   │   └── entity_update.glsl
│   ├── brush/
│   │   ├── brush.vert/frag
│   │   └── canvas.vert/frag
│   ├── camera/
│   │   ├── camera.vert/frag
│   │   ├── march.frag
│   │   └── cam_brush.vert/frag + pp
│   └── diagnostic/
│       └── noise_test.frag
└── README.md
```

**Decision needed:** Keep flat structure or reorganize?

---

## Phase 3: Documentation

### 3.1 Add Module Docstrings
- [ ] **main.py**: Entry point, App orchestration
- [ ] **sim.py**: Core simulation loop, entity/canvas update pipeline
- [ ] **ui.py**: ImGui interface, parameter controls, rule history
- [ ] **camera.py**: 2D camera + volumetric rendering modes
- [ ] **DensityRender.py**: Gaussian blur and volumetric ray marching
- [ ] **util.py**: Shader loading, rule I/O, image utilities

### 3.2 Document Key Systems
- [ ] **Rule system**: How RBF centers work, mutation algorithm, cohort-based variation
- [ ] **Three-stage update loop**: Brush render → Entity compute → Canvas update
- [ ] **Entity struct layout**: Sync GLSL struct with Python SIZE_OF_ENTITY_STRUCT
- [ ] **Free list mechanism**: Stack-based entity allocation/deallocation
- [ ] **Lock system**: Spinlock-based concurrency, potential contention issues

### 3.3 Add Inline Comments for Algorithms
- [ ] **entity_update.glsl**: Sensory tap geometry, symmetric response function
- [ ] **canvas.frag**: Tone mapping algorithm (HSV brightness normalization)
- [ ] **save_frame_gpu.py**: Supersampling + motion blur accumulation

### 3.4 Create README.md
- [ ] Project description
- [ ] System architecture diagram
- [ ] Installation/dependencies (moderngl, imgui, numpy, etc.)
- [ ] Usage instructions
- [ ] Parameter guide (what each slider does)
- [ ] Rule evolution workflow (left-click to capture, right-click to undo)
- [ ] Video recording workflow

---

## Phase 4: Code Quality Improvements

### 4.1 Fix Global State Issues
- [ ] `FREE_TESTER` global in main.py - encapsulate in App class
- [ ] `muted` warnings dict in util.py - consider proper logging system

### 4.2 Bound Rule History
**ui.py line 32:** `rule_history` list grows unbounded
- [ ] Add MAX_HISTORY limit (e.g., 100 rules)
- [ ] Implement circular buffer or pop oldest

### 4.3 Improve Error Handling
- [ ] Add try/except around shader compilation with better error messages
- [ ] Validate texture sizes match CANVAS_SHAPE
- [ ] Check ENTITY_COUNT vs START_COUNT consistency

### 4.4 Standardize Shader Uniform Setting
**Current:** Mix of set_uniform, set_sampler, manual binding
- [ ] Document uniform naming conventions
- [ ] Group related uniforms (e.g., all behavior sliders)

### 4.5 Clean Up Diagnostic Features
**Current state:** Stack tester and RBF noise tester integrated but cluttering UI
- [ ] Keep functionality but improve UI organization
- [ ] Add "Diagnostics" collapsing header in ImGui
- [ ] Document when to use each diagnostic tool

---

## Phase 5: Performance & Optimization Opportunities

### 5.1 Lock Contention Analysis
**entity_update.glsl:** Atomic exchange spinlock
- [ ] Measure: Is lock contention actually occurring?
- [ ] Consider: Double-buffering entities instead of locks
- [ ] Document: Why locks are needed (concurrent mutations?)

### 5.2 Canvas Decay Optimization
**canvas.frag:** DRAIN blending every frame
- [ ] Verify: Is VIEWDRAIN=0 always? If so, simplify shader
- [ ] Consider: Exponential decay LUT for non-linear effects

### 5.3 Brush Rendering Batching
**Current:** 1M particle instances rendered every frame
- [ ] Measure: GPU bottleneck on brush rendering?
- [ ] Consider: Occlusion culling for off-screen particles
- [ ] Keep as-is if performance adequate

---

## Phase 6: Feature Consolidation

### 6.1 Rendering Mode Clarity
**Three modes:** Normal (canvas), March (volumetric), CamBrush (particles)
- [ ] Document use case for each mode
- [ ] Add mode switching to main UI (currently view_options menu)
- [ ] Unify camera transforms across modes

### 6.2 Kaleidoscope Feature
**Status:** Commented out with #ifdef KAL
- [ ] Decision: Enable as optional feature OR remove entirely
- [ ] If enable: Add UI toggle, document 3-fold symmetry
- [ ] If remove: Delete all KAL code blocks

### 6.3 Reference Image Feature
**Status:** Loaded but neutralized (refcol=vec3(1))
- [ ] Decision: Implement properly OR remove
- [ ] If implement: Add UI for image selection, blend mode
- [ ] If remove: Delete ref_img loading in sim.py

---

## Phase 7: Testing & Validation

### 7.1 Validate Core Systems
- [ ] Test: Entity spawn/death with free list (use stack_tester)
- [ ] Test: Rule mutation doesn't explode (NaN/Inf checks)
- [ ] Test: Canvas doesn't accumulate errors over long runs
- [ ] Test: Video recording with supersampling + motion blur

### 7.2 Cross-Platform Compatibility
- [ ] Current: Windows paths (backslashes), test on Linux/Mac
- [ ] Shader: Check GLSL version compatibility (currently #version 430)

### 7.3 Edge Case Handling
- [ ] Free list empty (all 1M entities alive)
- [ ] Rule history overflow
- [ ] Extreme parameter values (DRAIN=0, DRAG=0, dt > 10)

---

## Implementation Priority

### High Priority (Core Cleanup)
1. Remove dead code & deprecated files (Phase 1)
2. Add module docstrings (Phase 3.1)
3. Extract magic numbers to constants (Phase 2.3)
4. Fix unbounded rule history (Phase 4.2)

### Medium Priority (Organization)
5. Consolidate shader includes (Phase 2.1)
6. Normalize naming conventions (Phase 2.2)
7. Create README.md (Phase 3.4)
8. Document key algorithms (Phase 3.3)

### Low Priority (Polish)
9. File structure reorganization (Phase 2.4) - optional
10. Kaleidoscope/reference image decisions (Phase 6.2, 6.3)
11. Performance profiling (Phase 5) - only if needed
12. Cross-platform testing (Phase 7.2)

---

## Risks & Decisions Needed

### Decision Points
1. **File reorganization:** Keep flat structure or create subdirectories?
2. **Kaleidoscope feature:** Enable with UI toggle or delete entirely?
3. **Reference image:** Implement properly or remove loading code?
4. **RBF generator:** Keep rbf_gen.py for future extensibility or delete?
5. **Texture naming:** Rename for clarity or document current scheme?

### Risks
- Shader changes could introduce subtle bugs (test rendering carefully)
- Constant extraction might miss shader/Python sync points
- File moves will break relative imports (update all paths)

---

## Success Criteria
- [ ] No commented-out code in main codebase
- [ ] All Python modules have docstrings
- [ ] README.md explains architecture and usage
- [ ] Magic numbers extracted to named constants
- [ ] Deprecated files removed or archived
- [ ] Rule history bounded
- [ ] All rendering modes documented and functional
