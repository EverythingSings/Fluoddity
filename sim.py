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
        tryset(self.entity_update_program, 'AXIAL_FORCE', self._state.AXIAL_FORCE)
        tryset(self.entity_update_program, 'LATERAL_FORCE', self._state.LATERAL_FORCE)
        tryset(self.entity_update_program, 'SENSOR_GAIN', self._state.SENSOR_GAIN)
        tryset(self.entity_update_program, 'MUTATION_SCALE', self._state.MUTATION_SCALE)
        tryset(self.entity_update_program, 'DRAG', self._state.DRAG)
        tryset(self.entity_update_program, 'STRAFE_POWER', self._state.STRAFE_POWER)
        tryset(self.entity_update_program, 'SENSOR_ANGLE', self._state.SENSOR_ANGLE)
        tryset(self.entity_update_program, 'GLOBAL_FORCE_MULT', self._state.GLOBAL_FORCE_MULT)
        tryset(self.entity_update_program, 'SENSOR_DISTANCE', self._state.SENSOR_DISTANCE)
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
