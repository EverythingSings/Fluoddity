import glfw
import moderngl
from camera import Camera
from sim import Sim
from ui import UI
global FREE_TESTER
from stack_tester import StackFreeListTester
FREE_TESTER=None




class App:
    def __init__(self):
        # Initialize GLFW
        if not glfw.init():
            raise Exception("GLFW initialization failed")
        self.window = glfw.create_window(800, 600, "Compute Shader Simulation", None, None)
        if not self.window:
            glfw.terminate()
            raise Exception("GLFW window creation failed")
        
        glfw.make_context_current(self.window)
        glfw.swap_interval(1)  # Enable vsync
        
        # Initialize ModernGL
        self.ctx = moderngl.create_context()
        self.ctx.gc_mode = 'auto'
        
        #always on top
        glfw.set_window_attrib(self.window, glfw.FLOATING, glfw.TRUE)
        
        # Create simulation, camera, and UI
        self.sim = Sim(self.ctx)
        self.frame_count=0

        ###############STACK TESTER
        global FREE_TESTER
        FREE_TESTER=StackFreeListTester(self.ctx)
        self.sim.view_options+=[FREE_TESTER.stack_test_tex]
        self.sim.view_option_labels+=['Free List tester']
        #self.sim.view_tex=FREE_TESTER.ring_buffer_test_tex
        self.camera = Camera(self.ctx, self.sim, self.window)
        self.ui = UI(self.sim, self.camera, self.window)

    def run(self):
        while not glfw.window_should_close(self.window):
            glfw.poll_events()
            
            #print(self.ctx.info['GL_MAX_COMPUTE_WORK_GROUP_INVOCATIONS'])
            # Update simulation
            if self.sim.going:
                speedmult = self.sim.speedmult

                if speedmult > 1:
                    # Run multiple simulation steps and accumulate for motion blur
                    for step in range(speedmult):
                        self.sim.update(self.ctx)
                        # Generate the view texture based on current mode
                        view_tex = self.camera.generate_view_texture()
                        # Accumulate it
                        accumulated_tex = self.sim.temporal_accumulator.accumulate_frame(
                            view_tex, speedmult
                        )

                    # After all steps, use the accumulated texture for display
                    if accumulated_tex is not None:
                        self.camera.accumulated_view_texture = accumulated_tex
                        self.camera.use_accumulated_view = True
                else:
                    # Normal operation: single step, no accumulation
                    self.sim.update(self.ctx)
                    self.camera.use_accumulated_view = False

                self.frame_count+=1
                self.ui.recorder.frame(self.camera.ctx,self.camera.cam_brush_target,max_frames = self.ui.recorder_max_frames,mb_samples = self.ui.motion_blur_samps,ssk_w = self.ui.supersample_k)

            ###############RING BUFFER
            #global FREE_TESTER
            #FREE_TESTER.render(self.ctx,self.sim.free_list_buffer)

            #reload shaders every 300 frames if box is checked
            if self.ui.shader_refresh and self.frame_count%300 == 0:
                self.sim.reload()
                self.camera.reload()
            # Render camera view
            self.camera.render()
            if self.camera.march_mode and glfw.joystick_present(0):
                self.ui.update_gamepad(glfw.get_gamepad_state(0))
            
            # Render UI
            self.ui.render()
            glfw.swap_buffers(self.window)
        
        self.cleanup()
    def dump_state(self):
        print('final state:')

    def cleanup(self):
        self.ui.cleanup()
        glfw.terminate()


        

if __name__ == "__main__":
    # Required packages:
    # pip install glfw imgui[glfw] moderngl numpy PyOpenGL
    app = App()
    app.run()