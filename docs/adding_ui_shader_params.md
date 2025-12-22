# Guide: Adding ImGui Elements Connected to Shader Uniforms

This guide walks through adding a new slider (or other ImGui element) that controls a shader uniform in the orchestrator architecture.

## Overview

Data flows in one direction:
```
UI (renders widget) → SimState (holds value) → Sim.entity_update() → Shader uniform
```

## Step-by-Step Process

### Step 1: Add to SimState

**File:** `state/sim_state.py`

Add a new field with a default value:

```python
@dataclass
class SimState:
    # ... existing fields ...

    # Add your new parameter
    SENSOR_DISTANCE: float = 1.0  # default value
```

### Step 2: Add Uniform to Shader

**File:** Your shader (e.g., `shaders/entity_update.glsl`)

Declare the uniform near other uniforms:

```glsl
uniform float DRAG;
uniform float STRAFE_POWER;
// ... existing uniforms ...
uniform float SENSOR_DISTANCE;  // Add here
```

Use it in the shader logic:

```glsl
float samplen = 3*.0016 * SENSOR_DISTANCE;  // Multiply or use as needed
```

### Step 3: Pass Uniform from Sim to Shader

**File:** `sim.py` in `entity_update()` method

Add a `tryset` call to pass the value:

```python
def entity_update(self, ctx: moderngl.Context):
    # ... existing tryset calls ...
    tryset(self.entity_update_program, 'SENSOR_DISTANCE', self._state.SENSOR_DISTANCE)
```

### Step 4: Add ImGui Widget in UI

**File:** `ui.py` in `render_main_window()` method

Add the slider (or other widget):

```python
_, self.state.sim.SENSOR_DISTANCE = imgui.slider_float(
    label="Sensor Distance",
    v=self.state.sim.SENSOR_DISTANCE,
    v_min=0.0,
    v_max=5.0,
)
```

## Common ImGui Widget Patterns

```python
# Float slider
_, self.state.sim.PARAM = imgui.slider_float(
    label="Label", v=self.state.sim.PARAM, v_min=0.0, v_max=1.0
)

# Int slider
_, self.state.sim.PARAM = imgui.slider_int(
    label="Label", v=self.state.sim.PARAM, v_min=1, v_max=10
)

# Checkbox (bool)
_, self.state.sim.ENABLED = imgui.checkbox("Label", self.state.sim.ENABLED)

# Input field
_, self.state.sim.PARAM = imgui.input_float("Label", self.state.sim.PARAM)
```

## Naming Convention

- **SimState fields:** ALL_CAPS_UNDERSCORE (e.g., `SENSOR_DISTANCE`)
- **Shader uniforms:** ALL_CAPS_UNDERSCORE (matching SimState)
- **UI labels:** Title Case with spaces (e.g., "Sensor Distance")

## Quick Reference Checklist

| Step | File | Action |
|------|------|--------|
| 1 | `state/sim_state.py` | Add field to dataclass |
| 2 | `shaders/*.glsl` | Add `uniform` declaration and use it |
| 3 | `sim.py` | Add `tryset()` call in update method |
| 4 | `ui.py` | Add ImGui widget in render method |

## Notes

- **No wiring needed** - The orchestrator pattern handles the connection automatically
- **Type matching** - Ensure Python type matches GLSL type (float→float, int→int)
- **tryset()** - Gracefully handles missing uniforms (useful during shader development)
- **Hot reload** - Press `V` to reload shaders without restarting
