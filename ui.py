import glfw
from imgui_bundle import imgui
from imgui_bundle.python_backends import glfw_backend
import time
import sim
import numpy as np
from noise_tester import RBFNoiseTester
from util import readback_rule, set_rule_uniform, tryset
from vid_saver import VidSaver
from DensityRender import VolumetricRenderProgram, GaussianBlurer
from math import cos,sin,fmod
class UI:
    def __init__(self, sim:sim.Sim, camera, window):
        self.sim = sim
        self.camera = camera
        self.window = window
        self.mouse_pos=(0,0)
        
        # Initialize ImGui
        imgui.create_context()
        self.imgui_renderer = glfw_backend.GlfwRenderer(window)
        
        # Set up event callbacks
        self.setup_callbacks()
        
        # UI state
        self.show_demo_window = False
        self.slider0=.2
        self.slider1 = 6

        #History 
        self.rule_history=[]
        # Key tracking
        self.keys_pressed = set()
        self.last_update_time = time.time()

        #regular updating shaders
        self.shader_refresh=False

        #screen recording
        self.recorder_max_frames = 150*12
        self.motion_blur_samps = 12
        self.supersample_k = 2
        self.recorder = VidSaver()
        #diagnostic program
        self.noise_test_program = RBFNoiseTester(self.camera.ctx)
        self.sim.view_options.append(self.noise_test_program.rbf_tex)
        self.sim.view_option_labels.append('noise_test')
        #3d renderer
    
    def setup_callbacks(self):
        # Don't override callbacks - let ImGui renderer set them up
        # We'll wrap them to add our custom logic

        # Store the ImGui callbacks that were set by the renderer
        self.imgui_mouse_callback = glfw.set_mouse_button_callback(self.window, None)
        self.imgui_cursor_callback = glfw.set_cursor_pos_callback(self.window, None)
        self.imgui_scroll_callback = glfw.set_scroll_callback(self.window, None)
        self.imgui_key_callback = glfw.set_key_callback(self.window, None)
        self.imgui_char_callback = glfw.set_char_callback(self.window, None)

        # Now set our wrapped versions
        glfw.set_mouse_button_callback(self.window, self.mouse_button_callback)
        glfw.set_cursor_pos_callback(self.window, self.cursor_pos_callback)
        glfw.set_scroll_callback(self.window, self.scroll_callback)
        glfw.set_key_callback(self.window, self.key_callback)
        glfw.set_char_callback(self.window, self.char_callback)
    def mouse_button_callback(self, window, button, action, mods):
        # Call ImGui's callback first if it exists
        if self.imgui_mouse_callback:
            self.imgui_mouse_callback(window, button, action, mods)

        # Handle mouse button events only if ImGui doesn't want the input
        if imgui.get_io().want_capture_mouse:
            return

        # Only handle PRESS events for custom logic
        if action != glfw.PRESS:
            return

        if button == glfw.MOUSE_BUTTON_LEFT:
            ent_cache=np.frombuffer(self.sim.entities.read(),dtype=np.float32)
            tmouse=self.camera.screen_to_tex(self.mouse_pos)
            xs=ent_cache[::16].copy()
            ys=ent_cache[1::16].copy()
            xs=xs/2.+.5
            ys=ys/2.+.5
            xs-=tmouse[0]
            ys-=tmouse[1]
            xs=xs**2
            ys=ys**2
            xs+=ys
            focused_id=xs.argmin()
            print(focused_id)
            targ_rule = readback_rule(self.sim.rule_buffer,focused_id)
            self.rule_history.append(targ_rule)
            set_rule_uniform(self.sim.entity_update_program,targ_rule)
        elif button == glfw.MOUSE_BUTTON_RIGHT:
            if len(self.rule_history)>1:
                self.rule_history.pop()
                prev_rule = self.rule_history[-1]
                set_rule_uniform(self.sim.entity_update_program,prev_rule)
            else:#just go back to a blank slate
                self.rule_history=[]
                set_rule_uniform(self.sim.entity_update_program,np.zeros((10,8),dtype=np.float32))

        
    
    def cursor_pos_callback(self, window, xpos, ypos):
        # Call ImGui's callback first if it exists
        if self.imgui_cursor_callback:
            self.imgui_cursor_callback(window, xpos, ypos)

        # Handle mouse movement for custom logic
        self.mouse_pos=(xpos,ypos)
    
    def scroll_callback(self, window, xoffset, yoffset):
        # Call ImGui's callback first if it exists
        if self.imgui_scroll_callback:
            self.imgui_scroll_callback(window, xoffset, yoffset)
    
    def key_callback(self, window, key, scancode, action, mods):
        # Call ImGui's callback first if it exists
        if self.imgui_key_callback:
            self.imgui_key_callback(window, key, scancode, action, mods)

        if imgui.get_io().want_capture_keyboard:
            return
        # Track key press/release states
        if action == glfw.PRESS:
            self.keys_pressed.add(key)
        elif action == glfw.RELEASE:
            self.keys_pressed.discard(key)
        if key==glfw.KEY_V and action == glfw.PRESS:
            self.sim.reload()
            if len(self.rule_history)>0:
                set_rule_uniform(self.sim.entity_update_program,self.rule_history[-1])
            self.camera.reload()
            self.noise_test_program.reload(self.camera.ctx)
        if key == glfw.KEY_P and action == glfw.PRESS: #start or stop screen recording
            if self.recorder.active:
                self.recorder.finish()
            else:
                self.recorder.active = True
        if key == glfw.KEY_G and action == glfw.PRESS:
            self.sim.going=not self.sim.going
        # Handle special keys
        if key == glfw.KEY_ESCAPE and action == glfw.PRESS:
            glfw.set_window_should_close(window, True)
        elif key == glfw.KEY_F1 and action == glfw.PRESS:
            self.show_demo_window = not self.show_demo_window
    
    def char_callback(self, window, char):
        # Call ImGui's callback first if it exists
        if self.imgui_char_callback:
            self.imgui_char_callback(window, char)
    
    def update_cam(self):
        # Calculate delta time
        current_time = time.time()
        dt = current_time - self.last_update_time
        self.last_update_time = current_time
        
        # Movement speed (units per second)
        move_speed = 2.0 * dt
        zoom_speed = 2.6 * dt
        
        # Adjust move speed based on zoom (move faster when zoomed out)
        move_speed *= self.camera.zoom
        
        # Handle movement (WASD)
        if glfw.KEY_W in self.keys_pressed:
            self.camera.position[1] -= move_speed
        if glfw.KEY_S in self.keys_pressed:
            self.camera.position[1] += move_speed
        if glfw.KEY_A in self.keys_pressed:
            self.camera.position[0] -= move_speed
        if glfw.KEY_D in self.keys_pressed:
            self.camera.position[0] += move_speed
        
        # Handle zoom (QE)
        if glfw.KEY_E in self.keys_pressed:
            self.camera.zoom *= (1.0 - zoom_speed)
        if glfw.KEY_Q in self.keys_pressed:
            self.camera.zoom *= (1.0 + zoom_speed)
        
        # Clamp zoom to reasonable bounds
        #self.camera.zoom = max(0.1, min(10.0, self.camera.zoom))

        if glfw.KEY_R in self.keys_pressed:
            self.sim.reset()
            #self.camera.reset()
        if glfw.KEY_Z in self.keys_pressed:
            self.sim.reset()
            self.rule_history=[]
            set_rule_uniform(self.sim.entity_update_program,np.zeros((10,8),dtype=np.float32))
    
    def update_gamepad(self,pad_state):
        def DZ(x,zone = .5):
            if abs(x)<zone:
                return 0
            return x
        left_stick_x = pad_state.axes[glfw.GAMEPAD_AXIS_LEFT_X]
        left_stick_y = pad_state.axes[glfw.GAMEPAD_AXIS_LEFT_Y]
        
        left_stick_x = DZ(left_stick_x)
        left_stick_y = DZ(left_stick_y)
        

        right_stick_x = pad_state.axes[glfw.GAMEPAD_AXIS_RIGHT_X]
        right_stick_y = pad_state.axes[glfw.GAMEPAD_AXIS_RIGHT_Y]

        right_stick_x = DZ(right_stick_x)
        right_stick_y = DZ(right_stick_y)

        right_trig = pad_state.axes[glfw.GAMEPAD_AXIS_RIGHT_TRIGGER]
        left_trig = pad_state.axes[glfw.GAMEPAD_AXIS_LEFT_TRIGGER]

        def pR(x,y,alpha):
            return cos(alpha)*x+sin(alpha)*y,cos(alpha)*y-sin(alpha)*x
        mov_sens=.03
        turn_sens = .162
        if pad_state.buttons[glfw.GAMEPAD_BUTTON_RIGHT_BUMPER]>0:
            mov_sens*=5
        march_offset = [
            mov_sens*left_stick_x,
            mov_sens*(right_trig-left_trig),
            -mov_sens*left_stick_y
        ]
        march_offset[0],march_offset[2] = pR(march_offset[0],march_offset[2],self.camera.march_ori[0])
        for i in range(len(self.camera.march_pos)):
            self.camera.march_pos[i]+=march_offset[i]
        
        march_turn = [
            turn_sens*right_stick_x,
            -turn_sens*right_stick_y,
        ]
        PI = 3.141592
        self.camera.march_ori[0]=fmod(self.camera.march_ori[0]+march_turn[0],PI*2)

        self.camera.march_ori[1]=max(-PI/2,min(PI/2,(self.camera.march_ori[1]+march_turn[1])))
    def render(self):
        # Update camera based on input
        self.update_cam()
        
        # Process ImGui inputs
        self.imgui_renderer.process_inputs()
        
        # Start new ImGui frame
        imgui.new_frame()
        
        # Render UI elements
        self.render_main_window()
        
        if self.show_demo_window:
            imgui.show_demo_window()
        
        # Render ImGui
        imgui.render()
        self.imgui_renderer.render(imgui.get_draw_data())
        if self.sim.current_view_option==self.sim.view_option_labels.index('noise_test'):
            self.noise_test_program.render(self.camera.ctx,0,self.sim.frame_count,1)
    def render_main_window(self):
        imgui.begin("Simulation Controls")
        # Display current time
        imgui.text(f"Simulation Time: {self.sim.time:.2f}, Frame: {self.sim.frame_count}")
        _, self.shader_refresh=imgui.checkbox('shader refresh',self.shader_refresh)
        # Texture info
        width, height = self.sim.view_tex.size
        _,self.camera.amplitude=imgui.slider_float(
            label="amp",
            v=self.camera.amplitude,
            v_min=0.0,
            v_max=4.0,
        )
        imgui.text(f"Texture Size: {width}x{height}")
        _,self.sim.dt_slider=imgui.slider_float(
            label="dt",
            v=self.sim.dt_slider,
            v_min=0.0,
            v_max=1.0,
        )
        if imgui.button('Hist'):
            from hist import display_brightness_histogram
            import numpy as np
            canaray=np.frombuffer(self.sim.can.read(),dtype=np.float32)
            #canaray=np.log(canaray+.01)
            display_brightness_histogram(canaray,50)

        #camera dropdown
        changed, self.sim.current_view_option = imgui.combo(
        label="Current View",
        current_item=self.sim.current_view_option,
        items=self.sim.view_option_labels+['March','cam_brush']
        )

        if changed:
            #if we picked 'cam_brush'
            if self.sim.current_view_option==len(self.sim.view_option_labels)+1:
                self.camera.cam_brush_mode=True
                self.camera.march_mode = False
            elif self.sim.current_view_option==len(self.sim.view_option_labels):
                self.camera.cam_brush_mode = False
                self.camera.march_mode = True
            else:
                self.camera.cam_brush_mode=False
                self.camera.march_mode = False
                print(f"Selected: {self.sim.view_option_labels[self.sim.current_view_option]}")
                self.sim.view_tex=self.sim.view_options[self.sim.current_view_option]
        
        #brush blend mode dropdown
        changed, self.sim.current_brush_blend_option = imgui.combo(
        label="Brush Blend",
        current_item=self.sim.current_brush_blend_option,
        items=self.sim.brush_blend_options
        )
        changed,flatQ=imgui.checkbox('flat_kernel',self.sim.brush_kernel_mode==1)
        if changed:
            if flatQ:
                self.sim.brush_kernel_mode=1
            else:
                self.sim.brush_kernel_mode=0

                # DRAIN
        _,self.sim.DRAIN=imgui.slider_float(
            label="DRAIN",
            v=self.sim.DRAIN,
            v_min=0.0,
            v_max=1.0,
        )
        _,self.sim.VIEWDRAIN=imgui.slider_float(
            label="VIEWDRAIN",
            v=self.sim.VIEWDRAIN,
            v_min=0.0,
            v_max=1.0,
        )
        changed,self.slider0 = imgui.slider_float(
            label="sig",
            v=self.slider0,
            v_min=.0001,
            v_max=1.,
        )
        
        self.camera.march_program.sig = self.slider0
        changed, self.slider1 = imgui.slider_float(
            label="wid",
            v=self.slider1,
            v_min=1,
            v_max=8,
        )
        
        self.camera.march_program.wid = self.slider1
        imgui.separator()
        imgui.text("Camera:")
        imgui.text(f"Position: ({self.camera.position[0]:.1f}, {self.camera.position[1]:.1f})")
        imgui.text(f"Zoom: {self.camera.zoom:.2f}")
        
        imgui.separator()
        imgui.text("Screen Recording:")
        _,self.recorder_max_frames = imgui.input_int('Max Frames',self.recorder_max_frames)
        _,self.motion_blur_samps = imgui.input_int('Motion Blur Samples',self.motion_blur_samps)
        _,self.supersample_k = imgui.input_int('Supersample Kernel Width',self.supersample_k)
        
        imgui.separator()
        # Controls hint
        imgui.text("Controls:")
        imgui.text("WASD - Move camera")
        imgui.text("Q/E - Zoom out/in")
        imgui.text("F1 - Toggle ImGui Demo Window")
        imgui.text("ESC - Exit")
        
        imgui.end()
        imgui.begin('Sliders')
        s_labels = ['Axial Force','Lateral Force','Rule Sensitivity','Mutation Scale']
        for i in range(len(self.sim.generic_sliders)):
            _,self.sim.generic_sliders[i]=imgui.slider_float(
                label=s_labels[i],
                v=self.sim.generic_sliders[i],
                v_min=-1.0,
                v_max=1.0,
            )
        _,self.sim.DRAG = imgui.slider_float(
                label=f"DRAG",
                v=self.sim.DRAG,
                v_min=-1.0,
                v_max=1.0,
            )
        _,self.sim.STRAFE_SCALE = imgui.slider_float(
                label=f"STRAFE_SCALE",
                v=self.sim.STRAFE_SCALE,
                v_min=0,
                v_max=4.0,
            )
        _,self.sim.TAP_STRETCH = imgui.slider_float(
                label=f"TAP_STRETCH",
                v=self.sim.TAP_STRETCH,
                v_min=-3,
                v_max=3,
            )
        imgui.end()
    def cleanup(self):
        self.imgui_renderer.shutdown()
        if self.recorder.active:
            self.recorder.finish()