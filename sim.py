import moderngl
import time
from util import read_shader, shader_prepend, prepend_defines, tryset
from temporal_accumulator import TemporalAccumulator

# Global constants
ENTITY_COUNT = 1024*1024
SIZE_OF_ENTITY_STRUCT = 4*12  # 4 bytes per 32bit value. 12 values (pos:2, vel:2, size:1, padding:3, color:4)
SIZE_OF_RULE_STRUCT = 4*4*20  # 4 bytes per float32. 4 floats per vec4. 20 vec4s per rule
CANVAS_SHAPE = (1024, 1024)

class Sim:
    def __init__(self, ctx: moderngl.Context):
        self.entity_count = ENTITY_COUNT
        self.PARTICLE_ALPHA = 1
        self.ctx = ctx
        self.time = 0.0
        self.start_time_stamp = time.time()
        self.frame_count = 0
        self.setup_simulation_state()
        self.setup_shaders()

        # UI settings
        self.going = True
        self.speedmult = 1
        self.generic_sliders = [.371, -.707, .116, 0.]
        self.current_view_option = 2 #cam_brush mode
        self.view_options = [self.can, self.brush_tex]
        self.view_option_labels = ['can', 'brush_tex']

        self.DRAIN = .938
        self.DRAG = .504
        self.STRAFE_SCALE = .224
        self.TAP_STRETCH = .2
        self.RULE_OUTPUT_GAIN = 1.0

    def setup_simulation_state(self):
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

        # Create temporal accumulator for motion blur
        self.temporal_accumulator = TemporalAccumulator(self.ctx, self.can)
        self.accumulated_view_tex = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')

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
        tryset(self.entity_update_program, 'frame_count', self.frame_count)
        tryset(self.entity_update_program, 'canvas', 1)
        tryset(self.entity_update_program, 'sliders', self.generic_sliders)
        tryset(self.entity_update_program, 'DRAG', self.DRAG)
        tryset(self.entity_update_program, 'STRAFE_SCALE', self.STRAFE_SCALE)
        tryset(self.entity_update_program, 'TAP_STRETCH', self.TAP_STRETCH)
        tryset(self.entity_update_program, 'RULE_OUTPUT_GAIN', self.RULE_OUTPUT_GAIN)

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
        tryset(self.canvas_update_program, 'DRAIN', self.DRAIN)
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
        print('reloading')
        self.setup_shaders()
        print('done')
