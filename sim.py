#RING BUFFER EMPTY SLOTS

import moderngl
import time
import numpy as np
import math
from util import create_grid_coords, read_shader, shader_prepend, prepend_defines,tryset, load_image_as_texture
from imgui_bundle import imgui
from temporal_accumulator import TemporalAccumulator
# Global constants
ENTITY_COUNT = 1024*1024 #free_list and stack_tester AND #INTITIALIZE FREE LIST
SIZE_OF_ENTITY_STRUCT=4*16 #4 bytes per 32bit value. 16 values (pos:2,vel:2,status:1,size:1,spare*2,color:4, lock:1,padding: 3)
SIZE_OF_RULE_STRUCT=4*4*20 #4 bytes per float32. 4 floats per vec4. 20 vec4s per rule 
CANVAS_SHAPE = (1024,1024)
POS_SCALE=1.#SYNC WITH UPDATE.GLSL
class Sim:
    def __init__(self, ctx:moderngl.Context):
        self.entity_count=ENTITY_COUNT# for camera to have it too
        self.PARTICLE_ALPHA = 1
        self.ctx = ctx
        self.time = 0.0
        self.start_time_stamp = time.time()
        self.frame_count=0
        self.setup_simulation_state()
        self.setup_shaders()
        
        #ui settings
        self.going=True
        self.brush_blend_mode=True
        self.current_brush_blend_option=1
        self.brush_blend_options=['MAX','ADD','OFF']
        self.dt_slider=1#.887#.024#.25*.33
        self.speedmult=1  # Speed multiplier for temporal accumulation
        self.generic_sliders=[.371,-.707,.116,0.]#[.185,.336,.241,.013]#[.009,.036,.129,.036]#[.326,.116,.103,.116]#[.304,.058,-.085,.098]#[.214,.674,-.549,.424]#[.509,.156,.188,.317]#[1,.732,.004,.143]#[-.134,-1.,.317,.022]#[.295,.326,.031,.348]#[1.,.732,.004,.143]#[.179,.330,.036,0.02]#[.991,-.107,.107,.038]#[.865,1.,.019,.50]#[.519,.635,.269,.173]#[.692,481,.385,0]
        self.current_view_option=0
        self.view_options=[self.view_can,self.can,self.view_brush_tex,self.brush_tex]
        self.view_option_labels=['view_can','can','view_brush_tex','brush_tex']
        self.brush_kernel_mode=0
        
        self.DRAIN=.938
        self.VIEWDRAIN=0
        self.DRAG = .504#.25
        self.STRAFE_SCALE = .224#1.
        self.TAP_STRETCH = .2

        self.reference_tex = load_image_as_texture(ctx, 'colorspace.jpg')

    
    def setup_simulation_state(self):
        
        self.entities = self.ctx.buffer(reserve=ENTITY_COUNT*SIZE_OF_ENTITY_STRUCT)
        #INITIALIZE RULE_BUFFER
        self.rule_buffer=self.ctx.buffer(reserve=ENTITY_COUNT*SIZE_OF_RULE_STRUCT)

        #INITIALIZE FREE_LIST
        self.byte_packed_free_list_data=np.zeros(1+ENTITY_COUNT+64,dtype=np.uint32)
        self.byte_packed_free_list_data=self.byte_packed_free_list_data.tobytes()
        self.free_list_buffer = self.ctx.buffer(self.byte_packed_free_list_data)


        #BIND ENTITY AND FREE_LIST BUFFERS
        self.entities.bind_to_storage_buffer(0)
        self.free_list_buffer.bind_to_storage_buffer(1)
        self.rule_buffer.bind_to_storage_buffer(2)
        
        # Create canvas textures (4-channel float32)
        self.can = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')
        self.view_can = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')
        self.can.repeat_x=False
        self.can.repeat_y=False
        self.view_can.repeat_x=False
        self.view_can.repeat_y=False
        # Create canvas framebuffer with 2 color attachments
        self.canvas = self.ctx.framebuffer([self.can, self.view_can])
        
        # Create brush textures and framebuffer
        self.brush_tex = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')
        self.view_brush_tex=self.ctx.texture(CANVAS_SHAPE,4,dtype = 'f4')
        self.brush_tex.repeat_x=False
        self.brush_tex.repeat_y=False
        self.view_brush_tex.repeat_x=False
        self.view_brush_tex.repeat_y=False
        self.brush = self.ctx.framebuffer([self.brush_tex,self.view_brush_tex])
        
        

        # For camera to use
        self.view_tex = self.view_can

        # Create temporal accumulator for motion blur
        self.temporal_accumulator = TemporalAccumulator(self.ctx, self.view_can)
        self.accumulated_view_tex = self.ctx.texture(CANVAS_SHAPE, 4, dtype='f4')

        # Clear canvases initially
        self.canvas.use()
        self.ctx.clear()
    
    def setup_shaders(self):
        # 1. Entity update compute shader
        #build source string
        self.entity_update_source = read_shader('shaders/entity_update.glsl')
        self.entity_update_source=shader_prepend(self.entity_update_source,read_shader('shaders/free_list.glsl'))
        self.entity_update_source=shader_prepend(self.entity_update_source,read_shader('shaders/rbf4_4.glsl'))
        self.entity_update_source=prepend_defines(self.entity_update_source,ENTITY_COUNT)
        
        #try to compile it
        try:
            self.entity_update_program = self.ctx.compute_shader(self.entity_update_source)
        except Exception as e:
            print('Entity Update Compilation Failed:')
            print(e)

        #set static uniforms for entity program
        tryset(self.entity_update_program,'canvas_resolution', CANVAS_SHAPE)
        tryset(self.entity_update_program,'canvas', 1)
        

        # 2. Brush update shaders (instanced rendering)
        #build source strings
        self.brush_vertex_source = read_shader('shaders/brush.vert')
        self.brush_vertex_source=prepend_defines(self.brush_vertex_source,ENTITY_COUNT)
        self.brush_fragment_source = read_shader('shaders/brush.frag')

        #try to compile it
        try:
            self.brush_update_program = self.ctx.program(
                vertex_shader=self.brush_vertex_source,
                fragment_shader=self.brush_fragment_source
            )
        except Exception as e:
            print('Brush Update Compilation Failed:')
            print(e)


        # Set static uniforms
        self.brush_update_program['canvas_resolution']=CANVAS_SHAPE
        # Create VAO for instanced rendering (no vertex data - generated in shader)
        self.brush_vao = self.ctx.vertex_array(self.brush_update_program, [])
        


        # 3. Canvas update shaders (fullscreen quad)
        #build source strings 
        self.canvas_vertex_source = read_shader('shaders/canvas.vert')
        self.canvas_fragment_source = read_shader('shaders/canvas.frag')
        
        #try to compile them
        try:
            self.canvas_update_program = self.ctx.program(
                vertex_shader=self.canvas_vertex_source,
                fragment_shader=self.canvas_fragment_source
            )
        except Exception as e:
            print('Canvas Update Compilation Failed:')
            print(e)
        
        # Create VAO for fullscreen quad (no vertex data - generated in shader)
        self.canvas_vao = self.ctx.vertex_array(self.canvas_update_program, [])

    def entity_update(self,ctx:moderngl.Context,dt):
        #uniforms
        tryset(self.entity_update_program,'dt',dt)
        tryset(self.entity_update_program,'frame_count',self.frame_count)
        tryset(self.entity_update_program,'canvas',1)
        #ui uniforms
        tryset(self.entity_update_program,'sliders',self.generic_sliders)
        tryset(self.entity_update_program,'DRAG',self.DRAG)
        tryset(self.entity_update_program,'STRAFE_SCALE',self.STRAFE_SCALE)
        tryset(self.entity_update_program,'TAP_STRETCH',self.TAP_STRETCH)
        tryset(self.entity_update_program,'reference_image',5)
        
        # Dispatch compute shader - need enough workgroups for all entities
        num_workgroups = (ENTITY_COUNT + 63) // 64
        ctx.memory_barrier()
        self.entity_update_program.run(num_workgroups)
    def brush_update(self,ctx:moderngl.Context):
        # 2. Update brush (instanced rendering)
        # Clear brush framebuffer
        self.brush.use()
        ctx.clear(0.0, 0.0, 0.0, 0.0)
        
        # Enable additive blending
        current_blendmode=self.brush_blend_options[self.current_brush_blend_option]
        if current_blendmode=="ADD":
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE
            ctx.blend_equation=moderngl.FUNC_ADD
        elif current_blendmode=="MAX":
            ctx.enable(moderngl.BLEND)
            ctx.blend_equation=moderngl.MAX
        else:
            ctx.disable(moderngl.BLEND)
        tryset(self.brush_update_program,'kernel_mode',self.brush_kernel_mode)

        #self.view_brush
        #self.brush_update_program['brush_tex'].value=0
        # Render entities as small quads - use triangle fan for 4 vertices
        self.brush_vao.render(mode=moderngl.TRIANGLE_FAN, instances=ENTITY_COUNT, vertices=4)
    def can_update(self,ctx:moderngl.Context):
        # Bind textures for sampling



        tryset(self.canvas_update_program,'DRAIN', self.DRAIN)
        tryset(self.canvas_update_program,'VIEWDRAIN',self.VIEWDRAIN)
        tryset(self.canvas_update_program,'can_tex', 1)
        tryset(self.canvas_update_program,'view_can_tex', 2)
        tryset(self.canvas_update_program,'brush_tex',3)
        tryset(self.canvas_update_program,'view_brush_tex',4)
        
        # Render to canvas framebuffer (both attachments)
        self.canvas.use()
        #ctx.clear(0,0,0,0)
        
        self.canvas_vao.render(mode=moderngl.TRIANGLE_FAN, vertices=4)
        
    def update(self, ctx):
        self.can.use(location=1) 
        self.view_can.use(location=2)
        self.brush_tex.use(location=3)
        self.view_brush_tex.use(location=4)
        self.reference_tex.use(location=5)
        # Calculate delta time
        current_time = time.time()
        dt = self.dt_slider#min(0.016, current_time - self.start_time_stamp - self.time)  # Cap at 60fps
        self.time = current_time - self.start_time_stamp
        
        self.brush_update(ctx)
        # Memory barrier to ensure entity updates are complete
        ctx.memory_barrier()
        self.entity_update(ctx,dt)
        
        
        # 3. Update canvas (fullscreen quad with additive brush application)
        # Disable blending for canvas update
        ctx.disable(moderngl.BLEND)
        
        self.can_update(ctx)
        self.frame_count+=1
    def reset(self):
        #freelist diagnostic
        #current_free=np.frombuffer(self.free_list_buffer.read(),dtype=np.uint32)
        #print(np.mod(current_free[:2],len(current_free-2)))
        #track old_fbo so we can revert state changes for IMGUI
        old_fbo=self.ctx.fbo
        #erase canvas
        self.canvas.use()
        self.ctx.clear(0,0,0,0)
        #reset entities
        #self.entities.write(self.byte_packed_entity_data)
        self.frame_count=0
        self.free_list_buffer.write(self.byte_packed_free_list_data)
        #erase brush for good measure.
        self.brush.use()
        self.ctx.clear(0,0,0,0)
        #cleanup
        old_fbo.use()
    def reload(self):
        print('reloading')
        self.setup_shaders()
        print('done')
