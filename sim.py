import moderngl
import time
import numpy as np
from utilities.gl_helpers import read_shader, shader_prepend, prepend_defines, tryset, set_rule_uniform
from state import SimState

# Global constants
ENTITY_COUNT = 600000
SIZE_OF_ENTITY_STRUCT = 4*12  # 4 bytes per 32bit value. 12 values (pos:2, vel:2, size:1, padding:3, color:4)
SIZE_OF_RULE_STRUCT = 4*4*20  # 4 bytes per float32. 4 floats per vec4. 20 vec4s per rule
CANVAS_SHAPE = (1024, 1024) # Changing canvas size can significantly alter particle behavior. Presets all assume 1024 x 1024 

class Sim:
    def __init__(self, ctx: moderngl.Context):
        self.entity_count = ENTITY_COUNT
        self.ctx = ctx
        self.time = 0.0
        self.start_time_stamp = time.time()
        self.frame_count = 0
        self.setup_simulation_state()
        self.setup_shaders()

        # View options (for UI combo box)
        self.view_options = [self.can, self.brush_tex]
        self.view_option_labels = ['can', 'brush_tex']

        # Current state (will be updated by apply_state each frame)
        self._state = SimState()
        self._camera_state = None  # Will be set by apply_camera_state

    def setup_simulation_state(self):
        # Allocate state buffers
        self.entities = self.ctx.buffer(reserve=ENTITY_COUNT * SIZE_OF_ENTITY_STRUCT)
        self.rule_buffer = self.ctx.buffer(reserve=ENTITY_COUNT * SIZE_OF_RULE_STRUCT)

        # Bind entity and rule buffers
        self.entities.bind_to_storage_buffer(0)
        self.rule_buffer.bind_to_storage_buffer(2)

        # Create canvas texture (4-channel float32)
        self.can = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')
        self.can.repeat_x = False
        self.can.repeat_y = False
        self.canvas = self.ctx.framebuffer([self.can])

        # Create brush texture and framebuffer
        self.brush_tex = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')
        self.brush_tex.repeat_x = False
        self.brush_tex.repeat_y = False
        self.brush = self.ctx.framebuffer([self.brush_tex])

        # For camera to use
        self.view_tex = self.can

        # Clear canvases initially
        self.canvas.use()
        self.ctx.clear()

    def setup_shaders(self):
        # 1. Entity update compute shader
        self.entity_update_source = read_shader('shaders/entity_update.glsl')
        self.entity_update_source = shader_prepend(self.entity_update_source, read_shader('shaders/fourier4_4.glsl'))
        self.entity_update_source = prepend_defines(self.entity_update_source, ENTITY_COUNT)

        try:
            self.entity_update_program = self.ctx.compute_shader(self.entity_update_source)
        except Exception as e:
            print('Entity Update Compilation Failed:')
            print(e)

        tryset(self.entity_update_program, 'canvas_resolution', CANVAS_SHAPE)
        tryset(self.entity_update_program, 'canvas', 1)

        # 2. Brush update shaders (instanced rendering)
        self.brush_vertex_source = read_shader('shaders/brush.vert')
        self.brush_vertex_source = prepend_defines(self.brush_vertex_source, ENTITY_COUNT)
        self.brush_fragment_source = read_shader('shaders/brush.frag')

        try:
            self.brush_update_program = self.ctx.program(
                vertex_shader=self.brush_vertex_source,
                fragment_shader=self.brush_fragment_source
            )
        except Exception as e:
            print('Brush Update Compilation Failed:')
            print(e)

        self.brush_update_program['canvas_resolution'] = CANVAS_SHAPE
        self.brush_vao = self.ctx.vertex_array(self.brush_update_program, [])

        # 3. Canvas update shaders (fullscreen quad)
        self.canvas_vertex_source = read_shader('shaders/canvas.vert')
        self.canvas_fragment_source = read_shader('shaders/canvas.frag')

        try:
            self.canvas_update_program = self.ctx.program(
                vertex_shader=self.canvas_vertex_source,
                fragment_shader=self.canvas_fragment_source
            )
        except Exception as e:
            print('Canvas Update Compilation Failed:')
            print(e)

        self.canvas_vao = self.ctx.vertex_array(self.canvas_update_program, [])


    
    def entity_update(self, ctx: moderngl.Context):
        '''
        Run a single physics update on all particles
        '''
        tryset(self.entity_update_program, 'frame_count', self.frame_count)
        tryset(self.entity_update_program, 'canvas', 1)
        self._assign_physics_setting('AXIAL_FORCE_SETTING', self._state.AXIAL_FORCE, 'Axial Force', 'AXIAL_FORCE', -1.0, 1.0)
        self._assign_physics_setting('LATERAL_FORCE_SETTING', self._state.LATERAL_FORCE, 'Lateral Force', 'LATERAL_FORCE', -1.0, 1.0)
        self._assign_physics_setting('SENSOR_GAIN_SETTING', self._state.SENSOR_GAIN, 'Sensor Gain', 'SENSOR_GAIN', 0.0, 5.0)
        self._assign_physics_setting('MUTATION_SCALE_SETTING', self._state.MUTATION_SCALE, 'Mutation Scale', 'MUTATION_SCALE', -0.5, 0.5)
        self._assign_physics_setting('DRAG_SETTING', self._state.DRAG, 'Drag', 'DRAG', -1.0, 1.0)
        self._assign_physics_setting('STRAFE_POWER_SETTING', self._state.STRAFE_POWER, 'Strafe Power', 'STRAFE_POWER', 0.0, 0.5)
        self._assign_physics_setting('SENSOR_ANGLE_SETTING', self._state.SENSOR_ANGLE, 'Sensor Angle', 'SENSOR_ANGLE', -1.0, 1.0)
        self._assign_physics_setting('GLOBAL_FORCE_MULT_SETTING', self._state.GLOBAL_FORCE_MULT, 'Global Force Mult', 'GLOBAL_FORCE_MULT', 0.0, 2.0)
        self._assign_physics_setting('SENSOR_DISTANCE_SETTING', self._state.SENSOR_DISTANCE, 'Sensor Distance', 'SENSOR_DISTANCE', 0.0, 4.0)
        tryset(self.entity_update_program, 'DISABLE_SYMMETRY', self._state.DISABLE_SYMMETRY)
        tryset(self.entity_update_program, 'ABSOLUTE_ORIENTATION', self._state.ABSOLUTE_ORIENTATION)

        # Camera state uniforms
        if self._camera_state is not None:
            tryset(self.entity_update_program, 'HUE_SENSITIVITY', self._camera_state.HUE_SENSITIVITY)

        # Preferences uniforms
        if hasattr(self, '_preferences') and self._preferences is not None:
            tryset(self.entity_update_program, 'COLOR_BY_COHORT', self._preferences.color_by_cohort)
            tryset(self.entity_update_program, 'RULE_SEED', self._preferences.rule_seed)

        num_workgroups = (ENTITY_COUNT + 63) // 64
        ctx.memory_barrier()
        self.entity_update_program.run(num_workgroups)

    def brush_update(self, ctx: moderngl.Context):
        self.brush.use()
        ctx.clear(0.0, 0.0, 0.0, 0.0)

        # Always use additive blending
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
        ctx.blend_equation = moderngl.FUNC_ADD

        self.brush_vao.render(mode=moderngl.TRIANGLE_FAN, instances=ENTITY_COUNT, vertices=4)

    def can_update(self, ctx: moderngl.Context):
        tryset(self.canvas_update_program, 'TRAIL_PERSISTENCE', self._state.TRAIL_PERSISTENCE)
        tryset(self.canvas_update_program, 'can_tex', 1)
        tryset(self.canvas_update_program, 'brush_tex', 3)

        self.canvas.use()
        self.canvas_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)

    def update(self, ctx):
        self.can.use(location=1)
        self.brush_tex.use(location=3)

        current_time = time.time()
        self.time = current_time - self.start_time_stamp

        self.brush_update(ctx)
        ctx.memory_barrier()
        self.entity_update(ctx)

        ctx.disable(moderngl.BLEND)
        self.can_update(ctx)
        self.frame_count += 1

    def reset(self):
        old_fbo = self.ctx.fbo
        self.canvas.use()
        self.ctx.clear(0, 0, 0, 0)
        self.frame_count = 0
        self.brush.use()
        self.ctx.clear(0, 0, 0, 0)
        old_fbo.use()

    def reload(self):
        print('reloading shaders')
        self.setup_shaders()
        print('reload done')

    def apply_state(self, state: SimState) -> None:
        """Apply state from Orchestrator before update."""
        self._state = state
        # Update view_tex based on current_view_option
        if state.current_view_option < len(self.view_options):
            self.view_tex = self.view_options[state.current_view_option]

    def apply_camera_state(self, camera_state) -> None:
        """Apply camera state from Orchestrator before update."""
        self._camera_state = camera_state

    def _get_slider_range(self, slider_label: str, default_min: float, default_max: float) -> tuple[float, float]:
        """Get the current min/max range for a slider from preferences."""
        if self._preferences is None:
            return (default_min, default_max)

        if slider_label not in self._preferences.slider_ranges:
            return (default_min, default_max)

        return (self._preferences.slider_ranges[slider_label][0],
                self._preferences.slider_ranges[slider_label][1])

    def calculate_setting(self, slider_value: float, min_value: float, max_value: float,
                         pos: tuple[float, float], cohort: float,
                         x_sweep: bool, y_sweep: bool, cohort_sweep: bool) -> float:
        """Python version of GLSL calculate_setting() function.

        Calculates the effective parameter value based on sweeps and position/cohort.
        Mirrors the shader function for use when clicking particles to set slider values.

        Args:
            slider_value: Base slider value when no sweeps are active
            min_value: Minimum value for parameter sweeps
            max_value: Maximum value for parameter sweeps
            pos: (x, y) world position of entity in [-1, 1] range
            cohort: Normalized cohort value in [0, 1] range
            x_sweep: Whether x-position sweep is active
            y_sweep: Whether y-position sweep is active
            cohort_sweep: Whether cohort sweep is active

        Returns:
            Effective parameter value at the given position/cohort
        """
        # If no sweeps active, return slider value
        if not (x_sweep or y_sweep or cohort_sweep):
            return slider_value

        # Convert pos from [-1, 1] to [0, 1] for mixing
        pos_norm = ((pos[0] + 1) / 2, (pos[1] + 1) / 2)

        # Accumulate sweep contributions
        result = 0.0
        active_sweeps = 0

        if x_sweep:
            # mix(min_value, max_value, pos_norm[0])
            result += min_value + (max_value - min_value) * pos_norm[0]
            active_sweeps += 1

        if y_sweep:
            result += min_value + (max_value - min_value) * pos_norm[1]
            active_sweeps += 1

        if cohort_sweep:
            result += min_value + (max_value - min_value) * cohort
            active_sweeps += 1

        # Average the results to keep within min/max range
        return result / active_sweeps if active_sweeps > 0 else slider_value

    def _assign_physics_setting(self, uniform_name: str, slider_value: float, slider_label: str, param_name: str, default_min: float, default_max: float):
        """Assign a PhysicsSetting struct uniform with dynamically fetched min/max ranges and sweep states."""
        min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)

        tryset(self.entity_update_program, f'{uniform_name}.slider_value', slider_value)
        tryset(self.entity_update_program, f'{uniform_name}.min_value', min_val)
        tryset(self.entity_update_program, f'{uniform_name}.max_value', max_val)
        tryset(self.entity_update_program, f'{uniform_name}.x_sweep', self._state.x_sweeps.get(param_name, False))
        tryset(self.entity_update_program, f'{uniform_name}.y_sweep', self._state.y_sweeps.get(param_name, False))
        tryset(self.entity_update_program, f'{uniform_name}.cohort_sweep', self._state.cohort_sweeps.get(param_name, False))

    def apply_preferences(self, preferences) -> None:
        """Apply preferences from Orchestrator before update."""
        self._preferences = preferences

    def apply_rule(self, rule: np.ndarray | None) -> None:
        """Apply a rule to the shader."""
        if rule is None:
            set_rule_uniform(self.entity_update_program, np.zeros((10, 8), dtype=np.float32))
        else:
            set_rule_uniform(self.entity_update_program, rule)

    def get_entity_buffer(self) -> moderngl.Buffer:
        """Expose entity buffer for EntityPicker."""
        return self.entities

    def get_rule_buffer(self) -> moderngl.Buffer:
        """Expose rule buffer for rule readback."""
        return self.rule_buffer

    def update_sliders_from_particle(self, pos: tuple[float, float], cohort: float) -> None:
        """Update all slider values based on effective values at a particle's position/cohort.

        When a particle is clicked and parameter sweeps are active, this calculates what
        the effective parameter values are at that particle's location and updates the
        sliders to show those values.

        Args:
            pos: (x, y) world position of entity in [-1, 1] range
            cohort: Normalized cohort value in [0, 1] range
        """
        # Define all 9 parameters with their state field, slider label, and default ranges
        parameters = [
            ('AXIAL_FORCE', 'Axial Force', -1.0, 1.0),
            ('LATERAL_FORCE', 'Lateral Force', -1.0, 1.0),
            ('SENSOR_GAIN', 'Sensor Gain', 0.0, 5.0),
            ('MUTATION_SCALE', 'Mutation Scale', -0.5, 0.5),
            ('DRAG', 'Drag', -1.0, 1.0),
            ('STRAFE_POWER', 'Strafe Power', 0.0, 0.5),
            ('SENSOR_ANGLE', 'Sensor Angle', -1.0, 1.0),
            ('GLOBAL_FORCE_MULT', 'Global Force Mult', 0.0, 2.0),
            ('SENSOR_DISTANCE', 'Sensor Distance', 0.0, 4.0),
        ]

        for param_name, slider_label, default_min, default_max in parameters:
            # Get current slider value
            current_value = getattr(self._state, param_name)

            # Get sweep states for this parameter
            x_sweep = self._state.x_sweeps.get(param_name, False)
            y_sweep = self._state.y_sweeps.get(param_name, False)
            cohort_sweep = self._state.cohort_sweeps.get(param_name, False)

            # Only update if at least one sweep is active
            if x_sweep or y_sweep or cohort_sweep:
                # Get min/max range for this parameter
                min_val, max_val = self._get_slider_range(slider_label, default_min, default_max)

                # Calculate effective value at this particle's position/cohort
                effective_value = self.calculate_setting(
                    current_value, min_val, max_val,
                    pos, cohort,
                    x_sweep, y_sweep, cohort_sweep
                )

                # Update the slider value
                setattr(self._state, param_name, effective_value)
