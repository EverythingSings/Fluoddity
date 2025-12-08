import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw

def main():
    if not glfw.init():
        return
    
    window = glfw.create_window(800, 600, "ImGui Example", None, None)
    if not window:
        glfw.terminate()
        return
    
    glfw.make_context_current(window)
    
    imgui.create_context()
    renderer = GlfwRenderer(window)
    
    # Your application state
    my_value = 0
    
    def key_callback(window, key, scancode, action, mods):
        # Let ImGui process the input first
        renderer.keyboard_callback(window, key, scancode, action, mods)
        
        # Check if ImGui wants to capture keyboard input
        io = imgui.get_io()
        if io.want_capture_keyboard:
            # ImGui wants this input (e.g., typing in a text field)
            return
        
        # ImGui doesn't want it, so handle it in your application
        if action == glfw.PRESS:
            if key == glfw.KEY_SPACE:
                print("Space pressed - handled by application")
            elif key == glfw.KEY_ESCAPE:
                glfw.set_window_should_close(window, True)
    
    # Set the callback
    glfw.set_key_callback(window, key_callback)
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        imgui.new_frame()
        
        imgui.begin("Test Window")
        
        # When you're typing in this field, want_capture_keyboard will be True
        changed, my_value = imgui.input_int("My Int", my_value)
        if changed:
            print(f"Value changed to: {my_value}")
        
        imgui.text("Try pressing SPACE when focused vs unfocused on the input")
        imgui.text("ESC to quit (when not typing in input)")
        
        imgui.end()
        
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
    
    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()